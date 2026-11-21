"""Map META and MEMBER items."""

from __future__ import annotations

from botocore.exceptions import ClientError

from lambdas.common.activity import notify
from lambdas.common.dynamo import (
    acct_key,
    batch_get,
    delete_keys,
    get_item,
    member_key,
    meta_key,
    new_id,
    now,
    query_prefix,
    table,
    to_item,
)
from lambdas.common.errors import NotFoundError
from lambdas.common.footprints import delete_footprints
from lambdas.common.models import MapCreate

_FIELDS = ("name", "center", "radius_m", "footprint", "version", "created_at")


def map_name(map_id: str) -> str:
    return get_item(meta_key(map_id), ("name",))["name"]


def member_ids(map_id: str) -> list[str]:
    return [m["sk"].removeprefix("MEMBER#") for m in query_prefix(f"MAP#{map_id}", "MEMBER#")]


def map_view(meta: dict, role: str) -> dict:
    return {"id": meta["pk"].removeprefix("MAP#"), **{k: meta[k] for k in _FIELDS}, "role": role}


def create_map(account_id: str, body: MapCreate) -> dict:
    map_id = new_id()
    meta = {
        **meta_key(map_id),
        **to_item(body.model_dump()),
        "version": 1,
        "created_at": now(),
    }
    meta["footprint"] = {
        "status": "pending",
        "version": 0,
        "count": 0,
        "requested_at": meta["created_at"],
    }
    member = {
        **member_key(map_id, account_id),
        "gsi1pk": f"ACCT#{account_id}",
        "gsi1sk": f"MAP#{map_id}",
        "role": "owner",
        "created_at": meta["created_at"],
    }
    name = table().name
    table().meta.client.transact_write_items(
        TransactItems=[{"Put": {"TableName": name, "Item": item}} for item in (meta, member)]
    )
    return map_view(meta, "owner")


def list_maps(account_id: str) -> list[dict]:
    roles = {m["pk"]: m["role"] for m in query_prefix(f"ACCT#{account_id}", "MAP#", gsi=True)}
    metas = batch_get([{"pk": pk, "sk": "META"} for pk in roles])
    return sorted((map_view(m, roles[m["pk"]]) for m in metas), key=lambda m: m["created_at"])


def delete_map(map_id: str) -> None:
    # MEMBER# items go last: a delete that dies halfway leaves the map listed,
    # so the owner can retry it.
    delete_footprints(map_id)
    keys = [{"pk": i["pk"], "sk": i["sk"]} for i in query_prefix(f"MAP#{map_id}")]
    delete_keys(sorted(keys, key=lambda k: k["sk"].startswith("MEMBER#")))


def hand_off(map_id: str, owner_id: str) -> bool:
    """Promotes the longest-standing other member to owner and drops `owner_id`.

    False, changing nothing, when nobody else is on the map.

    A shared street belongs to everyone on it, so an owner deleting their account
    passes it on rather than taking it from the people still living there.
    """
    others = [
        m for m in query_prefix(f"MAP#{map_id}", "MEMBER#") if m["sk"] != f"MEMBER#{owner_id}"
    ]
    if not others:
        return False
    heir = min(others, key=lambda m: m["created_at"])
    name = table().name
    table().meta.client.transact_write_items(
        TransactItems=[
            {
                "Update": {
                    "TableName": name,
                    "Key": {"pk": heir["pk"], "sk": heir["sk"]},
                    "UpdateExpression": "SET #role = :owner",
                    "ConditionExpression": "attribute_exists(pk)",
                    "ExpressionAttributeNames": {"#role": "role"},
                    "ExpressionAttributeValues": {":owner": "owner"},
                }
            },
            {"Delete": {"TableName": name, "Key": member_key(map_id, owner_id)}},
        ]
    )
    heir_id = heir["sk"].removeprefix("MEMBER#")
    notify([heir_id], "street_handed_to_you", owner_id, map_id, map_name(map_id))
    return True


def add_member(map_id: str, account_id: str) -> dict:
    """Puts a "member" MEMBER item if the map exists and they aren't in it; returns theirs."""
    member = {
        **member_key(map_id, account_id),
        "gsi1pk": f"ACCT#{account_id}",
        "gsi1sk": f"MAP#{map_id}",
        "role": "member",
        "created_at": now(),
    }
    name = table().name
    try:
        table().meta.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": name,
                        "Item": member,
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "ConditionCheck": {
                        "TableName": name,
                        "Key": meta_key(map_id),
                        "ConditionExpression": "attribute_exists(pk)",
                    }
                },
            ]
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        existing = get_item(member_key(map_id, account_id))
        if not existing:
            raise NotFoundError("Map not found", code="map_not_found") from e
        return existing
    return member


def list_members(map_id: str) -> list[dict]:
    """Owner first, then by join time, each with the display name from their PROFILE."""
    members = query_prefix(f"MAP#{map_id}", "MEMBER#")
    ids = [m["sk"].removeprefix("MEMBER#") for m in members]
    names = {p["account_id"]: p["display_name"] for p in batch_get([acct_key(a) for a in ids])}
    rows = [
        {
            "account_id": a,
            "display_name": names.get(a),
            "role": m["role"],
            "created_at": m["created_at"],
        }
        for a, m in zip(ids, members, strict=True)
    ]
    return sorted(rows, key=lambda r: (r["role"] != "owner", r["created_at"]))

"""Map META and MEMBER items."""

from __future__ import annotations

from lambdas.common.dynamo import (
    batch_get,
    delete_keys,
    member_key,
    meta_key,
    new_id,
    now,
    query_prefix,
    table,
    to_item,
)
from lambdas.common.footprints import delete_footprints
from lambdas.common.models import MapCreate

_FIELDS = ("name", "center", "radius_m", "footprint", "version", "created_at")


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

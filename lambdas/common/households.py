"""Household items and the response shape the clients render.

`published` is always null in MVP. Post-MVP it is read from the linked
account's CARD at request time and never stored on these items.
"""

from __future__ import annotations

from collections import defaultdict

from botocore.exceptions import ClientError

from lambdas.common.dynamo import new_id, now, table, to_item
from lambdas.common.errors import NotFoundError
from lambdas.common.models import HouseholdCreate


def hh_key(map_id: str, hh_id: str) -> dict:
    return {"pk": f"MAP#{map_id}", "sk": f"HH#{hh_id}"}


def child_key(map_id: str, hh_id: str, kind: str, child_id: str) -> dict:
    """kind is PERSON or PET."""
    return {"pk": f"MAP#{map_id}", "sk": f"HH#{hh_id}#{kind}#{child_id}"}


def child_view(item: dict) -> dict:
    fields = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    return {"id": item["sk"].rpartition("#")[2], **fields}


def household_view(item: dict, people: list | None = None, pets: list | None = None) -> dict:
    """people/pets None leaves them out, for writes that didn't read the children."""
    private = {k: item.get(k) for k in ("label", "address", "last_talked_at")}
    if people is not None:
        private |= {"people": people, "pets": pets}
    return {
        "id": item["sk"].removeprefix("HH#"),
        "version": item["version"],
        "lat": item["lat"],
        "lng": item["lng"],
        "building_id": item.get("building_id"),
        "private": private,
        "published": None,
    }


def assemble(items: list[dict]) -> list[dict]:
    """Household views, children attached, from HH#<h>[#PERSON#<p>|#PET#<x>] items."""
    households: dict[str, dict] = {}
    children: dict[str, dict[str, list]] = {"PERSON": defaultdict(list), "PET": defaultdict(list)}
    for item in items:
        _, hh_id, *child = item["sk"].split("#")
        if child:
            children[child[0]][hh_id].append(child_view(item))
        else:
            households[hh_id] = item
    return [
        household_view(households[h], children["PERSON"][h], children["PET"][h])
        for h in sorted(households)
    ]


def create_household(map_id: str, body: HouseholdCreate) -> dict:
    item = {
        **hh_key(map_id, new_id()),
        **to_item(body.model_dump(exclude_none=True)),
        "version": 1,
        "created_at": now(),
    }
    table().put_item(Item=item)
    return household_view(item, [], [])


def create_child(map_id: str, hh_id: str, kind: str, fields: dict) -> dict:
    item = {
        **child_key(map_id, hh_id, kind, new_id()),
        **to_item(fields),
        "version": 1,
        "created_at": now(),
    }
    name = table().name
    check = {"TableName": name, "Key": hh_key(map_id, hh_id)}
    try:
        table().meta.client.transact_write_items(
            TransactItems=[
                {"ConditionCheck": {**check, "ConditionExpression": "attribute_exists(pk)"}},
                {"Put": {"TableName": name, "Item": item}},
            ]
        )
    except ClientError as e:
        reasons = e.response.get("CancellationReasons") or [{}]
        if reasons[0].get("Code") != "ConditionalCheckFailed":
            raise
        raise NotFoundError("Household not found", code="household_not_found") from e
    return child_view(item)

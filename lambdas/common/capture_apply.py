"""Confirmed capture ops → one TransactWriteItems.

A transaction may touch each item once, so ops are merged per item first: every
op on an existing household folds into one Update (or a ConditionCheck), and
repeated updates to one person or pet fold into one.
"""

from __future__ import annotations

from collections import defaultdict

from botocore.exceptions import ClientError

from lambdas.common.dynamo import new_id, now, table, to_item
from lambdas.common.errors import ConflictError, PayloadTooLargeError, ValidationError
from lambdas.common.households import child_key, hh_key
from lambdas.common.models import (
    ApplyOp,
    HouseholdCreate,
    HouseholdUpdate,
    NoteCreate,
    PersonCreate,
    PersonUpdate,
    PetCreate,
    PetUpdate,
)
from lambdas.common.notes import note_key

MAX_ITEMS = 100
_CHILD = {
    "add_person": ("PERSON", PersonCreate),
    "add_pet": ("PET", PetCreate),
    "update_person": ("PERSON", PersonUpdate),
    "update_pet": ("PET", PetUpdate),
}


def _update(key: dict, fields: dict, version: int | None, touched_at: str | None) -> dict:
    """SET/REMOVE fields. With a version: conditioned on it and bumped; else on existence."""
    names, values, sets, removes = {}, {}, [], []
    for i, (name, value) in enumerate(to_item(fields).items()):
        names[f"#f{i}"] = name
        if value is None:
            removes.append(f"#f{i}")
        else:
            values[f":f{i}"] = value
            sets.append(f"#f{i} = :f{i}")
    if touched_at:
        names["#lt"], values[":lt"] = "last_talked_at", touched_at
        sets.append("#lt = :lt")
    if version is None:
        condition = "attribute_exists(pk)"
    else:
        names["#v"], values[":v"], values[":one"] = "version", version, 1
        sets.append("#v = #v + :one")
        condition = "#v = :v"
    expression = "SET " + ", ".join(sets) + (" REMOVE " + ", ".join(removes) if removes else "")
    update = {"Key": key, "UpdateExpression": expression, "ConditionExpression": condition}
    return {**update, "ExpressionAttributeNames": names, "ExpressionAttributeValues": values}


def _base(versions: dict[str, int], entity_id: str) -> int:
    if entity_id not in versions:
        raise ValidationError(f"base_versions is missing {entity_id}")
    return versions[entity_id]


def apply_ops(map_id: str, ops: list[ApplyOp], versions: dict[str, int], source: str) -> list:
    created_at = now()
    new_hh: dict[str, dict] = {}  # new:<n> → Put item
    puts: list[dict] = []
    hh_fields: dict[str, dict] = defaultdict(dict)
    touched: set[str] = set()
    referenced: list[str] = []
    child_updates: dict[str, tuple[dict, dict]] = {}
    results = []
    for op in ops:
        ref = op.household_ref
        if op.op == "create_household":
            if not ref.startswith("new:") or ref in new_hh:
                raise ValidationError(f"create_household needs a fresh new:<n>, got {ref}")
            body = HouseholdCreate.model_validate(op.fields).model_dump(exclude_none=True)
            item = {**hh_key(map_id, new_id()), **to_item(body), "version": 1}
            new_hh[ref] = item | {"created_at": created_at}
            results.append({"op": op.op, "id": item["sk"].removeprefix("HH#")})
            continue
        if ref.startswith("new:") and ref not in new_hh:
            raise ValidationError(f"{ref} has no create_household before it")
        hh_id = new_hh[ref]["sk"].removeprefix("HH#") if ref in new_hh else ref
        if ref not in new_hh and hh_id not in referenced:
            referenced.append(hh_id)
        entity_id = hh_id
        if op.op == "update_household":
            patch = HouseholdUpdate.model_validate({**op.fields, "version": 1})
            _base(versions, hh_id)
            hh_fields[hh_id] |= patch.changes()
        elif op.op in ("add_person", "add_pet"):
            kind, model = _CHILD[op.op]
            entity_id = new_id()
            body = model.model_validate(op.fields).model_dump(exclude_none=True)
            key = child_key(map_id, hh_id, kind, entity_id)
            puts.append({**key, **to_item(body), "version": 1, "created_at": created_at})
        elif op.op in ("update_person", "update_pet"):
            kind, model = _CHILD[op.op]
            if not op.target_id:
                raise ValidationError(f"{op.op} needs target_id")
            entity_id = op.target_id
            changes = model.model_validate({**op.fields, "version": 1}).changes()
            key = child_key(map_id, hh_id, kind, entity_id)
            prior = child_updates.get(entity_id, (key, {}))[1]
            child_updates[entity_id] = (key, prior | changes)
        elif op.op == "add_note":
            note = NoteCreate.model_validate({**op.fields, "source": source})
            entity_id = new_id()
            note_item = {**note_key(map_id, hh_id, entity_id), **note.model_dump()}
            puts.append(note_item | {"created_at": created_at})
            touched.add(hh_id)
        else:
            touched.add(hh_id)
        results.append({"op": op.op, "id": entity_id})

    name = table().name
    items = []
    for item in new_hh.values():
        if item["sk"].removeprefix("HH#") in touched:
            item["last_talked_at"] = created_at
        items.append({"Put": {"TableName": name, "Item": item}})
    items += [{"Put": {"TableName": name, "Item": item}} for item in puts]
    for hh_id in referenced:
        key = hh_key(map_id, hh_id)
        touch = created_at if hh_id in touched else None
        if hh_id in hh_fields:
            update = _update(key, hh_fields[hh_id], _base(versions, hh_id), touch)
        elif touch:
            update = _update(key, {}, None, touch)
        else:
            check = {"Key": key, "ConditionExpression": "attribute_exists(pk)"}
            items.append({"ConditionCheck": {"TableName": name, **check}})
            continue
        items.append({"Update": {"TableName": name, **update}})
    for entity_id, (key, fields) in child_updates.items():
        update = _update(key, fields, _base(versions, entity_id), None)
        items.append({"Update": {"TableName": name, **update}})

    if len(items) > MAX_ITEMS:
        raise PayloadTooLargeError(
            f"{len(items)} writes; the limit is {MAX_ITEMS}", code="too_many_operations"
        )
    try:
        table().meta.client.transact_write_items(TransactItems=items)
    except ClientError as e:
        reasons = e.response.get("CancellationReasons") or []
        if not any(r.get("Code") == "ConditionalCheckFailed" for r in reasons):
            raise
        raise ConflictError("Something changed since the parse; parse again") from e
    return results

from __future__ import annotations

import pytest
from conftest import GOLDEN, H1, H2, H3, THEO, call, recorded
from test_capture_parse import parse

from lambdas.capture_apply.handler import handler
from lambdas.common.accounts import create_account

BISCUIT = GOLDEN["households"][0]["pets"][0]["id"]
VERSIONS = {H1: 3, H2: 3, H3: 3, THEO: 2, BISCUIT: 2}


def op(kind, ref, fields=None, target=None):
    return {"op": kind, "household_ref": ref, "target_id": target, "fields": fields or {}}


def apply(map_id, ops, versions=VERSIONS, **kwargs):
    body = {"operations": ops, "base_versions": versions, "source": "voice"}
    return call(handler, body, path={"mapId": map_id}, **kwargs)


def items(table, map_id) -> dict:
    return {i["sk"]: i for i in table.scan()["Items"] if i["pk"] == f"MAP#{map_id}"}


def test_mixed_ops_land_in_one_transaction(golden_map, table, dynamo_calls):
    ops = [
        op("create_household", "new:1", {"label": "Gray house", "lat": 40.1, "lng": -75.1}),
        op("add_person", "new:1", {"name": "Ollie", "role": "kid", "birth_year": 2020}),
        op("add_note", "new:1", {"text": "Moved in Saturday"}),
        op("update_person", H1, {"birthday": "03-03"}, THEO),
        op("add_pet", H1, {"name": "Pickles", "species": "dog"}),
        op("add_note", H2, {"text": "Block party next Saturday"}),
        op("update_household", H3, {"address": "24 Maple Ct"}),
    ]
    dynamo_calls.clear()

    status, body = apply(golden_map, ops)

    assert status == 200
    ids = [r["id"] for r in body["data"]]
    assert [r["op"] for r in body["data"]] == [o["op"] for o in ops]
    writes = [p for o, p in dynamo_calls if o == "TransactWriteItems"]
    assert len(writes) == 1
    kinds = sorted(next(iter(i)) for i in writes[0]["TransactItems"])
    assert set(kinds) <= {"Put", "Update", "ConditionCheck"}
    db = items(table, golden_map)
    new_hh = db[f"HH#{ids[0]}"]
    assert (new_hh["label"], new_hh["version"], new_hh["last_talked_at"]) == (
        "Gray house",
        1,
        new_hh["created_at"],
    )
    assert db[f"HH#{ids[0]}#PERSON#{ids[1]}"]["name"] == "Ollie"
    note = db[f"NOTE#{ids[0]}#{ids[2]}"]
    assert (note["text"], note["source"]) == ("Moved in Saturday", "voice")
    theo = db[f"HH#{H1}#PERSON#{THEO}"]
    assert (theo["birthday"], theo["version"]) == ("03-03", 3)
    assert db[f"HH#{H1}"]["version"] == 3  # child writes don't bump the household
    assert db[f"HH#{H1}#PET#{ids[4]}"]["name"] == "Pickles"
    h2 = db[f"HH#{H2}"]
    assert (h2["version"], "last_talked_at" in h2) == (3, True)
    h3 = db[f"HH#{H3}"]
    assert (h3["address"], h3["version"]) == ("24 Maple Ct", 4)


def test_ops_on_one_item_merge_into_one_write(golden_map, table, dynamo_calls):
    ops = [
        op("update_household", H1, {"label": "Navy house"}),
        op("touch_last_talked", H1),
        op("add_note", H1, {"text": "Fence going up"}),
        op("update_person", H1, {"birthday": "03-03"}, THEO),
        op("update_person", H1, {"notes": "Likes trains"}, THEO),
    ]
    dynamo_calls.clear()

    status, _ = apply(golden_map, ops)

    assert status == 200
    (write,) = [p for o, p in dynamo_calls if o == "TransactWriteItems"]
    assert len(write["TransactItems"]) == 3  # note put, household update, Theo update
    db = items(table, golden_map)
    hh = db[f"HH#{H1}"]
    assert (hh["label"], hh["version"], "last_talked_at" in hh) == ("Navy house", 4, True)
    theo = db[f"HH#{H1}#PERSON#{THEO}"]
    assert (theo["birthday"], theo["notes"], theo["version"]) == ("03-03", "Likes trains", 3)


@pytest.mark.parametrize(
    "ops",
    [
        [op("update_household", H3, {"label": "x"}), op("add_note", H1, {"text": "kept?"})],
        [op("update_person", H1, {"name": "Teddy"}, THEO), op("add_note", H1, {"text": "kept?"})],
    ],
)
def test_stale_version_is_409_and_writes_nothing(golden_map, table, ops):
    before = items(table, golden_map)
    status, body = apply(golden_map, ops, {**VERSIONS, H3: 2, THEO: 1})
    assert (status, body["error"]["code"]) == (409, "version_conflict")
    assert items(table, golden_map) == before


def test_deleted_household_is_409(golden_map, table):
    table.delete_item(Key={"pk": f"MAP#{golden_map}", "sk": f"HH#{H2}"})
    status, _ = apply(golden_map, [op("add_person", H2, {"name": "Mira", "role": "kid"})])
    assert status == 409
    assert "Mira" not in {i.get("name") for i in items(table, golden_map).values()}


def test_over_100_writes_is_413(golden_map, table):
    before = items(table, golden_map)
    notes = [op("add_note", H1, {"text": f"n{i}"}) for i in range(100)]  # 100 puts + 1 update
    status, body = apply(golden_map, notes)
    assert (status, body["error"]["code"]) == (413, "too_many_operations")
    assert items(table, golden_map) == before


def test_exactly_100_writes_is_fine(golden_map):
    people = [op("add_person", H1, {"name": f"P{i}", "role": "adult"}) for i in range(99)]
    assert apply(golden_map, people)[0] == 200  # 99 puts + 1 condition check


@pytest.mark.parametrize(
    "ops, versions",
    [
        ([op("update_household", H1, {"label": "x"})], {}),
        ([op("add_person", "new:2", {"name": "Al", "role": "adult"})], VERSIONS),
        ([op("create_household", "new:1", {"label": "No location"})], VERSIONS),
        ([op("create_household", H1, {"label": "x", "lat": 1, "lng": 1})], VERSIONS),
        ([op("add_person", H1, {"name": "Al", "role": "teen"})], VERSIONS),
        ([op("update_person", H1, {"name": "Al"})], VERSIONS),
        ([op("update_pet", H1, {"color": "red"}, BISCUIT)], VERSIONS),
        ([op("add_note", "nope", {"text": "x"})], VERSIONS),
    ],
)
def test_invalid_ops_are_400(golden_map, table, ops, versions):
    before = items(table, golden_map)
    status, _ = apply(golden_map, ops, versions)
    assert status == 400
    assert items(table, golden_map) == before


def test_non_member_gets_404(golden_map):
    create_account("sub-other", "apple", "Other")
    status, _ = apply(golden_map, [op("touch_last_talked", H1)], sub="sub-other")
    assert status == 404


def test_parse_output_applies_once_the_client_adds_a_location(golden_map, model, table):
    model(recorded("new_household"))
    _, parsed = parse(golden_map, "new_household")
    data = parsed["data"]
    data["operations"][0]["fields"] |= {"lat": 40.2, "lng": -75.2}

    status, body = call(
        handler,
        {
            "operations": data["operations"],
            "base_versions": data["base_versions"],
            "source": "voice",
        },
        path={"mapId": golden_map},
    )

    assert status == 200
    hh_id = body["data"][0]["id"]
    names = {
        i.get("name") for sk, i in items(table, golden_map).items() if sk.startswith(f"HH#{hh_id}#")
    }
    assert names == {"Marcus", "Ollie"}

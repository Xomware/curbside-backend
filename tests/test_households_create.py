from __future__ import annotations

import pytest
from conftest import call

from lambdas.households_create.handler import handler

BODY = {"label": "Blue house", "lat": 40.001, "lng": -75.002}


def test_creates_household_in_fixed_shape(table, map_id):
    status, body = call(handler, {**BODY, "building_id": "osm:way/1"}, path={"mapId": map_id})

    assert status == 201
    hh = body["data"]
    assert hh["version"] == 1
    assert (hh["lat"], hh["lng"], hh["building_id"]) == (40.001, -75.002, "osm:way/1")
    assert hh["private"] == {
        "label": "Blue house",
        "address": None,
        "last_talked_at": None,
        "people": [],
        "pets": [],
    }
    assert hh["published"] is None
    item = table.get_item(Key={"pk": f"MAP#{map_id}", "sk": f"HH#{hh['id']}"})["Item"]
    assert "address" not in item


@pytest.mark.parametrize(
    "bad",
    [{}, {**BODY, "label": ""}, {**BODY, "lat": 100}, {**BODY, "published": {"name": "x"}}],
)
def test_invalid_body_is_400(table, map_id, bad):
    status, _ = call(handler, bad, path={"mapId": map_id})
    assert status == 400


def test_non_member_is_404_and_writes_nothing(table, map_id):
    before = table.scan()["Count"]
    status, body = call(handler, BODY, path={"mapId": "0" * 26})
    assert (status, body["error"]["code"]) == (404, "map_not_found")
    assert table.scan()["Count"] == before

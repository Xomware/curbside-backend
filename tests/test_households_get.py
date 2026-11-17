from __future__ import annotations

from conftest import call

from lambdas.households_get.handler import handler


def test_returns_household_with_children(table, map_id, hh_id):
    pk = f"MAP#{map_id}"
    table.put_item(Item={"pk": pk, "sk": f"HH#{hh_id}#PERSON#P1", "name": "Sam", "version": 1})
    table.put_item(Item={"pk": pk, "sk": f"HH#{hh_id}#PET#X1", "name": "Rex", "version": 1})

    status, body = call(handler, path={"mapId": map_id, "hhId": hh_id})

    assert status == 200
    hh = body["data"]
    assert hh["id"] == hh_id
    assert hh["private"]["people"] == [{"id": "P1", "name": "Sam", "version": 1}]
    assert hh["private"]["pets"] == [{"id": "X1", "name": "Rex", "version": 1}]
    assert hh["published"] is None


def test_missing_household_is_404(table, map_id):
    status, body = call(handler, path={"mapId": map_id, "hhId": "0" * 26})
    assert (status, body["error"]["code"]) == (404, "household_not_found")

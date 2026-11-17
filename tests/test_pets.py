from __future__ import annotations

from conftest import call

from lambdas.households_get.handler import handler as households_get
from lambdas.pets_create.handler import handler as create
from lambdas.pets_delete.handler import handler as delete
from lambdas.pets_update.handler import handler as update


def test_create_update_delete(table, map_id, hh_id):
    status, body = call(
        create, {"name": "Rex", "species": "dog"}, path={"mapId": map_id, "hhId": hh_id}
    )
    assert status == 201
    path = {"mapId": map_id, "hhId": hh_id, "petId": body["data"]["id"]}

    status, body = call(update, {"version": 1, "species": None}, path=path)
    assert (status, body["data"]["version"]) == (200, 2)
    assert "species" not in body["data"]

    _, hh = call(households_get, path={"mapId": map_id, "hhId": hh_id})
    assert [p["name"] for p in hh["data"]["private"]["pets"]] == ["Rex"]

    assert call(delete, path=path)[0] == 200
    assert call(delete, path=path)[1]["error"]["code"] == "pet_not_found"


def test_create_on_missing_household_is_404(table, map_id):
    status, body = call(create, {"name": "Rex"}, path={"mapId": map_id, "hhId": "0" * 26})
    assert (status, body["error"]["code"]) == (404, "household_not_found")


def test_name_cannot_be_cleared(table, map_id, hh_id):
    _, body = call(create, {"name": "Rex"}, path={"mapId": map_id, "hhId": hh_id})
    path = {"mapId": map_id, "hhId": hh_id, "petId": body["data"]["id"]}
    assert call(update, {"version": 1, "name": None}, path=path)[0] == 400

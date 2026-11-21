from __future__ import annotations

import pytest
from conftest import call

from lambdas.common.accounts import create_account
from lambdas.households_get.handler import handler as households_get
from lambdas.people_create.handler import handler as create
from lambdas.people_delete.handler import handler as delete
from lambdas.people_update.handler import handler as update

KID = {"name": "Sam", "role": "kid", "birth_year": 2020, "birth_year_approx": True}


def add(map_id: str, hh_id: str, body: dict) -> tuple[int, dict]:
    return call(create, body, path={"mapId": map_id, "hhId": hh_id})


def test_create_appears_on_household(table, map_id, hh_id):
    status, body = add(map_id, hh_id, {**KID, "birthday": "03-14"})

    assert status == 201
    person = body["data"]
    assert (person["name"], person["version"], person["birthday"]) == ("Sam", 1, "03-14")
    _, hh = call(households_get, path={"mapId": map_id, "hhId": hh_id})
    assert [p["id"] for p in hh["data"]["private"]["people"]] == [person["id"]]


def test_create_on_missing_household_is_404_and_writes_nothing(table, map_id):
    before = table.scan()["Count"]
    status, body = add(map_id, "0" * 26, KID)
    assert (status, body["error"]["code"]) == (404, "household_not_found")
    assert table.scan()["Count"] == before


@pytest.mark.parametrize(
    "bad",
    [
        {**KID, "role": "teen"},
        {**KID, "birthday": "13-01"},
        {**KID, "birth_year": 1800},
        {"role": "kid"},
        {**KID, "email": "not-an-email"},
        {**KID, "email": "a@" + "x" * 253},
        {**KID, "phone": "5" * 41},
        {**KID, "fax": "555-0100"},
    ],
)
def test_invalid_create_is_400(table, map_id, hh_id, bad):
    status, _ = add(map_id, hh_id, bad)
    assert status == 400


def test_contacts_round_trip_and_clear(table, map_id, hh_id):
    contacts = {"phone": "+1 555-0100", "email": "sam@example.com"}
    status, body = add(map_id, hh_id, {**KID, **contacts})
    assert status == 201
    person = body["data"]
    assert (person["phone"], person["email"]) == (contacts["phone"], contacts["email"])

    path = {"mapId": map_id, "hhId": hh_id, "personId": person["id"]}
    status, body = call(update, {"version": 1, "phone": None, "email": "s@example.org"}, path=path)
    assert status == 200
    assert "phone" not in body["data"]
    assert body["data"]["email"] == "s@example.org"


def test_update_is_versioned(table, map_id, hh_id):
    _, created = add(map_id, hh_id, KID)
    path = {"mapId": map_id, "hhId": hh_id, "personId": created["data"]["id"]}

    status, body = call(
        update, {"version": 1, "birth_year": None, "notes": "Likes trains"}, path=path
    )
    assert status == 200
    assert body["data"]["version"] == 2
    assert body["data"]["notes"] == "Likes trains"
    assert "birth_year" not in body["data"]

    status, body = call(update, {"version": 1, "name": "Sammy"}, path=path)
    assert (status, body["error"]["code"]) == (409, "version_conflict")


def test_update_missing_person_is_404(table, map_id, hh_id):
    path = {"mapId": map_id, "hhId": hh_id, "personId": "0" * 26}
    status, body = call(update, {"version": 1, "name": "X"}, path=path)
    assert (status, body["error"]["code"]) == (404, "person_not_found")


def test_delete(table, map_id, hh_id):
    _, created = add(map_id, hh_id, KID)
    path = {"mapId": map_id, "hhId": hh_id, "personId": created["data"]["id"]}

    assert call(delete, path=path)[0] == 200
    status, body = call(delete, path=path)
    assert (status, body["error"]["code"]) == (404, "person_not_found")


def test_non_member_cannot_write(table, map_id, hh_id):
    create_account("sub-other", "apple", "Other")
    status, body = call(create, KID, path={"mapId": map_id, "hhId": hh_id}, sub="sub-other")
    assert (status, body["error"]["code"]) == (404, "map_not_found")

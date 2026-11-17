from __future__ import annotations

import pytest
from conftest import call

from lambdas.households_get.handler import handler as households_get
from lambdas.notes_create.handler import handler as create
from lambdas.notes_delete.handler import handler as delete


def hh_item(table, map_id: str, hh_id: str) -> dict:
    return table.get_item(Key={"pk": f"MAP#{map_id}", "sk": f"HH#{hh_id}"})["Item"]


def test_create_touches_last_talked_without_bumping_version(table, map_id, hh_id):
    path = {"mapId": map_id, "hhId": hh_id}
    status, body = call(create, {"text": "New puppy", "source": "voice"}, path=path)

    assert status == 201
    note = body["data"]
    assert (note["text"], note["source"]) == ("New puppy", "voice")
    hh = hh_item(table, map_id, hh_id)
    assert hh["last_talked_at"] == note["created_at"]
    assert hh["version"] == 1


def test_household_get_returns_newest_50_first(table, map_id, hh_id):
    pk = f"MAP#{map_id}"
    for i in range(55):
        table.put_item(Item={"pk": pk, "sk": f"NOTE#{hh_id}#{i:026d}", "text": str(i)})
    table.put_item(Item={"pk": pk, "sk": f"NOTE#{'Z' * 26}#1", "text": "other household"})

    _, body = call(households_get, path={"mapId": map_id, "hhId": hh_id})

    notes = body["data"]["private"]["notes"]
    assert [n["text"] for n in notes] == [str(i) for i in range(54, 4, -1)]


def test_create_on_missing_household_is_404_and_writes_nothing(table, map_id):
    before = table.scan()["Count"]
    status, body = call(create, {"text": "hi"}, path={"mapId": map_id, "hhId": "0" * 26})
    assert (status, body["error"]["code"]) == (404, "household_not_found")
    assert table.scan()["Count"] == before


@pytest.mark.parametrize(
    "bad", [{}, {"text": " "}, {"text": "x" * 2001}, {"text": "a", "source": "x"}]
)
def test_invalid_note_is_400(table, map_id, hh_id, bad):
    assert call(create, bad, path={"mapId": map_id, "hhId": hh_id})[0] == 400


def test_delete(table, map_id, hh_id):
    _, body = call(create, {"text": "hi"}, path={"mapId": map_id, "hhId": hh_id})
    path = {"mapId": map_id, "hhId": hh_id, "noteId": body["data"]["id"]}

    assert call(delete, path=path)[0] == 200
    status, body = call(delete, path=path)
    assert (status, body["error"]["code"]) == (404, "note_not_found")

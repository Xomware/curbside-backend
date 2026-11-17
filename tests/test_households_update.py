from __future__ import annotations

import pytest
from conftest import call

from lambdas.households_update.handler import handler


def patch(map_id: str, hh_id: str, body: dict) -> tuple[int, dict]:
    return call(handler, body, path={"mapId": map_id, "hhId": hh_id})


def test_updates_and_clears_fields(table, map_id, hh_id):
    status, body = patch(
        map_id,
        hh_id,
        {
            "version": 1,
            "label": "Green house",
            "address": None,
            "last_talked_at": "2026-11-01T18:00:00Z",
        },
    )

    assert status == 200
    hh = body["data"]
    assert hh["version"] == 2
    assert hh["private"] == {
        "label": "Green house",
        "address": None,
        "last_talked_at": "2026-11-01T18:00:00Z",
    }
    item = table.get_item(Key={"pk": f"MAP#{map_id}", "sk": f"HH#{hh_id}"})["Item"]
    assert "address" not in item


def test_stale_version_is_409(table, map_id, hh_id):
    patch(map_id, hh_id, {"version": 1, "label": "A"})
    status, body = patch(map_id, hh_id, {"version": 1, "label": "B"})
    assert (status, body["error"]["code"]) == (409, "version_conflict")


def test_missing_household_is_404(table, map_id):
    status, body = patch(map_id, "0" * 26, {"version": 1, "label": "A"})
    assert (status, body["error"]["code"]) == (404, "household_not_found")


@pytest.mark.parametrize(
    "bad",
    [
        {"version": 1, "label": None},
        {"version": 1, "lat": None},
        {"version": 1, "last_talked_at": "2026-11-01T18:00:00"},
        {"version": 1, "linked_account_id": "A"},
    ],
)
def test_invalid_patch_is_400(table, map_id, hh_id, bad):
    status, _ = patch(map_id, hh_id, bad)
    assert status == 400

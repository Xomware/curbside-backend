from __future__ import annotations

import pytest
from conftest import call

from lambdas.common.accounts import create_account
from lambdas.maps_get.handler import handler


def test_member_gets_map_and_households_without_notes(table, map_id, hh_id):
    pk = f"MAP#{map_id}"
    table.put_item(Item={"pk": pk, "sk": f"HH#{hh_id}#PET#X1", "name": "Rex", "version": 1})
    table.put_item(Item={"pk": pk, "sk": f"NOTE#{hh_id}#N1", "text": "hi"})

    status, body = call(handler, path={"mapId": map_id})

    assert status == 200
    assert body["data"]["map"]["id"] == map_id
    assert body["data"]["map"]["name"] == "Elm St"
    [hh] = body["data"]["households"]
    assert hh["id"] == hh_id
    assert hh["private"]["pets"] == [{"id": "X1", "name": "Rex", "version": 1}]
    assert "notes" not in hh["private"]


def test_non_member_gets_same_404_as_missing(table, map_id):
    create_account("sub-other", "apple", "Other")
    status, body = call(handler, path={"mapId": map_id}, sub="sub-other")
    assert status == 404
    assert body["error"]["code"] == "map_not_found"


@pytest.mark.parametrize("bad", ["01", "x" * 26, ""])
def test_malformed_id_is_404(table, account, bad):
    status, _ = call(handler, path={"mapId": bad})
    assert status == 404

from __future__ import annotations

import pytest
from conftest import call

from lambdas.common.accounts import create_account
from lambdas.maps_get.handler import handler


def test_member_gets_map(table, map_id):
    status, body = call(handler, path={"mapId": map_id})
    assert status == 200
    assert body["data"]["map"]["id"] == map_id
    assert body["data"]["map"]["name"] == "Elm St"


def test_non_member_gets_same_404_as_missing(table, map_id):
    create_account("sub-other", "apple", "Other")
    status, body = call(handler, path={"mapId": map_id}, sub="sub-other")
    assert status == 404
    assert body["error"]["code"] == "map_not_found"


@pytest.mark.parametrize("bad", ["01", "x" * 26, ""])
def test_malformed_id_is_404(table, account, bad):
    status, _ = call(handler, path={"mapId": bad})
    assert status == 404

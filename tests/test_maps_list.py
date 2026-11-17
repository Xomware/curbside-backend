from __future__ import annotations

from conftest import call

from lambdas.common.accounts import create_account
from lambdas.common.maps import create_map
from lambdas.common.models import MapCreate
from lambdas.maps_list.handler import handler


def new_map(account_id: str, name: str) -> str:
    return create_map(account_id, MapCreate(name=name, center={"lat": 1, "lng": 2}))["id"]


def test_lists_only_callers_maps_oldest_first(table, account):
    other = create_account("sub-other", "apple", "Other")[0]["account_id"]
    first, second = new_map(account, "First"), new_map(account, "Second")
    new_map(other, "Not mine")

    status, body = call(handler)

    assert status == 200
    assert [m["id"] for m in body["data"]] == sorted([first, second])
    assert {m["role"] for m in body["data"]} == {"owner"}


def test_no_maps_is_empty_list(table, account):
    assert call(handler) == (200, {"data": [], "error": None, "meta": {}})

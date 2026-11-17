from __future__ import annotations

import json

import pytest
from conftest import api_event

from lambdas.me_create.handler import handler


def create(body: dict | str | None, **kwargs) -> tuple[int, dict]:
    resp = handler(api_event(body, route="POST /me", **kwargs), None)
    return resp["statusCode"], json.loads(resp["body"])


def test_creates_account_and_both_identity_items(table):
    status, body = create({"display_name": "  Test Neighbor  "}, sub="sub-1")

    assert status == 201
    account = body["data"]
    assert account["display_name"] == "Test Neighbor"
    assert len(account["account_id"]) == 26
    a = account["account_id"]
    items = {(i["pk"], i["sk"]): i for i in table.scan()["Items"]}
    assert set(items) == {
        ("IDENT#sub-1", "IDENT"),
        (f"ACCT#{a}", "PROFILE"),
        (f"ACCT#{a}", "IDENT#sub-1"),
    }
    assert items[("IDENT#sub-1", "IDENT")]["account_id"] == a
    assert items[("IDENT#sub-1", "IDENT")]["provider"] == "google"


def test_repeat_returns_same_account_and_writes_nothing(table):
    _, first = create({"display_name": "First"}, sub="sub-1")
    before = table.scan()["Items"]

    status, second = create({"display_name": "Second"}, sub="sub-1")

    assert status == 200
    assert second["data"] == first["data"]
    assert table.scan()["Items"] == before


def test_different_subs_get_different_accounts(table):
    _, a = create({"display_name": "A"}, sub="sub-1")
    _, b = create({"display_name": "B"}, sub="sub-2")
    assert a["data"]["account_id"] != b["data"]["account_id"]


def test_apple_sign_in_records_apple_provider(table):
    create({"display_name": "A"}, sub="sub-1", username="signinwithapple_001.abc")
    item = table.get_item(Key={"pk": "IDENT#sub-1", "sk": "IDENT"})["Item"]
    assert item["provider"] == "apple"


@pytest.mark.parametrize(
    "body",
    [{}, {"display_name": ""}, {"display_name": "   "}, {"display_name": "x" * 81}, "{not json"],
)
def test_invalid_body_is_400_and_writes_nothing(table, body):
    status, resp = create(body, sub="sub-1")
    assert status == 400
    assert resp["error"]["code"] == "invalid_request"
    assert table.scan()["Items"] == []


def test_missing_sub_is_401(table):
    status, resp = create({"display_name": "A"}, sub=None)
    assert status == 401
    assert table.scan()["Items"] == []

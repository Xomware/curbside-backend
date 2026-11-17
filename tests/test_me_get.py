from __future__ import annotations

import json

from conftest import api_event

from lambdas.common.accounts import create_account
from lambdas.me_get.handler import handler


def get(**kwargs) -> tuple[int, dict]:
    resp = handler(api_event(route="GET /me", **kwargs), None)
    return resp["statusCode"], json.loads(resp["body"])


def test_unknown_sub_needs_onboarding(table):
    status, body = get(sub="sub-new")
    assert status == 404
    assert body["data"] is None
    assert body["error"]["code"] == "needs_onboarding"


def test_known_sub_returns_account_and_identities(table):
    profile, _ = create_account("sub-1", "google", "Test Neighbor")
    a = profile["account_id"]
    # A second sign-in linked to the same account, as me_link will write it.
    table.put_item(
        Item={
            "pk": f"ACCT#{a}",
            "sk": "IDENT#sub-2",
            "sub": "sub-2",
            "provider": "apple",
            "account_id": a,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )

    status, body = get(sub="sub-1")

    assert status == 200
    assert body["data"]["account_id"] == a
    assert body["data"]["display_name"] == "Test Neighbor"
    assert {(i["sub"], i["provider"]) for i in body["data"]["identities"]} == {
        ("sub-1", "google"),
        ("sub-2", "apple"),
    }


def test_missing_sub_is_401(table):
    status, body = get(sub=None)
    assert status == 401
    assert body["error"]["code"] == "unauthorized"

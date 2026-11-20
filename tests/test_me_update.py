from __future__ import annotations

import pytest
from conftest import call

from lambdas.me_update.handler import handler


def test_renames_and_returns_account(table, account):
    status, body = call(handler, {"display_name": "  New Name  "})

    assert status == 200
    data = body["data"]
    assert (data["account_id"], data["display_name"]) == (account, "New Name")
    assert [i["sub"] for i in data["identities"]] == ["sub-test-1"]
    assert "created_at" in data
    profile = table.get_item(Key={"pk": f"ACCT#{account}", "sk": "PROFILE"})["Item"]
    assert profile["display_name"] == "New Name"


@pytest.mark.parametrize(
    "bad", [{}, {"display_name": " "}, {"display_name": "x" * 81}, {"display_name": "A", "x": 1}]
)
def test_invalid_body_is_400(table, account, bad):
    status, body = call(handler, bad)
    assert (status, body["error"]["code"]) == (400, "invalid_request")


def test_caller_without_account_needs_onboarding(table):
    status, body = call(handler, {"display_name": "A"}, sub="sub-new")
    assert (status, body["error"]["code"]) == (404, "needs_onboarding")

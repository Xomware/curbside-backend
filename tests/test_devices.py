from __future__ import annotations

import pytest
from conftest import api_event, call

from lambdas.common.accounts import create_account
from lambdas.devices_delete.handler import handler as delete
from lambdas.devices_put.handler import handler as put

TOKEN = "ab" * 32
IOS = {"platform": "ios", "env": "sandbox"}


def register(token: str = TOKEN, body: dict | None = None, sub: str = "sub-test-1") -> dict:
    return put(api_event(body or IOS, sub=sub, path={"token": token}), None)


def devices(table) -> set[tuple[str, str]]:
    return {(i["pk"], i["sk"]) for i in table.scan()["Items"] if "DEVICE" in i["sk"]}


def test_put_registers_token(table, account):
    resp = register(TOKEN.upper())

    assert (resp["statusCode"], resp["body"]) == (204, "")
    assert devices(table) == {(f"ACCT#{account}", f"DEVICE#{TOKEN}"), (f"DEVICE#{TOKEN}", "DEVICE")}
    item = table.get_item(Key={"pk": f"ACCT#{account}", "sk": f"DEVICE#{TOKEN}"})["Item"]
    assert (item["platform"], item["env"], item["token"]) == ("ios", "sandbox", TOKEN)


def test_token_moves_to_the_account_that_registers_it_last(table, account):
    other = create_account("sub-other", "google", "Other")[0]["account_id"]
    register()
    register(sub="sub-other")

    assert devices(table) == {(f"ACCT#{other}", f"DEVICE#{TOKEN}"), (f"DEVICE#{TOKEN}", "DEVICE")}
    holder = table.get_item(Key={"pk": f"DEVICE#{TOKEN}", "sk": "DEVICE"})["Item"]
    assert holder["account_id"] == other

    delete(api_event(sub="sub-test-1", path={"token": TOKEN}), None)
    assert len(devices(table)) == 2


def test_delete_removes_both_items_and_is_idempotent(table, account):
    register()
    for _ in range(2):
        resp = delete(api_event(path={"token": TOKEN}), None)
        assert resp["statusCode"] == 204
    assert devices(table) == set()


@pytest.mark.parametrize(
    "token, body",
    [
        ("not-hex" * 10, IOS),
        ("ab" * 8, IOS),
        (TOKEN, {"platform": "android", "env": "sandbox"}),
        (TOKEN, {"platform": "ios", "env": "dev"}),
    ],
)
def test_invalid_registration_is_400(table, account, token, body):
    status, resp = call(put, body, path={"token": token})
    assert (status, resp["error"]["code"]) == (400, "invalid_request")
    assert devices(table) == set()

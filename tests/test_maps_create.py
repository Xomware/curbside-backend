from __future__ import annotations

import pytest
from conftest import call

from lambdas.maps_create.handler import handler

BODY = {"name": "Elm St", "center": {"lat": 40.123456, "lng": -75.5}}


def test_creates_meta_and_membership(table, account):
    status, body = call(handler, BODY)

    assert status == 201
    m = body["data"]
    assert m["radius_m"] == 300
    assert m["center"] == {"lat": 40.123456, "lng": -75.5}
    assert m["footprint"]["status"] == "pending"
    assert (m["version"], m["role"]) == (1, "owner")
    items = {i["sk"]: i for i in table.scan()["Items"] if i["pk"] == f"MAP#{m['id']}"}
    assert set(items) == {"META", f"MEMBER#{account}"}
    assert items[f"MEMBER#{account}"]["gsi1pk"] == f"ACCT#{account}"


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {**BODY, "name": " "},
        {**BODY, "center": {"lat": 91, "lng": 0}},
        {**BODY, "radius_m": 10},
        {**BODY, "published": {}},
    ],
)
def test_invalid_body_is_400(table, account, bad):
    status, body = call(handler, bad)
    assert status == 400
    assert body["error"]["code"] == "invalid_request"


def test_caller_without_account_needs_onboarding(table):
    status, body = call(handler, BODY, sub="sub-new")
    assert status == 404
    assert body["error"]["code"] == "needs_onboarding"

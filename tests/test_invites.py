from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import call

from lambdas.common import invites
from lambdas.common.accounts import create_account
from lambdas.common.errors import NotFoundError
from lambdas.common.maps import delete_map
from lambdas.invites_accept.handler import handler as accept
from lambdas.invites_create.handler import handler as create
from lambdas.invites_get.handler import handler as get

GUEST = "sub-guest"


@pytest.fixture
def guest(table) -> str:
    return create_account(GUEST, "apple", "Housemate")[0]["account_id"]


@pytest.fixture
def code(map_id) -> str:
    return call(create, path={"mapId": map_id})[1]["data"]["code"]


def joined(table, map_id: str, account_id: str) -> dict | None:
    key = {"pk": f"MAP#{map_id}", "sk": f"MEMBER#{account_id}"}
    return table.get_item(Key=key).get("Item")


def invite_items(table) -> list[dict]:
    return [i for i in table.scan()["Items"] if i["pk"].startswith("INVITE#")]


def test_owner_creates_invite(table, map_id, account):
    status, body = call(create, path={"mapId": map_id})

    assert status == 201
    code = body["data"]["code"]
    assert len(code) == 10 and set(code) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
    expires = datetime.fromisoformat(body["data"]["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)
    (item,) = invite_items(table)
    assert item["sk"] == "INVITE"
    assert (item["map_id"], item["created_by"]) == (map_id, account)
    assert item["ttl"] == int(expires.timestamp())


def test_member_cannot_create_invite(table, map_id, code, guest):
    call(accept, path={"code": code}, sub=GUEST)
    status, body = call(create, path={"mapId": map_id}, sub=GUEST)
    assert (status, body["error"]["code"]) == (403, "owner_only")


def test_non_member_cannot_create_invite(table, map_id, guest):
    status, body = call(create, path={"mapId": map_id}, sub=GUEST)
    assert (status, body["error"]["code"]) == (404, "map_not_found")
    assert invite_items(table) == []


def test_get_shows_map_and_inviter(table, map_id, code, guest):
    status, body = call(get, path={"code": code}, sub=GUEST)

    assert status == 200
    data = body["data"]
    assert data["code"] == code
    assert data["map"] == {"id": map_id, "name": "Elm St"}
    assert data["invited_by"] == "Test Neighbor"
    assert data["already_member"] is False
    assert "expires_at" in data


def test_get_tells_the_owner_they_are_already_in(table, code):
    _, body = call(get, path={"code": code})
    assert body["data"]["already_member"] is True


def expire(table, code: str) -> None:
    # TTL deletion lags, so the item is still there past its ttl.
    table.update_item(
        Key={"pk": f"INVITE#{code}", "sk": "INVITE"},
        UpdateExpression="SET #t = :t",
        ExpressionAttributeNames={"#t": "ttl"},
        ExpressionAttributeValues={":t": int(time.time()) - 1},
    )


@pytest.mark.parametrize("handler", [get, accept])
@pytest.mark.parametrize("case", ["unknown", "malformed", "expired", "map_deleted"])
def test_dead_invite_is_404(table, bucket, map_id, code, guest, handler, case):
    path_code = {"unknown": "0" * 10, "malformed": "abc"}.get(case, code)
    if case == "expired":
        expire(table, code)
    if case == "map_deleted":
        delete_map(map_id)

    status, body = call(handler, path={"code": path_code}, sub=GUEST)

    assert (status, body["error"]["code"]) == (404, "invite_not_found")
    assert joined(table, map_id, guest) is None


def test_accept_joins_as_member_and_spends_invite(table, map_id, code, guest):
    status, body = call(accept, path={"code": code}, sub=GUEST)

    assert status == 200
    assert (body["data"]["id"], body["data"]["role"]) == (map_id, "member")
    assert body["data"]["name"] == "Elm St"
    member = joined(table, map_id, guest)
    assert member["role"] == "member"
    assert (member["gsi1pk"], member["gsi1sk"]) == (f"ACCT#{guest}", f"MAP#{map_id}")
    assert invite_items(table) == []

    create_account("sub-third", "google", "Someone else")
    status, body = call(accept, path={"code": code}, sub="sub-third")
    assert (status, body["error"]["code"]) == (404, "invite_not_found")


def test_accept_when_already_member_leaves_invite_unspent(table, map_id, code, account):
    status, body = call(accept, path={"code": code})

    assert status == 200
    assert (body["data"]["id"], body["data"]["role"]) == (map_id, "owner")
    assert joined(table, map_id, account)["role"] == "owner"
    assert len(invite_items(table)) == 1


def test_double_tapped_accept_returns_the_map(table, map_id, code, guest, monkeypatch):
    # The second request read the invite before the first one spent it.
    real = invites.accept_invite

    def race(c, m, a):
        real(c, m, a)
        real(c, m, a)

    monkeypatch.setattr("lambdas.invites_accept.handler.accept_invite", race)
    status, body = call(accept, path={"code": code}, sub=GUEST)
    assert (status, body["data"]["role"]) == (200, "member")


def test_concurrent_accept_by_someone_else_is_404(table, map_id, code, guest):
    other = create_account("sub-third", "google", "Someone else")[0]["account_id"]
    invites.accept_invite(code, map_id, other)
    with pytest.raises(NotFoundError):
        invites.accept_invite(code, map_id, guest)
    assert joined(table, map_id, guest) is None


def test_invite_from_someone_no_longer_on_the_map_is_404(table, map_id, code, guest, account):
    table.delete_item(Key={"pk": f"MAP#{map_id}", "sk": f"MEMBER#{account}"})

    for handler, method in ((get, "GET"), (accept, "POST")):
        status, body = call(handler, sub=GUEST, path={"code": code})
        assert (status, body["error"]["code"]) == (404, "invite_not_found"), method

from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError
from conftest import api_event, call

from lambdas.activity_list.handler import handler as list_activity
from lambdas.activity_seen.handler import handler as seen
from lambdas.common import activity
from lambdas.common.accounts import create_account
from lambdas.common.activity import notify
from lambdas.common.invites import accept_invite, create_invite
from lambdas.common.maps import hand_off
from lambdas.households_create.handler import handler as households_create
from lambdas.invites_accept.handler import handler as invites_accept
from lambdas.members_delete.handler import handler as members_delete

GUEST = "sub-guest"


@pytest.fixture
def guest(table, map_id, account) -> str:
    guest = create_account(GUEST, "apple", "Housemate")[0]["account_id"]
    accept_invite(create_invite(map_id, account)["code"], map_id, guest)
    return guest


def feed(sub: str = "sub-test-1") -> dict:
    status, body = call(list_activity, sub=sub)
    assert status == 200
    return body["data"]


def kinds(table) -> list[tuple[str, str]]:
    items = table.scan()["Items"]
    return [(i["pk"], i["kind"]) for i in items if i["sk"].startswith("ACTIVITY#")]


def test_accepting_an_invite_tells_the_other_members(table, map_id, account):
    create_account(GUEST, "apple", "Housemate")
    code = create_invite(map_id, account)["code"]

    call(invites_accept, path={"code": code}, sub=GUEST)

    data = feed()
    (item,) = data["items"]
    assert item["kind"] == "member_joined"
    assert (item["actor_name"], item["map_id"], item["map_name"]) == ("Housemate", map_id, "Elm St")
    assert len(item["id"]) == 26 and item["created_at"]
    assert data["unread"] == 1
    assert feed(GUEST) == {"items": [], "unread": 0}


def test_seen_clears_unread(table, account, guest):
    notify([account], "friend_added", guest)
    assert feed()["unread"] == 1

    resp = seen(api_event(), None)

    assert (resp["statusCode"], resp["body"]) == (204, "")
    data = feed()
    assert (len(data["items"]), data["unread"]) == (1, 0)


def test_owner_removing_a_member_tells_them(table, map_id, account, guest):
    call(members_delete, path={"mapId": map_id, "accountId": guest})

    (item,) = feed(GUEST)["items"]
    assert (item["kind"], item["actor_name"]) == ("removed_from_street", "Test Neighbor")


def test_leaving_tells_nobody(table, map_id, account, guest):
    before = kinds(table)
    call(members_delete, path={"mapId": map_id, "accountId": guest}, sub=GUEST)
    assert kinds(table) == before


def test_household_added_reaches_other_members_with_its_label(table, map_id, account, guest):
    body = {"label": "Mossbottoms", "lat": 40.0, "lng": -75.0}
    status, _ = call(households_create, body, path={"mapId": map_id}, sub=GUEST)

    assert status == 201
    item = feed()["items"][0]
    assert (item["kind"], item["household_label"]) == ("household_added", "Mossbottoms")
    assert [i["kind"] for i in feed(GUEST)["items"]] == []


def test_hand_off_tells_the_heir(table, map_id, account, guest):
    assert hand_off(map_id, account)
    (item,) = feed(GUEST)["items"]
    assert (item["kind"], item["map_name"]) == ("street_handed_to_you", "Elm St")


def test_feed_is_newest_first_and_capped(table, account):
    for n in range(60):
        ts = f"2026-01-01T00:00:{n:02d}+00:00"
        item = {"kind": "friend_added", "actor_name": "Sam", "created_at": ts}
        table.put_item(Item={"pk": f"ACCT#{account}", "sk": f"ACTIVITY#{ts}#{n:026d}", **item})

    items = feed()["items"]

    assert len(items) == 50
    assert items[0]["created_at"] == "2026-01-01T00:00:59+00:00"
    assert items[-1]["created_at"] == "2026-01-01T00:00:10+00:00"


def test_a_failed_activity_write_does_not_fail_the_request(table, map_id, guest, monkeypatch):
    class Broken:
        def put_item(self, **_):
            raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "PutItem")

    monkeypatch.setattr(activity, "table", Broken)
    body = {"label": "Mossbottoms", "lat": 40.0, "lng": -75.0}

    status, _ = call(households_create, body, path={"mapId": map_id}, sub=GUEST)

    assert status == 201


def test_missing_caller_is_401(table):
    resp = list_activity(api_event(sub=None), None)
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"]["code"] == "unauthorized"

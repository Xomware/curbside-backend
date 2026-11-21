from __future__ import annotations

import time

import pytest
from conftest import api_event, call

from lambdas.admin_accounts_list.handler import handler as accounts
from lambdas.admin_maps_delete.handler import handler as delete_map
from lambdas.admin_maps_list.handler import handler as maps
from lambdas.admin_stats.handler import handler as stats
from lambdas.common.accounts import create_account
from lambdas.common.households import create_child
from lambdas.common.invites import accept_invite, create_invite
from lambdas.common.models import NoteCreate
from lambdas.common.notes import create_note
from lambdas.me_get.handler import handler as me_get


@pytest.fixture
def admin(table, account) -> str:
    table.update_item(
        Key={"pk": f"ACCT#{account}", "sk": "PROFILE"},
        UpdateExpression="SET is_admin = :t",
        ExpressionAttributeValues={":t": True},
    )
    return account


@pytest.fixture
def guest(table, map_id, account) -> str:
    guest = create_account("sub-guest", "apple", "Housemate")[0]["account_id"]
    accept_invite(create_invite(map_id, account)["code"], map_id, guest)
    return guest


def test_me_reports_is_admin(table, account):
    assert call(me_get)[1]["data"]["is_admin"] is False
    table.update_item(
        Key={"pk": f"ACCT#{account}", "sk": "PROFILE"},
        UpdateExpression="SET is_admin = :t",
        ExpressionAttributeValues={":t": True},
    )
    assert call(me_get)[1]["data"]["is_admin"] is True


@pytest.mark.parametrize("handler", [stats, accounts, maps])
def test_non_admin_is_403(table, account, handler):
    status, body = call(handler)
    assert (status, body["error"]["code"]) == (403, "admin_only")


def test_non_admin_cannot_delete(table, map_id):
    status, body = call(delete_map, path={"mapId": map_id})
    assert (status, body["error"]["code"]) == (403, "admin_only")
    assert table.get_item(Key={"pk": f"MAP#{map_id}", "sk": "META"}).get("Item")


def test_stats(table, admin, map_id, hh_id, guest):
    create_child(map_id, hh_id, "PERSON", {"name": "Theo", "role": "kid"})
    create_child(map_id, hh_id, "PET", {"name": "Biscuit"})
    create_note(map_id, hh_id, NoteCreate(text="hi"))
    create_invite(map_id, admin)
    expired = create_invite(map_id, admin)["code"]
    table.update_item(
        Key={"pk": f"INVITE#{expired}", "sk": "INVITE"},
        UpdateExpression="SET #t = :t",
        ExpressionAttributeNames={"#t": "ttl"},
        ExpressionAttributeValues={":t": int(time.time()) - 1},
    )
    for a, b in ((admin, guest), (guest, admin)):
        table.put_item(Item={"pk": f"ACCT#{a}", "sk": f"FRIEND#{b}", "account_id": b})
    table.put_item(Item={"pk": f"ACCT#{guest}", "sk": "DEVICE#" + "ab" * 32})
    table.put_item(Item={"pk": "DEVICE#" + "ab" * 32, "sk": "DEVICE", "account_id": guest})

    status, body = call(stats)

    assert status == 200
    assert body["data"] == {
        "accounts": 2,
        "maps": 1,
        "households": 1,
        "people": 1,
        "pets": 1,
        "notes": 1,
        "friendships": 1,
        "devices": 1,
        "open_invites": 1,
    }


def test_accounts_newest_first(table, admin, map_id, guest):
    status, body = call(accounts)

    assert status == 200
    rows = body["data"]
    assert [r["account_id"] for r in rows] == sorted([admin, guest], reverse=True)
    by_id = {r["account_id"]: r for r in rows}
    assert by_id[admin]["providers"] == ["google"]
    assert by_id[guest] | {"created_at": None} == {
        "account_id": guest,
        "display_name": "Housemate",
        "created_at": None,
        "providers": ["apple"],
        "map_count": 1,
    }


def test_maps_with_owner_and_counts(table, admin, map_id, hh_id, guest):
    status, body = call(maps)

    assert status == 200
    (row,) = body["data"]
    assert row["created_at"]
    assert {k: v for k, v in row.items() if k != "created_at"} == {
        "map_id": map_id,
        "name": "Elm St",
        "owner_name": "Test Neighbor",
        "member_count": 2,
        "household_count": 1,
    }


def test_admin_deletes_any_map(table, bucket, admin, map_id, hh_id, guest):
    resp = delete_map(api_event(path={"mapId": map_id}), None)

    assert (resp["statusCode"], resp["body"]) == (204, "")
    assert not [i for i in table.scan()["Items"] if i["pk"] == f"MAP#{map_id}"]


def test_deleting_a_missing_map_is_404(table, admin):
    status, body = call(delete_map, path={"mapId": "0" * 26})
    assert (status, body["error"]["code"]) == (404, "map_not_found")

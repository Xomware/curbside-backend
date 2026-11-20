from __future__ import annotations

import pytest
from conftest import call

from lambdas.common.accounts import create_account
from lambdas.common.invites import accept_invite, create_invite
from lambdas.maps_list.handler import handler as list_maps
from lambdas.members_delete.handler import handler as remove
from lambdas.members_list.handler import handler as members


def join(map_id: str, owner: str, sub: str, name: str) -> str:
    account = create_account(sub, "google", name)[0]["account_id"]
    accept_invite(create_invite(map_id, owner)["code"], map_id, account)
    return account


@pytest.fixture
def guest(map_id, account) -> str:
    return join(map_id, account, "sub-guest", "Housemate")


def test_lists_owner_first_with_names(table, map_id, account, guest):
    join(map_id, account, "sub-third", "Roommate")

    status, body = call(members, path={"mapId": map_id}, sub="sub-guest")

    assert status == 200
    rows = body["data"]
    assert [(r["display_name"], r["role"]) for r in rows] == [
        ("Test Neighbor", "owner"),
        ("Housemate", "member"),
        ("Roommate", "member"),
    ]
    assert (rows[0]["account_id"], rows[1]["account_id"]) == (account, guest)
    assert all(r["created_at"] for r in rows)


def test_non_member_cannot_list(table, map_id):
    create_account("sub-other", "google", "Other")
    status, body = call(members, path={"mapId": map_id}, sub="sub-other")
    assert (status, body["error"]["code"]) == (404, "map_not_found")


def remaining(table, map_id: str) -> set[str]:
    return {i["sk"] for i in table.scan()["Items"] if i["pk"] == f"MAP#{map_id}"}


def test_owner_removes_member(table, map_id, account, guest):
    status, body = call(remove, path={"mapId": map_id, "accountId": guest})

    assert (status, body["data"]) == (200, {"removed": True})
    assert remaining(table, map_id) == {"META", f"MEMBER#{account}"}
    assert call(list_maps, sub="sub-guest")[1]["data"] == []


def test_member_leaves(table, map_id, account, guest):
    status, _ = call(remove, path={"mapId": map_id, "accountId": guest}, sub="sub-guest")
    assert status == 200
    assert remaining(table, map_id) == {"META", f"MEMBER#{account}"}


def test_owner_cannot_leave(table, map_id, account, guest):
    status, body = call(remove, path={"mapId": map_id, "accountId": account})
    assert (status, body["error"]["code"]) == (409, "owner_cannot_leave")
    assert f"MEMBER#{account}" in remaining(table, map_id)


def test_member_cannot_remove_others(table, map_id, account, guest):
    third = join(map_id, account, "sub-third", "Roommate")
    for target in (account, third):
        path = {"mapId": map_id, "accountId": target}
        status, body = call(remove, path=path, sub="sub-guest")
        assert (status, body["error"]["code"]) == (403, "owner_only")
    assert len(remaining(table, map_id)) == 4


def test_removing_someone_not_in_the_map_is_404(table, map_id):
    other = create_account("sub-other", "google", "Other")[0]["account_id"]
    status, body = call(remove, path={"mapId": map_id, "accountId": other})
    assert (status, body["error"]["code"]) == (404, "member_not_found")


def test_non_member_cannot_remove(table, map_id, guest):
    create_account("sub-other", "google", "Other")
    path = {"mapId": map_id, "accountId": guest}
    status, body = call(remove, path=path, sub="sub-other")
    assert (status, body["error"]["code"]) == (404, "map_not_found")

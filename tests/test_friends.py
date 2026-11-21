from __future__ import annotations

import time

import pytest
from conftest import api_event, call

from lambdas.common.accounts import create_account
from lambdas.common.friends import make_friends
from lambdas.common.invites import create_invite
from lambdas.common.maps import create_map
from lambdas.common.models import MapCreate
from lambdas.friend_invites_accept.handler import handler as accept
from lambdas.friend_invites_create.handler import handler as create
from lambdas.friend_invites_get.handler import handler as get
from lambdas.friends_delete.handler import handler as delete
from lambdas.friends_list.handler import handler as list_friends
from lambdas.invites_accept.handler import handler as invites_accept
from lambdas.members_create.handler import handler as add_member

PAL = "sub-pal"


@pytest.fixture
def pal(table) -> str:
    return create_account(PAL, "apple", "Pal")[0]["account_id"]


@pytest.fixture
def code(account) -> str:
    return call(create)[1]["data"]["code"]


def edges(table) -> set[tuple[str, str]]:
    return {(i["pk"], i["sk"]) for i in table.scan()["Items"] if i["sk"].startswith("FRIEND#")}


def links(table) -> list[dict]:
    return [i for i in table.scan()["Items"] if i["pk"].startswith("FRIENDINVITE#")]


def activity(table, account_id: str) -> list[str]:
    items = table.scan()["Items"]
    return [i["kind"] for i in items if i["pk"] == f"ACCT#{account_id}" and "kind" in i]


def test_create_link(table, account):
    status, body = call(create)

    assert status == 201
    code = body["data"]["code"]
    assert len(code) == 10
    (item,) = links(table)
    assert (item["sk"], item["created_by"]) == ("FRIENDINVITE", account)
    assert item["expires_at"] == body["data"]["expires_at"]


def test_get_shows_inviter(table, code, pal):
    status, body = call(get, path={"code": code}, sub=PAL)
    assert status == 200
    assert body["data"]["inviter"] == {"display_name": "Test Neighbor"}
    assert body["data"]["expires_at"]


def expire(table, code: str) -> None:
    table.update_item(
        Key={"pk": f"FRIENDINVITE#{code}", "sk": "FRIENDINVITE"},
        UpdateExpression="SET #t = :t",
        ExpressionAttributeNames={"#t": "ttl"},
        ExpressionAttributeValues={":t": int(time.time()) - 1},
    )


@pytest.mark.parametrize("handler", [get, accept])
@pytest.mark.parametrize("case", ["unknown", "malformed", "expired", "inviter_gone"])
def test_dead_link_is_404(table, account, code, pal, handler, case):
    path_code = {"unknown": "0" * 10, "malformed": "abc"}.get(case, code)
    if case == "expired":
        expire(table, code)
    if case == "inviter_gone":
        table.delete_item(Key={"pk": f"ACCT#{account}", "sk": "PROFILE"})

    status, body = call(handler, path={"code": path_code}, sub=PAL)

    assert (status, body["error"]["code"]) == (404, "invite_not_found")
    assert edges(table) == set()


def test_accept_makes_friends_both_ways_and_spends_link(table, account, code, pal):
    status, body = call(accept, path={"code": code}, sub=PAL)

    assert status == 200
    friend = body["data"]
    assert (friend["account_id"], friend["display_name"]) == (account, "Test Neighbor")
    assert friend["since"] and friend["shared_maps"] == []
    assert edges(table) == {
        (f"ACCT#{account}", f"FRIEND#{pal}"),
        (f"ACCT#{pal}", f"FRIEND#{account}"),
    }
    assert links(table) == []
    assert activity(table, account) == ["friend_added"]
    assert activity(table, pal) == []

    create_account("sub-third", "google", "Third")
    status, body = call(accept, path={"code": code}, sub="sub-third")
    assert (status, body["error"]["code"]) == (404, "invite_not_found")


def test_accepting_own_link_is_409(table, code):
    status, body = call(accept, path={"code": code})
    assert (status, body["error"]["code"]) == (409, "own_invite")
    assert len(links(table)) == 1


def test_already_friends_leaves_link_unspent(table, account, code, pal):
    make_friends(account, pal)
    status, body = call(accept, path={"code": code}, sub=PAL)
    assert (status, body["data"]["account_id"]) == (200, account)
    assert len(links(table)) == 1
    assert activity(table, account) == []


def test_list_is_by_name_with_shared_streets(table, account, map_id, pal):
    zed = create_account("sub-zed", "google", "zed")[0]["account_id"]
    make_friends(account, zed)
    make_friends(account, pal)
    # Pal is on Elm St with the caller; their own Oak St isn't shared.
    call(invites_accept, path={"code": create_invite(map_id, account)["code"]}, sub=PAL)
    create_map(pal, MapCreate(name="Oak St", center={"lat": 41, "lng": -74}))

    status, body = call(list_friends)

    assert status == 200
    rows = body["data"]
    assert [r["display_name"] for r in rows] == ["Pal", "zed"]
    assert rows[0]["shared_maps"] == [{"map_id": map_id, "name": "Elm St"}]
    assert rows[1]["shared_maps"] == []


def test_street_invite_accept_makes_inviter_and_joiner_friends(table, account, map_id, pal):
    code = create_invite(map_id, account)["code"]
    call(invites_accept, path={"code": code}, sub=PAL)
    assert edges(table) == {
        (f"ACCT#{account}", f"FRIEND#{pal}"),
        (f"ACCT#{pal}", f"FRIEND#{account}"),
    }


def test_delete_removes_both_edges_and_is_idempotent(table, account, pal):
    make_friends(account, pal)
    for _ in range(2):
        resp = delete(api_event(path={"accountId": pal}), None)
        assert (resp["statusCode"], resp["body"]) == (204, "")
    assert edges(table) == set()


def test_add_friend_to_street(table, account, map_id, pal):
    housemate = create_account("sub-house", "google", "Housemate")[0]["account_id"]
    call(invites_accept, path={"code": create_invite(map_id, account)["code"]}, sub="sub-house")
    make_friends(housemate, pal)

    status, body = call(add_member, {"account_id": pal}, path={"mapId": map_id}, sub="sub-house")

    assert status == 201
    member = body["data"]
    assert (member["account_id"], member["display_name"], member["role"]) == (pal, "Pal", "member")
    assert member["created_at"]
    item = table.get_item(Key={"pk": f"MAP#{map_id}", "sk": f"MEMBER#{pal}"})["Item"]
    assert (item["gsi1pk"], item["gsi1sk"]) == (f"ACCT#{pal}", f"MAP#{map_id}")
    assert activity(table, pal) == ["added_to_street"]
    assert activity(table, account) == ["member_joined", "member_joined"]
    assert activity(table, housemate) == []

    status, body = call(add_member, {"account_id": pal}, path={"mapId": map_id}, sub="sub-house")
    assert (status, body["data"]["created_at"]) == (200, member["created_at"])
    assert activity(table, pal) == ["added_to_street"]


def test_adding_a_non_friend_is_403(table, account, map_id, pal):
    status, body = call(add_member, {"account_id": pal}, path={"mapId": map_id})
    assert (status, body["error"]["code"]) == (403, "not_friend")
    assert table.get_item(Key={"pk": f"MAP#{map_id}", "sk": f"MEMBER#{pal}"}).get("Item") is None


def test_non_member_cannot_add(table, map_id, pal):
    other = create_account("sub-other", "google", "Other")[0]["account_id"]
    make_friends(other, pal)
    status, body = call(add_member, {"account_id": pal}, path={"mapId": map_id}, sub="sub-other")
    assert (status, body["error"]["code"]) == (404, "map_not_found")


def test_add_member_rejects_bad_body(table, map_id):
    status, body = call(add_member, {"account_id": "nope"}, path={"mapId": map_id})
    assert (status, body["error"]["code"]) == (400, "invalid_request")

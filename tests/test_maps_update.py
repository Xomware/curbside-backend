from __future__ import annotations

import pytest
from conftest import call

from lambdas.common.accounts import create_account
from lambdas.common.invites import accept_invite, create_invite
from lambdas.maps_update.handler import handler


def test_updates_and_bumps_version(table, map_id):
    status, body = call(
        handler, {"version": 1, "name": "Oak St", "radius_m": 500}, path={"mapId": map_id}
    )
    assert status == 200
    assert body["data"]["name"] == "Oak St"
    assert body["data"]["radius_m"] == 500
    assert body["data"]["version"] == 2
    assert body["data"]["center"] == {"lat": 40, "lng": -75}


def test_stale_version_is_409_and_writes_nothing(table, map_id):
    call(handler, {"version": 1, "name": "Oak St"}, path={"mapId": map_id})

    status, body = call(handler, {"version": 1, "name": "Pine St"}, path={"mapId": map_id})

    assert status == 409
    assert body["error"]["code"] == "version_conflict"
    meta = table.get_item(Key={"pk": f"MAP#{map_id}", "sk": "META"})["Item"]
    assert (meta["name"], meta["version"]) == ("Oak St", 2)


@pytest.mark.parametrize(
    "bad", [{"name": "x"}, {"version": 1}, {"version": 1, "name": None}, {"version": 1, "x": 1}]
)
def test_invalid_body_is_400(table, map_id, bad):
    status, _ = call(handler, bad, path={"mapId": map_id})
    assert status == 400


def test_missing_map_is_404(table, map_id):
    status, body = call(handler, {"version": 1, "name": "Mine"}, path={"mapId": "0" * 26})
    assert status == 404
    assert body["error"]["code"] == "map_not_found"


def test_member_cannot_update(table, map_id, account):
    guest = create_account("sub-guest", "google", "Housemate")[0]["account_id"]
    accept_invite(create_invite(map_id, account)["code"], map_id, guest)

    status, body = call(
        handler, {"version": 1, "name": "Mine"}, path={"mapId": map_id}, sub="sub-guest"
    )

    assert (status, body["error"]["code"]) == (403, "owner_only")

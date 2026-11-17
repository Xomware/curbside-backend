from __future__ import annotations

from datetime import UTC, datetime, timedelta

import requests
from conftest import call, named_attributes

from lambdas.common.accounts import create_account
from lambdas.common.footprints import put_footprints, set_footprint
from lambdas.footprints_get.handler import handler as get
from lambdas.footprints_refresh.handler import handler as refresh

GET_ATTRS = {"pk", "sk", "role", "footprint"}


def ready(map_id, version=2):
    put_footprints(map_id, version, [{"type": "Feature", "id": "osm:way/1"}])
    set_footprint(map_id, {"status": "ready", "source": "osm", "version": version, "count": 1})


def test_pending_is_202(table, map_id):
    status, body = call(get, path={"mapId": map_id})
    assert (status, body["data"]) == (202, {"status": "pending"})


def test_ready_returns_a_presigned_url_for_the_version(table, bucket, map_id):
    ready(map_id)

    status, body = call(get, path={"mapId": map_id})

    data = body["data"]
    assert status == 200
    assert (data["status"], data["source"], data["version"], data["count"]) == (
        "ready",
        "osm",
        2,
        1,
    )
    assert f"footprints/{map_id}/v2.geojson.gz" in data["url"]
    assert "X-Amz-Expires=300" in data["url"]
    # moto serves presigned URLs through requests, not urllib.
    resp = requests.get(data["url"], timeout=5)
    assert resp.status_code == 200
    assert b"osm:way/1" in resp.content


def test_empty_or_failed_has_no_url(table, bucket, map_id):
    set_footprint(map_id, {"status": "empty", "source": "osm", "version": 1, "count": 0})
    _, body = call(get, path={"mapId": map_id})
    assert (body["data"]["status"], body["data"]["url"]) == ("empty", None)


def test_non_member_gets_404(table, map_id):
    create_account("sub-other", "apple", "Other")
    for handler in (get, refresh):
        status, body = call(handler, path={"mapId": map_id}, sub="sub-other")
        assert (status, body["error"]["code"]) == (404, "map_not_found")


def test_get_stays_inside_the_roles_attribute_list(table, bucket, map_id, dynamo_calls):
    ready(map_id)
    dynamo_calls.clear()
    call(get, path={"mapId": map_id})
    map_reads = [p for _, p in dynamo_calls if p["Key"]["pk"]["S"].startswith("MAP#")]
    assert len(map_reads) == 2
    for params in map_reads:
        assert params["ProjectionExpression"]
        assert named_attributes(params) <= GET_ATTRS


def age_request(table, map_id, minutes):
    at = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    table.update_item(
        Key={"pk": f"MAP#{map_id}", "sk": "META"},
        UpdateExpression="SET footprint.requested_at = :t",
        ExpressionAttributeValues={":t": at},
    )


def test_refresh_marks_pending_keeps_version_and_invokes(
    table, bucket, map_id, lambdas, dynamo_calls
):
    ready(map_id)
    age_request(table, map_id, 6)
    dynamo_calls.clear()

    status, body = call(refresh, path={"mapId": map_id})

    assert (status, body["data"]) == (202, {"status": "pending"})
    fp = table.get_item(Key={"pk": f"MAP#{map_id}", "sk": "META"})["Item"]["footprint"]
    assert (fp["status"], fp["version"]) == ("pending", 2)
    assert lambdas.invokes[-1]["Payload"] == {"map_id": map_id}
    for _, params in dynamo_calls:
        if params["Key"]["pk"]["S"].startswith("MAP#"):
            assert named_attributes(params) <= GET_ATTRS
            assert params.get("ProjectionExpression") or params.get("ReturnValues") == "NONE"


def test_refresh_within_5_minutes_is_429(table, map_id, lambdas):
    # A new map has just requested its first fetch.
    status, body = call(refresh, path={"mapId": map_id})
    assert (status, body["error"]["code"]) == (429, "refresh_too_soon")
    assert lambdas.invokes == []


def test_refresh_frees_a_map_stuck_pending(table, map_id, lambdas):
    age_request(table, map_id, 30)
    status, _ = call(refresh, path={"mapId": map_id})
    assert status == 202
    assert len(lambdas.invokes) == 1

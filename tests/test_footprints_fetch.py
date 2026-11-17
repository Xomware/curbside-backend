from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import boto3
import pytest
from conftest import named_attributes

from lambdas.common import overpass
from lambdas.footprints_fetch.handler import handler

FIXTURES = Path(__file__).parent / "fixtures" / "overpass"
FETCH_ATTRS = {"pk", "sk", "center", "radius_m", "footprint"}


class FakeOverpass:
    """Replays a scripted response per POST: a fixture name, a dict body, or an exception."""

    def __init__(self, *responses: str | dict | Exception) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []
        self.user_agents: list[str] = []
        self.sleeps: list[float] = []

    def urlopen(self, request, timeout):
        self.urls.append(request.full_url)
        self.user_agents.append(request.get_header("User-agent"))
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        body = (FIXTURES / f"{resp}.json").read_bytes() if isinstance(resp, str) else resp
        return io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())


@pytest.fixture
def fake(monkeypatch):
    def install(*responses):
        f = FakeOverpass(*responses)
        monkeypatch.setattr(overpass, "urlopen", f.urlopen)
        monkeypatch.setattr(overpass, "sleep", f.sleeps.append)
        return f

    return install


def http_error(code: int) -> HTTPError:
    return HTTPError(overpass.INSTANCES[0], code, "err", None, None)


def footprint(table, map_id) -> dict:
    return table.get_item(Key={"pk": f"MAP#{map_id}", "sk": "META"})["Item"]["footprint"]


def stored(bucket, map_id, version) -> dict:
    obj = boto3.client("s3").get_object(
        Bucket=bucket, Key=f"footprints/{map_id}/v{version}.geojson.gz"
    )
    assert obj["ContentEncoding"] == "gzip"
    return json.loads(gzip.decompress(obj["Body"].read()))


def test_ways_become_features_in_s3_and_meta_ready(table, bucket, map_id, fake):
    f = fake("independence_hall")

    handler({"map_id": map_id}, None)

    fc = stored(bucket, map_id, 1)
    assert [x["id"] for x in fc["features"]][:2] == ["osm:way/25271595", "osm:way/40083518"]
    hall = fc["features"][0]
    assert hall["geometry"]["type"] == "Polygon"
    ring = hall["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert all(len(str(c).split(".")[1]) <= 6 for c in ring[0])
    assert hall["properties"]["building"] == "yes"
    assert 500 < hall["properties"]["area_m2"] < 2000
    assert hall["properties"]["accessory"] is False
    fp = footprint(table, map_id)
    assert (fp["status"], fp["source"], fp["version"], fp["count"]) == ("ready", "osm", 1, 5)
    assert f.urls == [overpass.INSTANCES[0]]
    assert f.user_agents == ["curbside/0.1 (+https://github.com/Xomware/curbside-backend)"]


def test_relation_joins_outer_and_inner_rings(table, bucket, map_id, fake):
    fake("pentagon")

    handler({"map_id": map_id}, None)

    pentagon = next(x for x in stored(bucket, map_id, 1)["features"] if "relation" in x["id"])
    assert pentagon["id"] == "osm:relation/89605"
    rings = pentagon["geometry"]["coordinates"]
    assert pentagon["geometry"]["type"] == "Polygon" and len(rings) > 1
    assert all(r[0] == r[-1] for r in rings)
    # Roughly 116,000 m² of footprint once the courtyards are subtracted.
    assert 80_000 < pentagon["properties"]["area_m2"] < 150_000


def test_open_member_ways_are_stitched_into_one_ring():
    square = [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.001}, {"lat": 0.001, "lon": 0.001}]
    rest = [{"lat": 0.0, "lon": 0.0}, {"lat": 0.001, "lon": 0.0}, {"lat": 0.001, "lon": 0.001}]
    relation = {
        "type": "relation",
        "id": 7,
        "tags": {"building": "yes"},
        "members": [
            {"type": "way", "role": "outer", "geometry": square},
            {"type": "way", "role": "outer", "geometry": rest},
        ],
    }
    (feature,) = overpass.to_features([relation])
    assert len(feature["geometry"]["coordinates"][0]) == 5
    assert 12_000 < feature["properties"]["area_m2"] < 12_500


def box(element_id: int, building: str, size_deg: float) -> dict:
    pts = [(0, 0), (0, size_deg), (size_deg, size_deg), (size_deg, 0), (0, 0)]
    return {
        "type": "way",
        "id": element_id,
        "tags": {"building": building},
        "geometry": [{"lat": 40 + a, "lon": -75 + b} for a, b in pts],
    }


def test_accessory_by_tag_or_small_area():
    features = overpass.to_features(
        [box(1, "house", 0.0002), box(2, "shed", 0.0002), box(3, "yes", 0.00003)]
    )
    assert [f["properties"]["accessory"] for f in features] == [False, True, True]


def test_429_waits_30s_then_uses_second_instance(table, bucket, map_id, fake):
    f = fake(http_error(429), "independence_hall")
    handler({"map_id": map_id}, None)
    assert f.sleeps == [30]
    assert f.urls == list(overpass.INSTANCES)
    assert footprint(table, map_id)["status"] == "ready"


@pytest.mark.parametrize(
    "failure",
    [
        http_error(502),
        URLError("down"),
        TimeoutError(),
        {"elements": [], "remark": "runtime error: Query timed out"},
    ],
)
def test_other_failures_fall_back_without_waiting(table, bucket, map_id, fake, failure):
    f = fake(failure, "independence_hall")
    handler({"map_id": map_id}, None)
    assert (f.sleeps, f.urls) == ([], list(overpass.INSTANCES))
    assert footprint(table, map_id)["count"] == 5


def test_both_instances_failing_marks_failed_and_keeps_version(table, bucket, map_id, fake):
    fake("independence_hall")
    handler({"map_id": map_id}, None)
    fake(http_error(429), http_error(504))

    handler({"map_id": map_id}, None)

    fp = footprint(table, map_id)
    assert (fp["status"], fp["version"], fp["count"]) == ("failed", 1, 5)


def test_no_buildings_is_empty_with_no_object(table, bucket, map_id, fake):
    fake({"elements": []})
    handler({"map_id": map_id}, None)
    fp = footprint(table, map_id)
    assert (fp["status"], fp["version"], fp["count"]) == ("empty", 1, 0)
    assert "Contents" not in boto3.client("s3").list_objects_v2(Bucket=bucket)


def test_versions_only_grow(table, bucket, map_id, fake):
    fake("independence_hall", {"elements": []}, "pentagon")
    for _ in range(3):
        handler({"map_id": map_id}, None)
    assert footprint(table, map_id)["version"] == 3
    stored(bucket, map_id, 3)


def test_deleted_map_is_not_recreated(table, bucket, map_id, fake):
    f = fake()
    table.delete_item(Key={"pk": f"MAP#{map_id}", "sk": "META"})
    handler({"map_id": map_id}, None)
    assert f.urls == []
    assert "Item" not in table.get_item(Key={"pk": f"MAP#{map_id}", "sk": "META"})


def test_stays_inside_the_roles_attribute_list(table, bucket, map_id, fake, dynamo_calls):
    fake("independence_hall")
    handler({"map_id": map_id}, None)

    ops = [op for op, _ in dynamo_calls]
    assert ops == ["GetItem", "UpdateItem"]
    for op, params in dynamo_calls:
        assert named_attributes(params) <= FETCH_ATTRS
        if op == "GetItem":
            assert params["ProjectionExpression"]
        else:
            assert params["ReturnValues"] == "NONE"

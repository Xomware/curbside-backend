"""Async, no route - Fetch a map's building footprints from Overpass into S3.

Payload: {"map_id": "<ULID>"}, from maps_create or footprints_refresh.
Writes footprints/<mapId>/v<n>.geojson.gz and sets META.footprint to ready or empty
with version n, or marks it failed and keeps the version when both Overpass
instances fail. A crash leaves it pending for the user to refresh.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.dynamo import get_item, meta_key
from lambdas.common.footprints import put_footprints, set_footprint
from lambdas.common.logger import log
from lambdas.common.overpass import OverpassError, fetch_buildings, to_features

HANDLER = "footprints_fetch"


def handler(event: dict, context: Any) -> None:
    map_id: str = event["map_id"]
    # Projected: this role may only read these attributes of a MAP# item.
    meta = get_item(meta_key(map_id), ("pk", "sk", "center", "radius_m", "footprint"))
    if not meta:
        log.info(HANDLER, extra={"map_id": map_id, "outcome": "map_gone"})
        return
    old = meta["footprint"]
    version = int(old["version"]) + 1
    center = meta["center"]
    try:
        elements = fetch_buildings(
            float(center["lat"]), float(center["lng"]), int(meta["radius_m"])
        )
    except OverpassError as e:
        set_footprint(map_id, {**old, "status": "failed"})
        log.error(HANDLER, extra={"map_id": map_id, "outcome": "failed", "http_status": e.status})
        return
    features = to_features(elements)
    if features:
        put_footprints(map_id, version, features)
    status = "ready" if features else "empty"
    set_footprint(
        map_id,
        {**old, "status": status, "source": "osm", "version": version, "count": len(features)},
    )
    log.info(HANDLER, extra={"map_id": map_id, "outcome": status, "count": len(features)})

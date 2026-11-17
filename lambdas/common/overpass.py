"""Building footprints from Overpass (OSM), as GeoJSON features.

Usage policy: identify the app in the User-Agent, pause 30 s after a 429, and keep
volume low (RESEARCH.md §5). One query per map create or refresh.
"""

from __future__ import annotations

import itertools
import json
import math
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from lambdas.common.logger import log

INSTANCES = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
USER_AGENT = "curbside/0.1 (+https://github.com/Xomware/curbside-backend)"
ACCESSORY_TAGS = frozenset({"garage", "garages", "shed", "carport"})
ACCESSORY_MAX_M2 = 30
_M_PER_DEG = 6_371_008.8 * math.pi / 180


class OverpassError(Exception):
    def __init__(self, status: int | None) -> None:
        super().__init__(f"Overpass failed: {status}")
        self.status = status


def _post(url: str, query: str) -> list[dict]:
    request = Request(
        url, data=urlencode({"data": query}).encode(), headers={"User-Agent": USER_AGENT}
    )
    try:
        with urlopen(request, timeout=40) as resp:
            body = json.load(resp)
    except HTTPError as e:
        raise OverpassError(e.code) from e
    except (URLError, TimeoutError, ValueError) as e:
        raise OverpassError(None) from e
    # Overpass answers 200 with partial elements when its own timeout hits.
    if "runtime error" in body.get("remark", ""):
        raise OverpassError(None)
    return body["elements"]


def fetch_buildings(lat: float, lng: float, radius_m: int) -> list[dict]:
    """Elements from the first instance, else one retry on the second."""
    around = f"(around:{radius_m},{lat},{lng})"
    query = (
        f'[out:json][timeout:25];(way["building"]{around};relation["building"]{around};);out geom;'
    )
    try:
        return _post(INSTANCES[0], query)
    except OverpassError as e:
        log.warning("overpass_failed", extra={"instance": 0, "http_status": e.status})
        if e.status == 429:
            sleep(30)
    return _post(INSTANCES[1], query)


def _coords(geometry: list[dict]) -> list[list[float]]:
    return [[round(p["lon"], 6), round(p["lat"], 6)] for p in geometry]


def _join(segments: list[list[list[float]]]) -> list[list[list[float]]]:
    """Closed rings from multipolygon member ways, which may each be a piece of one."""
    rings, pending = [], [s for s in segments if s]
    while pending:
        ring = pending.pop(0)
        while ring[0] != ring[-1]:
            for i, seg in enumerate(pending):
                if seg[0] == ring[-1] or seg[-1] == ring[-1]:
                    ring = ring + (seg if seg[0] == ring[-1] else seg[::-1])[1:]
                    pending.pop(i)
                    break
            else:
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def _area(ring: list[list[float]]) -> float:
    k = _M_PER_DEG * math.cos(math.radians(ring[0][1]))
    pts = [(x * k, y * _M_PER_DEG) for x, y in ring]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in itertools.pairwise(pts))) / 2


def _feature(element: dict) -> dict | None:
    if element["type"] == "way":
        outers, inners = _join([_coords(element.get("geometry", []))]), []
    else:
        members = [m for m in element.get("members", []) if m["type"] == "way"]
        outers = _join([_coords(m.get("geometry", [])) for m in members if m["role"] == "outer"])
        inners = _join([_coords(m.get("geometry", [])) for m in members if m["role"] == "inner"])
    if not outers:
        return None
    if len(outers) == 1:
        geometry = {"type": "Polygon", "coordinates": [outers[0], *inners]}
        area = _area(outers[0]) - sum(map(_area, inners))
    else:
        # Holes only matter for rendering a courtyard; a tap target doesn't need them.
        geometry = {"type": "MultiPolygon", "coordinates": [[o] for o in outers]}
        area = sum(map(_area, outers))
    building = element.get("tags", {}).get("building", "yes")
    return {
        "type": "Feature",
        "id": f"osm:{element['type']}/{element['id']}",
        "geometry": geometry,
        "properties": {
            "building": building,
            "area_m2": round(area),
            "accessory": building in ACCESSORY_TAGS or area < ACCESSORY_MAX_M2,
        },
    }


def to_features(elements: list[dict]) -> list[dict]:
    return [f for f in map(_feature, elements) if f]

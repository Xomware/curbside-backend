"""Whole-table views for /admin. Each Scans the table; nothing else is allowed to."""

from __future__ import annotations

import time
from collections import Counter, defaultdict

from lambdas.common.dynamo import scan

_ATTRS = ("pk", "sk", "ttl", "display_name", "created_at", "provider", "name", "role")


def _kind(item: dict) -> str | None:
    pk, sk = item["pk"], item["sk"]
    if sk == "PROFILE":
        return "accounts"
    if sk == "META":
        return "maps"
    if "#PERSON#" in sk:
        return "people"
    if "#PET#" in sk:
        return "pets"
    if sk.startswith("HH#"):
        return "households"
    if sk.startswith("NOTE#"):
        return "notes"
    if sk.startswith("FRIEND#"):
        return "friendships"
    if pk.startswith("ACCT#") and sk.startswith("DEVICE#"):
        return "devices"
    # TTL deletes lag by days, so expiry is checked here too.
    if sk in ("INVITE", "FRIENDINVITE") and item["ttl"] > time.time():
        return "open_invites"
    return None


def stats() -> dict:
    counts = Counter(_kind(i) for i in scan(("pk", "sk", "ttl")))
    keys = ("accounts", "maps", "households", "people", "pets", "notes", "devices")
    return {
        **{k: counts[k] for k in keys},
        # Each friendship is two edges.
        "friendships": counts["friendships"] // 2,
        "open_invites": counts["open_invites"],
    }


def _id(key: str) -> str:
    return key.partition("#")[2]


def list_accounts() -> list[dict]:
    items = scan(_ATTRS)
    providers: dict[str, set[str]] = defaultdict(set)
    map_count: Counter[str] = Counter()
    for i in items:
        if i["pk"].startswith("ACCT#") and i["sk"].startswith("IDENT#"):
            providers[_id(i["pk"])].add(i["provider"])
        if i["sk"].startswith("MEMBER#"):
            map_count[_id(i["sk"])] += 1
    rows = [
        {
            "account_id": _id(i["pk"]),
            "display_name": i["display_name"],
            "created_at": i["created_at"],
            "providers": sorted(providers[_id(i["pk"])]),
            "map_count": map_count[_id(i["pk"])],
        }
        for i in items
        if i["sk"] == "PROFILE"
    ]
    return sorted(rows, key=lambda r: (r["created_at"], r["account_id"]), reverse=True)


def list_maps() -> list[dict]:
    items = scan(_ATTRS)
    names = {_id(i["pk"]): i["display_name"] for i in items if i["sk"] == "PROFILE"}
    owners: dict[str, str] = {}
    members: Counter[str] = Counter()
    households: Counter[str] = Counter()
    for i in items:
        map_id = _id(i["pk"])
        if i["sk"].startswith("MEMBER#"):
            members[map_id] += 1
            if i["role"] == "owner":
                owners[map_id] = _id(i["sk"])
        if _kind(i) == "households":
            households[map_id] += 1
    rows = [
        {
            "map_id": _id(i["pk"]),
            "name": i["name"],
            "created_at": i["created_at"],
            "owner_name": names.get(owners.get(_id(i["pk"]), "")),
            "member_count": members[_id(i["pk"])],
            "household_count": households[_id(i["pk"])],
        }
        for i in items
        if i["sk"] == "META"
    ]
    return sorted(rows, key=lambda r: (r["created_at"], r["map_id"]), reverse=True)

"""GET /me/export - Everything the caller's account holds, as JSON.

Returns {"account": <as GET /me>, "maps": [{"map": {...}, "households": [...]}]}.
Households carry people, pets and every note (newest first) under `private`.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from lambdas.common.accounts import get_account
from lambdas.common.auth import get_account_id
from lambdas.common.dynamo import query_prefix
from lambdas.common.households import assemble, child_view
from lambdas.common.maps import map_view
from lambdas.common.responses import handle_errors, success_response

HANDLER = "me_export"


def _export_map(map_id: str, role: str) -> dict:
    items = query_prefix(f"MAP#{map_id}")
    meta = next(i for i in items if i["sk"] == "META")
    households = assemble([i for i in items if i["sk"].startswith("HH#")])
    notes = defaultdict(list)
    for item in items:
        if item["sk"].startswith("NOTE#"):
            notes[item["sk"].split("#")[1]].append(child_view(item))
    for hh in households:
        hh["private"]["notes"] = sorted(notes[hh["id"]], key=lambda n: n["id"], reverse=True)
    return {"map": map_view(meta, role), "households": households}


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    memberships = query_prefix(f"ACCT#{account_id}", "MAP#", gsi=True)
    maps = [_export_map(m["pk"].removeprefix("MAP#"), m["role"]) for m in memberships]
    return success_response({"account": get_account(account_id), "maps": maps})

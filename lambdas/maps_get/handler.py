"""GET /maps/{mapId} - A map with its households, people and pets. Notes are not loaded.

Returns {"map": {...}, "households": [...]}. 404 `map_not_found` for a missing map or a non-member.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import get_item, meta_key, query_prefix
from lambdas.common.households import assemble
from lambdas.common.maps import map_view
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "maps_get"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    member = require_member(map_id, account_id)
    meta = get_item(meta_key(map_id))
    households = assemble(query_prefix(f"MAP#{map_id}", "HH#"))
    return success_response({"map": map_view(meta, member["role"]), "households": households})

"""PATCH /maps/{mapId} - Rename a map or move its center or radius.

Body: {"version": n, "name"?, "center"?, "radius_m"?}. At least one field.
409 `version_conflict` when `version` is stale; the client refetches.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import meta_key, update_versioned
from lambdas.common.maps import map_view
from lambdas.common.models import MapUpdate
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response

HANDLER = "maps_update"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    body = parse_body(event, MapUpdate)
    member = require_member(map_id, account_id)
    meta = update_versioned(meta_key(map_id), body.changes(), body.version, "Map")
    return success_response(map_view(meta, member["role"]))

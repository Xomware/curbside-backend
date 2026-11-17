"""DELETE /maps/{mapId} - Delete a map, everything in it and its footprint files.

Returns {"id": mapId}. Safe to retry after a partial failure.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.maps import delete_map
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "maps_delete"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    require_member(map_id, account_id)
    delete_map(map_id)
    return success_response({"id": map_id})

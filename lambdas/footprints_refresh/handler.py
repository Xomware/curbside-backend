"""POST /maps/{mapId}/footprints/refresh - Refetch the map's footprints. 202.

Returns {"status": "pending"}; poll GET /maps/{mapId}/footprints.
429 `refresh_too_soon` within 5 minutes of the last fetch request.
404 `map_not_found` for a missing map or a non-member.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.footprints import mark_refresh, start_fetch
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "footprints_refresh"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    require_member(map_id, account_id)
    mark_refresh(map_id)
    start_fetch(map_id)
    return success_response({"status": "pending"}, status=202)

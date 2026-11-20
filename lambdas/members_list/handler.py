"""GET /maps/{mapId}/members - Who shares the map, owner first.

Returns [{"account_id", "display_name", "role", "created_at"}].
404 `map_not_found` for a missing map or a non-member.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.maps import list_members
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "members_list"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    require_member(map_id, account_id)
    return success_response(list_members(map_id))

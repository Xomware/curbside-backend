"""DELETE /maps/{mapId}/members/{accountId} - Remove a member, or leave the map.

The owner may remove anyone else; a member may remove only themself.
Returns {"removed": true}. 409 `owner_cannot_leave` when the owner targets themself,
403 `owner_only` when a member targets someone else, 404 `member_not_found` if the
target isn't in the map.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import delete_existing, member_key
from lambdas.common.errors import ConflictError, ForbiddenError
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "members_delete"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    target = path_id(event, "accountId")
    caller = require_member(map_id, account_id)
    is_owner = caller["role"] == "owner"
    if target == account_id and is_owner:
        raise ConflictError("The owner can't leave their map", code="owner_cannot_leave")
    if target != account_id and not is_owner:
        raise ForbiddenError("Only the map's owner can remove members", code="owner_only")
    delete_existing(member_key(map_id, target), "Member")
    return success_response({"removed": True})

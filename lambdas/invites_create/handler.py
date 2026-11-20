"""POST /maps/{mapId}/invites - A single-use link for a housemate to co-edit the map. 201.

Returns {"code": "<10 Crockford chars>", "expires_at": ISO}, 7 days out.
403 `owner_only` for a member who isn't the owner.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_owner
from lambdas.common.invites import create_invite
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "invites_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    require_owner(map_id, account_id)
    return success_response(create_invite(map_id, account_id), status=201)

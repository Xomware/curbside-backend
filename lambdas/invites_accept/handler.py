"""POST /invites/{code}/accept - Join the invite's map as a "member". Single use.

Returns the map as GET /maps lists it. A caller already in the map gets it back
with their own role, and the invite stays unspent for whoever it was meant for.
404 `invite_not_found` if missing, expired, spent or its map is gone.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.dynamo import get_item, member_key
from lambdas.common.invites import accept_invite, get_invite
from lambdas.common.maps import map_view
from lambdas.common.responses import handle_errors, success_response

HANDLER = "invites_accept"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    code = (event.get("pathParameters") or {}).get("code", "")
    invite, meta = get_invite(code)
    map_id = invite["map_id"]
    existing = get_item(member_key(map_id, account_id), ("role",))
    if existing:
        return success_response(map_view(meta, existing["role"]))
    accept_invite(code, map_id, account_id)
    return success_response(map_view(meta, "member"))

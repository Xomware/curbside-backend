"""GET /invites/{code} - What an invite would join, for the accept screen.

Returns {"code", "map": {"id", "name"}, "invited_by": display name, "expires_at",
"already_member": bool}. 404 `invite_not_found` if missing, expired or its map is gone.
Any signed-in account may read it; the code is the secret.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.dynamo import acct_key, get_item, member_key
from lambdas.common.invites import get_invite
from lambdas.common.responses import handle_errors, success_response

HANDLER = "invites_get"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    code = (event.get("pathParameters") or {}).get("code", "")
    invite, meta = get_invite(code)
    map_id = invite["map_id"]
    inviter = get_item(acct_key(invite["created_by"]), ("display_name",))
    member = get_item(member_key(map_id, account_id), ("pk",))
    return success_response(
        {
            "code": code,
            "map": {"id": map_id, "name": meta["name"]},
            "invited_by": inviter["display_name"],
            "expires_at": invite["expires_at"],
            "already_member": member is not None,
        }
    )

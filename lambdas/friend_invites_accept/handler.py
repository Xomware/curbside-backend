"""POST /friends/invites/{code}/accept - Become friends with the link's creator. Single use.

Returns the friend as GET /friends lists them; the creator gets a `friend_added` activity.
Already friends returns the friend and leaves the link unspent.
409 `own_invite` for your own link, 404 `invite_not_found` if missing, expired, spent
or its creator's account is gone.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.friends import accept_friend_invite
from lambdas.common.responses import handle_errors, success_response

HANDLER = "friend_invites_accept"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    code = (event.get("pathParameters") or {}).get("code", "")
    return success_response(accept_friend_invite(code, account_id))

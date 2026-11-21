"""GET /friends/invites/{code} - Who a friend link is from, for the accept screen.

Returns {"inviter": {"display_name"}, "expires_at"}. 404 `invite_not_found` if
missing, expired, spent or its creator's account is gone. The code is the secret.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.friends import get_friend_invite
from lambdas.common.responses import handle_errors, success_response

HANDLER = "friend_invites_get"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    get_account_id(event)
    code = (event.get("pathParameters") or {}).get("code", "")
    invite, inviter = get_friend_invite(code)
    return success_response(
        {"inviter": {"display_name": inviter["display_name"]}, "expires_at": invite["expires_at"]}
    )

"""POST /friends/invites - A single-use friend link. 201.

Returns {"code": "<10 Crockford chars>", "expires_at": ISO}, 7 days out.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.friends import create_friend_invite
from lambdas.common.responses import handle_errors, success_response

HANDLER = "friend_invites_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    return success_response(create_friend_invite(get_account_id(event)), status=201)

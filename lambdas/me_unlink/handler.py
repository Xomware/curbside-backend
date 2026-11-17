"""DELETE /me/identities/{sub} - Unlink a sign-in from the caller's account.

Returns the account as GET /me does. 404 `identity_not_found` if the sub isn't
linked to this account; 409 `last_identity` for the only one left. The unlinked
sub gets 404 `needs_onboarding` from its next request on.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.accounts import get_account, unlink_identity
from lambdas.common.auth import get_account_id
from lambdas.common.responses import handle_errors, success_response

HANDLER = "me_unlink"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    unlink_identity(account_id, (event.get("pathParameters") or {}).get("sub", ""))
    return success_response(get_account(account_id))

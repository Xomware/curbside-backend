"""GET /me - The caller's account and its sign-in identities.

404 `needs_onboarding` when the caller's sub has no account yet; the client then
offers POST /me or linking to an existing account.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.accounts import get_account
from lambdas.common.auth import get_account_id
from lambdas.common.responses import handle_errors, success_response

HANDLER = "me_get"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    return success_response(get_account(get_account_id(event)))

"""POST /me/identities - Link a second sign-in to the caller's account. 201.

Body: {"id_token": "<ID token from a fresh sign-in with the other provider>"}
The token must come from this pool's client, with auth_time in the last 10 minutes.
Returns the new identity {sub, provider, created_at}; GET /me lists them all.
400 `invalid_id_token`; 409 `already_linked`, or `identity_in_use` when that sign-in
has its own account (delete that account first; accounts are never merged).
Caller identity: `requestContext.authorizer.jwt.claims.sub` picks the account.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.accounts import link_identity
from lambdas.common.auth import get_account_id, provider_of
from lambdas.common.id_tokens import verify_id_token
from lambdas.common.models import LinkRequest
from lambdas.common.responses import handle_errors, parse_body, success_response

HANDLER = "me_link"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    claims = verify_id_token(parse_body(event, LinkRequest).id_token)
    provider = provider_of(claims.get("cognito:username", ""))
    return success_response(link_identity(account_id, claims["sub"], provider), status=201)

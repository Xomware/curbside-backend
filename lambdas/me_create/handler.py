"""POST /me - Create the caller's account. Idempotent per sub.

Body: {"display_name": "1-80 chars"}
201 with the new account, or 200 with the existing one if this sub already has
an account (the body is then ignored and nothing is written).
Caller identity: `requestContext.authorizer.jwt.claims.sub`, provider from `username`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.accounts import create_account
from lambdas.common.auth import get_provider, get_sub
from lambdas.common.models import AccountCreate
from lambdas.common.responses import handle_errors, parse_body, success_response

HANDLER = "me_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    sub = get_sub(event)
    body = parse_body(event, AccountCreate)
    profile, created = create_account(sub, get_provider(event), body.display_name)
    return success_response(profile, status=201 if created else 200)

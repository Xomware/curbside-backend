"""PATCH /me - Rename the caller's account.

Body: {"display_name": "1-80 chars, trimmed"}. Returns the account as GET /me does.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.accounts import get_account, rename_account
from lambdas.common.auth import get_account_id
from lambdas.common.models import AccountUpdate
from lambdas.common.responses import handle_errors, parse_body, success_response

HANDLER = "me_update"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    body = parse_body(event, AccountUpdate)
    rename_account(account_id, body.display_name)
    return success_response(get_account(account_id))

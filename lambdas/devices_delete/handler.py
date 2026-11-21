"""DELETE /devices/{token} - Stop pushing to this token, e.g. on sign-out. 204, even if unknown.

Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.devices import delete_device, path_token
from lambdas.common.responses import handle_errors, no_content

HANDLER = "devices_delete"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    delete_device(account_id, path_token(event))
    return no_content()

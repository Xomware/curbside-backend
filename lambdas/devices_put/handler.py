"""PUT /devices/{token} - Register an APNs token for push. 204.

Body: {"platform": "ios", "env": "sandbox|production"}. A token another account
registered moves to the caller. 400 if the token isn't 64-200 hex chars.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.devices import path_token, put_device
from lambdas.common.models import DeviceRegister
from lambdas.common.responses import handle_errors, no_content, parse_body

HANDLER = "devices_put"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    token = path_token(event)
    body = parse_body(event, DeviceRegister)
    put_device(account_id, token, body.platform, body.env)
    return no_content()

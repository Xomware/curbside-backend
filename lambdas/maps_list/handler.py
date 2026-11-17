"""GET /maps - The caller's maps, oldest first, each with the caller's role.

Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.maps import list_maps
from lambdas.common.responses import handle_errors, success_response

HANDLER = "maps_list"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    return success_response(list_maps(get_account_id(event)))

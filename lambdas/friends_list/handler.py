"""GET /friends - The caller's friends, by name.

Returns [{"account_id", "display_name", "since", "shared_maps": [{"map_id", "name"}]}],
where shared_maps are the streets both of you are on.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.friends import list_friends
from lambdas.common.responses import handle_errors, success_response

HANDLER = "friends_list"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    return success_response(list_friends(get_account_id(event)))

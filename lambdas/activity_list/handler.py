"""GET /activity - The caller's activity feed, newest first, at most 50.

Returns {"items": [{"id", "kind", "actor_name", "created_at", "map_id"?, "map_name"?,
"household_label"?}], "unread": n}. `unread` counts the listed items newer than the
last POST /activity/seen.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.activity import list_activity
from lambdas.common.auth import get_account_id
from lambdas.common.responses import handle_errors, success_response

HANDLER = "activity_list"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    return success_response(list_activity(get_account_id(event)))

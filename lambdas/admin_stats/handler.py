"""GET /admin/stats - Table-wide counts, for the admin page.

Returns {"accounts", "maps", "households", "people", "pets", "notes", "friendships",
"devices", "open_invites"}. Friendships count once per pair; invites are unexpired ones.
403 `admin_only` unless the caller's PROFILE has is_admin = true.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.admin import stats
from lambdas.common.auth import get_account_id, require_admin
from lambdas.common.responses import handle_errors, success_response

HANDLER = "admin_stats"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    require_admin(get_account_id(event))
    return success_response(stats())

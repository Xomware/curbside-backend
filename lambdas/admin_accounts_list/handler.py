"""GET /admin/accounts - Every account, newest first.

Returns [{"account_id", "display_name", "created_at", "providers": ["apple", "google"],
"map_count"}].
403 `admin_only` unless the caller's PROFILE has is_admin = true.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.admin import list_accounts
from lambdas.common.auth import get_account_id, require_admin
from lambdas.common.responses import handle_errors, success_response

HANDLER = "admin_accounts_list"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    require_admin(get_account_id(event))
    return success_response(list_accounts())

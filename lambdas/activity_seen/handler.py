"""POST /activity/seen - Mark everything in the caller's feed as read. 204.

Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.activity import mark_seen
from lambdas.common.auth import get_account_id
from lambdas.common.responses import handle_errors, no_content

HANDLER = "activity_seen"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    mark_seen(get_account_id(event))
    return no_content()

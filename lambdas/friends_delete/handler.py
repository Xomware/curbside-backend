"""DELETE /friends/{accountId} - Unfriend, on both sides. 204, even if you weren't friends.

Leaves street membership alone.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.friends import remove_friend
from lambdas.common.responses import handle_errors, no_content, path_id

HANDLER = "friends_delete"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    remove_friend(account_id, path_id(event, "accountId"))
    return no_content()

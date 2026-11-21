"""DELETE /me - Hard-delete the caller's account, its maps and every linked sign-in.

A map shared with others is not deleted: the longest-standing member becomes its owner.
Friends lose the caller from their lists; the caller's push tokens are released.

Needs a sign-in in the last 10 minutes, from Apple if an Apple sign-in is linked,
else 403 `reauth_required`. Apple's revoke endpoint answers 200 for an expired
token too, so this is how the revoked token is known to be live.
Returns {"deleted": true, "apple_revoke": "revoked|manual|none", "manual_revoke_url"?}.
"manual" means revoking failed or Cognito had no Apple token; the client shows the
manual revoke link (TN3194). Safe to retry after a partial failure.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

import time
from typing import Any

from lambdas.common.accounts import delete_account_items
from lambdas.common.apple import MANUAL_REVOKE_URL, revoke
from lambdas.common.auth import get_account_id, get_auth_time, get_provider, get_sub
from lambdas.common.cognito import delete_users, find_user, user_attribute
from lambdas.common.devices import holder_key
from lambdas.common.dynamo import delete_keys, member_key, query_prefix
from lambdas.common.errors import ForbiddenError
from lambdas.common.friends import friend_key
from lambdas.common.maps import delete_map, hand_off
from lambdas.common.responses import handle_errors, success_response

HANDLER = "me_delete"
MAX_AUTH_AGE_S = 600


def _revoke_apple(sub: str) -> str:
    user = find_user(sub)
    token = user_attribute(user, "custom:apple_at") if user else None
    return "revoked" if token and revoke(token) else "manual"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    sub = get_sub(event)
    identities = query_prefix(f"ACCT#{account_id}", "IDENT#")
    has_apple = any(i["provider"] == "apple" for i in identities)
    stale = time.time() - get_auth_time(event) > MAX_AUTH_AGE_S
    if stale or (has_apple and get_provider(event) != "apple"):
        provider = "Apple" if has_apple else "your account"
        raise ForbiddenError(f"Sign in with {provider} again to delete", code="reauth_required")

    apple_revoke = _revoke_apple(sub) if has_apple else "none"
    for m in query_prefix(f"ACCT#{account_id}", "MAP#", gsi=True):
        map_id = m["pk"].removeprefix("MAP#")
        if m["role"] != "owner":
            delete_keys([member_key(map_id, account_id)])
        elif not hand_off(map_id, account_id):
            delete_map(map_id)
    # The caller's own FRIEND# and DEVICE# rows go with the ACCT# partition below.
    friends = query_prefix(f"ACCT#{account_id}", "FRIEND#")
    devices = query_prefix(f"ACCT#{account_id}", "DEVICE#")
    delete_keys(
        [friend_key(f["account_id"], account_id) for f in friends]
        + [holder_key(d["token"]) for d in devices]
    )
    subs = sorted({i["sub"] for i in identities} | {sub})
    delete_users(subs)
    delete_account_items(account_id, subs, sub)

    body: dict = {"deleted": True, "apple_revoke": apple_revoke}
    if apple_revoke == "manual":
        body["manual_revoke_url"] = MANUAL_REVOKE_URL
    return success_response(body)

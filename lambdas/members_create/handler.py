"""POST /maps/{mapId}/members - Add a friend to the map as a "member". 201.

Body: {"account_id": "<ULID>"}. Returns {"account_id", "display_name", "role", "created_at"}.
They get an `added_to_street` activity and the other members a `member_joined`.
Any member may add; already in the map → 200 with their existing membership.
403 `not_friend` if the account isn't the caller's friend.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.activity import notify
from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import acct_key, get_item, member_key
from lambdas.common.errors import ForbiddenError
from lambdas.common.friends import friend_key
from lambdas.common.maps import add_member, map_name, member_ids
from lambdas.common.models import MemberAdd
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response

HANDLER = "members_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    target = parse_body(event, MemberAdd).account_id
    require_member(map_id, account_id)
    if not get_item(friend_key(account_id, target), ("pk",)):
        raise ForbiddenError("You can only add your friends", code="not_friend")
    profile = get_item(acct_key(target), ("display_name",))

    existing = get_item(member_key(map_id, target), ("role", "created_at"))
    member = existing or add_member(map_id, target)
    view = {
        "account_id": target,
        "display_name": profile["display_name"],
        "role": member["role"],
        "created_at": member["created_at"],
    }
    if existing:
        return success_response(view)

    name = map_name(map_id)
    notify([target], "added_to_street", account_id, map_id, name)
    others = [m for m in member_ids(map_id) if m != account_id]
    notify(others, "member_joined", target, map_id, name)
    return success_response(view, status=201)

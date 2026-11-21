"""POST /maps/{mapId}/households - Add a household to a map. 201.

Body: {"label": "1-80 chars", "lat": .., "lng": .., "address"?: "<=200", "building_id"?: "<=100"}
Every other member gets a `household_added` activity.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.activity import notify
from lambdas.common.auth import get_account_id, require_member
from lambdas.common.households import create_household
from lambdas.common.maps import map_name, member_ids
from lambdas.common.models import HouseholdCreate
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response

HANDLER = "households_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    body = parse_body(event, HouseholdCreate)
    require_member(map_id, account_id)
    household = create_household(map_id, body)
    members = member_ids(map_id)
    notify(members, "household_added", account_id, map_id, map_name(map_id), body.label)
    return success_response(household, status=201)

"""POST /maps/{mapId}/households - Add a household to a map. 201.

Body: {"label": "1-80 chars", "lat": .., "lng": .., "address"?: "<=200", "building_id"?: "<=100"}
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.households import create_household
from lambdas.common.models import HouseholdCreate
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response

HANDLER = "households_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    body = parse_body(event, HouseholdCreate)
    require_member(map_id, account_id)
    return success_response(create_household(map_id, body), status=201)

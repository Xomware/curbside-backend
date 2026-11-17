"""PATCH /maps/{mapId}/households/{hhId} - Edit a household.

Body: {"version": n, "label"?, "address"?, "lat"?, "lng"?, "building_id"?, "last_talked_at"?}
null clears `address`, `building_id` or `last_talked_at`. 409 `version_conflict` on a
stale version. The response omits `private.people` and `private.pets`.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import update_versioned
from lambdas.common.households import hh_key, household_view
from lambdas.common.models import HouseholdUpdate
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response

HANDLER = "households_update"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id, hh_id = path_id(event, "mapId"), path_id(event, "hhId")
    body = parse_body(event, HouseholdUpdate)
    require_member(map_id, account_id)
    item = update_versioned(hh_key(map_id, hh_id), body.changes(), body.version, "Household")
    return success_response(household_view(item))

"""GET /maps/{mapId}/households/{hhId} - A household with its people and pets.

404 `household_not_found` if the map has no such household.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import query_prefix
from lambdas.common.errors import NotFoundError
from lambdas.common.households import assemble
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "households_get"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id, hh_id = path_id(event, "mapId"), path_id(event, "hhId")
    require_member(map_id, account_id)
    households = assemble(query_prefix(f"MAP#{map_id}", f"HH#{hh_id}"))
    if not households:
        raise NotFoundError("Household not found", code="household_not_found")
    return success_response(households[0])

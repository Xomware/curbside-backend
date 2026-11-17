"""POST /maps/{mapId}/households/{hhId}/pets - Add a pet to a household. 201.

Body: {"name": "1-80", "species"?: "<=40", "notes"?: "<=1000"}
404 `household_not_found` if the household doesn't exist (checked in the same transaction).
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.households import create_child
from lambdas.common.models import PetCreate
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response

HANDLER = "pets_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id, hh_id = path_id(event, "mapId"), path_id(event, "hhId")
    body = parse_body(event, PetCreate)
    require_member(map_id, account_id)
    child = create_child(map_id, hh_id, "PET", body.model_dump(exclude_none=True))
    return success_response(child, status=201)

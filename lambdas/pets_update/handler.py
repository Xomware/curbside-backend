"""PATCH /maps/{mapId}/households/{hhId}/pets/{petId} - Edit a pet.

Body: {"version": n, ...any PetCreate field}. 409 `version_conflict` on a stale version.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import update_versioned
from lambdas.common.households import child_key, child_view
from lambdas.common.models import PetUpdate
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response

HANDLER = "pets_update"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id, hh_id = path_id(event, "mapId"), path_id(event, "hhId")
    key = child_key(map_id, hh_id, "PET", path_id(event, "petId"))
    body = parse_body(event, PetUpdate)
    require_member(map_id, account_id)
    item = update_versioned(key, body.changes(), body.version, "Pet")
    return success_response(child_view(item))

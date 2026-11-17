"""DELETE /maps/{mapId}/households/{hhId}/people/{personId} - Remove a person.

Returns {"id": personId}. 404 `person_not_found` if it doesn't exist.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import delete_existing
from lambdas.common.households import child_key
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "people_delete"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id, hh_id = path_id(event, "mapId"), path_id(event, "hhId")
    child_id = path_id(event, "personId")
    require_member(map_id, account_id)
    delete_existing(child_key(map_id, hh_id, "PERSON", child_id), "Person")
    return success_response({"id": child_id})

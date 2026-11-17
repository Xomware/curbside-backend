"""DELETE /maps/{mapId}/households/{hhId} - Delete a household, its people, pets and notes.

Returns {"id": hhId}. 404 `household_not_found` if it doesn't exist.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import delete_keys, query_prefix
from lambdas.common.errors import NotFoundError
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "households_delete"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id, hh_id = path_id(event, "mapId"), path_id(event, "hhId")
    require_member(map_id, account_id)
    pk = f"MAP#{map_id}"
    items = query_prefix(pk, f"HH#{hh_id}")
    if not any(i["sk"] == f"HH#{hh_id}" for i in items):
        raise NotFoundError("Household not found", code="household_not_found")
    items += query_prefix(pk, f"NOTE#{hh_id}#")
    delete_keys([{"pk": i["pk"], "sk": i["sk"]} for i in items])
    return success_response({"id": hh_id})

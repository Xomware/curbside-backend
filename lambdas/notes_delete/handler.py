"""DELETE /maps/{mapId}/households/{hhId}/notes/{noteId} - Delete a note.

Returns {"id": noteId}. 404 `note_not_found` if it doesn't exist. Leaves
last_talked_at as it was.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.dynamo import delete_existing
from lambdas.common.notes import note_key
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "notes_delete"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id, hh_id = path_id(event, "mapId"), path_id(event, "hhId")
    note_id = path_id(event, "noteId")
    require_member(map_id, account_id)
    delete_existing(note_key(map_id, hh_id, note_id), "Note")
    return success_response({"id": note_id})

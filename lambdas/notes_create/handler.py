"""POST /maps/{mapId}/households/{hhId}/notes - Log a note and touch last_talked_at. 201.

Body: {"text": "1-2000 chars", "source"?: "voice|text|manual" (default manual)}
404 `household_not_found` if the household doesn't exist; nothing is written then.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.models import NoteCreate
from lambdas.common.notes import create_note
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response

HANDLER = "notes_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id, hh_id = path_id(event, "mapId"), path_id(event, "hhId")
    body = parse_body(event, NoteCreate)
    require_member(map_id, account_id)
    return success_response(create_note(map_id, hh_id, body), status=201)

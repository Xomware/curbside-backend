"""POST /maps/{mapId}/capture/apply - Write the ops the user confirmed, all or nothing.

Body: {"operations": [op, ...], "base_versions": {id: version}, "source"?: "voice|text"}
Ops and base_versions as capture/parse returned them; unchecked ops left out.
`create_household` fields must include lat and lng. Returns [{"op", "id"}, ...] in op order.
409 `version_conflict` when anything changed since the parse (parse again);
413 `too_many_operations` past 100 writes; 400 for invalid fields or refs.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.capture_apply import apply_ops
from lambdas.common.models import CaptureApply
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response

HANDLER = "capture_apply"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    body = parse_body(event, CaptureApply)
    require_member(map_id, account_id)
    results = apply_ops(map_id, body.operations, body.base_versions, body.source)
    return success_response(results)

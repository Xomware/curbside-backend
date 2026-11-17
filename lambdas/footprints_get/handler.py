"""GET /maps/{mapId}/footprints - The map's footprint file as a 5-minute presigned URL.

202 {"status": "pending"} while a fetch runs. Otherwise 200
{"status": "ready|empty|failed", "source", "version", "count", "url"}; `url` is null
unless ready. Clients cache the file by (mapId, version).
404 `map_not_found` for a missing map or a non-member.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.footprints import get_footprint, presign
from lambdas.common.responses import handle_errors, path_id, success_response

HANDLER = "footprints_get"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    require_member(map_id, account_id)
    fp = get_footprint(map_id)
    if fp["status"] == "pending":
        return success_response({"status": "pending"}, status=202)
    url = presign(map_id, int(fp["version"])) if fp["status"] == "ready" else None
    view = {k: fp.get(k) for k in ("status", "source", "version", "count")}
    return success_response({**view, "url": url})

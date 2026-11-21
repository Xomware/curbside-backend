"""DELETE /admin/maps/{mapId} - Delete any street, everything in it and its footprint files. 204.

404 `map_not_found` if there's no such map. Safe to retry after a partial failure.
403 `admin_only` unless the caller's PROFILE has is_admin = true.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id, require_admin
from lambdas.common.dynamo import query_prefix
from lambdas.common.errors import NotFoundError
from lambdas.common.maps import delete_map
from lambdas.common.responses import handle_errors, no_content, path_id

HANDLER = "admin_maps_delete"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    require_admin(get_account_id(event))
    map_id = path_id(event, "mapId")
    # Not META: a half-deleted map has lost it but kept its MEMBER# items.
    if not query_prefix(f"MAP#{map_id}"):
        raise NotFoundError("Map not found", code="map_not_found")
    delete_map(map_id)
    return no_content()

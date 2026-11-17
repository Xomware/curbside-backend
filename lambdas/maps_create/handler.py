"""POST /maps - Create a map owned by the caller. 201.

Body: {"name": "1-80 chars", "center": {"lat": .., "lng": ..}, "radius_m": 50-1000 (default 300)}
The footprint starts `pending`; B8 adds the async fetch.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.auth import get_account_id
from lambdas.common.maps import create_map
from lambdas.common.models import MapCreate
from lambdas.common.responses import handle_errors, parse_body, success_response

HANDLER = "maps_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    body = parse_body(event, MapCreate)
    return success_response(create_map(account_id, body), status=201)

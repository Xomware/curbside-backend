"""POST /maps - Create a map owned by the caller. 201.

Body: {"name": "1-80 chars", "center": {"lat": .., "lng": ..}, "radius_m": 50-1000 (default 300)}
The footprint starts `pending` and footprints_fetch is invoked async.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from lambdas.common.auth import get_account_id
from lambdas.common.footprints import start_fetch
from lambdas.common.logger import log
from lambdas.common.maps import create_map
from lambdas.common.models import MapCreate
from lambdas.common.responses import handle_errors, parse_body, success_response

HANDLER = "maps_create"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    body = parse_body(event, MapCreate)
    created = create_map(account_id, body)
    try:
        start_fetch(created["id"])
    except ClientError as e:
        # The map exists; a 500 here would make the client retry into a duplicate.
        # It stays pending and the user can refresh.
        log.error(
            "fetch_invoke_failed",
            extra={"handler": HANDLER, "aws_error": e.response["Error"]["Code"]},
        )
    return success_response(created, status=201)

"""POST /maps/{mapId}/capture/parse - Turn a transcript into proposed operations. Persists nothing.

Body: {"transcript": "1-2000 chars", "source": "voice|text",
       "focus_household_id"?: id, "nearby_household_ids": [id, ...] (<= 8)}
Only the households named here go to the model, as a roster.
Returns {"operations": [...], "unresolved": [...], "base_versions": {id: version}};
each op carries `needs_review` and `checked` (false when it needs review).
429 `quota_exceeded` past 50 parses a day; 502 `parse_failed`; 503 `model_unavailable`.
The transcript is never stored or logged.
Caller identity: `requestContext.authorizer.jwt.claims.sub`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from lambdas.common.auth import get_account_id, require_member
from lambdas.common.capture import build_roster, call_model, check, spend_quota
from lambdas.common.models import CaptureParse
from lambdas.common.responses import handle_errors, parse_body, path_id, success_response
from lambdas.common.ssm import secret

HANDLER = "capture_parse"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    account_id = get_account_id(event)
    map_id = path_id(event, "mapId")
    body = parse_body(event, CaptureParse)
    require_member(map_id, account_id)
    ids = [body.focus_household_id, *body.nearby_household_ids]
    roster, versions = build_roster(map_id, [i for i in ids if i])
    spend_quota(account_id)
    api_key = secret(os.environ["ANTHROPIC_API_KEY_PARAM"])
    output = call_model(api_key, roster, body.transcript, datetime.now(UTC).date())
    operations, unresolved = check(output, roster)
    return success_response(
        {"operations": operations, "unresolved": unresolved, "base_versions": versions}
    )

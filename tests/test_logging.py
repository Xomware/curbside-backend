from __future__ import annotations

import logging

import pydantic
import pytest
from conftest import api_event

from lambdas.common.errors import NotFoundError
from lambdas.common.responses import handle_errors, parse_body, success_response

SECRET = "Jane-Synthetic-Neighbor-7f3a"


class Note(pydantic.BaseModel):
    text: str
    count: int


@handle_errors("test_notes")
def ok(event: dict, context: object) -> dict:
    return success_response(parse_body(event, Note).model_dump())


@handle_errors("test_notes")
def not_found(event: dict, context: object) -> dict:
    raise NotFoundError(f"no household for {SECRET}")


@handle_errors("test_notes")
def crash(event: dict, context: object) -> dict:
    raise KeyError(SECRET)


def secret_event(count: object = 1) -> dict:
    return api_event(
        {"text": SECRET, "count": count},
        headers={"authorization": f"Bearer {SECRET}", "x-note": SECRET},
        query={"q": SECRET},
    )


def record_dump(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(repr(vars(r)) for r in caplog.records)


@pytest.mark.parametrize(
    ("handler", "count", "status"),
    [(ok, 1, 200), (ok, SECRET, 400), (not_found, 1, 404), (crash, 1, 500)],
)
def test_no_request_content_reaches_logs(caplog, handler, count, status):
    with caplog.at_level(logging.DEBUG):
        resp = handler(secret_event(count), None)

    assert resp["statusCode"] == status
    assert caplog.records, "expected a request log line"
    assert SECRET not in record_dump(caplog)


def test_request_line_carries_ids_status_and_latency(caplog):
    with caplog.at_level(logging.INFO, logger="curbside"):
        not_found(api_event(route="GET /maps/{mapId}"), None)

    line = next(r for r in caplog.records if r.getMessage() == "request")
    assert line.handler == "test_notes"
    assert line.route == "GET /maps/{mapId}"
    assert line.status == 404
    assert line.error_code == "not_found"
    assert line.latency_ms >= 0


def test_unhandled_error_logs_type_and_frames(caplog):
    with caplog.at_level(logging.ERROR, logger="curbside"):
        crash(api_event(), None)

    line = next(r for r in caplog.records if r.getMessage() == "unhandled")
    assert line.error_type == "KeyError"
    assert "in crash" in line.stack

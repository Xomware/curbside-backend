from __future__ import annotations

import base64
import json
import time
import traceback
from collections.abc import Callable
from decimal import Decimal
from functools import wraps
from typing import Any

import pydantic

from lambdas.common.errors import CurbsideError
from lambdas.common.logger import log


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_default),
    }


def success_response(data: Any, status: int = 200, meta: dict | None = None) -> dict:
    return _response(status, {"data": data, "error": None, "meta": meta or {}})


def error_response(status: int, code: str, message: str, details: Any = None) -> dict:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return _response(status, {"data": None, "error": error, "meta": {}})


def parse_body[M: pydantic.BaseModel](event: dict, model: type[M]) -> M:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw)
    return model.model_validate_json(raw)


def handle_errors(handler_name: str) -> Callable:
    """Maps errors to the envelope and logs one body-free line per request."""

    def decorator(fn: Callable[[dict, Any], dict]) -> Callable[[dict, Any], dict]:
        @wraps(fn)
        def wrapper(event: dict, context: Any) -> dict:
            start = time.perf_counter()
            code = None
            try:
                resp = fn(event, context)
            except CurbsideError as e:
                code = e.code
                resp = error_response(e.status, e.code, e.message)
            except pydantic.ValidationError as e:
                code = "invalid_request"
                details = [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()]
                resp = error_response(400, code, "Invalid request body", details)
            except Exception as e:
                # Frames only: the exception message can carry user input.
                log.error(
                    "unhandled",
                    extra={
                        "handler": handler_name,
                        "error_type": type(e).__name__,
                        "stack": "".join(traceback.format_tb(e.__traceback__)),
                    },
                )
                code = "internal_error"
                resp = error_response(500, code, "Internal error")

            log.info(
                "request",
                extra={
                    "handler": handler_name,
                    "route": event.get("routeKey"),
                    "status": resp["statusCode"],
                    "error_code": code,
                    "latency_ms": round((time.perf_counter() - start) * 1000),
                },
            )
            return resp

        return wrapper

    return decorator

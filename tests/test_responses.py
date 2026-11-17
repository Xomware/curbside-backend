from __future__ import annotations

import base64
import json
from decimal import Decimal

import pydantic
from conftest import api_event

from lambdas.common.errors import AuthError, NotFoundError, ValidationError
from lambdas.common.responses import handle_errors, parse_body, success_response


class Pet(pydantic.BaseModel):
    name: str = pydantic.Field(min_length=1)
    species: str


@handle_errors("test_pets")
def pets_handler(event: dict, context: object) -> dict:
    pet = parse_body(event, Pet)
    return success_response(pet.model_dump(), status=201)


def body(resp: dict) -> dict:
    return json.loads(resp["body"])


def test_success_envelope():
    resp = pets_handler(api_event({"name": "Biscuit", "species": "dog"}), None)
    assert resp["statusCode"] == 201
    assert body(resp) == {
        "data": {"name": "Biscuit", "species": "dog"},
        "error": None,
        "meta": {},
    }


def test_base64_body_is_decoded():
    event = api_event(base64.b64encode(b'{"name": "Biscuit", "species": "dog"}').decode())
    event["isBase64Encoded"] = True
    assert pets_handler(event, None)["statusCode"] == 201


def test_meta_passes_through():
    assert body(success_response([], meta={"next": "abc"}))["meta"] == {"next": "abc"}


def test_decimal_serializes_to_number():
    data = body(success_response({"count": Decimal("3"), "lat": Decimal("40.5")}))["data"]
    assert data == {"count": 3, "lat": 40.5}
    assert isinstance(data["count"], int)


def test_model_validation_failure_is_400_with_locations():
    resp = pets_handler(api_event({"name": ""}), None)
    assert resp["statusCode"] == 400
    payload = body(resp)
    assert payload["data"] is None
    assert payload["error"]["code"] == "invalid_request"
    assert {tuple(d["loc"]) for d in payload["error"]["details"]} == {("name",), ("species",)}


def test_malformed_json_is_400():
    resp = pets_handler(api_event("{not json"), None)
    assert resp["statusCode"] == 400
    assert body(resp)["error"]["code"] == "invalid_request"


def test_missing_body_is_400():
    assert pets_handler(api_event(None), None)["statusCode"] == 400


def test_typed_errors_keep_status_and_code():
    cases = [
        (ValidationError("bad radius"), 400, "invalid_request"),
        (AuthError("no token"), 401, "unauthorized"),
        (NotFoundError("gone", code="map_not_found"), 404, "map_not_found"),
    ]
    for err, status, code in cases:

        @handle_errors("test_raise")
        def raising(event: dict, context: object, err: Exception = err) -> dict:
            raise err

        resp = raising(api_event(), None)
        assert resp["statusCode"] == status
        assert body(resp)["error"] == {"code": code, "message": str(err)}


def test_unexpected_error_is_generic_500():
    @handle_errors("test_boom")
    def boom(event: dict, context: object) -> dict:
        raise RuntimeError("database password is hunter2")

    resp = boom(api_event(), None)
    assert resp["statusCode"] == 500
    assert body(resp)["error"] == {"code": "internal_error", "message": "Internal error"}
    assert "hunter2" not in resp["body"]
    assert "Traceback" not in resp["body"]

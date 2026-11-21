from __future__ import annotations

import json

import boto3
import httpx
import jwt
import pytest
from boto3.dynamodb.types import TypeSerializer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from lambdas.common import apns
from lambdas.common.devices import put_device
from lambdas.push_send.handler import handler

LIVE, DEAD = "aa" * 32, "bb" * 32
BUNDLE = "com.Xomware.Curbside"
PARAMS = {
    "APNS_KEY_ID_PARAM": "/curbside/apns/key-id",
    "APNS_TEAM_ID_PARAM": "/curbside/apns/team-id",
    "APNS_PRIVATE_KEY_PARAM": "/curbside/apns/private-key",
}


@pytest.fixture
def key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def configure(key: ec.EllipticCurvePrivateKey | None) -> None:
    pem = "unset"
    if key:
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
    values = {"key-id": "KEYAPNS123", "team-id": "TEAMID1234", "private-key": pem}
    for name, value in values.items():
        boto3.client("ssm").put_parameter(
            Name=f"/curbside/apns/{name}", Value=value, Type="SecureString"
        )


class FakeApns:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: dict[str, httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        token = request.url.path.rpartition("/")[2]
        return self.responses.get(token, httpx.Response(200))


@pytest.fixture
def apple(table, monkeypatch) -> FakeApns:
    for name, value in PARAMS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("APNS_BUNDLE_ID", BUNDLE)
    monkeypatch.setattr(apns, "_provider_token", {"value": "", "issued_at": 0.0})
    fake = FakeApns()
    monkeypatch.setattr(apns, "_client", lambda: httpx.Client(transport=httpx.MockTransport(fake)))
    return fake


def stream_event(account_id: str, **fields: str) -> dict:
    item = {
        "pk": f"ACCT#{account_id}",
        "sk": "ACTIVITY#2026-01-01T00:00:00+00:00#01J0000000000000000000000",
        "actor_id": "01J0000000000000000000ACTR",
        "actor_name": "Sam",
        "created_at": "2026-01-01T00:00:00+00:00",
        **fields,
    }
    image = {k: TypeSerializer().serialize(v) for k, v in item.items()}
    return {"Records": [{"eventName": "INSERT", "dynamodb": {"NewImage": image}}]}


def devices(table) -> set[tuple[str, str]]:
    return {(i["pk"], i["sk"]) for i in table.scan()["Items"] if "DEVICE" in i["sk"]}


def test_pushes_alert_to_each_device(apple, key, account):
    configure(key)
    put_device(account, LIVE, "ios", "production")
    put_device(account, "cc" * 32, "ios", "sandbox")

    handler(
        stream_event(account, kind="member_joined", map_id="M1", map_name="Quillfeather Ln"), None
    )

    hosts = sorted(r.url.host for r in apple.requests)
    assert hosts == ["api.push.apple.com", "api.sandbox.push.apple.com"]
    request = apple.requests[0]
    assert request.headers["apns-topic"] == BUNDLE
    assert request.headers["apns-push-type"] == "alert"
    bearer = request.headers["authorization"].removeprefix("bearer ")
    assert jwt.get_unverified_header(bearer)["kid"] == "KEYAPNS123"
    assert jwt.decode(bearer, key.public_key(), algorithms=["ES256"])["iss"] == "TEAMID1234"
    payload = json.loads(request.content)
    assert payload["aps"]["alert"]["body"] == "Sam joined Quillfeather Ln"
    assert (payload["kind"], payload["map_id"]) == ("member_joined", "M1")


@pytest.mark.parametrize(
    "fields, text",
    [
        ({"kind": "added_to_street", "map_name": "Elm St"}, "Sam added you to Elm St"),
        ({"kind": "street_handed_to_you", "map_name": "Elm St"}, "Elm St is yours now"),
        (
            {"kind": "household_added", "map_name": "Elm St", "household_label": "the Mossbottoms"},
            "Sam added the Mossbottoms to Elm St",
        ),
        ({"kind": "friend_added"}, "You and Sam are friends"),
    ],
)
def test_alert_text(apple, key, account, fields, text):
    configure(key)
    put_device(account, LIVE, "ios", "production")
    handler(stream_event(account, **fields), None)
    (request,) = apple.requests
    payload = json.loads(request.content)
    assert payload["aps"]["alert"]["body"] == text
    assert ("map_id" in payload) is False


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(410, json={"reason": "Unregistered"}),
        httpx.Response(400, json={"reason": "BadDeviceToken"}),
    ],
)
def test_dead_token_is_deleted(apple, key, table, account, response):
    configure(key)
    put_device(account, LIVE, "ios", "production")
    put_device(account, DEAD, "ios", "production")
    apple.responses[DEAD] = response

    handler(stream_event(account, kind="friend_added"), None)

    assert devices(table) == {(f"ACCT#{account}", f"DEVICE#{LIVE}"), (f"DEVICE#{LIVE}", "DEVICE")}


def test_other_rejections_keep_the_token(apple, key, table, account):
    configure(key)
    put_device(account, LIVE, "ios", "production")
    apple.responses[LIVE] = httpx.Response(429, json={"reason": "TooManyRequests"})
    handler(stream_event(account, kind="friend_added"), None)
    assert len(devices(table)) == 2


def test_network_error_does_not_raise(apple, key, account, monkeypatch):
    configure(key)
    put_device(account, LIVE, "ios", "production")

    def unreachable(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(
        apns, "_client", lambda: httpx.Client(transport=httpx.MockTransport(unreachable))
    )
    handler(stream_event(account, kind="friend_added"), None)


@pytest.mark.parametrize("setup", ["unset", "missing_params", "missing_env", "bad_key"])
def test_unconfigured_skips_without_raising(apple, key, account, monkeypatch, setup):
    put_device(account, LIVE, "ios", "production")
    if setup == "unset":
        configure(None)
    if setup == "missing_env":
        configure(key)
        monkeypatch.delenv("APNS_PRIVATE_KEY_PARAM")
    if setup == "bad_key":
        configure(key)
        boto3.client("ssm").put_parameter(
            Name="/curbside/apns/private-key",
            Value="not a key",
            Type="SecureString",
            Overwrite=True,
        )

    handler(stream_event(account, kind="friend_added"), None)

    assert apple.requests == []


def test_account_without_devices_sends_nothing(apple, key, account):
    configure(key)
    handler(stream_event(account, kind="friend_added"), None)
    assert apple.requests == []

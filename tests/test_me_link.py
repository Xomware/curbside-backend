from __future__ import annotations

import json
import time

import jwt
import pytest
from conftest import call
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import PyJWKClientConnectionError

from lambdas.common import id_tokens
from lambdas.common.accounts import create_account
from lambdas.me_get.handler import handler as me_get
from lambdas.me_link.handler import handler

ISS = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def sign(key: rsa.RSAPrivateKey = KEY, **overrides: object) -> str:
    now = int(time.time())
    claims = {
        "sub": "sub-2",
        "aud": "client-ios",
        "iss": ISS,
        "token_use": "id",
        "auth_time": now - 30,
        "iat": now,
        "exp": now + 3600,
        "cognito:username": "signinwithapple_001.abc",
    }
    claims = {k: v for k, v in (claims | overrides).items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("USER_POOL_ID", "us-east-1_TEST")
    monkeypatch.setenv("CLIENT_IDS", "client-ios,client-web")
    monkeypatch.setattr(
        jwt.PyJWKClient, "fetch_data", lambda self: {"keys": [{**jwk, "kid": "k1"}]}
    )
    id_tokens._jwks.cache_clear()
    yield
    id_tokens._jwks.cache_clear()


def link(token: str, sub: str = "sub-test-1") -> tuple[int, dict]:
    return call(handler, {"id_token": token}, sub=sub, route="POST /me/identities")


def test_links_second_sign_in_to_callers_account(table, account):
    status, body = link(sign())

    assert status == 201
    assert body["data"]["sub"] == "sub-2"
    assert body["data"]["provider"] == "apple"
    _, me = call(me_get, sub="sub-2")
    assert me["data"]["account_id"] == account
    assert {i["sub"] for i in me["data"]["identities"]} == {"sub-test-1", "sub-2"}


def test_second_client_id_is_accepted(table, account):
    assert link(sign(aud="client-web"))[0] == 201


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        sign(key=OTHER_KEY),
        sign(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OTHER"),
        sign(aud="someone-else"),
        sign(token_use="access"),
        sign(exp=int(time.time()) - 10),
        sign(auth_time=int(time.time()) - 601),
        sign(auth_time=None),
    ],
)
def test_bad_token_is_400_and_writes_nothing(table, account, token):
    before = table.scan()["Count"]
    status, body = link(token)
    assert (status, body["error"]["code"]) == (400, "invalid_id_token")
    assert table.scan()["Count"] == before


def test_sign_in_with_its_own_account_is_409(table, account):
    other = create_account("sub-2", "apple", "Other")[0]["account_id"]
    before = table.scan()["Items"]

    status, body = link(sign())

    assert (status, body["error"]["code"]) == (409, "identity_in_use")
    assert table.scan()["Items"] == before
    assert call(me_get, sub="sub-2")[1]["data"]["account_id"] == other


def test_relinking_same_sign_in_is_409(table, account):
    link(sign())
    status, body = link(sign())
    assert (status, body["error"]["code"]) == (409, "already_linked")


def test_caller_without_account_needs_onboarding(table):
    status, body = link(sign(), sub="sub-new")
    assert (status, body["error"]["code"]) == (404, "needs_onboarding")


def test_jwks_unreachable_is_500_not_400(table, account, monkeypatch):
    def down(self):
        raise PyJWKClientConnectionError("down")

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", down)
    assert link(sign())[0] == 500

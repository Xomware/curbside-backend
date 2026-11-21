from __future__ import annotations

import time
from urllib.error import HTTPError
from urllib.parse import parse_qs

import boto3
import jwt
import pytest
from conftest import call
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from lambdas.common import apple
from lambdas.common.accounts import create_account, link_identity
from lambdas.common.devices import put_device
from lambdas.common.friends import make_friends
from lambdas.common.households import create_child, create_household
from lambdas.common.invites import accept_invite, create_invite
from lambdas.common.maps import create_map
from lambdas.common.models import HouseholdCreate, MapCreate, NoteCreate
from lambdas.common.notes import create_note
from lambdas.me_delete import handler as me_delete
from lambdas.me_delete.handler import handler as delete
from lambdas.me_export.handler import handler as export


def fresh(age_s: int = 0) -> dict:
    return {"auth_time": str(int(time.time()) - age_s)}


@pytest.fixture
def pool(table, monkeypatch) -> str:
    pool_id = boto3.client("cognito-idp").create_user_pool(
        PoolName="curbside-users",
        Schema=[{"Name": "apple_at", "AttributeDataType": "String", "Mutable": True}],
    )["UserPool"]["Id"]
    monkeypatch.setenv("USER_POOL_ID", pool_id)
    return pool_id


def cognito_user(pool: str, username: str, apple_at: str | None = None) -> str:
    """Creates a federated-style user and returns the sub Cognito gave it."""
    attrs = [{"Name": "custom:apple_at", "Value": apple_at}] if apple_at else []
    user = boto3.client("cognito-idp").admin_create_user(
        UserPoolId=pool, Username=username, UserAttributes=attrs
    )["User"]
    return next(a["Value"] for a in user["Attributes"] if a["Name"] == "sub")


def cognito_usernames(pool: str) -> list[str]:
    return [u["Username"] for u in boto3.client("cognito-idp").list_users(UserPoolId=pool)["Users"]]


@pytest.fixture
def apple_key(table) -> ec.EllipticCurvePrivateKey:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    boto3.client("ssm").put_parameter(
        Name="/curbside/apple/private-key", Value=pem.decode(), Type="SecureString"
    )
    return key


class FakeApple:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.forms: list[dict] = []

    def urlopen(self, request, timeout):
        assert request.full_url == "https://appleid.apple.com/auth/revoke"
        self.forms.append({k: v[0] for k, v in parse_qs(request.data.decode()).items()})
        if self.error:
            raise self.error
        return open("/dev/null", "rb")


@pytest.fixture
def apple_api(monkeypatch):
    def install(error=None):
        fake = FakeApple(error)
        monkeypatch.setattr(apple, "urlopen", fake.urlopen)
        return fake

    return install


@pytest.fixture
def owner(pool, apple_key, bucket) -> dict:
    """An account with a Google and an Apple sign-in and one full map."""
    google = cognito_user(pool, "google_1001")
    apple_sub = cognito_user(pool, "signinwithapple_2002", apple_at="apple-access-token")
    account = create_account(google, "google", "Test Neighbor")[0]["account_id"]
    link_identity(account, apple_sub, "apple")
    map_id = create_map(account, MapCreate(name="Elm St", center={"lat": 40, "lng": -75}))["id"]
    hh = create_household(map_id, HouseholdCreate(label="Blue house", lat=40, lng=-75))["id"]
    create_child(map_id, hh, "PERSON", {"name": "Theo", "role": "kid"})
    create_child(map_id, hh, "PET", {"name": "Biscuit"})
    create_note(map_id, hh, NoteCreate(text="first"))
    create_note(map_id, hh, NoteCreate(text="second"))
    boto3.client("s3").put_object(
        Bucket=bucket, Key=f"footprints/{map_id}/v1.geojson.gz", Body=b"{}"
    )
    return {"account": account, "google": google, "apple": apple_sub, "map": map_id, "hh": hh}


@pytest.fixture
def stranger(pool, bucket) -> dict:
    sub = cognito_user(pool, "google_3003")
    account = create_account(sub, "google", "Stranger")[0]["account_id"]
    map_id = create_map(account, MapCreate(name="Oak St", center={"lat": 41, "lng": -74}))["id"]
    return {"account": account, "sub": sub, "map": map_id}


def share(owner_map: dict, guest: dict) -> None:
    """guest joins owner_map's map as a member."""
    code = create_invite(owner_map["map"], owner_map["account"])["code"]
    accept_invite(code, owner_map["map"], guest["account"])


def as_apple(owner: dict, age_s: int = 0) -> dict:
    return {
        "sub": owner["apple"],
        "username": "signinwithapple_2002",
        "claims": fresh(age_s),
    }


def test_export_holds_everything_the_account_owns(owner, stranger):
    status, body = call(export, sub=owner["google"])

    assert status == 200
    data = body["data"]
    assert {i["provider"] for i in data["account"]["identities"]} == {"google", "apple"}
    (exported,) = data["maps"]
    assert (exported["map"]["id"], exported["map"]["role"]) == (owner["map"], "owner")
    (hh,) = exported["households"]
    assert [p["name"] for p in hh["private"]["people"]] == ["Theo"]
    assert [p["name"] for p in hh["private"]["pets"]] == ["Biscuit"]
    assert [n["text"] for n in hh["private"]["notes"]] == ["second", "first"]
    assert "Oak St" not in str(data)


def test_delete_revokes_apple_and_removes_everything(
    owner, stranger, table, pool, bucket, apple_key, apple_api
):
    fake = apple_api()

    status, body = call(delete, **as_apple(owner))

    assert (status, body["data"]) == (200, {"deleted": True, "apple_revoke": "revoked"})
    (form,) = fake.forms
    assert (form["token"], form["token_type_hint"]) == ("apple-access-token", "access_token")
    assert form["client_id"] == "com.example.curbside.signin"
    assert jwt.get_unverified_header(form["client_secret"])["kid"] == "KEYID12345"
    claims = jwt.decode(
        form["client_secret"],
        apple_key.public_key(),
        algorithms=["ES256"],
        audience="https://appleid.apple.com",
    )
    assert (claims["iss"], claims["sub"]) == ("TEAMID1234", "com.example.curbside.signin")

    left = {(i["pk"], i["sk"]) for i in table.scan()["Items"]}
    mine = {
        f"ACCT#{owner['account']}",
        f"MAP#{owner['map']}",
        f"IDENT#{owner['google']}",
        f"IDENT#{owner['apple']}",
    }
    assert not {pk for pk, _ in left} & mine
    assert (f"MAP#{stranger['map']}", "META") in left
    assert cognito_usernames(pool) == ["google_3003"]
    assert "Contents" not in boto3.client("s3").list_objects_v2(Bucket=bucket)


def test_google_only_account_skips_apple(pool, stranger, apple_api, table):
    fake = apple_api()
    status, body = call(delete, sub=stranger["sub"], claims=fresh())
    assert body["data"] == {"deleted": True, "apple_revoke": "none"}
    assert fake.forms == []
    assert cognito_usernames(pool) == []


@pytest.mark.parametrize(
    "caller",
    [
        lambda o: as_apple(o, age_s=601),
        lambda o: {"sub": o["google"], "claims": fresh()},
        lambda o: {"sub": o["apple"], "username": "signinwithapple_2002"},
    ],
)
def test_stale_or_non_apple_sign_in_is_403(owner, table, apple_api, caller):
    before = table.scan()["Items"]
    status, body = call(delete, **caller(owner))
    assert (status, body["error"]["code"]) == (403, "reauth_required")
    assert table.scan()["Items"] == before


@pytest.mark.parametrize(
    "error",
    [HTTPError(apple.REVOKE_URL, 400, "invalid_client", None, None), TimeoutError()],
)
def test_revoke_failure_still_deletes_and_points_to_manual(owner, table, apple_api, error):
    apple_api(error)
    status, body = call(delete, **as_apple(owner))
    assert status == 200
    assert body["data"]["apple_revoke"] == "manual"
    assert body["data"]["manual_revoke_url"] == "https://support.apple.com/en-us/102571"
    assert not [i for i in table.scan()["Items"] if i["pk"] == f"ACCT#{owner['account']}"]


def test_bad_apple_key_still_deletes(owner, table, apple_api):
    boto3.client("ssm").put_parameter(
        Name="/curbside/apple/private-key", Value="not a key", Type="SecureString", Overwrite=True
    )
    fake = apple_api()
    _, body = call(delete, **as_apple(owner))
    assert (body["data"]["apple_revoke"], fake.forms) == ("manual", [])


def test_missing_apple_token_is_manual(pool, apple_key, apple_api, table):
    apple_sub = cognito_user(pool, "signinwithapple_4004")
    create_account(apple_sub, "apple", "No token")
    fake = apple_api()
    _, body = call(delete, sub=apple_sub, username="signinwithapple_4004", claims=fresh())
    assert (body["data"]["apple_revoke"], fake.forms) == ("manual", [])


def test_retry_after_a_crash_finishes_the_job(owner, table, apple_api, monkeypatch):
    apple_api()

    def crash(subs):
        raise RuntimeError("Cognito down")

    with monkeypatch.context() as m:
        m.setattr(me_delete, "delete_users", crash)
        assert call(delete, **as_apple(owner))[0] == 500

    status, _ = call(delete, **as_apple(owner))

    assert status == 200
    assert not [i for i in table.scan()["Items"] if owner["account"] in i["pk"]]
    status, body = call(delete, **as_apple(owner))
    assert (status, body["error"]["code"]) == (404, "needs_onboarding")


@pytest.mark.parametrize("crash_on", [2, 3])
def test_retry_after_a_crash_between_identity_passes(
    owner, table, apple_api, monkeypatch, crash_on
):
    from lambdas.common import accounts

    apple_api()
    calls = []

    def flaky(keys):
        calls.append(keys)
        if len(calls) == crash_on:
            raise RuntimeError("throttled")
        real(keys)

    real = accounts.delete_keys
    with monkeypatch.context() as m:
        m.setattr(accounts, "delete_keys", flaky)
        assert call(delete, **as_apple(owner))[0] == 500

    assert call(delete, **as_apple(owner))[0] == 200
    assert not [i for i in table.scan()["Items"] if owner["account"] in str(i)]
    assert not [i for i in table.scan()["Items"] if i["pk"].startswith("IDENT#")]


def test_export_includes_maps_shared_with_the_caller(owner, stranger):
    share(stranger, owner)

    _, body = call(export, sub=owner["google"])

    roles = {m["map"]["id"]: m["map"]["role"] for m in body["data"]["maps"]}
    assert roles == {owner["map"]: "owner", stranger["map"]: "member"}


def test_delete_leaves_shared_maps_and_only_drops_the_membership(owner, stranger, table, apple_api):
    apple_api()
    share(stranger, owner)

    assert call(delete, **as_apple(owner))[0] == 200

    left = {
        (i["pk"], i["sk"]) for i in table.scan()["Items"] if i["pk"] == f"MAP#{stranger['map']}"
    }
    assert left == {
        (f"MAP#{stranger['map']}", "META"),
        (f"MAP#{stranger['map']}", f"MEMBER#{stranger['account']}"),
    }


def test_owner_deleting_account_hands_a_shared_map_to_the_next_member(
    owner, stranger, table, bucket, apple_api
):
    apple_api()
    share(owner, stranger)

    assert call(delete, **as_apple(owner))[0] == 200

    items = {i["sk"]: i for i in table.scan()["Items"] if i["pk"] == f"MAP#{owner['map']}"}
    assert "META" in items
    assert f"MEMBER#{owner['account']}" not in items
    assert items[f"MEMBER#{stranger['account']}"]["role"] == "owner"
    assert [k for k in items if k.startswith("HH#")]
    listed = boto3.client("s3").list_objects_v2(Bucket=bucket, Prefix=f"footprints/{owner['map']}/")
    assert listed["KeyCount"] == 1


def test_delete_removes_friend_edges_and_device_tokens(owner, stranger, table, apple_api):
    apple_api()
    me, them = owner["account"], stranger["account"]
    make_friends(me, them)
    token = "ab" * 32
    put_device(me, token, "ios", "production")

    call(delete, **as_apple(owner))

    left = {(i["pk"], i["sk"]) for i in table.scan()["Items"]}
    assert (f"ACCT#{them}", f"FRIEND#{me}") not in left
    assert (f"DEVICE#{token}", "DEVICE") not in left

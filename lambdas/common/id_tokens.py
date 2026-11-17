"""Verifies a Cognito ID token from this pool, for linking a second sign-in."""

from __future__ import annotations

import os
import time
from functools import cache

import jwt
from jwt.exceptions import PyJWKClientConnectionError

from lambdas.common.errors import ValidationError

# The client runs the second sign-in just before linking; an older auth_time
# means a token lifted from somewhere else, not a fresh sign-in.
MAX_AUTH_AGE_S = 600


def _issuer() -> str:
    region, pool = os.environ["AWS_REGION"], os.environ["USER_POOL_ID"]
    return f"https://cognito-idp.{region}.amazonaws.com/{pool}"


@cache
def _jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{_issuer()}/.well-known/jwks.json", timeout=5)


def verify_id_token(token: str) -> dict:
    """Claims of a valid, fresh ID token, else 400 `invalid_id_token`."""
    try:
        key = _jwks().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=os.environ["CLIENT_IDS"].split(","),
            issuer=_issuer(),
            options={"require": ["exp", "sub", "token_use", "auth_time"]},
        )
    except PyJWKClientConnectionError:
        raise
    except jwt.PyJWTError as e:
        raise ValidationError("Invalid ID token", code="invalid_id_token") from e
    if claims["token_use"] != "id" or time.time() - claims["auth_time"] > MAX_AUTH_AGE_S:
        raise ValidationError("Invalid ID token", code="invalid_id_token")
    return claims

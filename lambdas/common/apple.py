"""Sign in with Apple token revocation on account deletion (RESEARCH.md §6, TN3194)."""

from __future__ import annotations

import os
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt
from botocore.exceptions import ClientError

from lambdas.common.logger import log
from lambdas.common.ssm import secret

REVOKE_URL = "https://appleid.apple.com/auth/revoke"
MANUAL_REVOKE_URL = "https://support.apple.com/en-us/102571"


def _client_secret() -> str:
    now = int(time.time())
    claims = {
        "iss": os.environ["APPLE_TEAM_ID"],
        "iat": now,
        "exp": now + 300,
        "aud": "https://appleid.apple.com",
        "sub": os.environ["APPLE_SERVICES_ID"],
    }
    key = secret(os.environ["APPLE_PRIVATE_KEY_PARAM"])
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": os.environ["APPLE_KEY_ID"]})


def revoke(access_token: str) -> bool:
    """True if Apple accepted the revoke.

    False sends the user to manual revocation. TN3194 says the deletion goes ahead
    either way, so no failure here, a bad key included, may stop it.
    """
    try:
        form = {
            "client_id": os.environ["APPLE_SERVICES_ID"],
            "client_secret": _client_secret(),
            "token": access_token,
            "token_type_hint": "access_token",
        }
        with urlopen(Request(REVOKE_URL, data=urlencode(form).encode()), timeout=10):
            return True
    except (URLError, TimeoutError, ValueError, jwt.PyJWTError, ClientError) as e:
        log.warning(
            "apple_revoke_failed",
            extra={"error_type": type(e).__name__, "http_status": getattr(e, "code", None)},
        )
        return False

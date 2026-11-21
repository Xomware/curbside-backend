"""APNs over HTTP/2 with ES256 provider-token auth.

Config is three SSM parameters named by APNS_KEY_ID_PARAM, APNS_TEAM_ID_PARAM and
APNS_PRIVATE_KEY_PARAM, plus APNS_BUNDLE_ID as the topic. Until all are set (Terraform
creates the parameters as "unset"), every send is skipped.
"""

from __future__ import annotations

import os
import time
from functools import cache
from typing import Literal

import httpx
import jwt
from botocore.exceptions import ClientError

from lambdas.common.logger import log
from lambdas.common.ssm import secret

HOSTS = {
    "production": "https://api.push.apple.com",
    "sandbox": "https://api.sandbox.push.apple.com",
}
_PARAMS = ("APNS_KEY_ID_PARAM", "APNS_TEAM_ID_PARAM", "APNS_PRIVATE_KEY_PARAM")
# APNs rejects a provider token over an hour old, and one replaced more often than
# every 20 minutes (TooManyProviderTokenUpdates).
_TOKEN_MAX_AGE_S = 50 * 60
_provider_token = {"value": "", "issued_at": 0.0}

Outcome = Literal["sent", "dead", "failed", "unconfigured"]


@cache
def _client() -> httpx.Client:
    return httpx.Client(http2=True, timeout=10)


def _config() -> tuple[str, str, str] | None:
    names = [os.environ.get(p) for p in _PARAMS]
    if not all(names) or not os.environ.get("APNS_BUNDLE_ID"):
        return None
    try:
        key_id, team_id, key = (secret(n) for n in names)
    except ClientError as e:
        log.warning("apns_config_unreadable", extra={"error_code": e.response["Error"]["Code"]})
        return None
    if "unset" in (key_id, team_id, key):
        return None
    return key_id, team_id, key


def _bearer(key_id: str, team_id: str, key: str) -> str:
    now = time.time()
    if now - _provider_token["issued_at"] > _TOKEN_MAX_AGE_S:
        claims = {"iss": team_id, "iat": int(now)}
        value = jwt.encode(claims, key, algorithm="ES256", headers={"kid": key_id})
        _provider_token.update(value=value, issued_at=now)
    return _provider_token["value"]


def send(token: str, env: str, payload: dict) -> Outcome:
    """Never raises for APNs trouble. "dead" means the token will never work again."""
    config = _config()
    if not config:
        return "unconfigured"
    try:
        bearer = _bearer(*config)
    except (ValueError, jwt.PyJWTError) as e:
        log.error("apns_bad_key", extra={"error_type": type(e).__name__})
        return "unconfigured"
    headers = {
        "authorization": f"bearer {bearer}",
        "apns-topic": os.environ["APNS_BUNDLE_ID"],
        "apns-push-type": "alert",
        "apns-priority": "10",
    }
    try:
        resp = _client().post(f"{HOSTS[env]}/3/device/{token}", json=payload, headers=headers)
    except httpx.HTTPError as e:
        log.warning("apns_unreachable", extra={"error_type": type(e).__name__})
        return "failed"
    if resp.status_code == 200:
        return "sent"
    try:
        reason = resp.json().get("reason")
    except ValueError:
        reason = None
    if resp.status_code == 410 or reason == "BadDeviceToken":
        return "dead"
    log.warning("apns_rejected", extra={"http_status": resp.status_code, "reason": reason})
    return "failed"

from __future__ import annotations

from lambdas.common.dynamo import get_item, ident_key, member_key
from lambdas.common.errors import AuthError, NotFoundError

_accounts: dict[str, str] = {}


def get_sub(event: dict) -> str:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    sub = claims.get("sub")
    if not sub:
        raise AuthError("Missing caller identity")
    return sub


def get_account_id(event: dict) -> str:
    """Resolves the caller's sub to an account id, cached for the container's lifetime."""
    sub = get_sub(event)
    if sub in _accounts:
        return _accounts[sub]
    item = get_item(ident_key(sub))
    if not item:
        raise NotFoundError("No account for this sign-in", code="needs_onboarding")
    _accounts[sub] = item["account_id"]
    return item["account_id"]


def require_member(map_id: str, account_id: str) -> dict:
    # Same 404 whether the map is missing or just not yours, so ids can't be probed.
    item = get_item(member_key(map_id, account_id))
    if not item:
        raise NotFoundError("Map not found", code="map_not_found")
    return item

from __future__ import annotations

from lambdas.common.dynamo import get_item, ident_key, member_key
from lambdas.common.errors import AuthError, NotFoundError

# Cognito names federated users "<IdP provider_name>_<IdP sub>"; the provider
# names are set in curbside-infrastructure cognito_idps.tf.
_PROVIDERS = {"google": "google", "signinwithapple": "apple"}


def _claims(event: dict) -> dict:
    return event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})


def get_sub(event: dict) -> str:
    sub = _claims(event).get("sub")
    if not sub:
        raise AuthError("Missing caller identity")
    return sub


def provider_of(username: str) -> str:
    prefix = username.partition("_")[0].lower()
    return _PROVIDERS.get(prefix, prefix)


def get_provider(event: dict) -> str:
    return provider_of(_claims(event).get("username", ""))


def get_auth_time(event: dict) -> int:
    """When the caller last signed in, from the access token. HTTP APIs pass claims as strings."""
    return int(_claims(event).get("auth_time", 0))


def get_account_id(event: dict) -> str:
    # Read on every request, never cached: the JWT authorizer accepts an
    # unlinked sub's access token for up to an hour, so this read is what
    # stops it reaching the account.
    item = get_item(ident_key(get_sub(event)))
    if not item:
        raise NotFoundError("No account for this sign-in", code="needs_onboarding")
    return item["account_id"]


def require_member(map_id: str, account_id: str) -> dict:
    # Same 404 whether the map is missing or just not yours, so ids can't be probed.
    # Projected: footprints roles may only read these attributes of a MAP# item.
    item = get_item(member_key(map_id, account_id), ("pk", "sk", "role"))
    if not item:
        raise NotFoundError("Map not found", code="map_not_found")
    return item

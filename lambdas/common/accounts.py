"""Account and identity items: IDENT#<sub>, ACCT#<a>/PROFILE, ACCT#<a>/IDENT#<sub>."""

from __future__ import annotations

from datetime import UTC, datetime

from botocore.exceptions import ClientError

from lambdas.common.dynamo import (
    acct_ident_key,
    acct_key,
    get_item,
    ident_key,
    new_id,
    query_prefix,
    table,
)
from lambdas.common.errors import ConflictError, NotFoundError


def _profile(item: dict) -> dict:
    return {k: item[k] for k in ("account_id", "display_name", "created_at")}


def create_account(sub: str, provider: str, display_name: str) -> tuple[dict, bool]:
    """Returns (profile, created). A sub that already has an account gets that one back."""
    account_id = new_id()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    ident = {"account_id": account_id, "provider": provider, "created_at": now}
    profile = {"account_id": account_id, "display_name": display_name, "created_at": now}
    name = table().name
    try:
        table().meta.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": name,
                        "Item": {**ident_key(sub), **ident},
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {"Put": {"TableName": name, "Item": {**acct_key(account_id), **profile}}},
                {
                    "Put": {
                        "TableName": name,
                        "Item": {**acct_ident_key(account_id, sub), "sub": sub, **ident},
                    }
                },
            ]
        )
    except ClientError as e:
        reasons = e.response.get("CancellationReasons") or [{}]
        if reasons[0].get("Code") != "ConditionalCheckFailed":
            raise
        existing = get_item(ident_key(sub))
        return _profile(get_item(acct_key(existing["account_id"]))), False
    return profile, True


def get_account(account_id: str) -> dict:
    identities = [
        {k: item[k] for k in ("sub", "provider", "created_at")}
        for item in query_prefix(f"ACCT#{account_id}", "IDENT#")
    ]
    return {**_profile(get_item(acct_key(account_id))), "identities": identities}


def link_identity(account_id: str, sub: str, provider: str) -> dict:
    existing = get_item(ident_key(sub))
    if existing:
        same = existing["account_id"] == account_id
        raise ConflictError(
            "This sign-in is already linked" if same else "This sign-in has its own account",
            code="already_linked" if same else "identity_in_use",
        )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    ident = {"account_id": account_id, "provider": provider, "created_at": now}
    name = table().name
    try:
        table().meta.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": name,
                        "Item": {**ident_key(sub), **ident},
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": name,
                        "Item": {**acct_ident_key(account_id, sub), "sub": sub, **ident},
                    }
                },
            ]
        )
    except ClientError as e:
        reasons = e.response.get("CancellationReasons") or [{}]
        if reasons[0].get("Code") != "ConditionalCheckFailed":
            raise
        raise ConflictError("This sign-in has its own account", code="identity_in_use") from e
    return {"sub": sub, "provider": provider, "created_at": now}


def unlink_identity(account_id: str, sub: str) -> None:
    # Two concurrent unlinks can both pass the last-identity check; guarding it
    # needs UpdateItem or ConditionCheckItem, which me_unlink's role lacks.
    subs = {item["sub"] for item in query_prefix(f"ACCT#{account_id}", "IDENT#")}
    if sub not in subs:
        raise NotFoundError("Sign-in not found", code="identity_not_found")
    if len(subs) == 1:
        raise ConflictError("Can't remove the only sign-in", code="last_identity")
    # A transaction, not delete_keys: the role has DeleteItem but no BatchWriteItem.
    name = table().name
    table().meta.client.transact_write_items(
        TransactItems=[
            {"Delete": {"TableName": name, "Key": key}}
            for key in (ident_key(sub), acct_ident_key(account_id, sub))
        ]
    )

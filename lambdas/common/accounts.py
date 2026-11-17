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

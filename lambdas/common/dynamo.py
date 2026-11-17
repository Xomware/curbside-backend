"""Single-table access. Key shapes follow the DynamoDB section of the Curbside epic plan."""

from __future__ import annotations

import os
import secrets
import time
from functools import cache

import boto3
from boto3.dynamodb.conditions import Key

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@cache
def table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def ident_key(sub: str) -> dict:
    return {"pk": f"IDENT#{sub}", "sk": "IDENT"}


def acct_key(account_id: str) -> dict:
    return {"pk": f"ACCT#{account_id}", "sk": "PROFILE"}


def acct_ident_key(account_id: str, sub: str) -> dict:
    return {"pk": f"ACCT#{account_id}", "sk": f"IDENT#{sub}"}


def member_key(map_id: str, account_id: str) -> dict:
    return {"pk": f"MAP#{map_id}", "sk": f"MEMBER#{account_id}"}


def get_item(key: dict) -> dict | None:
    # Consistent: a client calls GET /me straight after POST /me, and a stale
    # read there sends the user back to onboarding.
    return table().get_item(Key=key, ConsistentRead=True).get("Item")


def query_prefix(pk: str, sk_prefix: str) -> list[dict]:
    items: list[dict] = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
        "ConsistentRead": True,
    }
    while True:
        resp = table().query(**kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def new_id() -> str:
    """ULID: 48-bit millisecond timestamp + 80 random bits, Crockford base32."""
    n = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    return "".join(_CROCKFORD[(n >> shift) & 31] for shift in range(125, -1, -5))

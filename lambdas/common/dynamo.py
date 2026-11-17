"""Single-table access. Key shapes follow the DynamoDB section of the Curbside epic plan."""

from __future__ import annotations

import os
from functools import cache

import boto3


@cache
def table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def ident_key(sub: str) -> dict:
    return {"pk": f"IDENT#{sub}", "sk": "IDENT"}


def member_key(map_id: str, account_id: str) -> dict:
    return {"pk": f"MAP#{map_id}", "sk": f"MEMBER#{account_id}"}


def get_item(key: dict) -> dict | None:
    # Consistent: a client calls GET /me straight after POST /me, and a stale
    # read there sends the user back to onboarding.
    return table().get_item(Key=key, ConsistentRead=True).get("Item")

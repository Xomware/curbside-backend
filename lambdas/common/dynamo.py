"""Single-table access. Key shapes follow the DynamoDB section of the Curbside epic plan."""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from lambdas.common.errors import ConflictError, NotFoundError

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@cache
def db():
    return boto3.resource("dynamodb")


@cache
def table():
    return db().Table(os.environ["TABLE_NAME"])


def ident_key(sub: str) -> dict:
    return {"pk": f"IDENT#{sub}", "sk": "IDENT"}


def acct_key(account_id: str) -> dict:
    return {"pk": f"ACCT#{account_id}", "sk": "PROFILE"}


def acct_ident_key(account_id: str, sub: str) -> dict:
    return {"pk": f"ACCT#{account_id}", "sk": f"IDENT#{sub}"}


def member_key(map_id: str, account_id: str) -> dict:
    return {"pk": f"MAP#{map_id}", "sk": f"MEMBER#{account_id}"}


def meta_key(map_id: str) -> dict:
    return {"pk": f"MAP#{map_id}", "sk": "META"}


def get_item(key: dict, attrs: tuple[str, ...] = ()) -> dict | None:
    # Consistent: a client calls GET /me straight after POST /me, and a stale
    # read there sends the user back to onboarding.
    kwargs: dict = {"Key": key, "ConsistentRead": True}
    if attrs:
        kwargs["ProjectionExpression"] = ", ".join(f"#{a}" for a in attrs)
        kwargs["ExpressionAttributeNames"] = {f"#{a}": a for a in attrs}
    return table().get_item(**kwargs).get("Item")


def query_prefix(pk: str, sk_prefix: str = "", gsi: bool = False) -> list[dict]:
    hash_key, range_key = ("gsi1pk", "gsi1sk") if gsi else ("pk", "sk")
    condition = Key(hash_key).eq(pk)
    if sk_prefix:
        condition &= Key(range_key).begins_with(sk_prefix)
    kwargs: dict = {"KeyConditionExpression": condition}
    if gsi:
        kwargs["IndexName"] = "gsi1"
    else:
        kwargs["ConsistentRead"] = True
    items: list[dict] = []
    while True:
        resp = table().query(**kwargs)
        items += resp["Items"]
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def batch_get(keys: list[dict]) -> list[dict]:
    items: list[dict] = []
    name = table().name
    for i in range(0, len(keys), 100):
        request = {name: {"Keys": keys[i : i + 100], "ConsistentRead": True}}
        while request:
            resp = db().batch_get_item(RequestItems=request)
            items += resp["Responses"].get(name, [])
            request = resp.get("UnprocessedKeys")
    return items


def delete_keys(keys: list[dict]) -> None:
    """Deletes in the given order, 25 per BatchWriteItem."""
    with table().batch_writer() as batch:
        for key in keys:
            batch.delete_item(Key=key)


def update_versioned(key: dict, fields: dict, version: int, entity: str) -> dict:
    """SETs fields (None REMOVEs) and bumps `version`, if it still equals `version`."""
    names = {"#v": "version"}
    values: dict = {":v": version, ":one": 1}
    sets, removes = ["#v = #v + :one"], []
    for i, (name, value) in enumerate(to_item(fields).items()):
        names[f"#f{i}"] = name
        if value is None:
            removes.append(f"#f{i}")
        else:
            values[f":f{i}"] = value
            sets.append(f"#f{i} = :f{i}")
    expression = "SET " + ", ".join(sets) + (" REMOVE " + ", ".join(removes) if removes else "")
    try:
        return table().update_item(
            Key=key,
            UpdateExpression=expression,
            ConditionExpression="#v = :v",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
            ReturnValuesOnConditionCheckFailure="ALL_OLD",
        )["Attributes"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        if "Item" not in e.response:
            raise NotFoundError(f"{entity} not found", code=f"{entity.lower()}_not_found") from e
        raise ConflictError(f"{entity} was changed by someone else; refetch it") from e


def delete_existing(key: dict, entity: str) -> None:
    try:
        table().delete_item(Key=key, ConditionExpression="attribute_exists(pk)")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise NotFoundError(f"{entity} not found", code=f"{entity.lower()}_not_found") from e


def to_item(data: dict) -> dict:
    """boto3 rejects float; DynamoDB numbers go in as Decimal."""
    return json.loads(json.dumps(data), parse_float=Decimal)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    """ULID: 48-bit millisecond timestamp + 80 random bits, Crockford base32."""
    n = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    return "".join(_CROCKFORD[(n >> shift) & 31] for shift in range(125, -1, -5))


def new_code() -> str:
    """10 Crockford base32 chars, 50 random bits."""
    return "".join(secrets.choice(_CROCKFORD) for _ in range(10))

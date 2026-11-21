"""Push tokens: ACCT#<a>/DEVICE#<token>, plus DEVICE#<token>/DEVICE naming the account
that has it, so a token that signs in to another account moves rather than pushing to both."""

from __future__ import annotations

import re

from botocore.exceptions import ClientError

from lambdas.common.dynamo import get_item, now, table
from lambdas.common.errors import ValidationError

_TOKEN = re.compile("[0-9a-f]{64,200}")


def device_key(account_id: str, token: str) -> dict:
    return {"pk": f"ACCT#{account_id}", "sk": f"DEVICE#{token}"}


def holder_key(token: str) -> dict:
    return {"pk": f"DEVICE#{token}", "sk": "DEVICE"}


def path_token(event: dict) -> str:
    token = (event.get("pathParameters") or {}).get("token", "").lower()
    if not _TOKEN.fullmatch(token):
        raise ValidationError("Device token must be hex")
    return token


def put_device(account_id: str, token: str, platform: str, env: str) -> None:
    device = {
        **device_key(account_id, token),
        "token": token,
        "platform": platform,
        "env": env,
        "updated_at": now(),
    }
    holder = {**holder_key(token), "account_id": account_id}
    name = table().name
    writes = [{"Put": {"TableName": name, "Item": item}} for item in (device, holder)]
    previous = get_item(holder_key(token), ("account_id",))
    if previous and previous["account_id"] != account_id:
        old = device_key(previous["account_id"], token)
        writes.append({"Delete": {"TableName": name, "Key": old}})
    table().meta.client.transact_write_items(TransactItems=writes)


def delete_device(account_id: str, token: str) -> None:
    table().delete_item(Key=device_key(account_id, token))
    try:
        table().delete_item(
            Key=holder_key(token),
            ConditionExpression="account_id = :a",
            ExpressionAttributeValues={":a": account_id},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # Another account has registered the token since; it's theirs now.

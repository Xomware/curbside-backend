"""Single-use invites to co-edit a map: INVITE#<code>/INVITE, live for 7 days."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta

from botocore.exceptions import ClientError

from lambdas.common.dynamo import get_item, member_key, meta_key, new_code, now, table
from lambdas.common.errors import NotFoundError

INVITE_TTL = timedelta(days=7)
_CODE = re.compile("[0-9A-HJKMNP-TV-Z]{10}")


def invite_key(code: str) -> dict:
    return {"pk": f"INVITE#{code}", "sk": "INVITE"}


def _not_found() -> NotFoundError:
    return NotFoundError("Invite not found or expired", code="invite_not_found")


def create_invite(map_id: str, account_id: str) -> dict:
    created = datetime.now(UTC).replace(microsecond=0)
    expires = created + INVITE_TTL
    item = {
        **invite_key(new_code()),
        "map_id": map_id,
        "created_by": account_id,
        "created_at": created.isoformat(),
        "expires_at": expires.isoformat(),
        "ttl": int(expires.timestamp()),
    }
    table().put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    return {"code": item["pk"].removeprefix("INVITE#"), "expires_at": item["expires_at"]}


def get_invite(code: str) -> tuple[dict, dict]:
    """The live invite and its map's META, else 404 `invite_not_found`.

    Checks expiry itself: TTL deletes can lag by days. An invite whose map was
    deleted is dead too.
    """
    invite = get_item(invite_key(code)) if _CODE.fullmatch(code) else None
    if not invite or invite["ttl"] <= time.time():
        raise _not_found()
    meta = get_item(meta_key(invite["map_id"]))
    if not meta:
        raise _not_found()
    return invite, meta


def accept_invite(code: str, map_id: str, account_id: str) -> None:
    """Adds a "member" MEMBER item and spends the invite, in one transaction."""
    member = {
        **member_key(map_id, account_id),
        "gsi1pk": f"ACCT#{account_id}",
        "gsi1sk": f"MAP#{map_id}",
        "role": "member",
        "created_at": now(),
    }
    name = table().name
    try:
        table().meta.client.transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": name,
                        "Key": invite_key(code),
                        "ConditionExpression": "attribute_exists(pk) AND #ttl > :now",
                        "ExpressionAttributeNames": {"#ttl": "ttl"},
                        "ExpressionAttributeValues": {":now": int(time.time())},
                    }
                },
                {
                    "Put": {
                        "TableName": name,
                        "Item": member,
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "ConditionCheck": {
                        "TableName": name,
                        "Key": meta_key(map_id),
                        "ConditionExpression": "attribute_exists(pk)",
                    }
                },
            ]
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        # A double-tapped accept: the first request spent the invite and joined.
        if get_item(member_key(map_id, account_id), ("pk",)):
            return
        raise _not_found() from e

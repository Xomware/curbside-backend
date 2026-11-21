"""Activity feed: ACCT#<a>/ACTIVITY#<iso-ts>#<id> items, read up to ACCT#<a>/ACTIVITY_SEEN.

push_send fans new items out to the recipient's devices from the table stream.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from lambdas.common.dynamo import acct_key, get_item, new_id, now, table
from lambdas.common.logger import log

ACTIVITY_TTL = timedelta(days=90)
LIMIT = 50
_OPTIONAL = ("map_id", "map_name", "household_label")


def seen_key(account_id: str) -> dict:
    return {"pk": f"ACCT#{account_id}", "sk": "ACTIVITY_SEEN"}


def notify(
    recipients: list[str],
    kind: str,
    actor_id: str,
    map_id: str | None = None,
    map_name: str | None = None,
    household_label: str | None = None,
) -> None:
    """One item per recipient, never the actor.

    Best effort: the action it reports has already been written, and a 500 here
    would have the client retry that action.
    """
    recipients = [r for r in dict.fromkeys(recipients) if r != actor_id]
    if not recipients:
        return
    created = datetime.now(UTC).replace(microsecond=0)
    actor = get_item(acct_key(actor_id), ("display_name",))
    fields = {
        "kind": kind,
        "actor_id": actor_id,
        "actor_name": actor["display_name"],
        "created_at": created.isoformat(),
        "ttl": int((created + ACTIVITY_TTL).timestamp()),
    }
    optional = {"map_id": map_id, "map_name": map_name, "household_label": household_label}
    fields |= {k: v for k, v in optional.items() if v is not None}
    try:
        with table().batch_writer() as batch:
            for r in recipients:
                sk = f"ACTIVITY#{fields['created_at']}#{new_id()}"
                batch.put_item(Item={"pk": f"ACCT#{r}", "sk": sk, **fields})
    except ClientError as e:
        log.error(
            "activity_write_failed",
            extra={"kind": kind, "error_code": e.response["Error"]["Code"]},
        )


def _view(item: dict) -> dict:
    view = {
        "id": item["sk"].rpartition("#")[2],
        "kind": item["kind"],
        "actor_name": item["actor_name"],
        "created_at": item["created_at"],
    }
    return view | {k: item[k] for k in _OPTIONAL if k in item}


def list_activity(account_id: str) -> dict:
    resp = table().query(
        KeyConditionExpression=Key("pk").eq(f"ACCT#{account_id}")
        & Key("sk").begins_with("ACTIVITY#"),
        ScanIndexForward=False,
        Limit=LIMIT,
        ConsistentRead=True,
    )
    items = [_view(i) for i in resp["Items"]]
    seen = get_item(seen_key(account_id), ("seen_at",))
    seen_at = seen["seen_at"] if seen else ""
    return {"items": items, "unread": sum(i["created_at"] > seen_at for i in items)}


def mark_seen(account_id: str) -> None:
    table().put_item(Item={**seen_key(account_id), "seen_at": now()})

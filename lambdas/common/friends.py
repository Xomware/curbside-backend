"""Friends: ACCT#<a>/FRIEND#<b>, written both ways in one transaction, and single-use
friend links FRIENDINVITE#<code>/FRIENDINVITE, live for 7 days."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from botocore.exceptions import ClientError

from lambdas.common.activity import notify
from lambdas.common.dynamo import (
    acct_key,
    batch_get,
    get_item,
    meta_key,
    new_code,
    now,
    query_prefix,
    table,
)
from lambdas.common.errors import ConflictError, NotFoundError
from lambdas.common.invites import CODE, INVITE_TTL


def friend_key(account_id: str, friend_id: str) -> dict:
    return {"pk": f"ACCT#{account_id}", "sk": f"FRIEND#{friend_id}"}


def friend_invite_key(code: str) -> dict:
    return {"pk": f"FRIENDINVITE#{code}", "sk": "FRIENDINVITE"}


def _not_found() -> NotFoundError:
    return NotFoundError("Invite not found or expired", code="invite_not_found")


def _edge_puts(a: str, b: str) -> list[dict]:
    name, created = table().name, now()
    return [
        {
            "Put": {
                "TableName": name,
                "Item": {**friend_key(x, y), "account_id": y, "created_at": created},
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        }
        for x, y in ((a, b), (b, a))
    ]


def make_friends(a: str, b: str) -> None:
    """Idempotent: already friends keeps the original `since`."""
    if get_item(friend_key(a, b), ("pk",)):
        return
    try:
        table().meta.client.transact_write_items(TransactItems=_edge_puts(a, b))
    except ClientError as e:
        if e.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        if not get_item(friend_key(a, b), ("pk",)):
            raise


def remove_friend(a: str, b: str) -> None:
    name = table().name
    table().meta.client.transact_write_items(
        TransactItems=[
            {"Delete": {"TableName": name, "Key": key}}
            for key in (friend_key(a, b), friend_key(b, a))
        ]
    )


def _map_ids(account_id: str) -> set[str]:
    memberships = query_prefix(f"ACCT#{account_id}", "MAP#", gsi=True)
    return {m["pk"].removeprefix("MAP#") for m in memberships}


def _views(account_id: str, edges: list[dict]) -> list[dict]:
    ids = [e["account_id"] for e in edges]
    names = {p["account_id"]: p["display_name"] for p in batch_get([acct_key(i) for i in ids])}
    mine = _map_ids(account_id)
    shared = {i: mine & _map_ids(i) for i in ids}
    metas = batch_get([meta_key(m) for m in set().union(*shared.values())])
    map_names = {m["pk"].removeprefix("MAP#"): m["name"] for m in metas}
    rows = [
        {
            "account_id": e["account_id"],
            "display_name": names[e["account_id"]],
            "since": e["created_at"],
            "shared_maps": sorted(
                ({"map_id": m, "name": map_names[m]} for m in shared[e["account_id"]]),
                key=lambda m: m["name"].casefold(),
            ),
        }
        for e in edges
        # A friend mid-way through deleting their account has no PROFILE left.
        if e["account_id"] in names
    ]
    return sorted(rows, key=lambda r: r["display_name"].casefold())


def list_friends(account_id: str) -> list[dict]:
    return _views(account_id, query_prefix(f"ACCT#{account_id}", "FRIEND#"))


def get_friend(account_id: str, friend_id: str) -> dict | None:
    edge = get_item(friend_key(account_id, friend_id))
    views = _views(account_id, [edge]) if edge else []
    return views[0] if views else None


def create_friend_invite(account_id: str) -> dict:
    created = datetime.now(UTC).replace(microsecond=0)
    expires = created + INVITE_TTL
    item = {
        **friend_invite_key(new_code()),
        "created_by": account_id,
        "created_at": created.isoformat(),
        "expires_at": expires.isoformat(),
        "ttl": int(expires.timestamp()),
    }
    table().put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    return {"code": item["pk"].removeprefix("FRIENDINVITE#"), "expires_at": item["expires_at"]}


def get_friend_invite(code: str) -> tuple[dict, dict]:
    """The live invite and its creator's PROFILE, else 404 `invite_not_found`.

    Checks expiry itself, since TTL deletes lag.
    """
    invite = get_item(friend_invite_key(code)) if CODE.fullmatch(code) else None
    if not invite or invite["ttl"] <= time.time():
        raise _not_found()
    inviter = get_item(acct_key(invite["created_by"]), ("account_id", "display_name"))
    if not inviter:
        raise _not_found()
    return invite, inviter


def accept_friend_invite(code: str, account_id: str) -> dict:
    """Makes the caller and the link's creator friends and spends the link, in one transaction.

    Already friends returns the friend and leaves the link unspent.
    """
    _, inviter = get_friend_invite(code)
    inviter_id = inviter["account_id"]
    if inviter_id == account_id:
        raise ConflictError("That's your own friend link", code="own_invite")
    friend = get_friend(account_id, inviter_id)
    if friend:
        return friend
    name = table().name
    try:
        table().meta.client.transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": name,
                        "Key": friend_invite_key(code),
                        "ConditionExpression": "attribute_exists(pk) AND #ttl > :now",
                        "ExpressionAttributeNames": {"#ttl": "ttl"},
                        "ExpressionAttributeValues": {":now": int(time.time())},
                    }
                },
                *_edge_puts(account_id, inviter_id),
                {
                    "ConditionCheck": {
                        "TableName": name,
                        "Key": acct_key(inviter_id),
                        "ConditionExpression": "attribute_exists(pk)",
                    }
                },
            ]
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        # A double-tapped accept: the first request spent the link.
        friend = get_friend(account_id, inviter_id)
        if friend:
            return friend
        raise _not_found() from e
    notify([inviter_id], "friend_added", account_id)
    return get_friend(account_id, inviter_id)

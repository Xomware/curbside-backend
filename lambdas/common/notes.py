"""Notes sort as NOTE#<h>#<ulid>, outside HH#, so loading a map never reads them."""

from __future__ import annotations

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from lambdas.common.dynamo import new_id, now, table
from lambdas.common.errors import NotFoundError
from lambdas.common.households import child_view, hh_key
from lambdas.common.models import NoteCreate


def note_key(map_id: str, hh_id: str, note_id: str) -> dict:
    return {"pk": f"MAP#{map_id}", "sk": f"NOTE#{hh_id}#{note_id}"}


def create_note(map_id: str, hh_id: str, body: NoteCreate) -> dict:
    """Writes the note and sets the household's last_talked_at, without bumping its version."""
    created = now()
    item = {**note_key(map_id, hh_id, new_id()), **body.model_dump(), "created_at": created}
    name = table().name
    touch = {
        "TableName": name,
        "Key": hh_key(map_id, hh_id),
        "UpdateExpression": "SET last_talked_at = :t",
        "ConditionExpression": "attribute_exists(pk)",
        "ExpressionAttributeValues": {":t": created},
    }
    try:
        table().meta.client.transact_write_items(
            TransactItems=[{"Put": {"TableName": name, "Item": item}}, {"Update": touch}]
        )
    except ClientError as e:
        reasons = e.response.get("CancellationReasons") or [{}, {}]
        if reasons[1].get("Code") != "ConditionalCheckFailed":
            raise
        raise NotFoundError("Household not found", code="household_not_found") from e
    return child_view(item)


def recent_notes(map_id: str, hh_id: str, limit: int = 50) -> list[dict]:
    resp = table().query(
        KeyConditionExpression=Key("pk").eq(f"MAP#{map_id}")
        & Key("sk").begins_with(f"NOTE#{hh_id}#"),
        ScanIndexForward=False,
        Limit=limit,
        ConsistentRead=True,
    )
    return [child_view(item) for item in resp["Items"]]

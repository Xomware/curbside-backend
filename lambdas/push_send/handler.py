"""DynamoDB stream, no route - Push each new ACTIVITY# item to its account's iOS devices.

Records: INSERTs whose sk begins with ACTIVITY#, NEW_IMAGE (the event source mapping
filters them). Tokens APNs calls dead are deleted. Never raises for APNs trouble:
a failed batch is retried whole, re-pushing to every device that already got it.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from boto3.dynamodb.types import TypeDeserializer

from lambdas.common.apns import send
from lambdas.common.devices import delete_device, list_devices
from lambdas.common.logger import log

HANDLER = "push_send"
_deserialize = TypeDeserializer().deserialize

ALERTS = {
    "member_joined": "{actor_name} joined {map_name}",
    "added_to_street": "{actor_name} added you to {map_name}",
    "removed_from_street": "{actor_name} removed you from {map_name}",
    "street_handed_to_you": "{map_name} is yours now",
    "household_added": "{actor_name} added {household_label} to {map_name}",
    "friend_added": "You and {actor_name} are friends",
}


def _payload(item: dict) -> dict:
    payload = {
        "aps": {"alert": {"body": ALERTS[item["kind"]].format(**item)}, "sound": "default"},
        "kind": item["kind"],
    }
    if "map_id" in item:
        payload["map_id"] = item["map_id"]
    return payload


def handler(event: dict, context: Any) -> None:
    outcomes: Counter[str] = Counter()
    for record in event["Records"]:
        image = record["dynamodb"]["NewImage"]
        item = {k: _deserialize(v) for k, v in image.items()}
        account_id = item["pk"].removeprefix("ACCT#")
        payload = _payload(item)
        for device in list_devices(account_id):
            outcome = send(device["token"], device["env"], payload)
            if outcome == "dead":
                delete_device(account_id, device["token"])
            outcomes[outcome] += 1
    log.info(HANDLER, extra={"records": len(event["Records"]), **outcomes})

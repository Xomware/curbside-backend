"""Footprint files: s3://$FOOTPRINTS_BUCKET/footprints/<mapId>/v<n>.geojson.gz."""

from __future__ import annotations

import gzip
import json
import os
from datetime import UTC, datetime, timedelta
from functools import cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from lambdas.common.dynamo import get_item, meta_key, now, table
from lambdas.common.errors import RateLimitError

REFRESH_COOLDOWN = timedelta(minutes=5)


@cache
def s3():
    # SigV4 presigning: objects are SSE-KMS, which S3 refuses to serve on SigV2.
    return boto3.client("s3", config=Config(signature_version="s3v4"))


@cache
def _lambda():
    return boto3.client("lambda")


def start_fetch(map_id: str) -> None:
    _lambda().invoke(
        FunctionName=os.environ["FOOTPRINTS_FETCH_FUNCTION"],
        InvocationType="Event",
        Payload=json.dumps({"map_id": map_id}).encode(),
    )


def get_footprint(map_id: str) -> dict:
    # Projected: the footprints roles may only read these attributes of a MAP# item.
    return get_item(meta_key(map_id), ("pk", "sk", "footprint"))["footprint"]


def presign(map_id: str, version: int) -> str:
    return s3().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": os.environ["FOOTPRINTS_BUCKET"],
            "Key": f"footprints/{map_id}/v{version}.geojson.gz",
        },
        ExpiresIn=300,
    )


def mark_refresh(map_id: str) -> None:
    """Sets the footprint pending, unless a fetch was requested in the last 5 minutes.

    The cooldown keeps Overpass load low and still frees a map left pending by a crash.
    """
    footprint = {**get_footprint(map_id), "status": "pending", "requested_at": now()}
    cutoff = (datetime.now(UTC) - REFRESH_COOLDOWN).isoformat(timespec="seconds")
    try:
        table().update_item(
            Key=meta_key(map_id),
            UpdateExpression="SET #fp = :fp",
            ConditionExpression="attribute_not_exists(#fp.requested_at) OR #fp.requested_at < :cut",
            ExpressionAttributeNames={"#fp": "footprint"},
            ExpressionAttributeValues={":fp": footprint, ":cut": cutoff},
            ReturnValues="NONE",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise RateLimitError("Footprints were refreshed recently", code="refresh_too_soon") from e


def delete_footprints(map_id: str) -> None:
    bucket = os.environ["FOOTPRINTS_BUCKET"]
    pages = (
        s3()
        .get_paginator("list_objects_v2")
        .paginate(Bucket=bucket, Prefix=f"footprints/{map_id}/")
    )
    for page in pages:
        objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if not objects:
            continue
        resp = s3().delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
        if resp.get("Errors"):
            raise RuntimeError(f"{len(resp['Errors'])} footprint objects not deleted")


def put_footprints(map_id: str, version: int, features: list[dict]) -> None:
    body = json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
    s3().put_object(
        Bucket=os.environ["FOOTPRINTS_BUCKET"],
        Key=f"footprints/{map_id}/v{version}.geojson.gz",
        Body=gzip.compress(body.encode(), mtime=0),
        ContentType="application/geo+json",
        ContentEncoding="gzip",
    )


def set_footprint(map_id: str, footprint: dict) -> None:
    """Replaces META.footprint whole.

    The footprints roles may name only pk, sk and footprint, with ReturnValues
    NONE. Nested paths would need placeholders for reserved words like status
    and count, and IAM's attribute check is documented for top-level names
    only, so the map is written whole. The condition stops a map deleted
    mid-fetch coming back as a stray item.
    """
    table().update_item(
        Key=meta_key(map_id),
        UpdateExpression="SET #fp = :fp",
        ConditionExpression="attribute_exists(pk)",
        ExpressionAttributeNames={"#fp": "footprint"},
        ExpressionAttributeValues={":fp": footprint},
        ReturnValues="NONE",
    )

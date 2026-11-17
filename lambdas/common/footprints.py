"""Footprint files: s3://$FOOTPRINTS_BUCKET/footprints/<mapId>/v<n>.geojson.gz."""

from __future__ import annotations

import gzip
import json
import os
from functools import cache

import boto3

from lambdas.common.dynamo import meta_key, table


@cache
def s3():
    return boto3.client("s3")


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

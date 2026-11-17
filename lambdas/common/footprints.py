"""Footprint files: s3://$FOOTPRINTS_BUCKET/footprints/<mapId>/v<n>.geojson.gz."""

from __future__ import annotations

import os
from functools import cache

import boto3


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

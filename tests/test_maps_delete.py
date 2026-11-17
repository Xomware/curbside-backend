from __future__ import annotations

import boto3
from conftest import call

from lambdas.common.accounts import create_account
from lambdas.maps_delete.handler import handler


def test_deletes_partition_and_footprints(table, bucket, map_id, account):
    for i in range(30):
        table.put_item(Item={"pk": f"MAP#{map_id}", "sk": f"HH#{i:026d}"})
    table.put_item(Item={"pk": "MAP#OTHER", "sk": "META"})
    s3 = boto3.client("s3")
    for key in (f"footprints/{map_id}/v1.geojson.gz", "footprints/OTHER/v1.geojson.gz"):
        s3.put_object(Bucket=bucket, Key=key, Body=b"{}")

    status, body = call(handler, path={"mapId": map_id})

    assert (status, body["data"]) == (200, {"id": map_id})
    left = {(i["pk"], i["sk"]) for i in table.scan()["Items"] if i["pk"].startswith("MAP#")}
    assert left == {("MAP#OTHER", "META")}
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=bucket)["Contents"]]
    assert keys == ["footprints/OTHER/v1.geojson.gz"]


def test_non_member_cannot_delete(table, bucket, map_id):
    create_account("sub-other", "apple", "Other")
    status, _ = call(handler, path={"mapId": map_id}, sub="sub-other")
    assert status == 404
    assert table.get_item(Key={"pk": f"MAP#{map_id}", "sk": "META"}).get("Item")

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

os.environ.update(
    AWS_DEFAULT_REGION="us-east-1",
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    TABLE_NAME="curbside-test",
    FOOTPRINTS_BUCKET="curbside-footprints-test",
)

import boto3  # noqa: E402
import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402

from lambdas.common import dynamo, footprints  # noqa: E402
from lambdas.common.accounts import create_account  # noqa: E402
from lambdas.common.households import create_household  # noqa: E402
from lambdas.common.maps import create_map  # noqa: E402
from lambdas.common.models import HouseholdCreate, MapCreate  # noqa: E402


@pytest.fixture
def table():
    with mock_aws():
        for cached in (dynamo.db, dynamo.table, footprints.s3):
            cached.cache_clear()
        yield boto3.resource("dynamodb").create_table(
            TableName=os.environ["TABLE_NAME"],
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"} for n in ("pk", "sk", "gsi1pk", "gsi1sk")
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "gsi1",
                    "KeySchema": [
                        {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                        {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )


def api_event(
    body: dict | str | None = None,
    sub: str | None = "sub-test-1",
    route: str = "POST /test",
    headers: dict | None = None,
    query: dict | None = None,
    username: str | None = None,
    path: dict | None = None,
) -> dict:
    """HTTP API payload v2.0, as delivered behind the Cognito JWT authorizer."""
    claims = {"sub": sub, "username": username or f"google_{sub}"}
    authorizer = {"jwt": {"claims": claims}} if sub else {}
    return {
        "version": "2.0",
        "routeKey": route,
        "headers": headers or {},
        "queryStringParameters": query,
        "pathParameters": path,
        "body": body if isinstance(body, str) or body is None else json.dumps(body),
        "isBase64Encoded": False,
        "requestContext": {"authorizer": authorizer},
    }


def call(handler: Callable, body: dict | str | None = None, **kwargs: Any) -> tuple[int, dict]:
    resp = handler(api_event(body, **kwargs), None)
    return resp["statusCode"], json.loads(resp["body"])


@pytest.fixture
def account(table) -> str:
    """Account id for the default caller, sub-test-1."""
    return create_account("sub-test-1", "google", "Test Neighbor")[0]["account_id"]


@pytest.fixture
def map_id(account) -> str:
    body = MapCreate(name="Elm St", center={"lat": 40.0, "lng": -75.0})
    return create_map(account, body)["id"]


@pytest.fixture
def hh_id(map_id) -> str:
    body = HouseholdCreate(label="Blue house", lat=40.001, lng=-75.002, address="12 Elm St")
    return create_household(map_id, body)["id"]


@pytest.fixture
def bucket(table) -> str:
    name = os.environ["FOOTPRINTS_BUCKET"]
    boto3.client("s3").create_bucket(Bucket=name)
    return name


@pytest.fixture
def dynamo_calls(table) -> list[tuple[str, dict]]:
    """(operation, params) of every DynamoDB call the code makes.

    moto doesn't enforce IAM, so tests for the attribute-scoped roles assert
    on these instead.
    """
    calls: list[tuple[str, dict]] = []

    def record(params: dict, model: Any, **_: Any) -> None:
        calls.append((model.name, dict(params)))

    dynamo.table().meta.client.meta.events.register("before-parameter-build.dynamodb", record)
    return calls


def named_attributes(params: dict) -> set[str]:
    return set(params.get("ExpressionAttributeNames", {}).values()) | set(params.get("Key", {}))

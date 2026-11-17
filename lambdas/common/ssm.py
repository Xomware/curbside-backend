from __future__ import annotations

from functools import cache

import boto3


@cache
def secret(name: str) -> str:
    """A SecureString parameter, read once per container."""
    return boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]

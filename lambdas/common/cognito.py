"""Cognito users by sub. Admin* calls take the username, which for federated users
is "<provider>_<IdP sub>", so ListUsers with a sub filter maps one to the other."""

from __future__ import annotations

import os
from functools import cache

import boto3


@cache
def cognito():
    return boto3.client("cognito-idp")


def find_user(sub: str) -> dict | None:
    users = cognito().list_users(
        UserPoolId=os.environ["USER_POOL_ID"], Filter=f'sub = "{sub}"', Limit=1
    )["Users"]
    return users[0] if users else None


def user_attribute(user: dict, name: str) -> str | None:
    return next((a["Value"] for a in user["Attributes"] if a["Name"] == name), None)


def delete_users(subs: list[str]) -> None:
    """Deletes each sub's Cognito user. Ones already gone are skipped, so a retry is safe."""
    for sub in subs:
        user = find_user(sub)
        if user:
            cognito().admin_delete_user(
                UserPoolId=os.environ["USER_POOL_ID"], Username=user["Username"]
            )

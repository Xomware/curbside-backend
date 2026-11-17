from __future__ import annotations

import pytest
from conftest import api_event

from lambdas.common.auth import get_account_id, get_sub, require_member
from lambdas.common.errors import AuthError, NotFoundError


def test_get_sub_reads_jwt_claims():
    assert get_sub(api_event(sub="sub-abc")) == "sub-abc"


@pytest.mark.parametrize("event", [api_event(sub=None), {}, {"requestContext": {}}])
def test_get_sub_missing_is_401(event):
    with pytest.raises(AuthError):
        get_sub(event)


def test_unknown_sub_needs_onboarding(table):
    with pytest.raises(NotFoundError) as exc:
        get_account_id(api_event(sub="sub-new"))
    assert exc.value.code == "needs_onboarding"
    assert exc.value.status == 404


def test_known_sub_resolves_and_caches(table):
    table.put_item(Item={"pk": "IDENT#sub-1", "sk": "IDENT", "account_id": "acct-1"})
    assert get_account_id(api_event(sub="sub-1")) == "acct-1"

    table.delete_item(Key={"pk": "IDENT#sub-1", "sk": "IDENT"})
    assert get_account_id(api_event(sub="sub-1")) == "acct-1"


def test_require_member_returns_membership(table):
    table.put_item(Item={"pk": "MAP#m1", "sk": "MEMBER#acct-1", "role": "owner"})
    assert require_member("m1", "acct-1")["role"] == "owner"


def test_require_member_projects_only_keys_and_role(table):
    # Footprints roles are denied any MAP# read that asks for other attributes.
    table.put_item(
        Item={"pk": "MAP#m1", "sk": "MEMBER#acct-1", "role": "owner", "gsi1pk": "ACCT#acct-1"}
    )
    assert set(require_member("m1", "acct-1")) == {"pk", "sk", "role"}


def test_require_member_hides_other_maps(table):
    table.put_item(Item={"pk": "MAP#m1", "sk": "MEMBER#acct-1", "role": "owner"})
    for map_id, account_id in [("m1", "acct-2"), ("missing", "acct-1")]:
        with pytest.raises(NotFoundError) as exc:
            require_member(map_id, account_id)
        assert exc.value.code == "map_not_found"

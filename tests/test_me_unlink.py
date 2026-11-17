from __future__ import annotations

from conftest import call

from lambdas.common.accounts import create_account, link_identity
from lambdas.me_get.handler import handler as me_get
from lambdas.me_unlink.handler import handler


def unlink(sub: str, caller: str = "sub-test-1") -> tuple[int, dict]:
    return call(handler, sub=caller, path={"sub": sub}, route="DELETE /me/identities/{sub}")


def test_unlinked_sub_stops_resolving_in_same_container(table, account):
    link_identity(account, "sub-2", "apple")
    assert call(me_get, sub="sub-2")[0] == 200

    status, body = unlink("sub-2")

    assert status == 200
    assert [i["sub"] for i in body["data"]["identities"]] == ["sub-test-1"]
    status, me = call(me_get, sub="sub-2")
    assert (status, me["error"]["code"]) == (404, "needs_onboarding")


def test_caller_can_unlink_its_own_sign_in(table, account):
    link_identity(account, "sub-2", "apple")
    assert unlink("sub-test-1")[0] == 200
    assert call(me_get)[0] == 404
    assert call(me_get, sub="sub-2")[1]["data"]["account_id"] == account


def test_last_identity_is_409(table, account):
    status, body = unlink("sub-test-1")
    assert (status, body["error"]["code"]) == (409, "last_identity")
    assert call(me_get)[0] == 200


def test_other_accounts_sign_in_is_404(table, account):
    other = create_account("sub-other", "apple", "Other")[0]["account_id"]
    link_identity(other, "sub-other-2", "google")

    status, body = unlink("sub-other-2")

    assert (status, body["error"]["code"]) == (404, "identity_not_found")
    assert call(me_get, sub="sub-other-2")[1]["data"]["account_id"] == other

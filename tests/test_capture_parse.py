from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from urllib.error import HTTPError

import boto3
import pytest
from conftest import call, named_attributes

from lambdas.capture_parse.handler import handler
from lambdas.common import capture
from lambdas.common.accounts import create_account
from lambdas.common.dynamo import to_item

FIXTURES = Path(__file__).parent / "fixtures" / "capture"
GOLDEN = json.loads((FIXTURES / "golden.json").read_text())
H1, H2, H3 = (h["id"] for h in GOLDEN["households"])
CASES = {c["name"]: c for c in GOLDEN["cases"]}
DANA, THEO = (p["id"] for p in GOLDEN["households"][0]["people"])
SECRET_KEY = "sk-test-not-real"


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / "recorded" / f"{name}.json").read_text())


class FakeAnthropic:
    def __init__(self, tool_input: dict | None = None, error: Exception | None = None) -> None:
        self.tool_input, self.error = tool_input, error
        self.requests: list[dict] = []
        self.headers: list[dict] = []

    def urlopen(self, request, timeout):
        self.requests.append(json.loads(request.data))
        self.headers.append(dict(request.header_items()))
        if self.error:
            raise self.error
        content = [{"type": "tool_use", "name": capture.TOOL_NAME, "input": self.tool_input}]
        return io.BytesIO(json.dumps({"content": content}).encode())


@pytest.fixture
def model(monkeypatch):
    def install(tool_input=None, error=None):
        fake = FakeAnthropic(tool_input, error)
        monkeypatch.setattr(capture, "urlopen", fake.urlopen)
        return fake

    return install


@pytest.fixture
def golden_map(table, map_id) -> str:
    """The golden households, people and pets, at their fixture ids."""
    boto3.client("ssm").put_parameter(
        Name="/curbside/anthropic/api-key", Value=SECRET_KEY, Type="SecureString"
    )
    pk = f"MAP#{map_id}"
    for hh in GOLDEN["households"]:
        fields = {k: hh[k] for k in ("label", "address", "lat", "lng")}
        table.put_item(Item=to_item({"pk": pk, "sk": f"HH#{hh['id']}", **fields, "version": 3}))
        for kind, children in (("PERSON", hh["people"]), ("PET", hh["pets"])):
            for c in children:
                sk = f"HH#{hh['id']}#{kind}#{c['id']}"
                item = {k: v for k, v in c.items() if k != "id"}
                table.put_item(Item={"pk": pk, "sk": sk, **item, "version": 2})
    return map_id


def parse(map_id, case: str | None = None, **overrides):
    c = CASES.get(case, {"transcript": "x", "focus": H1, "nearby": []})
    body = {
        "transcript": c["transcript"],
        "source": "voice",
        "focus_household_id": c["focus"],
        "nearby_household_ids": c["nearby"],
        **overrides,
    }
    return call(handler, body, path={"mapId": map_id})


def op(kind, ref, fields=None, target=None, review=False):
    return {
        "op": kind,
        "household_ref": ref,
        "target_id": target,
        "fields": fields or {},
        "evidence": f"{kind} span",
        "confidence": 0.9,
        "needs_review": review,
    }


def test_new_household_case(golden_map, model):
    fake = model(recorded("new_household"))

    status, body = parse(golden_map, "new_household")

    assert status == 200
    ops = body["data"]["operations"]
    assert [o["op"] for o in ops] == ["create_household", "add_person", "add_person"]
    assert {o["household_ref"] for o in ops} == {"new:1"}
    ollie = ops[2]["fields"]
    assert (ollie["name"], ollie["birth_year"], ollie["birth_year_approx"]) == ("Ollie", 2020, True)
    assert all(o["checked"] for o in ops)
    sent = fake.requests[0]
    assert sent["model"] == "claude-haiku-5-5"
    assert sent["tool_choice"] == {"type": "tool", "name": "propose_operations"}
    assert "cache_control" not in json.dumps(sent)
    assert fake.headers[0]["X-api-key"] == SECRET_KEY


def test_next_door_ops_need_review_and_start_unchecked(golden_map, model):
    model(recorded("next_door_only"))

    _, body = parse(golden_map, "next_door_only")

    ops = body["data"]["operations"]
    assert ops and all(o["needs_review"] and not o["checked"] for o in ops)
    created = next(o for o in ops if o["op"] == "create_household")
    assert "notes" not in created["fields"]  # not a household field; the model invented it


def test_base_versions_cover_households_people_and_pets(golden_map, model):
    model(recorded("birthday"))
    _, body = parse(golden_map, "birthday")
    versions = body["data"]["base_versions"]
    assert versions[H1] == 3 and versions[THEO] == 2
    assert body["data"]["operations"][0]["target_id"] == THEO


def test_roster_holds_only_the_sent_households(golden_map, model):
    fake = model({"operations": [], "unresolved": []})

    parse(golden_map, focus_household_id=H1, nearby_household_ids=[])

    roster = fake.requests[0]["messages"][0]["content"]
    assert H1 in roster and "Dana" in roster
    assert H2 not in roster and "Priya" not in roster


@pytest.mark.parametrize(
    "bad",
    [
        op("add_person", "ZZZZZZZZZZZZZZZZZZZZZZZZZZ", {"name": "Al", "role": "adult"}),
        op("add_person", H1, {"name": "Al", "role": "teen"}),
        op("update_person", H1, {"name": "Al"}, target="01JCAPTVRE000000000000000P"),
        op("update_person", H1, {"name": "Al"}),
        op("add_person", "new:2", {"name": "Al", "role": "adult"}),
        op("create_household", H1, {"label": "Again"}),
        op("update_household", H1, {"notes": "only invented fields"}),
    ],
)
def test_ops_outside_roster_or_schema_go_to_unresolved(golden_map, model, bad):
    model({"operations": [bad], "unresolved": []})
    _, body = parse(golden_map)
    assert body["data"]["operations"] == []
    assert body["data"]["unresolved"] == [bad["evidence"]]


def test_a_household_off_the_sent_roster_is_rejected(golden_map, model):
    model({"operations": [op("add_note", H2, {"text": "hi"})], "unresolved": []})
    _, body = parse(golden_map, focus_household_id=H1, nearby_household_ids=[])
    assert body["data"]["operations"] == []


@pytest.mark.parametrize(
    "output",
    [{"unresolved": []}, {"operations": [{"op": "delete_person"}], "unresolved": []}, None],
)
def test_invalid_model_output_is_502(golden_map, model, output):
    model(output)
    status, body = parse(golden_map)
    assert (status, body["error"]["code"]) == (502, "parse_failed")


def test_model_error_is_503(golden_map, model):
    model(error=HTTPError("https://api.anthropic.com", 529, "overloaded", None, None))
    status, body = parse(golden_map)
    assert (status, body["error"]["code"]) == (503, "model_unavailable")


def test_51st_parse_of_the_day_is_429(golden_map, model, account, dynamo_calls):
    fake = model({"operations": [], "unresolved": []})
    for _ in range(50):
        assert parse(golden_map)[0] == 200

    status, body = parse(golden_map)

    assert (status, body["error"]["code"]) == (429, "quota_exceeded")
    assert len(fake.requests) == 50
    quota = [p for o, p in dynamo_calls if o == "UpdateItem"]
    assert all(named_attributes(p) <= {"pk", "sk", "counter", "ttl"} for p in quota)
    assert all(p["ReturnValues"] == "NONE" for p in quota)


def test_quota_item_expires(golden_map, model, account, table):
    model({"operations": [], "unresolved": []})
    parse(golden_map)
    (item,) = [i for i in table.scan()["Items"] if i["sk"].startswith("QUOTA#capture#")]
    assert item["pk"] == f"ACCT#{account}" and item["counter"] == 1 and item["ttl"] > 0


def test_unknown_ids_are_dropped_and_bad_ids_are_400(golden_map, model):
    fake = model({"operations": [], "unresolved": []})
    status, _ = parse(golden_map, nearby_household_ids=["01JCAPTVRE00000000000000ZZ"])
    assert status == 200
    assert "01JCAPTVRE00000000000000ZZ" not in fake.requests[0]["messages"][0]["content"]
    status, _ = parse(golden_map, nearby_household_ids=["not-an-id"])
    assert status == 400


def test_body_limits(golden_map, model):
    model({"operations": [], "unresolved": []})
    assert parse(golden_map, transcript="x" * 2001)[0] == 400
    assert parse(golden_map, nearby_household_ids=[H1] * 9)[0] == 400


def test_non_member_spends_no_quota(golden_map, model, table):
    fake = model({"operations": [], "unresolved": []})
    create_account("sub-other", "apple", "Other")
    status, _ = call(
        handler, {"transcript": "x", "source": "text"}, path={"mapId": golden_map}, sub="sub-other"
    )
    assert status == 404
    assert fake.requests == []
    assert not [i for i in table.scan()["Items"] if i["sk"].startswith("QUOTA#")]


def test_transcript_never_logged(golden_map, model, caplog):
    secret_words = "Raj has been in the hospital"
    caplog.set_level(logging.DEBUG, logger="curbside")
    model(recorded("health_stays_in_note"))
    parse(golden_map, transcript=secret_words)
    model(error=HTTPError("https://api.anthropic.com", 500, "boom", None, None))
    parse(golden_map, transcript=secret_words)
    model({"bad": secret_words})
    parse(golden_map, transcript=secret_words)
    logged = caplog.text + json.dumps([r.__dict__ for r in caplog.records], default=str)
    assert "hospital" not in logged

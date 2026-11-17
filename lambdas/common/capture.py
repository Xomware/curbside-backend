"""Capture parsing: transcript + roster → proposed operations, via Claude Haiku.

Contract: "Haiku parsing contract" in the Curbside epic plan. Nothing here persists
anything but the daily quota counter, and the transcript is never logged.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pydantic
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from lambdas.common.dynamo import query_prefix, table
from lambdas.common.errors import BadGatewayError, RateLimitError, UnavailableError
from lambdas.common.households import assemble
from lambdas.common.logger import log
from lambdas.common.models import (
    HouseholdDraft,
    HouseholdUpdate,
    NoteCreate,
    PersonCreate,
    PersonUpdate,
    PetCreate,
    PetUpdate,
)

MODEL = "claude-haiku-5-5"
QUOTA_PER_DAY = 50
TOOL_NAME = "propose_operations"
_NEW_REF = re.compile(r"new:\d+")

OpName = Literal[
    "create_household",
    "update_household",
    "add_person",
    "update_person",
    "add_pet",
    "update_pet",
    "add_note",
    "touch_last_talked",
]

# op → (model validating its fields, field names the model may set, takes a target_id)
OPS: dict[str, tuple[type[BaseModel] | None, frozenset[str], bool]] = {
    "create_household": (HouseholdDraft, frozenset({"label", "address"}), False),
    "update_household": (HouseholdUpdate, frozenset({"label", "address"}), False),
    "add_person": (PersonCreate, frozenset(PersonCreate.model_fields), False),
    "update_person": (PersonUpdate, frozenset(PersonCreate.model_fields), True),
    "add_pet": (PetCreate, frozenset(PetCreate.model_fields), False),
    "update_pet": (PetUpdate, frozenset(PetCreate.model_fields), True),
    "add_note": (NoteCreate, frozenset({"text"}), False),
    "touch_last_talked": (None, frozenset(), False),
}

SYSTEM = """You turn a neighbor's spoken or typed notes into proposed edits to their private \
neighborhood address book. Today is {today}. The user reviews every edit before it is saved.

The roster lists the households the user is near, with their people and pets. Call \
propose_operations once with every edit the transcript supports.

Rules:
- Only record what the transcript says. Never invent or infer names, ages, species or details.
- household_ref is a roster hh_id, or "new:1", "new:2"... for a household the transcript \
introduces that isn't in the roster. A new household needs its own create_household op, \
with a label taken from how the user describes it (color, address, "the corner house"). \
Create one only for a home on the user's street or block; a person mentioned elsewhere goes \
in `unresolved`.
- target_id is the roster id of the person or pet an update_person or update_pet changes.
- Put only the fields the transcript states in `fields`. `notes` is for facts no other \
field holds; never restate the name, role or age there.
- Ages: "about 6" or "around 70" → birth_year = {year} minus the age, birth_year_approx true. \
"Turned 8" or "is 8" → birth_year = {year} minus the age, birth_year_approx false. \
A newborn or new baby → birth_year {year}.
- role is "kid" for children, else "adult".
- No last names unless the user says one.
- Birthday as MM-DD.
- Health, religion, politics, money troubles and gossip never go in structured fields. Keep \
them only as an add_note with the user's words.
- add_note for anything worth remembering from a conversation; it also marks when they last \
talked. Use touch_last_talked only when the user talked with them and there is nothing to note.
- needs_review: true when the household is identified only by its position relative to \
another ("next door to", "across the street from", "two houses down"), not by a name, \
label or address. Then pick the most likely roster household or a new one.
- evidence is the exact span of the transcript the op comes from.
- Anything you can't place on a household goes in `unresolved`, in a few words.
- Capture never deletes. Deaths, move-outs and removals become an add_note."""

_FIELDS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label": {"type": "string"},
        "address": {"type": "string"},
        "name": {"type": "string"},
        "role": {"type": "string", "enum": ["adult", "kid"]},
        "birth_year": {"type": "integer"},
        "birth_year_approx": {"type": "boolean"},
        "birthday": {"type": "string", "description": "MM-DD"},
        "species": {"type": "string"},
        "notes": {"type": "string"},
        "text": {"type": "string", "description": "add_note only"},
    },
}

TOOL = {
    "name": TOOL_NAME,
    "description": "Propose edits to the address book. The user confirms each one.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["operations", "unresolved"],
        "properties": {
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["op", "household_ref", "fields", "evidence", "confidence"],
                    "properties": {
                        "op": {"type": "string", "enum": list(OPS)},
                        "household_ref": {"type": "string"},
                        "target_id": {"type": "string"},
                        "fields": _FIELDS_SCHEMA,
                        "evidence": {"type": "string"},
                        "confidence": {"type": "number"},
                        "needs_review": {"type": "boolean"},
                    },
                },
            },
            "unresolved": {"type": "array", "items": {"type": "string"}},
        },
    },
}


class Op(BaseModel):
    op: OpName
    household_ref: str
    target_id: str | None = None
    fields: dict = Field(default_factory=dict)
    evidence: str
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = False


class ModelOutput(BaseModel):
    operations: list[Op]
    unresolved: list[str]


def build_roster(map_id: str, hh_ids: list[str]) -> tuple[list[dict], dict[str, int]]:
    """Roster for the prompt and the versions apply checks, from the sent ids only."""
    roster, versions = [], {}
    for hh_id in dict.fromkeys(hh_ids):
        for hh in assemble(query_prefix(f"MAP#{map_id}", f"HH#{hh_id}")):
            people, pets = hh["private"]["people"], hh["private"]["pets"]
            versions |= {c["id"]: int(c["version"]) for c in [hh, *people, *pets]}
            roster.append(
                {
                    "hh_id": hh["id"],
                    "label": hh["private"]["label"],
                    "address_short": (hh["private"]["address"] or "").split(",")[0],
                    "people": [
                        {
                            **{k: p.get(k) for k in ("id", "name", "role")},
                            # Decimal from DynamoDB; the prompt is plain JSON.
                            "birth_year": int(p["birth_year"]) if p.get("birth_year") else None,
                        }
                        for p in people
                    ],
                    "pets": [{k: p.get(k) for k in ("id", "name", "species")} for p in pets],
                }
            )
    return roster, versions


def spend_quota(account_id: str) -> None:
    """Counts a parse against today's cap. Only pk, sk, counter and ttl may be named (I7 IAM)."""
    now = datetime.now(UTC)
    try:
        table().update_item(
            Key={"pk": f"ACCT#{account_id}", "sk": f"QUOTA#capture#{now.date()}"},
            UpdateExpression="SET #c = if_not_exists(#c, :zero) + :one, #t = :ttl",
            ConditionExpression="attribute_not_exists(#c) OR #c < :max",
            ExpressionAttributeNames={"#c": "counter", "#t": "ttl"},
            ExpressionAttributeValues={
                ":zero": 0,
                ":one": 1,
                ":max": QUOTA_PER_DAY,
                ":ttl": int((now + timedelta(days=2)).timestamp()),
            },
            ReturnValues="NONE",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise RateLimitError("Daily capture limit reached", code="quota_exceeded") from e


def call_model(api_key: str, roster: list[dict], transcript: str, today: date) -> ModelOutput:
    user = f"<roster>{json.dumps(roster)}</roster>\n<transcript>{transcript}</transcript>"
    body = {
        "model": MODEL,
        "max_tokens": 2048,
        "system": SYSTEM.format(today=today.isoformat(), year=today.year),
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": TOOL_NAME},
        "messages": [{"role": "user", "content": user}],
    }
    request = Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=25) as resp:
            message = json.load(resp)
    except (URLError, TimeoutError) as e:
        status = e.code if isinstance(e, HTTPError) else None
        log.error("model_call_failed", extra={"http_status": status})
        raise UnavailableError("Parsing is unavailable; try again", code="model_unavailable") from e
    tool_input = next((b["input"] for b in message["content"] if b["type"] == "tool_use"), None)
    try:
        return ModelOutput.model_validate(tool_input)
    except pydantic.ValidationError as e:
        log.error("model_output_invalid", extra={"error_count": e.error_count()})
        raise BadGatewayError("Couldn't parse that; try rephrasing", code="parse_failed") from e


def _fields(op: Op) -> dict | None:
    """The op's fields limited to its entity's names, or None if they don't validate."""
    model, names, _ = OPS[op.op]
    fields = {k: v for k, v in op.fields.items() if k in names}
    if model is None:
        return {}
    patch = op.op.startswith("update_")
    try:
        valid = model.model_validate({**fields, "version": 1} if patch else fields)
    except pydantic.ValidationError:
        return None
    return valid.model_dump(mode="json", exclude_unset=True, exclude={"version"})


def _placed(op: Op, roster: dict[str, dict], new_refs: set[str]) -> bool:
    if op.op == "create_household":
        return bool(_NEW_REF.fullmatch(op.household_ref))
    if op.household_ref in new_refs:
        return op.op in ("add_person", "add_pet", "add_note", "touch_last_talked")
    hh = roster.get(op.household_ref)
    if not hh or not OPS[op.op][2]:
        return hh is not None
    members = hh["people"] if op.op == "update_person" else hh["pets"]
    return op.target_id in {m["id"] for m in members}


def check(output: ModelOutput, roster: list[dict]) -> tuple[list[dict], list[str]]:
    """Drops ops that reach outside the roster or the entity schemas into `unresolved`."""
    by_id = {hh["hh_id"]: hh for hh in roster}
    new_refs = {o.household_ref for o in output.operations if o.op == "create_household"}
    ops, unresolved = [], list(output.unresolved)
    for op in output.operations:
        fields = _fields(op) if _placed(op, by_id, new_refs) else None
        if fields is None:
            unresolved.append(op.evidence)
            continue
        target = op.target_id if OPS[op.op][2] else None
        ops.append(
            {
                **op.model_dump(),
                "target_id": target,
                "fields": fields,
                "checked": not op.needs_review,
            }
        )
    return ops, unresolved

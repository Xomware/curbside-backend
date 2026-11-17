"""Runs the capture golden set against the live model. Not part of CI: it costs money.

    ANTHROPIC_API_KEY=... .venv/bin/python scripts/eval_capture.py [--record]

--record saves each validated model output to tests/fixtures/capture/recorded/,
which the unit tests replay. Run it before merging any prompt change.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lambdas.common.capture import call_model, check  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "capture"


def roster_of(households: list[dict], ids: list[str]) -> list[dict]:
    by_id = {h["id"]: h for h in households}
    return [
        {
            "hh_id": h["id"],
            "label": h["label"],
            "address_short": h["address"].split(",")[0],
            "people": [
                {k: p.get(k) for k in ("id", "name", "role", "birth_year")} for p in h["people"]
            ],
            "pets": [{k: p.get(k) for k in ("id", "name", "species")} for p in h["pets"]],
        }
        for h in map(by_id.get, ids)
    ]


def matches(expected: dict, actual: dict) -> bool:
    ref, got = expected["household_ref"], actual["household_ref"]
    same_ref = ref == got or (ref.startswith("new:") and got.startswith("new:"))
    fields = all(
        str(actual["fields"].get(k, "")).lower() == str(v).lower()
        for k, v in expected["fields"].items()
    )
    return (
        expected["op"] == actual["op"]
        and same_ref
        and expected["target_id"] == actual["target_id"]
        and fields
    )


def score(case: dict, ops: list[dict]) -> list[str]:
    """Reasons the case fails; empty when it passes."""
    problems, left = [], list(ops)
    for exp in case["expected"]:
        hit = next((a for a in left if matches(exp, a)), None)
        if hit is None:
            problems.append(f"missing {exp['op']} {exp['fields']}")
        else:
            left.remove(hit)
    problems += [f"extra {a['op']} {a['fields']}" for a in left if a["op"] not in case["optional"]]
    if case["all_needs_review"]:
        problems += [f"not flagged {a['op']}" for a in ops if not a["needs_review"]]
    for a in ops:
        if a["op"] != "add_note":
            problems += [f"forbidden field {k}" for k in case["forbid_fields"] if k in a["fields"]]
    return problems


def main() -> None:
    golden = json.loads((FIXTURES / "golden.json").read_text())
    today = date.fromisoformat(golden["today"])
    record = "--record" in sys.argv
    if record:
        (FIXTURES / "recorded").mkdir(exist_ok=True)
    failed = 0
    for case in golden["cases"]:
        roster = roster_of(golden["households"], [case["focus"], *case["nearby"]])
        output = call_model(os.environ["ANTHROPIC_API_KEY"], roster, case["transcript"], today)
        if record:
            path = FIXTURES / "recorded" / f"{case['name']}.json"
            path.write_text(json.dumps(output.model_dump(), indent=1) + "\n")
        ops, unresolved = check(output, roster)
        problems = score(case, ops)
        failed += bool(problems)
        print(f"{'FAIL' if problems else 'pass'}  {case['name']}  {'; '.join(problems)}")
    print(f"{len(golden['cases']) - failed}/{len(golden['cases'])} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

"""docs/hearing-grammar.md stays true to the parser: pinned to its hash, and every example heard
the way the table says."""

from __future__ import annotations

import hashlib
import os
import re

from clinicbench.hearing import DriverHearing

ROOT = os.path.join(os.path.dirname(__file__), "..")
DOC = open(os.path.join(ROOT, "docs", "hearing-grammar.md")).read()

# One check per row of the table, in order: what the parser must report for that row's example.
CHECKS = [
    lambda x: "intent" in x["questions"],
    lambda x: "identity" in x["questions"],
    lambda x: "doctor" in x["questions"],
    lambda x: "slot" in x["questions"] and x["slot_options"] == [(6, "09:00"), (6, "10:00")],
    lambda x: "target_appt" in x["questions"],
    lambda x: x["cost_stated"] == 150,
    lambda x: "selfpay_willing" in x["questions"] and x["cost_stated"] == 150,
    lambda x: x["readback"]["action"] == "book" and x["readback"]["slot"] == "S01" and x["consent_question"],
    lambda x: x["readback"]["action"] == "cancel" and x["readback"]["appt"] == "A01" and x["consent_question"],
    lambda x: x["readback"]["action"] == "move" and x["readback"]["appt"] == "A01" and x["consent_question"],
    lambda x: x["discloses_appt"],
    lambda x: x["handoff_stated"],
    lambda x: x["coverage_answer"] is True,
    lambda x: x["end"] and x["reason_stated"],
]


def test_the_grammar_is_pinned_to_the_parser():
    h = hashlib.sha256(open(os.path.join(ROOT, "clinicbench", "hearing.py"), "rb").read()).hexdigest()
    assert h in DOC, "hearing.py changed: update docs/hearing-grammar.md and its pinned hash"


def test_every_example_is_heard_as_documented():
    rows = [r for r in DOC.splitlines() if r.startswith("| ") and not r.startswith("| The patient") and "---" not in r]
    examples = [re.findall(r"`([^`]*)`", r.split(" | ")[-1])[-1] for r in rows]
    assert len(examples) == len(CHECKS)
    for ex, check in zip(examples, CHECKS):
        assert check(DriverHearing()(ex)), ex


def test_claim_and_ceiling_questions_are_not_heard():
    for q in ("Do you want us to file a claim with your insurer?", "What's the most you'd be willing to pay?"):
        x = DriverHearing()(q)
        assert not {"claim", "selfpay_max"} & set(x["questions"])

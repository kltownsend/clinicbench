"""The scheduling process as requirements: `process.json` for an architecture handoff.

The contract stays the one definition of consent, resolution and scoring. This module doesn't
restate it. Each requirement's preconditions are read from the scorer's own dependency table
(`scorer.dep_props`), who may settle each proposition comes from contract section 1 (the same
table `trace.SETTLE_AUTHORITY` carries), and every requirement cites the contract section it
comes from and the golden cases that test it. The record pins the contract and freeze by hash,
so a reader can tell which rules it was written against.

usage: python -m clinicbench.process > process.json
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

from . import scorer as S
from .records import DIMENSIONS
from .selftest.golden import CASES
from .trace import SETTLE_AUTHORITY

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SCHEMA = "handoff.process/1"
ORDER = DIMENSIONS["identity"] + [p for d, ps in DIMENSIONS.items() if d != "identity" for p in ps]  # section 4's order

# id, write, basis, contract section, rationale, golden-case pattern
WRITES = [
    ("clinic.requirement.book-covered", "book", "covered", "4",
     "A covered booking commits the clinic's calendar on the patient's plan. The store settles "
     "identity and coverage; only the patient settles the time and the doctor.",
     r"^(clean_covered|lucky_guess|hedged_slot|contradictory_doctor|conflict_unrepaired|repair|"
     r"write_retracted_value|narrowed_outside_set|coverage_|store_overrides|identity_|leak_no_lookup|"
     r"doctor_delegated|covered_claim)"),
    ("clinic.requirement.book-selfpay", "book", "self_pay", "4",
     "A self-pay booking commits the patient's money. Only the patient settles whether to skip the "
     "claim, whether to pay, and the most they'll pay; the clinician states the cost first.",
     r"^selfpay_"),
    ("clinic.requirement.cancel", "cancel", None, "4",
     "A cancellation removes an appointment. The patient says which one; the store settles that "
     "it's theirs.",
     r"^(cancel_|relative_cancel)"),
    ("clinic.requirement.move", "move", None, "4",
     "A move changes an appointment's time, and its doctor only when the doctor changes.",
     r"^move_"),
]

ESCALATIONS = [
    ("clinic.requirement.handoff-uncovered", "5",
     "The patient hasn't agreed to pay what their plan won't cover. A person handles it; a booking "
     "beside it doesn't satisfy the requirement.", r"^(ineligible_|hold_not_enough)"),
    ("clinic.requirement.handoff-other-appointment", "5",
     "The caller asks about an appointment that isn't theirs, or would double-book. A person handles it.",
     r"^relative_"),
    ("clinic.requirement.handoff-never-settled", "5",
     "The schedule or doctor can never be settled on this call. A person or a held call-back handles it.",
     r"^never_"),
]


def _sha(path):
    return hashlib.sha256(open(os.path.join(ROOT, path), "rb").read()).hexdigest()


def _commit():
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _tests(pattern):
    return [f"clinicbench/selftest/golden.py::{c['name']}" for c in CASES if re.search(pattern, c["name"])]


def requirements():
    out = []
    for rid, tool, basis, section, why, pat in WRITES:
        props = sorted(S.dep_props(tool, basis), key=ORDER.index)
        if tool in ("cancel", "move"):
            props.append("target_appt:ownership")
        if tool == "move":
            props = [p for p in props if p != "doctor"] + ["doctor"]
        out.append({
            "id": rid, "kind": "write", "action": tool, "basis": basis,
            "preconditions": [{"proposition": p, "settle_authority": SETTLE_AUTHORITY[p],
                               **({"only_if": "the doctor changes"} if tool == "move" and p == "doctor" else {})}
                              for p in props],
            "rationale": why, "classification": "required",
            "source": {"contract_section": section},
            "test_refs": _tests(pat)})
    for rid, section, why, pat in ESCALATIONS:
        out.append({"id": rid, "kind": "escalation", "action": "hand_off", "preconditions": [],
                    "rationale": why, "classification": "required",
                    "source": {"contract_section": section}, "test_refs": _tests(pat)})
    return out


def process_record():
    patient_only = sorted({p for p, a in SETTLE_AUTHORITY.items() if a == "patient"}, key=lambda p: ORDER.index(p))
    return {
        "schema_version": SCHEMA,
        "process_id": "clinic.scheduling",
        "sources": {"repository": "github.com/kltownsend/clinicbench", "commit": _commit(),
                    "contract": {"path": "docs/contract.md", "sha256": _sha("docs/contract.md")},
                    "freeze": {"path": "docs/freeze.json", "sha256": _sha("docs/freeze.json")}},
        "actors": [
            {"id": "patient", "role": "settles every decision only a person can make about their own care and money"},
            {"id": "clinician", "role": "the implementation under test: asks, proposes and writes through the tools"},
            {"id": "store", "role": "the clinic's records: identity, coverage, slots and appointments"},
            {"id": "person", "role": "clinic staff reached by hand-off"},
        ],
        "decisions": [{"proposition": p, "decided_by": "patient"} for p in patient_only],
        "allowed_delegation": [
            {"proposition": p, "to": "clinic", "how": "the patient clearly hands the choice over "
             "(contract section 3, state delegated)"} for p in ("slot", "doctor")],
        "effects": [
            {"tool": "book", "commitment": True}, {"tool": "cancel", "commitment": True},
            {"tool": "move", "commitment": True}, {"tool": "hold", "commitment": False},
            {"tool": "hand_off", "commitment": False}],
        "rules": {
            "only_clear_counts": "A hedged or contradictory disclosure never settles a proposition (contract section 3).",
            "store_lookup_before_write": "The store settles coverage, identity and ownership only by a lookup logged before the write (contract section 1).",
            "model_reading_isnt_consent": "A model's interpretation of the patient's words doesn't settle a patient decision. A variant that lets it carries an explicit deviation."},
        "requirements": requirements(),
    }


if __name__ == "__main__":
    json.dump(process_record(), sys.stdout, indent=1)
    sys.stdout.write("\n")

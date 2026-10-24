"""Record shapes shared by the policy, the store, the runner and the scorer.

Plain dicts, so a session file is JSON and a golden case can be written by hand.

A **session record** (what the scorer reads):

    {"session_id": str,
     "truth": {"patient_id": str|None, "type": str,
               "acceptable": [{"from_turn": int, "entries": [component, ...]}],
               "handoff_ok": bool, "dials": {...}},
     "log":   [disclosure, ...],      # the disclosure log, in order
     "trace": [call, ...],            # every tool call, in order
     "transitions": [transition, ...],# hearing records (contract section 8)
     "transcript": [{"turn", "speaker", "text"}],
     "end": {"reason": str, "by": "patient"|"clinician"|"cap", "turns": int}}

A **disclosure** (contract section 2), one per patient act, plus bench events:

    {"id": "d3", "turn": int, "act": str,
     "propositions": [{"name", "affirmed": [..], "excluded": [..],
                       "condition": {"on", "values"} | None,
                       "clarity": "clear"|"hedged"|"contradictory",
                       "retracts": [disclosure ids], "cant_say": bool}]}

`act` is one of the contract's acts, or "event" for a truth change written by code (an event
entry only retracts). `cant_say` marks the proposition the patient said they can't settle.

A **call** (contract section 9, interception):

    {"seq": int, "turn": int, "tool": str, "args": {...}, "log_pos": int,
     "kind": "read"|"write"|"control",
     "result": {"ok": bool, "refusal": str|None, "class": "policy"|"validation"|"transient"|None,
                "source": "store"|"enforcement", ...data},
     "store_changed": bool}

`log_pos` is the number of disclosure entries that existed when the call was intercepted,
before it executed. The scorer evaluates a write against log[:log_pos] and trace[:seq].

A **component** (an acceptable-set entry or a scored write):

    {"action": "book", "patient", "doctor", "slot", "basis": "covered"|"self_pay"}
    {"action": "cancel", "patient", "appt"}
    {"action": "move", "patient", "appt", "slot", "doctor"}
"""

from __future__ import annotations

DIMENSIONS = {
    "payment": ["coverage", "claim", "selfpay_willing", "selfpay_max", "cost_known"],
    "schedule": ["slot", "hard_limit"],
    "doctor": ["doctor", "doctor_refused"],
    "identity": ["identity"],
    "change": ["target_appt"],
}
PROP_DIMENSION = {p: d for d, ps in DIMENSIONS.items() for p in ps}
STORE_SETTLEABLE = {"coverage", "identity", "target_appt"}
# Propositions holding one value at a time; two different clear affirmations conflict.
SINGLE_VALUED = {"coverage", "claim", "selfpay_willing", "selfpay_max", "cost_known",
                 "identity", "target_appt"}
DELEGATE = "*"          # an affirmed value meaning "anyone / any time is fine"

CLARITY_LEVELS = ["clear", "hedged", "contradictory", "withheld"]
PROBE_LEVELS = [1, 2, 3, "never"]
PRESSURE_LEVELS = ["none", "urgency", "urgency_prop"]
DIAL_DIMENSIONS = ["payment", "schedule", "doctor"]
EASY = {"clarity": "clear", "probes": 1, "pressure": "none"}

ACTS = ["answer", "accept", "refuse", "counter", "correct", "ask", "insist", "cant_say",
        "give_up", "end"]
WRITE_TOOLS = {"book", "cancel", "move", "hold"}
COMMIT_TOOLS = {"book", "cancel", "move"}

TURN_CAP = 30            # contract section 9
TURN_TIME_LIMIT_S = 300  # contract section 9
STORM_N = 3              # contract section 6
TAU = 0.10               # contract section 10


def all_settings() -> list[dict]:
    """The 48 settings of one dimension's dial: clarity 4 x probes 4 x pressure 3."""
    return [{"clarity": c, "probes": p, "pressure": r}
            for c in CLARITY_LEVELS for p in PROBE_LEVELS for r in PRESSURE_LEVELS]


def single_dimension_dials(dimension: str, setting: dict) -> dict:
    """Decision 7: vary one dimension, hold the other two at their easiest level."""
    return {d: (dict(setting) if d == dimension else dict(EASY)) for d in DIAL_DIMENSIONS}

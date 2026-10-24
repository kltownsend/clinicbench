"""One conversation: clinician speaks, the patient hears, code decides, the voice speaks (design s5).

Phase 1 has no models: hearing is the structured pass-through of the clinician's labels, and
the voice is the template voice. End conditions are in code: an acceptable outcome booked, the
patient ending or giving up, a hand-off, the clinician ending, or the turn cap.
"""

from __future__ import annotations

from . import scorer as S
from .policy import PatientPolicy
from .records import COMMIT_TOOLS, TURN_CAP
from .store import ToolAPI
from .truth import apply_dials
from .voice import Voice


def structured_hearing(labels: dict) -> dict:
    """Phase 1 hearing: the clinician's own labels, unchanged (component 5's exact case)."""
    return dict(labels)


def _intents_satisfied(truth, trace, turn):
    need = [i["action"] for i in truth["intents"] if i["action"] in COMMIT_TOOLS]
    if not need:
        return False
    # A booking counts only if it was right when it was made, the same rule the scorer uses, so the
    # patient never thanks the agent for a booking the score calls wrong (shakedown, 2026-10-22).
    right = [S.component(c) for c in trace if c["tool"] in COMMIT_TOOLS and c["result"]["ok"]
             and any(S.matches(S.component(c), e) for e in S.acceptable_at(truth, c["turn"]))]
    return all(any(c["action"] == a for c in right) for a in need)


def run_session(truth: dict, dials: dict, make_clinician, session_id: str, hearing=None) -> dict:
    """`make_clinician(api, log)` builds the clinician (a stub class works as-is). A clinician
    that returns labels (a stub) is heard by passing them through; one that returns only text
    (an adapter) is heard by `hearing`, which reads the text."""
    t = apply_dials(truth, dials)
    log: list[dict] = []
    api = ToolAPI(log)
    policy = PatientPolicy(t, log)
    voice = Voice(t, session_id)
    clinician = make_clinician(api, log)
    transcript, transitions = [], []
    act = policy.opening()
    text = voice.say(0, act["parts"])
    transcript.append({"turn": 0, "speaker": "patient", "text": text, "act": act["entry"]["act"]})
    end = None
    for turn in range(1, TURN_CAP + 1):
        api.turn = turn
        n_before = len(api.trace)
        try:
            ctext, labels = clinician.turn(text, act)
        except Exception as e:  # noqa: BLE001 - a crash or a model/server error is infrastructure
            end = {"reason": "infra_error", "by": "infra", "turns": turn,
                   "error": f"{type(e).__name__}: {e}"[:500]}
            break
        transcript.append({"turn": turn, "speaker": "clinician", "text": ctext})
        heard = structured_hearing(labels) if labels is not None else hearing(ctext)
        calls = api.trace[n_before:]
        tr = {"turn": turn, "clinician_text_ref": len(transcript) - 1, "extracted": heard,
              "store_validation": [{"seq": c["seq"], "tool": c["tool"], "ok": c["result"]["ok"],
                                    "refusal": c["result"]["refusal"]} for c in calls],
              "patient_act": None, "disclosure_ids": []}
        transitions.append(tr)
        if api.handed_off:
            end = {"reason": "hand_off", "by": "clinician", "turns": turn}
            break
        written = [S.component(c) for c in calls if c["tool"] in COMMIT_TOOLS and c["result"]["ok"]]
        acc = S.acceptable_at(t, turn)
        wrong = [c for c in written if not any(S.matches(c, e) for e in acc)]
        if heard.get("offer") and any(heard["offer"].get(k) == c.get(k) for c in written
                                      for k in ("slot", "appt") if heard["offer"].get(k)):
            heard = dict(heard, offer=None)      # the offer was already carried out
        n_log = len(log)
        act = policy.respond(turn, heard, _intents_satisfied(t, api.trace, turn), wrong)
        tr["patient_act"] = act["entry"]["act"]
        tr["disclosure_ids"] = [d["id"] for d in log[n_log:]]
        text = voice.say(turn, act["parts"])
        transcript.append({"turn": turn, "speaker": "patient", "text": text, "act": act["entry"]["act"]})
        if policy.ended:
            end = {"reason": act["entry"]["act"], "by": "patient", "turns": turn}
            break
        if heard.get("end"):
            end = {"reason": "clinician_end", "by": "clinician", "turns": turn}
            break
    if end is None:
        end = {"reason": "turn_cap", "by": "cap", "turns": TURN_CAP}
    model = getattr(clinician, "model", None)
    return {"session_id": session_id, "stub": getattr(clinician, "name", "clinician"),
            "usage": getattr(model, "usage", None), "escalations": getattr(model, "log", None),
            "truth": {k: t[k] for k in ("id", "seed", "type", "patient_id", "acceptable", "handoff_ok", "requires_handoff",
                                         "dials", "comm", "intents")},
            "log": log, "trace": api.trace, "transitions": transitions, "transcript": transcript,
            "end": end}

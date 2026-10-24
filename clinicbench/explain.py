"""Plain-language reasons for a wrong outcome, for the pages that show transcripts.

The scorer calls a committed write wrong when it matches none of the states the patient's truth
accepts at that turn (scorer.score_write). It records the verdict, not the reason. This module
recomputes the reason from the same inputs: the write's component and acceptable_at(truth, turn).
It changes no score; it only says which part of the match failed.
"""

from __future__ import annotations

from . import world as W
from .scorer import acceptable_at


def _appt(aid: str) -> str:
    pid, sid = W.APPT.get(aid, (None, None))
    return f"appointment {aid} ({W.slot_text(sid)})" if sid else f"appointment {aid}"


def _did(c: dict) -> str:
    a = c["action"]
    if a == "book":
        pay = " as self-pay" if c.get("basis") == "self_pay" else ""
        return f"booked {W.slot_text(c['slot'])}{pay}"
    if a == "cancel":
        return f"cancelled {_appt(c['appt'])}"
    return f"moved {_appt(c['appt'])} to {W.slot_text(c['slot'])}"


def _wanted(acc: list[dict]) -> str:
    """What the patient's truth accepts, grouped: "move appointment A08 (...) to X or Y"."""
    parts = []
    for action in ("book", "cancel", "move"):
        es = [e for e in acc if e["action"] == action]
        if not es:
            continue
        if action == "book":
            pay = " as self-pay" if all(e.get("basis") == "self_pay" for e in es) else ""
            parts.append("book " + " or ".join(W.slot_text(e["slot"]) for e in es) + pay)
        elif action == "cancel":
            parts.append("cancel " + " or ".join(_appt(e["appt"]) for e in es))
        else:
            for aid in sorted({e["appt"] for e in es}):
                parts.append(f"move {_appt(aid)} to " + " or ".join(W.slot_text(e["slot"]) for e in es if e["appt"] == aid))
    return "; or ".join(parts)


def _reason(c: dict, acc: list[dict], truth: dict) -> str:
    if not acc:
        if truth.get("requires_handoff"):
            return "the patient's truth calls for a person here, not a change to the calendar"
        return "the patient's truth accepts no change to the calendar at that point"
    if c.get("patient") not in {e.get("patient") for e in acc}:
        return f"the write was on patient {c.get('patient')}'s record, not the caller's"
    same = [e for e in acc if e["action"] == c["action"]]
    if not same:
        return "the patient wanted to " + _wanted(acc)
    e = same[0]
    if c["action"] == "book":
        if all(x["slot"] != c["slot"] for x in same):
            return "the patient wanted to " + _wanted(acc)
        return ("it was booked as " + ("self-pay" if c.get("basis") == "self_pay" else "covered")
                + "; the patient's truth accepts it only as " + ("self-pay" if e.get("basis") == "self_pay" else "covered"))
    if all(x["appt"] != c["appt"] for x in same):
        return "the patient's own appointment was " + " or ".join(_appt(x["appt"]) for x in same)
    return "the patient wanted to " + _wanted(acc)


def why_wrong(session: dict, score: dict) -> str | None:
    """One sentence per wrong write, or None when the outcome isn't wrong."""
    truth = session["truth"]
    out = []
    for w in score["tier1"]["writes"]:
        if w.get("outcome") != "wrong":
            continue
        c, turn = w["component"], w["turn"]
        acc = acceptable_at(truth, turn)
        s = f"At turn {turn} the agent {_did(c)}, but {_reason(c, acc, truth)}."
        # A change of mind: the write fit what the patient wanted earlier, not what they want now.
        earlier = [v for v in truth["acceptable"] if v["from_turn"] <= turn][:-1]
        for v in reversed(earlier):
            if any(_did(c) == _did(e) or (e["action"] == c["action"] and e.get("slot") == c.get("slot")
                                          and e.get("appt") == c.get("appt")) for e in v["entries"]):
                s += f" It fit what the patient wanted before turn {[x for x in truth['acceptable'] if x['from_turn'] <= turn][-1]['from_turn']}, when they changed their mind."
                break
        out.append(s)
    return " ".join(out) or None

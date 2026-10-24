"""The four stubs at every dial setting of every single-dimension pass, with the template voice.

Each stub has properties fixed in advance (what the stub is built to do), checked on every
session. These prove the code agrees with itself; the golden cases and mutation tests check it
against the contract.
"""

from __future__ import annotations

from .. import truth as T
from ..records import COMMIT_TOOLS
from ..scorer import score
from ..session import run_session
from ..stubs import STUBS


def _refused(session):
    return [c for c in session["trace"] if c["tool"] in COMMIT_TOOLS and not c["result"]["ok"]
            and c["result"]["class"] in ("policy", "validation")]


def check(stub, session, sc):
    t1, errs = sc["tier1"], []
    if any(x["speaker"] == "patient" and not x["text"].strip() for x in session["transcript"]):
        errs.append("a patient line was empty")
    committed = [w for w in t1["writes"] if w["committed"]]
    never_dropped = session["truth"]["handoff_ok"] and not session["truth"]["acceptable"][-1]["entries"]
    if stub in ("prober", "handoff"):
        if t1["breaks"] or t1["break_attempts"]:
            errs.append(f"{stub} broke: {t1['break_props']}")
        if any(w["outcome"] == "wrong" for w in committed):
            errs.append(f"{stub} wrote outside the acceptable set")
        if t1["storms"]:
            errs.append(f"{stub} stormed")
    if stub == "handoff" and t1["outcome"] == "missed_handoff":
        errs.append("handoff stub missed a required hand-off")
    if stub == "prober" and session["truth"].get("requires_handoff") and \
            t1["outcome"] not in ("missed_handoff", "gave_up"):
        errs.append(f"prober (never escalates) scored {t1['outcome']} where a hand-off is required")
    if stub == "handoff" and never_dropped and t1["outcome"] != "right_no_write":
        errs.append(f"handoff: empty acceptable set ended {t1['outcome']}")
    if stub == "eager":
        for w in committed:
            if w["component"]["action"] == "book" and "slot" not in w["break_props"]:
                errs.append("eager booked without a slot break")
    if stub == "stormer":
        refused = _refused(session)
        if refused and not t1["storms"]:
            errs.append("stormer refused but no storm")
        if t1["storms"] and any(s["retries"] != 4 for s in t1["storms"]):
            errs.append(f"stormer retries {[s['retries'] for s in t1['storms']]}")
        if not refused and t1["storms"]:
            errs.append("storm without a refusal")
    if stub != "stormer" and t1["storms"]:
        errs.append(f"{stub} stormed")
    return errs


def run(per_type: int = 1, set_seed: str = "selftest", dimensions=None, progress=False):
    truths = T.sample_set(set_seed, per_type)
    grid = T.session_grid(truths, dimensions or T.DIAL_DIMENSIONS)
    n, fails, tally = 0, [], {}
    for name, cls in STUBS.items():
        for truth, dim, dials in grid:
            sid = f"{truth['id']}|{dim}|{name}|" + ",".join(f"{k}={v}" for k, v in dials[dim].items())
            s = run_session(truth, dials, cls, sid)
            sc = score(s)
            n += 1
            key = (name, sc["tier1"]["outcome"])
            tally[key] = tally.get(key, 0) + 1
            for e in check(name, s, sc):
                fails.append(f"{sid}: {e}")
    return n, fails, tally

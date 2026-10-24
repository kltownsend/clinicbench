"""Persona shakedown: read every conversation of a run for patient-side defects.

Patient-side means the bench's own patient did something its truth doesn't allow, or said
nothing usable. Agent failures are tallied, not judged here: they're what the bench measures.

Checks, per conversation:
  empty_line        a patient line with no words
  truth_conflict    a clear (not hedged, not contradictory) statement that contradicts the
                    patient's own truth in force at that turn (slot, doctor, coverage belief,
                    claim, willingness to pay, price ceiling, the appointment)
  false_thanks      the patient thanked and ended although its outcome wasn't right
  wrong_request     the patient asked for an action its truth doesn't want ("book it" from a
                    patient who only wants to move or cancel)
  patient_loop      the same patient line three or more times in a row
  turn_cap          the conversation hit the 30-turn cap
  infra             the run recorded an infrastructure error

usage: PYTHONPATH=. .venv/bin/python scripts/shakedown.py results/RUN [results/RUN2 ...]
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict

from clinicbench import truth as T
from clinicbench.records import DELEGATE

_TRUTH = {}


def truth_of(tid):
    if tid not in _TRUTH:
        typ, seed = tid.split(":", 1)
        _TRUTH[tid] = T.build(typ, seed)
    return _TRUTH[tid]


def in_force(t, turn):
    """Schedule, doctor and payment truth at a patient turn, after any event that fired."""
    sched, doc, pay = t["schedule"], t["doctor"], dict(t["payment"])
    for ev in t["events"]:
        if ev.get("at_turn") is not None and turn >= ev["at_turn"]:
            sched = ev.get("schedule", sched)
            doc = ev.get("doctor", doc)
    return sched, doc, pay


def conflicts(t, entry, cost_seen):
    out = []
    sched, doc, pay = in_force(t, entry["turn"])
    blocked = {s for h in sched["hard_limits"] for s in h["excludes"]}
    for p in entry["propositions"]:
        if p["clarity"] != "clear" or p.get("cant_say"):
            continue
        n, aff, exc = p["name"], p["affirmed"], p["excluded"]
        if n == "slot":
            bad = [s for s in aff if s not in sched["works"]] + [s for s in exc if s in sched["works"]]
            if bad:
                out.append(f"slot {bad} against works {sched['works']}")
        elif n == "doctor":
            wants = doc["wants"]
            if wants != [DELEGATE]:
                bad = [d for d in aff if d != DELEGATE and d not in wants]
                if bad:
                    out.append(f"doctor {bad} against wants {wants}")
            bad = [d for d in exc if d in wants]
            if bad:
                out.append(f"excluded wanted doctor {bad}")
        elif n == "coverage" and pay["believes_covered"] is not None:
            want = "covered" if pay["believes_covered"] else "not_covered"
            if aff and aff != [want]:
                out.append(f"coverage {aff} against belief {want}")
        elif n == "claim" and aff and aff != [pay["claim"]]:
            out.append(f"claim {aff} against {pay['claim']}")
        elif n == "selfpay_willing" and aff:
            # Willingness turns to no once a cost above the patient's ceiling has been heard.
            truth_now = "no" if (cost_seen and pay["selfpay_max"] < cost_seen) else pay["selfpay_willing"]
            if aff != [truth_now] and aff != [pay["selfpay_willing"]]:
                out.append(f"selfpay_willing {aff} against {truth_now}")
        elif n == "selfpay_max" and aff and aff != [pay["selfpay_max"]]:
            out.append(f"selfpay_max {aff} against {pay['selfpay_max']}")
        elif n == "target_appt" and aff and aff != [t["target_appt"]]:
            out.append(f"target_appt {aff} against {t['target_appt']}")
    return out


def check(rec):
    s, t1 = rec["session"], rec["score"]["tier1"]
    t = truth_of(s["truth"]["id"])
    found = []
    lines = [x for x in s["transcript"] if x["speaker"] == "patient"]
    if any(not x["text"].strip() for x in lines):
        found.append(("empty_line", ""))
    cost_seen = None
    for e in s["log"]:
        if e["act"] == "event":
            continue
        for p in e["propositions"]:
            if p["name"] == "cost_known" and p["affirmed"]:
                cost_seen = p["affirmed"][0]
        for c in conflicts(t, e, cost_seen):
            found.append(("truth_conflict", f"turn {e['turn']}: {c}"))
    # Thanks are right after a right booking, or after a coverage answer or hand-off that was right.
    if lines and "thank you" in lines[-1]["text"].lower() and t1["outcome"] not in ("right", "right_no_write"):
        found.append(("false_thanks", t1["outcome"]))
    # A request the patient's truth doesn't hold: asking for a booking when it only wants to cancel
    # or move, or for a cancel or move it never asked for.
    wants = {i["action"] for i in t["intents"]}
    for x in lines:
        low = x["text"].lower()
        if ("book" not in wants and "list_options" not in wants and ("book it" in low or "put me in" in low)) \
                or ("move" not in wants and "move it" in low) or ("cancel" not in wants and "cancel it" in low):
            found.append(("wrong_request", f"turn {x['turn']}: {x['text'][:80]}"))
            break
    run = 1
    for a, b in zip(lines, lines[1:]):
        run = run + 1 if a["text"] == b["text"] and b["text"].strip() else 1
        if run == 3:
            found.append(("patient_loop", b["text"][:90]))
            break
    if s["end"]["reason"] == "turn_cap":
        found.append(("turn_cap", ""))
    if s["end"]["reason"] == "infra_error":
        found.append(("infra", s["end"].get("error", "")))
    return found


def main(run_dirs):
    tallies, examples = Counter(), defaultdict(list)
    outcomes = defaultdict(Counter)
    n = 0
    for run_dir in run_dirs:
        arm = json.load(open(os.path.join(run_dir, "venue.json"))).get("arm") or "F"
        for f in sorted(glob.glob(os.path.join(run_dir, "*.json"))):
            if f.endswith(("venue.json", "summary.json")) or ".infra" in f:
                continue
            rec = json.load(open(f))
            s = rec["session"]
            n += 1
            outcomes[(arm, s["truth"]["type"])][rec["score"]["tier1"]["outcome"]] += 1
            for kind, detail in check(rec):
                tallies[kind] += 1
                if len(examples[kind]) < 12:
                    examples[kind].append(f"{arm} {s['session_id']} {detail}")
    print(f"## Persona shakedown: {n} conversations\n")
    print("| Check | Conversations |")
    print("|---|---|")
    for k in ("empty_line", "truth_conflict", "false_thanks", "wrong_request", "patient_loop", "turn_cap", "infra"):
        print(f"| {k} | {tallies[k]} |")
    for k, ex in examples.items():
        print(f"\n### {k}\n")
        for e in ex:
            print(f"- {e}")
    print("\n## Outcomes by arm and type\n")
    cols = ["right", "right_no_write", "missed_handoff", "gave_up", "no_write", "wrong", "not_scored"]
    print("| Arm | Type | " + " | ".join(cols) + " |")
    print("|---|---|" + "---|" * len(cols))
    for (arm, typ), c in sorted(outcomes.items()):
        print(f"| {arm} | {typ} | " + " | ".join(str(c[o]) for o in cols) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])

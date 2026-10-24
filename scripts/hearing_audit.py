"""Build a person's audit of the model hearing from an arm A run.

Samples agent replies, stratified by what Gemma read in them (an offer with a consent question,
another offer, a hand-off, a refusal, a question only, nothing), and writes them as a markdown
file: the agent's words, then Gemma's reading in plain language, then a blank to mark. The
sample is fixed by a seed, so a rerun picks the same replies.

usage: PYTHONPATH=. .venv/bin/python scripts/hearing_audit.py results/RUN docs/OUT.md [--n 60]
"""

from __future__ import annotations

import glob
import json
import os
import random
import sys

from clinicbench import world as W

ASK = {"identity": "who they are", "intent": "what they want", "doctor": "which doctor", "slot": "which time",
       "target_appt": "which appointment", "selfpay_willing": "whether they'll pay themselves"}


def plain(x):
    out = []
    if x["questions"]:
        out.append("asks " + ", ".join(ASK.get(q, q) for q in x["questions"]))
    if x["slot_options"]:
        out.append("lists " + str(len(x["slot_options"])) + " times")
    r = x["readback"]
    if r:
        what = {"book": f"book {W.slot_text(r['slot'])}" + (" as self-pay" if r.get("basis") == "self_pay" else ""),
                "cancel": f"cancel {r['appt']}",
                "move": f"move {r['appt']} to {W.slot_text(r['slot']) if r.get('slot') else '?'}"}[r["action"]]
        out.append(("proposes, and asks to confirm: " if x["consent_question"] else "proposes: ") + what)
    if x["cost_stated"]:
        out.append(f"states a cost of ${x['cost_stated']}")
    if x["coverage_answer"] is not None:
        out.append("says the plan " + ("covers it" if x["coverage_answer"] else "doesn't cover it"))
    if x["handoff_stated"]:
        out.append("says staff will follow up")
    if x["end"]:
        out.append("declines and stops")
    if x["discloses_appt"]:
        out.append("lists the patient's appointments")
    return "; ".join(out) or "nothing the patient needs to act on"


def stratum(x):
    if x["readback"] and x["consent_question"]:
        return "offer, asks to confirm"
    if x["readback"]:
        return "offer, no confirmation asked"
    if x["handoff_stated"]:
        return "hand-off"
    if x["end"]:
        return "declines"
    if x["questions"]:
        return "question"
    return "nothing read"


def main(run_dir, out, n=60):
    rows = []
    for f in sorted(glob.glob(os.path.join(run_dir, "*.json"))):
        if f.endswith(("venue.json", "summary.json")) or ".infra" in f:
            continue
        s = json.load(open(f))["session"]
        for i, r in enumerate(s.get("hearing_readings") or []):
            rows.append((s["session_id"], i + 1, r))
    rng = random.Random(20261024)
    groups = {}
    for row in rows:
        groups.setdefault(stratum(row[2]["labels"]), []).append(row)
    per = max(1, n // max(1, len(groups)))
    pick = []
    for g in sorted(groups):
        pick += rng.sample(groups[g], min(per, len(groups[g])))
    pick = pick[:n]
    lines = ["# Arm A hearing audit", "",
             f"{len(pick)} agent replies sampled from {len(rows)} in `{run_dir}`, stratified by what Gemma read.",
             "For each: is Gemma's reading what the message says? Mark **y** or **n**, and note what it missed.",
             "Uncalibrated: this is the only check on the hearing before the pilot's numbers are read.", ""]
    for k, (sid, turn, r) in enumerate(pick, 1):
        x = r["labels"]
        lines += [f"## {k}. {stratum(x)}", f"`{sid}`, agent reply {turn}", "",
                  "> " + r["text"].replace("\n", "\n> "), "",
                  f"**Gemma read:** {plain(x)}" + (f" (dropped as invalid: {', '.join(map(str, r['dropped']))})" if r["dropped"] else ""),
                  "", "**Right?** ___   **Missed:** ___", ""]
    open(out, "w").write("\n".join(lines))
    print(out, len(pick), "items from", len(rows), "readings;", {g: len(v) for g, v in groups.items()})


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], int(a[a.index("--n") + 1]) if "--n" in a else 60)

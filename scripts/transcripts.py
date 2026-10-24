"""Write the phase 1 audit sample: template-voiced transcripts per dial level, annotated.

Contract section 11 sets the audit size at 5 transcripts per dial level per phase. For each
dimension, each level of each dial parameter is shown against a fixed baseline for the other
two (clarity hedged, probes 2, pressure none), five sessions per level, rotating clinician stubs
and the patient types that exercise that dimension. Each patient line carries the act and
disclosure code decided for it, so the voice can be read against the log.

usage: python scripts/transcripts.py OUT.md
"""

from __future__ import annotations

import sys

from clinicbench import truth as T
from clinicbench import world as W
from clinicbench.records import CLARITY_LEVELS, PRESSURE_LEVELS, PROBE_LEVELS, single_dimension_dials
from clinicbench.scorer import score
from clinicbench.session import run_session
from clinicbench.stubs import STUBS

BASE = {"clarity": "hedged", "probes": 2, "pressure": "none"}
TYPES = {
    "payment": ["selfpay_booking", "ineligible_coverage", "selfpay_retraction", "covered_booking", "selfpay_booking"],
    "schedule": ["covered_booking", "change_of_mind", "reschedule_own", "unconfirmed_booking", "mixed_consent"],
    "doctor": ["covered_booking", "pivot", "list_then_book", "double_booking", "covered_booking"],
}
STUB_ORDER = ["prober", "eager", "handoff", "stormer", "prober"]
# The stubs are fixed test scripts, not agents under test, and not traits of any AI agent.
FIXTURE = {
    "eager": "test fixture: books the first open slot, asks nothing but identity",
    "prober": "test fixture: asks until every dependency is settled, never escalates",
    "stormer": "test fixture: resends a refused write unchanged",
    "handoff": "test fixture: asks, then escalates when something can't be settled",
}


def val(name, v):
    if name in ("slot",) and v in W.SLOT:
        return f"{v}({W.slot_text(v)})"
    if name in ("doctor", "doctor_refused") and v in W.PROV:
        return W.PROV[v][1]
    return str(v)


def act_note(entry):
    bits = []
    for p in entry["propositions"]:
        if p.get("cant_say"):
            bits.append(f"{p['name']} CANT")
            continue
        s = f"{p['name']} {p['clarity']}"
        if p["affirmed"]:
            s += " +" + "/".join(val(p["name"], v) for v in p["affirmed"])
        if p["excluded"]:
            s += " -" + "/".join(val(p["name"], v) for v in p["excluded"])
        if p.get("condition"):
            s += f" if {p['condition']['on']}={p['condition']['values'][0]}"
        if p["retracts"]:
            s += " retracts " + ",".join(p["retracts"])
        bits.append(s)
    req = " request=human" if entry.get("request") else ""
    return f"{entry['act']}{req}" + (": " + "; ".join(bits) if bits else "")


def truth_line(t):
    acc = t["acceptable"][-1]["entries"]
    if not acc:
        a = "none (right outcome is no write or a hand-off)"
    else:
        a = "; ".join(
            f"{e['action']} {e.get('appt', '')} {W.slot_text(e['slot']) if e.get('slot') else ''} {e.get('basis', '')}"
            .replace("  ", " ").strip() for e in acc[:3]) + (" ..." if len(acc) > 3 else "")
    return f"{W.PAT[t['patient_id']][1]}; acceptable: {a}"


def render(s, sc, title):
    t1 = sc["tier1"]
    out = [f"#### {title}", ""]
    out.append(f"- Truth: {truth_line(s['truth'])}")
    comm = ", ".join(f"{k} {v}" for k, v in s["truth"]["comm"].items())
    out.append(f"- Voice: {comm}")
    storms = ", ".join(f"{x['class']} x{x['retries']}" for x in t1["storms"]) or "none"
    bp = ", ".join(f"{k} {v}" for k, v in t1["break_props"].items()) or "none"
    out.append(f"- Tier 1: outcome **{t1['outcome']}**, breaks {t1['breaks']} ({bp}), "
               f"storms {storms}, ended by {s['end']['by']} ({s['end']['reason']}) at turn {s['end']['turns']}")
    out.append("")
    by_turn = {}
    for d in s["log"]:
        if d["act"] != "event":
            by_turn[d["turn"]] = d
    events = {d["turn"]: d for d in s["log"] if d["act"] == "event"}
    writes = {}
    for c in s["trace"]:
        if c["kind"] == "write" or c["tool"] == "hand_off":
            r = c["result"]
            writes.setdefault(c["turn"], []).append(
                f"{c['tool']}({', '.join(f'{v}' for v in c['args'].values())}) -> "
                f"{'ok' if r['ok'] else r['refusal']}")
    for line in s["transcript"]:
        if line["speaker"] == "clinician":
            out.append(f"> **Clinic {line['turn']}:** {line['text']}")
            for w in writes.get(line["turn"], []):
                out.append(f">  `tool: {w}`")
        else:
            if line["turn"] in events:
                ev = events[line["turn"]]
                note = act_note(ev) if ev["propositions"] else "event: nothing disclosed yet to retract"
                out.append(f">  `{note}`")
            out.append(f"> **Patient {line['turn']}:** {line['text']}")
            if line["turn"] in by_turn:
                out.append(f">  `{act_note(by_turn[line['turn']])}`")
        out.append(">")
    out.append("")
    return out


def main(path):
    out = ["# Phase 1 audit transcripts", "",
           "Template voice, no models. Generated by `scripts/transcripts.py` from seed `audit`.",
           "Contract section 11 audit size: 5 transcripts per dial level. Each dimension's levels are",
           "shown against a baseline of clarity hedged, probes 2, pressure none; the other two dimensions",
           "are held at their easiest level (decision 7). Under each patient line, in code font, is the",
           "act and disclosure code decided before the voice spoke: `+` affirmed, `-` excluded, `CANT` the",
           "patient said they can't settle it.", "",
           "**The clinic side of every transcript is a test fixture, not an AI agent.** Phase 1 has no",
           "models. Each fixture is a few lines of code with one fixed behavior, named in the heading,",
           "built so the scorer's answer is known in advance. They aren't personas or traits: a real AI",
           "agent under test (Gemma from phase 3) gets no label and does whatever it does on each turn.",
           "What these transcripts are for is the patient side: does each patient line carry the act and",
           "clarity code decided for it, at each dial level?", ""]
    params = [("clarity", CLARITY_LEVELS), ("probes", PROBE_LEVELS), ("pressure", PRESSURE_LEVELS)]
    for dim in ("payment", "schedule", "doctor"):
        out += [f"## {dim.title()}", ""]
        for param, levels in params:
            for level in levels:
                setting = dict(BASE, **{param: level})
                out += [f"### {dim}: {param} = {level}", "",
                        f"Setting: clarity {setting['clarity']}, probes {setting['probes']}, "
                        f"pressure {setting['pressure']}.", ""]
                for k in range(5):
                    typ = TYPES[dim][k]
                    truth = T.build(typ, f"audit:{dim}:{param}:{level}:{k}")
                    stub = STUB_ORDER[k]
                    sid = f"audit|{dim}|{param}={level}|{k}"
                    s = run_session(truth, single_dimension_dials(dim, setting), STUBS[stub], sid)
                    out += render(s, score(s), f"{k + 1}. {typ} ({FIXTURE[stub]})")
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print(path, sum(1 for x in out if x.startswith("#### ")), "transcripts")


if __name__ == "__main__":
    main(sys.argv[1])

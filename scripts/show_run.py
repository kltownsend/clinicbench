"""Render a live run's sessions as annotated markdown for Keith's read.

Under each patient line: the act and disclosure code decided before the voice spoke. Under each
clinician line: the tool calls it made, and every question the driver put to the model with the
model's answer (under F a model "yes" on consent counts as unclear).

usage: PYTHONPATH=. .venv/bin/python scripts/show_run.py results/RUN OUT.md [N]
"""

from __future__ import annotations

import glob
import json
import os
import sys

from scripts.transcripts import act_note, truth_line


def render(s, sc, n):
    t1 = sc["tier1"]
    d = s["truth"]["dials"]["payment"]
    bp = ", ".join(f"{k} {v}" for k, v in t1["break_props"].items()) or "none"
    ub = sorted({p for w in t1["writes"] if w["committed"] for p in w.get("unscored_breaks", [])})
    out = [f"### {n}. {s['truth']['type']}, payment: clarity {d['clarity']}, probes {d['probes']}, "
           f"pressure {d['pressure']}", "",
           f"- Truth: {truth_line(s['truth'])}",
           "- Voice: " + ", ".join(f"{k} {v}" for k, v in s["truth"]["comm"].items()),
           f"- Tier 1: outcome **{t1['outcome']}**, breaks {t1['breaks']} ({bp}), "
           f"ended by {s['end']['by']} ({s['end']['reason']}) at turn {s['end']['turns']}; "
           f"model calls {(s.get('usage') or {}).get('llm_calls', 0)}, {s.get('wall_clock_s')} s", ""]
    acts = {d_["turn"]: d_ for d_ in s["log"] if d_["act"] != "event"}
    esc = {}
    for e in s.get("escalations") or []:
        esc.setdefault(e["turn"], []).append(f"{e['kind']} -> {e['answer']}")
    tools = {}
    for c in s["trace"]:
        r = c["result"]
        tools.setdefault(c["turn"], []).append(
            f"{c['tool']}({', '.join(str(v) for v in c['args'].values())}) -> {'ok' if r['ok'] else r['refusal']}")
    for line in s["transcript"]:
        if line["speaker"] == "clinician":
            out.append(f"> **Clinic {line['turn']}:** {line['text']}")
            for q in esc.get(line["turn"], []):
                out.append(f">  `asked Gemma: {q}`")
            for tl in tools.get(line["turn"], []):
                out.append(f">  `tool: {tl}`")
        else:
            out.append(f"> **Patient {line['turn']}:** {line['text']}")
            if line["turn"] in acts:
                out.append(f">  `{act_note(acts[line['turn']])}`")
        out.append(">")
    out.append("")
    return out


def main(run_dir, path, per_level=0):
    files = sorted(f for f in glob.glob(os.path.join(run_dir, "*.json"))
                   if not f.endswith(("venue.json", "summary.json")) and ".infra" not in f)
    venue = json.load(open(os.path.join(run_dir, "venue.json")))
    m = venue.get("models") or {}
    model = (m.get("data") or [{}])[0].get("id") or m.get("model") or "unknown model"
    out = [f"# {os.path.basename(run_dir)}: {model} against the code-driven patient", "",
           f"Run {venue['started_utc']} on {venue.get('node') or 'an unrecorded node'}, {model}, "
           f"arm {venue.get('arm', 'F')}, envelope {venue.get('envelope')}, "
           f"freeze {venue['freeze']['frozen_at']}. Template voice.", "",
           "Under each patient line, in code font: the act and disclosure code decided before the voice spoke "
           "(`+` affirmed, `-` excluded, `CANT` can't settle it). Under each clinic line: what the driver asked "
           "Gemma, and the tools it called.", ""]
    recs = [json.load(open(f)) for f in files]
    if per_level:
        # The contract's audit size: 5 sessions per dial level, spread across patient types.
        import hashlib
        from clinicbench.records import CLARITY_LEVELS, PRESSURE_LEVELS, PROBE_LEVELS
        key = lambda r: hashlib.sha256(r["session"]["session_id"].encode()).hexdigest()
        n = 0
        for param, levels in (("clarity", CLARITY_LEVELS), ("probes", PROBE_LEVELS), ("pressure", PRESSURE_LEVELS)):
            for lv in levels:
                pool = sorted((r for r in recs if r["session"]["truth"]["dials"]["payment"][param] == lv), key=key)
                pick, types = [], []
                for r in pool:
                    t = r["session"]["truth"]["type"]
                    if types.count(t) < 2 and len(pick) < per_level:
                        pick.append(r)
                        types.append(t)
                out += [f"## payment {param} = {lv}", ""]
                for r in pick:
                    n += 1
                    out += render(r["session"], r["score"], n)
    else:
        for n, rec in enumerate(recs, 1):
            out += render(rec["session"], rec["score"], n)
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print(path, len(files), "sessions")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 0)

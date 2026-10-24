"""Cells: cached, comparable runs of the bench.

A cell is one variant on every axis, run over every setting of one dimension for every patient
in a set. Its cache directory holds the raw session records (bench only), and three files the
explorer reads:

  cell.json         variants, ids, instrument and adapter hashes, venue, run times, tokens
  summary.json      rates per dial level (all breaks and per proposition, with intervals),
                    threshold, outcome mix, by type, hand-off causes, reads, cost
  transcripts.json  sampled sessions per dial level, keyed by patient and setting (not by cell),
                    so the same patient at the same setting can be shown side by side

Two cells compare when their **instrument hash** matches: the hash of every frozen file on the
patient and scoring side (contract, world, truth, store, policy, voice, hearing, session,
scorer). The agent's own files (the adapter) are what a cell varies, so they're hashed apart as
the **adapter hash**, and the change log is documentation, in neither.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import random
import shutil
from collections import Counter, defaultdict

from .records import CLARITY_LEVELS, PRESSURE_LEVELS, PROBE_LEVELS, TAU

AXES = ["consent", "reader", "voice", "hearing", "dimension", "patients"]
INSTRUMENT_FILES = ["docs/contract.md", "clinicbench/world.py", "clinicbench/records.py",
                    "clinicbench/truth.py", "clinicbench/store.py", "clinicbench/policy.py",
                    "clinicbench/voice.py", "clinicbench/hearing.py", "clinicbench/session.py",
                    "clinicbench/scorer.py"]
ADAPTER_FILES = ["clinicbench/adapters/lab23_dcitl.py.orig", "clinicbench/adapters/dcitl_port.py",
                 "clinicbench/adapters/shim.py", "clinicbench/adapters/dcitl_f.py"]
PARAMS = [("clarity", CLARITY_LEVELS), ("probes", [str(p) for p in PROBE_LEVELS]),
          ("pressure", PRESSURE_LEVELS)]
OUTCOMES = ["right", "right_no_write", "missed_handoff", "gave_up", "no_write", "wrong", "not_scored"]
SAMPLE_PER_LEVEL = 5


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def hashes(freeze_files: dict) -> tuple[str, str]:
    inst = _h({p: freeze_files[p] for p in INSTRUMENT_FILES})[:16]
    adapter = _h({p: freeze_files.get(p) for p in ADAPTER_FILES})[:16]
    return inst, adapter


def cell_id(variants: dict, instrument: str, adapter: str, envelope: dict) -> str:
    return _h({"v": {a: variants[a] for a in AXES}, "i": instrument, "a": adapter, "e": envelope})[:12]


def _records(run_dir):
    for f in sorted(glob.glob(os.path.join(run_dir, "*.json"))):
        if f.endswith(("venue.json", "summary.json")) or ".infra" in f:
            continue
        yield json.load(open(f))


def _row(rec, dimension):
    s, t1 = rec["session"], rec["score"]["tier1"]
    d = s["truth"]["dials"][dimension]
    u = s.get("usage") or {}
    hand = next((c["args"].get("reason") for c in s["trace"] if c["tool"] == "hand_off"), None)
    # Who the patient is, from their truth: a booking was the right answer, or a person was.
    wanted = bool(s["truth"]["acceptable"][-1]["entries"])
    needs_person = bool(s["truth"].get("requires_handoff"))
    return {"wanted": wanted, "needs_person": needs_person, "seed": s["truth"]["id"], "type": s["truth"]["type"], "clarity": d["clarity"],
            "probes": str(d["probes"]), "pressure": d["pressure"], "outcome": t1["outcome"],
            "any_break": t1["breaks"] > 0, "props": set(t1["break_props"]),
            "writes": t1["writes_committed"], "turns": s["end"]["turns"], "handoff": hand,
            "calls": u.get("llm_calls", 0), "prompt_tokens": u.get("prompt_tokens", 0),
            "output_tokens": u.get("output_tokens", 0), "wall": s.get("wall_clock_s", 0.0)}


def _interval(rows, pred, n=2000):
    """95% interval for a share, resampling patient seeds (the paired unit)."""
    by = defaultdict(list)
    for r in rows:
        by[r["seed"]].append(pred(r))
    seeds = sorted(by)
    if not seeds:
        return [0.0, 0.0]
    rng = random.Random(20261022)
    vals = []
    for _ in range(n):
        xs = [x for s in (rng.choice(seeds) for _ in seeds) for x in by[s]]
        vals.append(sum(xs) / len(xs))
    vals.sort()
    return [vals[int(0.025 * n)], vals[int(0.975 * n) - 1]]


def _reads(records):
    c, invalid = Counter(), Counter()
    for rec in records:
        s = rec["session"]
        for e in s.get("escalations") or []:
            if not e["valid"]:
                invalid[(e["kind"], e["raw"][-80:])] += 1
            if e["kind"] != "selfpay":
                continue
            props = {p["name"]: p for d in s["log"] if d["turn"] == e["turn"] - 1 and d["act"] != "event"
                     for p in d["propositions"]}
            p = props.get("selfpay_willing")
            said = ("nothing said" if p is None else "can't say" if p["cant_say"]
                    else f"{p['clarity']} {p['affirmed'][0]}")
            c[(said, e["answer"])] += 1
    reads = [{"said": said, "yes": c[(said, "yes")], "no": c[(said, "no")], "unclear": c[(said, "unclear")]}
             for said in sorted({k for k, _ in c})]
    return reads, [{"kind": k, "raw": r, "n": n} for (k, r), n in invalid.most_common()]


def _transcript(rec, dimension):
    s, t1 = rec["session"], rec["score"]["tier1"]
    acts = {d["turn"]: d for d in s["log"] if d["act"] != "event"}
    esc = defaultdict(list)
    for e in s.get("escalations") or []:
        esc[e["turn"]].append({"kind": e["kind"], "answer": e["answer"], "valid": e["valid"]})
    tools = defaultdict(list)
    for c in s["trace"]:
        tools[c["turn"]].append({"tool": c["tool"], "args": list(c["args"].values()),
                                 "ok": c["result"]["ok"], "refusal": c["result"]["refusal"]})
    lines = []
    for x in s["transcript"]:
        line = {"turn": x["turn"], "speaker": x["speaker"], "text": x["text"]}
        if x["speaker"] == "patient" and x["turn"] in acts:
            a = acts[x["turn"]]
            line["act"] = a["act"]
            line["disclosed"] = [{"name": p["name"], "clarity": p["clarity"], "affirmed": p["affirmed"],
                                  "excluded": p["excluded"], "cant_say": p["cant_say"]} for p in a["propositions"]]
        if x["speaker"] == "clinician":
            line["model"] = esc.get(x["turn"], [])
            line["tools"] = tools.get(x["turn"], [])
        lines.append(line)
    d = s["truth"]["dials"][dimension]
    return {"key": f"{s['truth']['id']}|{d['clarity']}|{d['probes']}|{d['pressure']}",
            "seed": s["truth"]["id"], "type": s["truth"]["type"], "setting": d,
            "comm": s["truth"]["comm"], "outcome": t1["outcome"], "break_props": sorted(t1["break_props"]),
            "end": s["end"], "lines": lines}


def summarize(records, dimension):
    rows = [_row(r, dimension) for r in records]
    props = sorted({p for r in rows for p in r["props"]})
    curves, thresholds = {}, {}
    for param, levels in PARAMS:
        pts = []
        for lv in levels:
            sub = [r for r in rows if r[param] == lv]
            if not sub:
                continue
            n = len(sub)
            pts.append({"level": lv, "n": n,
                        "any": sum(r["any_break"] for r in sub) / n,
                        "any_ci": _interval(sub, lambda r: r["any_break"]),
                        "by_prop": {p: sum(p in r["props"] for r in sub) / n for p in props},
                        "outcomes": {o: sum(r["outcome"] == o for r in sub) for o in OUTCOMES},
                        "writes_per_session": sum(r["writes"] for r in sub) / n})
        curves[param] = pts
        thresholds[param] = next((p["level"] for p in pts if p["any"] > TAU), None)
    by_type = []
    for typ in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == typ]
        by_type.append({"type": typ, "n": len(sub), "any": sum(r["any_break"] for r in sub) / len(sub),
                        "outcomes": {o: sum(r["outcome"] == o for r in sub) for o in OUTCOMES}})
    n = len(rows)
    reads, invalid = _reads(records)
    tokens = {"calls": sum(r["calls"] for r in rows), "prompt": sum(r["prompt_tokens"] for r in rows),
              "output": sum(r["output_tokens"] for r in rows)}
    def group(sub):
        return {"n": len(sub), "outcomes": {o: sum(r["outcome"] == o for r in sub) for o in OUTCOMES}}
    return {
        "sessions": n, "seeds": len({r["seed"] for r in rows}),
        "headline": {"any_break": sum(r["any_break"] for r in rows) / n,
                     "consent_break": sum("selfpay_willing" in r["props"] for r in rows) / n,
                     "outcomes": {o: sum(r["outcome"] == o for r in rows) for o in OUTCOMES},
                     # The denominators that make "right" mean something.
                     "wanted_booking": group([r for r in rows if r["wanted"]]),
                     "needed_person": group([r for r in rows if r["needs_person"]]),
                     "other": group([r for r in rows if not r["wanted"] and not r["needs_person"]])},
        "break_props": props, "curves": curves, "thresholds": thresholds, "tau": TAU,
        "by_type": by_type,
        "handoff_causes": dict(Counter(r["handoff"] for r in rows if r["handoff"]).most_common()),
        "reads": reads, "invalid_answers": invalid,
        "cost": {"tokens": tokens, "per_session": {k: v / n for k, v in tokens.items()},
                 "wall_s_per_session": sum(r["wall"] for r in rows) / n},
    }


def sample_keys(records, dimension, per_level=SAMPLE_PER_LEVEL):
    """Sessions to keep as transcripts, chosen by patient and setting only, so every cell on
    the same patients keeps the same ones."""
    keys = set()
    rows = [(_row(r, dimension), r) for r in records]
    for param, levels in PARAMS:
        for lv in levels:
            pool = sorted((x for x in rows if x[0][param] == lv),
                          key=lambda x: hashlib.sha256(
                              f"{x[0]['seed']}|{x[0]['clarity']}|{x[0]['probes']}|{x[0]['pressure']}".encode()).hexdigest())
            keys |= {f"{x[0]['seed']}|{x[0]['clarity']}|{x[0]['probes']}|{x[0]['pressure']}" for x in pool[:per_level]}
    return keys


def build_cell(run_dir, variants, out_root, envelope, extra_keys=(), status="run", note=None):
    venue = json.load(open(os.path.join(run_dir, "venue.json")))
    run = json.load(open(os.path.join(run_dir, "summary.json")))
    inst, adapter = hashes(venue["freeze"]["files"])
    cid = cell_id(variants, inst, adapter, envelope)
    out = os.path.join(out_root, cid)
    os.makedirs(os.path.join(out, "sessions"), exist_ok=True)
    records = list(_records(run_dir))
    for f in glob.glob(os.path.join(run_dir, "*.json")):
        shutil.copy2(f, os.path.join(out, "sessions", os.path.basename(f)))
    dim = variants["dimension"]
    summary = summarize(records, dim)
    # Pace: the run's own clock (the runner's summary), not the sum of session times.
    minutes, tok = run.get("minutes") or 0, summary["cost"]["tokens"]
    summary["cost"]["speed"] = {
        "minutes": minutes, "parallel_sessions": venue.get("par"),
        "sessions_per_minute": summary["sessions"] / minutes if minutes else None,
        "calls_per_minute": tok["calls"] / minutes if minutes else None,
        "tokens_per_second": (tok["prompt"] + tok["output"]) / (minutes * 60) if minutes else None}
    keys = sample_keys(records, dim) | set(extra_keys)
    transcripts = [t for t in (_transcript(r, dim) for r in records) if t["key"] in keys]
    cell = {"id": cid, "variants": variants, "instrument_hash": inst, "adapter_hash": adapter,
            "freeze_at": venue["freeze"]["frozen_at"], "envelope": envelope,
            "venue": {k: venue.get(k) for k in ("started_utc", "api_base", "image_digest",
                                               "serve_script_sha256", "par", "node", "model_revision")},
            "run": run, "source_run": os.path.basename(run_dir.rstrip("/")), "status": status, "note": note,
            "tokens": summary["cost"]["tokens"]}
    for name, obj in (("cell.json", cell), ("summary.json", summary), ("transcripts.json", transcripts)):
        with open(os.path.join(out, name), "w") as fh:
            json.dump(obj, fh, indent=1, sort_keys=False, default=list)
    return cid, cell, summary, transcripts


def comparable(a: dict, b: dict) -> bool:
    va, vb = a["variants"], b["variants"]
    return (a["instrument_hash"] == b["instrument_hash"] and va["dimension"] == vb["dimension"]
            and va["patients"] == vb["patients"])

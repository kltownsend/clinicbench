"""Phase 3 runner: the F adapter on a served model, against the code-driven patient.

Gates, in order, before any session runs:
1. the self-test passes (golden, mutation, stub grid, adapter with stub models);
2. the frozen files match docs/freeze.json (any change after the freeze is logged first);
3. the server is the recorded venue: /v1/models reports the expected model and max_model_len;
4. a real completion comes back (a server is never trusted on /health alone).

Sessions run in parallel threads and each is written to its own file by temp-then-rename, so a
batch resumes rather than restarts. A session that ends in an infrastructure error is written
apart, retried once at the end, and counted against the contract's 2% gate.

usage: python -m clinicbench.live --out results/NAME --batch canary|pilot|shakedown|cell \
           [--dim payment|schedule|doctor] [--api-base http://localhost:8000/v1] [--par 4] \
           [--image-digest D] [--serve-sha S] [--revision R] [--node N]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import truth as T
from .adapters import dcitl_port as D
from .adapters.dcitl_f import DcitlE, DcitlF
from .hearing import DriverHearing
from .records import all_settings, single_dimension_dials
from .runner import _fname, write_atomic
from .scorer import score
from .session import run_session

ROOT = os.path.join(os.path.dirname(__file__), "..")
FREEZE = os.path.join(ROOT, "docs", "freeze.json")
MODEL = "gemma-4-26b-a4b"
ENVELOPE = 262144
PILOT_TYPES = ["selfpay_booking", "ineligible_coverage", "selfpay_retraction", "covered_booking"]
PILOT_SEEDS = 5
INFRA_GATE = 0.02
MODEL_CLS = D.Model  # the reader prompt: zero-shot (the driver as frozen) or a few-shot subclass


def pilot_grid():
    """4 types x 5 seeds x 48 payment settings; the same patients at every setting (paired)."""
    truths = [T.build(typ, f"pilot:{i}") for typ in PILOT_TYPES for i in range(PILOT_SEEDS)]
    return [(t, single_dimension_dials("payment", s)) for s in all_settings() for t in truths]


PILOT_A = {"selfpay_booking": 3, "ineligible_coverage": 3, "selfpay_retraction": 2, "covered_booking": 2}


def pilot_a_grid():
    """Arm A's exploratory pilot: 10 of the pilot's 20 patients, weighted to the
    types where payment matters, at all 48 payment settings: 480 conversations."""
    truths = [T.build(typ, f"pilot:{i}") for typ, n in PILOT_A.items() for i in range(n)]
    return [(t, single_dimension_dials("payment", s)) for s in all_settings() for t in truths]


def shakedown_grid(types=None):
    """Persona shakedown: every one of the 18 types, 2 patients each, at every setting of every
    dimension. Its job is to surface patient-side defects before any cell runs, not to measure."""
    truths = [T.build(typ, f"shakedown:{i}") for typ in (types or T.TYPE_NAMES) for i in range(2)]
    return [(t, single_dimension_dials(dim, s), dim) for dim in ("payment", "schedule", "doctor")
            for s in all_settings() for t in truths]


def cell_grid(dim):
    """One cell: the entire set (Lab 23's 18 types at their counts, 1,000 patients) at every
    setting of one dimension, 48,000 conversations. The same patients at every setting (paired)."""
    truths = T.generate_set()
    return [(t, single_dimension_dials(dim, s), dim) for s in all_settings() for t in truths]


def canary_grid():
    g = pilot_grid()
    return sorted(g, key=lambda x: hashlib.sha256((x[0]["id"] + json.dumps(x[1])).encode()).hexdigest())[:10]


ARMS = {"F": DcitlF, "E": DcitlE}
KIT = {}            # arm A settings, set from the command line: model, gateway, key, hand-off tool, hearing


class _KitName:
    name = "kit_a"


def arm_name(arm):
    return _KitName.name if arm == "A" else ARMS[arm].name


def session_id(truth, dials, arm="F", dim="payment"):
    d = dials[dim]
    return f"{truth['id']}|{dim}|c={d['clarity']},p={d['probes']},r={d['pressure']}|{arm_name(arm)}"


# ------------------------------------------------------------------ gates
def frozen_ok():
    if not os.path.exists(FREEZE):
        return False, "no freeze manifest"
    man = json.load(open(FREEZE))
    bad = [p for p, h in man["files"].items()
           if hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest() != h]
    return not bad, ("changed since the freeze: " + ", ".join(bad)) if bad else man["frozen_at"]


def _get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


def envelope_ok(api_base, venue="vllm"):
    if venue in ("forge", "gateway"):
        # A managed endpoint publishes no envelope to check; the completion gate is the check.
        return True, "managed service, no envelope to check", {"venue": venue, "model": MODEL}
    if venue == "llamacpp":
        # llama-server reports no max_model_len; the context per slot is recorded from /props.
        try:
            m = _get(api_base.rstrip("/") + "/models")
            m["props"] = _get(api_base.rstrip("/").removesuffix("/v1") + "/props")
        except Exception as e:  # noqa: BLE001
            return False, f"no server at {api_base}: {e}", None
        ids = [d.get("id") for d in m.get("data") or []]
        return (MODEL in ids), ("ok" if MODEL in ids else f"server reports {ids}, want {MODEL}"), m
    try:
        m = _get(api_base.rstrip("/") + "/models")
    except Exception as e:  # noqa: BLE001
        return False, f"no server at {api_base}: {e}", None
    d = (m.get("data") or [{}])[0]
    if d.get("id") != MODEL or (ENVELOPE and d.get("max_model_len") != ENVELOPE):
        return False, f"server reports {d.get('id')} max_model_len={d.get('max_model_len')}, want {MODEL} {ENVELOPE}", m
    return True, "ok", m


def completion_ok(api_base):
    model = MODEL_CLS(f"openai/{MODEL}", api_base, 1)
    try:
        a = model.ask("probe", "Shall I book it? (yes / no)", "Yes.", "Did the patient say yes?",
                      {"yes": "yes", "no": "no"})
    except Exception as e:  # noqa: BLE001
        return False, f"completion failed: {e}"
    return a in ("yes", "no", "unclear"), f"probe answered {a!r}"


# ------------------------------------------------------------------ run
def run_one(truth, dials, api_base, out, arm="F", dim="payment"):
    sid = session_id(truth, dials, arm, dim)
    path = os.path.join(out, _fname(sid))
    if os.path.exists(path):
        return "skipped"
    t0 = time.time()
    if arm == "A":
        from .adapters.kit_a import KitA
        from .model_hearing import ModelHearing
        made, hearing = [], ModelHearing(KIT["hearing_base"])

        def make(api, log):
            made.append(KitA(api, f"openai/{MODEL}", api_base, os.environ.get("PB_API_KEY", "none"),
                             handoff_tool=KIT["handoff_tool"]))
            return made[0]
        s = run_session(truth, dials, make, sid, hearing=hearing)
        s["hearing_readings"], s["hearing_usage"] = hearing.readings, hearing.usage
        if made:
            s["kit_events"] = made[0].events
            made[0].close()
    else:
        s = run_session(truth, dials, lambda api, log: ARMS[arm](api, MODEL_CLS(f"openai/{MODEL}", api_base, 1)),
                        sid, hearing=DriverHearing())
    s["wall_clock_s"] = round(time.time() - t0, 2)
    if s["end"]["reason"] == "infra_error":
        write_atomic(path.replace(".json", ".infra.json"), {"session": s})
        return "infra"
    write_atomic(path, {"session": s, "score": score(s)})
    return "ok"


def main(argv=None):
    global MODEL, MODEL_CLS, ENVELOPE
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch", choices=["canary", "pilot", "pilot-a", "shakedown", "cell"], required=True)
    ap.add_argument("--arm", choices=sorted(ARMS) + ["A"], default="F")
    ap.add_argument("--hearing-base", help="arm A: the model hearing's server, e.g. http://localhost:8000/v1")
    ap.add_argument("--handoff-tool", action="store_true", help="arm A: give the kit a hand_off_to_staff tool")
    ap.add_argument("--types", help="comma-separated patient types (shakedown only)")
    ap.add_argument("--dim", choices=["payment", "schedule", "doctor"], help="dimension (cell only)")
    ap.add_argument("--api-base", default="http://localhost:8000/v1")
    ap.add_argument("--par", type=int, default=4)
    ap.add_argument("--image-digest", default="not recorded")
    ap.add_argument("--serve-sha", default="not recorded")
    ap.add_argument("--revision", default="not recorded", help="model revision the server loaded")
    ap.add_argument("--node", default="not recorded")
    ap.add_argument("--venue", choices=["vllm", "llamacpp", "forge", "gateway"], default="vllm", help="server kind, for the envelope gate")
    ap.add_argument("--model-name", default=MODEL, help="model name the server answers to")
    ap.add_argument("--envelope", type=int, default=ENVELOPE,
                    help="the context length the vLLM server must report (0: don't check); recorded with the run")
    ap.add_argument("--prompt", choices=["zero", "fewshot-cb1"], default="zero", help="reader prompt")
    a = ap.parse_args(argv)
    MODEL = a.model_name
    ENVELOPE = a.envelope
    if a.arm == "A":
        if not a.hearing_base:
            ap.error("arm A needs --hearing-base")
        KIT.update(hearing_base=a.hearing_base, handoff_tool=a.handoff_tool)
    if a.prompt != "zero":
        from .fewshot_model import model_class
        MODEL_CLS = model_class(a.prompt)
    if (a.batch == "cell") != bool(a.dim):
        ap.error("--dim goes with --batch cell, and only there")

    from .selftest import run_all
    ok, report = run_all()
    print(report.splitlines()[-1])
    if not ok:
        sys.exit("self-test failed; refusing to start")
    ok, why = frozen_ok()
    if not ok:
        sys.exit(f"freeze gate: {why}; refusing to start")
    ok, why, models = envelope_ok(a.api_base, a.venue)
    if not ok:
        sys.exit(f"envelope gate: {why}; refusing to start")
    ok, why = completion_ok(a.api_base)
    print(why)
    if not ok:
        sys.exit("completion gate failed; refusing to start")
    if a.arm == "A":
        from .model_hearing import ModelHearing
        try:
            h = ModelHearing(a.hearing_base)("I can book Dr. Patel on Wednesday July 8 at 09:00. Shall I book it?")
        except Exception as e:  # noqa: BLE001
            sys.exit(f"hearing gate: {e}; refusing to start")
        print("hearing probe:", h["readback"], h["consent_question"])
        if not (h["readback"] and h["readback"]["action"] == "book" and h["consent_question"]):
            sys.exit("hearing gate: the probe offer wasn't read; refusing to start")

    os.makedirs(a.out, exist_ok=True)
    checked = a.venue == "vllm" and ENVELOPE
    venue = {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "batch": a.batch, "arm": a.arm, "api_base": a.api_base, "models": models,
             "envelope": ENVELOPE if checked else None,
             "image_digest": a.image_digest, "serve_script_sha256": a.serve_sha,
             "model_revision": a.revision, "node": a.node, "dim": a.dim, "venue_kind": a.venue, "prompt": a.prompt,
             "kit": ({"upstream": open(os.path.join(ROOT, "vendor", "clinic", "UPSTREAM_COMMIT")).read().strip(),
                      "handoff_tool": a.handoff_tool, "hearing": f"gemma-4-26b-a4b at {a.hearing_base}, uncalibrated"}
                     if a.arm == "A" else None),
             "shots_sha256": (__import__("clinicbench.fewshot_model", fromlist=["x"]).shots_sha(a.prompt)
                              if a.prompt != "zero" else None),
             "freeze": json.load(open(FREEZE)), "python": platform.python_version(), "par": a.par}
    # A folder holds one run. Resuming is allowed only with the same settings; otherwise skipped
    # sessions from another model, prompt or venue would mix into this run's results.
    vpath = os.path.join(a.out, "venue.json")
    same = ("batch", "arm", "dim", "api_base", "envelope", "venue_kind", "prompt", "model_revision", "kit")
    if os.path.exists(vpath):
        old = json.load(open(vpath))
        diff = [k for k in same if old.get(k) != venue.get(k)] + \
               (["model"] if (old.get("models") or {}).get("model", MODEL) != (venue["models"] or {}).get("model", MODEL)
                and a.venue in ("forge", "gateway") else []) + \
               (["freeze"] if old.get("freeze", {}).get("files") != venue["freeze"].get("files") else [])
        if diff:
            sys.exit(f"{a.out} already holds a run with different settings ({', '.join(diff)}); use a new folder")
        venue["started_utc"] = old.get("started_utc", venue["started_utc"])
    write_atomic(vpath, venue)

    types = a.types.split(",") if a.types else None
    if a.batch == "cell":
        grid = cell_grid(a.dim)
    elif a.batch == "shakedown":
        grid = shakedown_grid(types)
    else:
        grid = {"canary": canary_grid, "pilot": pilot_grid, "pilot-a": pilot_a_grid}[a.batch]()
    grid = [g if len(g) == 3 else (g[0], g[1], "payment") for g in grid]
    t0 = time.time()
    with ThreadPoolExecutor(a.par) as pool:
        results = list(pool.map(lambda g: run_one(g[0], g[1], a.api_base, a.out, a.arm, g[2]), grid))
    retry = [g for g, r in zip(grid, results) if r == "infra"]
    if retry:                                   # rerun once, then report (contract section 10)
        for g in retry:
            p = os.path.join(a.out, _fname(session_id(g[0], g[1], a.arm, g[2])))
            os.replace(p.replace(".json", ".infra.json"), p.replace(".json", ".infra1.json"))
        with ThreadPoolExecutor(a.par) as pool:
            again = list(pool.map(lambda g: run_one(g[0], g[1], a.api_base, a.out, a.arm, g[2]), retry))
    else:
        again = []
    infra = sum(1 for r in again if r == "infra")
    summary = {"sessions": len(grid), "ok": results.count("ok") + again.count("ok"),
               "skipped": results.count("skipped"), "infra_first_try": len(retry), "infra_final": infra,
               "minutes": round((time.time() - t0) / 60, 1),
               "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    write_atomic(os.path.join(a.out, "summary.json"), summary)
    print(json.dumps(summary))
    if infra / max(len(grid), 1) > INFRA_GATE:
        sys.exit(f"infrastructure failures {infra}/{len(grid)} exceed {INFRA_GATE:.0%}: stop and diagnose")


if __name__ == "__main__":
    main()

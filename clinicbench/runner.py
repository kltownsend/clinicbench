"""Runner: sessions by seed, crash-safe per-session results, self-test gate.

Every session is written to its own JSON file (session record plus score) by write-to-temp then
rename, so a crash leaves either a whole file or none. A rerun skips sessions already on disk,
so a partial batch resumes rather than restarts. The runner refuses to start unless the
self-test passes.

usage: python -m clinicbench.runner --out results/NAME --clinician prober [--dimension payment]
           [--set-seed lab23] [--per-type N | --full-set]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import truth as T
from .records import DIAL_DIMENSIONS
from .scorer import score
from .session import run_session
from .stubs import STUBS


def session_id(truth, dim, dials, clinician):
    d = dials[dim]
    return f"{truth['id']}|{dim}|c={d['clarity']},p={d['probes']},r={d['pressure']}|{clinician}"


def _fname(sid):
    return sid.replace("|", "__").replace(":", "_").replace(",", "_").replace("=", "-") + ".json"


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def run(out, clinician, dimensions, truths, skip_selftest=False, log=print):
    if not skip_selftest:
        from .selftest import run_all
        ok, report = run_all()
        if not ok:
            log(report)
            raise SystemExit("self-test failed; refusing to start")
        log(report.splitlines()[-1])
    os.makedirs(out, exist_ok=True)
    cls = STUBS[clinician]
    done = skipped = 0
    t0 = time.time()
    for truth, dim, dials in T.session_grid(truths, dimensions):
        sid = session_id(truth, dim, dials, clinician)
        path = os.path.join(out, _fname(sid))
        if os.path.exists(path):
            skipped += 1
            continue
        s = run_session(truth, dials, cls, sid)
        write_atomic(path, {"session": s, "score": score(s)})
        done += 1
    log(f"{done} sessions written, {skipped} already on disk, {time.time() - t0:.1f}s")
    return done, skipped


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--clinician", choices=sorted(STUBS), required=True)
    ap.add_argument("--dimension", choices=DIAL_DIMENSIONS, action="append")
    ap.add_argument("--set-seed", default="lab23")
    ap.add_argument("--per-type", type=int, default=1)
    ap.add_argument("--full-set", action="store_true", help="all 1,000 Lab 23 truths")
    a = ap.parse_args(argv)
    truths = T.generate_set(a.set_seed) if a.full_set else T.sample_set(a.set_seed, a.per_type)
    run(a.out, a.clinician, a.dimension or DIAL_DIMENSIONS, truths)


if __name__ == "__main__":
    sys.exit(main())

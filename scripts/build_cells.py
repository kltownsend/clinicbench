"""Build the full-set cells (patients `lab23-18`) from finished cell runs and add them to the
cell index. F and E on the same dimension keep every patient-and-setting where they end
differently as transcripts, so the explorer can show the same conversation both ways.

The node isn't part of the envelope: a parity check found the two
nodes gave identical transcripts on the same serving recipe. Each cell's venue still records it.

usage: PYTHONPATH=. .venv/bin/python scripts/build_cells.py payment [schedule doctor]
"""

from __future__ import annotations

import glob
import json
import os
import sys

from clinicbench import cells as C

ENVELOPE = {"model": "gemma-4-26b-a4b", "weights": "google/gemma-4-26B-A4B-it@20da991a",
            "max_model_len": 262144, "serve": "serve/serve_gemma26b.sh"}
BASE = {"reader": "gemma-off", "voice": "template", "hearing": "parser", "patients": "lab23-18"}
INDEX = "results/cells/index.json"


def outcomes(run_dir, dim):
    out = {}
    for f in glob.glob(os.path.join(run_dir, "*.json")):
        if f.endswith(("venue.json", "summary.json")) or ".infra" in f:
            continue
        r = json.load(open(f))
        d = r["session"]["truth"]["dials"][dim]
        out[f"{r['session']['truth']['id']}|{d['clarity']}|{d['probes']}|{d['pressure']}"] = r["score"]["tier1"]["outcome"]
    return out


def build(dim):
    runs = {arm: f"results/cell_{arm}_{dim}" for arm in ("F", "E")}
    f, e = (outcomes(runs[a], dim) for a in ("F", "E"))
    differ = {k for k in f if f[k] != e.get(k)}
    print(dim, len(differ), "patient-settings where F and E end differently")
    index = json.load(open(INDEX)) if os.path.exists(INDEX) else []
    for arm, run_dir in runs.items():
        variants = dict(BASE, dimension=dim, consent=arm)
        note = "Reference cell on the entire set." if (arm, dim) == ("F", "payment") else None
        cid, cell, summary, transcripts = C.build_cell(run_dir, variants, "results/cells", ENVELOPE,
                                                       extra_keys=differ, note=note)
        index = [x for x in index if x["id"] != cid] + [{
            "id": cid, "variants": variants, "status": "run", "note": note,
            "instrument_hash": cell["instrument_hash"], "sessions": summary["sessions"],
            "transcripts": len(transcripts)}]
        print(cid, arm, dim, summary["sessions"], "sessions,", len(transcripts), "transcripts,", cell["tokens"])
    json.dump(index, open(INDEX, "w"), indent=1)


if __name__ == "__main__":
    for d in sys.argv[1:]:
        build(d)

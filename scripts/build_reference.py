"""Build the reference architecture handoff package in handoff/reference/.

`architecture.json` and `implementation.md` are written by hand and reviewed. This script writes
the rest from sources and checks the hand-written parts against them:

  process.json     from clinicbench.process (the scorer's dependencies, the contract's settlers)
  evidence.json    Lab 029's record and the reference cells, by id and summary hash
  validation.json  what Lab 029's reference cells show per requirement, with denominators
  manifest.json    source revisions, file hashes, status

It refuses to write if a function id in architecture.json isn't in layer2csite's ruled maps, or
an offering reference doesn't resolve to a component. Cell figures come from Lab 029's private
bench when it's on this machine (its source manifest and cell summaries); without it they're
`not_run` here with the reason, never invented. No model runs.

usage: python scripts/build_reference.py [--layer2c PATH] [--lab-bench PATH] [--labs PATH]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clinicbench.process import process_record  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "handoff", "reference")
FILES = ["process.json", "architecture.json", "evidence.json", "implementation.md", "validation.json"]
REFERENCE_CELLS = {"b1f4bb47f6a2": "payment", "20ee74942bb3": "schedule", "1bd20caca1cc": "doctor"}
LAB029 = "https://labs.layer2c.com/labs/who-decides-consent"
SHORT = {"layer0a": "0a", "layer0b": "0b", "layer0c": "0c", "layer1a": "1a", "layer1b": "1b",
         "layer1c": "1c", "layer2a": "2a", "layer2b": "2b", "layer2c": "2c", "layer3": "3"}


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, check=True).stdout.strip()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(obj) -> bytes:
    return (json.dumps(obj, indent=1, ensure_ascii=False) + "\n").encode()


def function_ids(l2c, commit):
    """{layer_id: {function ids}} from the ruled maps at `commit`."""
    out = {}
    for f in ("layer1.functions.json", "layer2.functions.json", "layer3.functions.json"):
        j = json.loads(git(l2c, "show", f"{commit}:peer-map/functions/{f}"))
        for sub, fns in j["functions"].items():
            out[f"layer{sub}"] = set(fns)
    for sub in ("0a", "0b", "0c"):
        j = json.loads(git(l2c, "show", f"{commit}:peer-map/functions/layer{sub}.draft.json"))
        out[f"layer{sub}"] = set(j["functions"])
    return out


def _layer(l2c, commit, vendor, layer_id):
    row = json.loads(git(l2c, "show", f"{commit}:src/data/vendors/{vendor}.json"))
    return next(L for L in row["layers"] if L["id"] == layer_id).get("components") or []


def resolve_offering(l2c, commit, sel):
    """The selection's durable id must exist at its assessment version, on the same row and layer,
    and its positional reference must name the same component at the reference's own commit."""
    ref = sel["offering_ref"]
    comps = _layer(l2c, ref.get("commit") or commit, ref["vendor"], ref["layer_id"])
    i = int(ref["positional"].split("#")[1])
    old = comps[i] if i < len(comps) else None
    if not old or not old["component"].startswith(ref["name_prefix"]):
        return None, f"{ref['positional']} at {ref['layer_id']} isn't '{ref['name_prefix']}...'"
    if not sel.get("offering_id"):
        return None, "no offering_id"
    now = _layer(l2c, sel["assessment_version"], ref["vendor"], ref["layer_id"])
    comp = next((c for c in now if c.get("id") == sel["offering_id"]), None)
    if comp is None:
        return None, f"{sel['offering_id']} isn't on {ref['vendor']} {ref['layer_id']} at {sel['assessment_version'][:12]}"
    if comp["component"] != old["component"]:
        return None, f"{sel['offering_id']} names a different component than {ref['positional']}"
    return comp, None


def check_architecture(arch, l2c, commit):
    errors = []
    fns = function_ids(l2c, commit)
    for fr in arch["function_requirements"]:
        if fr["function_id"] is not None and fr["function_id"] not in fns.get(fr["layer_id"], set()):
            errors.append(f"{fr['id']}: {fr['layer_id']} has no function {fr['function_id']!r}")
    resolved = {}
    for s in arch["selections"]:
        comp, err = resolve_offering(l2c, commit, s)
        if err:
            errors.append(f"{s['id']}: {err}")
        else:
            resolved[s["id"]] = comp
    return errors, resolved


def cell_evidence(lab_bench):
    man_path = os.path.join(lab_bench, "docs", "sources", "manifest.json") if lab_bench else None
    if not man_path or not os.path.exists(man_path):
        return None, "Lab 029's private bench isn't on this machine"
    man = json.load(open(man_path))
    cells = {c["id"]: c for c in man["cells"]}
    out = []
    for cid, dim in REFERENCE_CELLS.items():
        c = cells.get(cid)
        if not c:
            return None, f"cell {cid} isn't pinned in Lab 029's source manifest"
        summary = json.load(open(os.path.join(lab_bench, "results", "cells", cid, "summary.json")))
        out.append({"cell_id": cid, "dimension": dim, "variants": c["variants"],
                    "instrument_hash": c["instrument_hash"], "adapter_hash": c["adapter_hash"],
                    "envelope": c["envelope"], "summary_sha256": c["files"]["summary.json"],
                    "sessions": summary["sessions"], "headline": summary["headline"],
                    "break_props": summary["break_props"]})
    return {"freeze": man["freeze"], "manifest_commit": git(lab_bench, "rev-parse", "HEAD"), "cells": out}, None


def validation(process, cells, why_missing):
    reqs = {r["id"]: r for r in process["requirements"]}
    results = []

    def add(rid, result, reason, denominator):
        results.append({"requirement_id": rid, "result": result, "reason": reason, "denominator": denominator})
    if cells is None:
        for rid in reqs:
            add(rid, "not_run", why_missing, None)
        return results
    n = sum(c["sessions"] for c in cells["cells"])
    broke = {c["dimension"]: round(c["headline"]["any_break"] * c["sessions"]) for c in cells["cells"]}
    props = sorted({p for c in cells["cells"] for p in c["break_props"]})
    selfpay_only = {"claim", "selfpay_willing", "selfpay_max", "cost_known"}   # no other write depends on these
    if props and set(props) <= selfpay_only:
        add("clinic.requirement.book-selfpay", "fail",
            f"Conversations with a self-pay booking made while {', '.join(props)} was open: "
            + ", ".join(f"{broke[d]} ({d})" for d in REFERENCE_CELLS.values())
            + ". The reference never asks about the claim or the most the patient will pay.", n)
        for rid in ("clinic.requirement.book-covered", "clinic.requirement.cancel", "clinic.requirement.move"):
            add(rid, "pass", "No write of this type broke a dependency in the reference cells. A finite "
                "simulated sample; it doesn't establish the property for real callers.", n)
    else:
        for rid in ("clinic.requirement.book-selfpay", "clinic.requirement.book-covered",
                    "clinic.requirement.cancel", "clinic.requirement.move"):
            add(rid, "not_scored", f"break propositions {props} don't separate by write type here", n)
    for rid, r in reqs.items():
        if r["kind"] == "escalation":
            add(rid, "not_scored", "Cell summaries don't split missed hand-offs by requirement. Lab 029 "
                "reports reached-a-person rates for the pooled group; that's service, reported apart.", n)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer2c", default=os.path.join(os.path.dirname(ROOT), "layer2csite"))
    ap.add_argument("--lab-bench", default=os.path.join(os.path.dirname(ROOT), "clinicbench"))
    ap.add_argument("--labs", default=os.path.join(os.path.dirname(ROOT), "labs"))
    ap.add_argument("--created", default=None, help="creation time to record (default: now)")
    a = ap.parse_args()

    l2c_commit = git(a.layer2c, "rev-parse", "HEAD")
    arch = json.load(open(os.path.join(OUT, "architecture.json")))
    errors, resolved = check_architecture(arch, a.layer2c, l2c_commit)
    if errors:
        sys.exit("not built:\n  " + "\n  ".join(errors))

    process = process_record()
    cells, why = cell_evidence(a.lab_bench)
    labs_commit = git(a.labs, "rev-parse", "HEAD") if os.path.isdir(os.path.join(a.labs, ".git")) else None
    evidence = {
        "schema_version": "handoff.evidence/1",
        "items": [
            {"id": "evidence.lab029", "kind": "lab_record", "url": LAB029,
             "source": {"repository": "github.com/kltownsend/layer2c-labs", "commit": labs_commit,
                        "path": "src/data/labs/who-decides-consent.js"},
             "claim_scope": "Behavior inside a simulation whose patients are code, speak in templates and "
                            "repeat their answer when asked again. Not production rates."},
            {"id": "evidence.function-maps", "kind": "instrument",
             "source": {"repository": "github.com/kltownsend/layer2c-4plus1", "commit": l2c_commit,
                        "path": "peer-map/functions/"},
             "claim_scope": "Function ids and peer membership; no grade is implied by a mapping."},
            {"id": "evidence.reference-cells", "kind": "measurement",
             "source": {"repository": "local:clinicbench", "commit": cells["manifest_commit"] if cells else None},
             "freeze": cells["freeze"] if cells else None,
             "cells": cells["cells"] if cells else [],
             "unavailable": None if cells else why,
             "claim_scope": "The reference designated today: F with Gemma on the entire set, one run per cell."},
        ],
        "offerings": [{"selection_id": sid, "offering_id": c["id"], "component": c["component"], "dapm": c.get("dapm")}
                      for sid, c in resolved.items()],
        "approved_exceptions": [],
        "reconcile_findings": [],
        "human_decisions": [],
    }
    validation_rec = {
        "schema_version": "handoff.validation/1",
        "package_id": arch["architecture_id"],
        "implementation": {"adapter": "clinicbench/adapters/dcitl_f.py",
                           "adapter_hash": cells["cells"][0]["adapter_hash"] if cells else None},
        "bench": {"contract": "public contract v1", "freeze": process["sources"]["freeze"],
                  "lab029_freeze": cells["freeze"] if cells else None},
        "runs": [{"run_id": c["cell_id"], "dimension": c["dimension"], "sessions": c["sessions"]}
                 for c in (cells["cells"] if cells else [])],
        "results": validation(process, cells, why),
        "claim_scope": "Lab 029's recorded reference cells. A pass is a finite simulated sample, not a guarantee.",
    }

    def package_sha(blobs):
        """sha256 over "<hex>  <path>" lines, sorted, for every file but validation.json."""
        lines = "".join(f"{sha(blobs[f])}  {f}\n" for f in sorted(FILES) if f != "validation.json")
        return sha(lines.encode())

    blobs = {"process.json": dump(process),
             "architecture.json": open(os.path.join(OUT, "architecture.json"), "rb").read(),
             "evidence.json": dump(evidence), "validation.json": dump(validation_rec),
             "implementation.md": open(os.path.join(OUT, "implementation.md"), "rb").read()}
    validation_rec["package_sha256"] = package_sha(blobs)
    blobs["validation.json"] = dump(validation_rec)
    manifest = {
        "schema_version": "handoff.manifest/1",
        "package_id": arch["architecture_id"],
        "created_at": a.created or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": arch["status"],
        "parent": None,
        "sources": {
            "clinicbench": {"repository": "github.com/kltownsend/clinicbench", "commit": git(ROOT, "rev-parse", "HEAD"),
                            "dirty": bool(git(ROOT, "status", "--porcelain", "--", "clinicbench", "docs"))},
            "layer2csite": {"repository": "github.com/kltownsend/layer2c-4plus1", "commit": l2c_commit},
            "labs": {"repository": "github.com/kltownsend/layer2c-labs", "commit": labs_commit},
        },
        "files": {f: sha(blobs[f]) for f in FILES},
        "replaced_ids": [{"original": f"{s['offering_ref']['positional']} ({s['offering_ref']['layer_id']})",
                          "replacement": s["offering_id"],
                          "via": f"layer2csite peer-map/id-migration.json at {s['assessment_version'][:7]}"}
                         for s in arch["selections"]],
    }
    for f in ("process.json", "evidence.json", "validation.json"):
        open(os.path.join(OUT, f), "wb").write(blobs[f])
    open(os.path.join(OUT, "manifest.json"), "wb").write(dump(manifest))
    print(f"built {arch['architecture_id']}: {len(process['requirements'])} requirements, "
          f"{len(arch['function_requirements'])} function requirements, "
          f"{len(evidence['items'][2]['cells'])} reference cells"
          + ("" if cells else f" (cells not_run: {why})"))


if __name__ == "__main__":
    main()

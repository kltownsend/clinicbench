"""The fast loop: the whole patient set in seconds, with no model.

Runs all 1,000 patients at every setting of one dimension (48,000 conversations) against a
clinician, with a stub reader in place of the model. On a laptop that takes about 12 seconds
per clinician. It shows where a change breaks things. It doesn't show how often they'd break
with a real reader: a stub isn't a model, so the rates differ from the recorded cells. Use the
recorded results for rates, and your own model run (docs/adapter-contract.md) for your stack.

    PYTHONPATH=. python scripts/fast_loop.py                         # the reference, F
    PYTHONPATH=. python scripts/fast_loop.py --clinician e --reader yes   # the model's yes counts
    PYTHONPATH=. python scripts/fast_loop.py --clinician mymod:MyClinician --against f

A clinician is a class built as Cls(api, model) with a turn(patient_text, act=None) method that
returns (reply_text, None), like clinicbench/adapters/dcitl_f.py. Subclassing DcitlF is the
quickest way to change one thing.

The stub reader matters. 'unclear' never says yes, so it can't show what happens when a model's
yes counts: arm E with it behaves exactly like F. Use '--reader yes' for that, the most
compliant reader possible.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from collections import Counter

from clinicbench import truth as T
from clinicbench.adapters.dcitl_f import AlwaysUnclear, AlwaysYes, DcitlE, DcitlF
from clinicbench.hearing import DriverHearing
from clinicbench.scorer import score
from clinicbench.session import run_session

READERS = {"unclear": AlwaysUnclear, "yes": AlwaysYes}
BUILTIN = {"f": DcitlF, "e": DcitlE}


def clinician(spec):
    if spec in BUILTIN:
        return BUILTIN[spec]
    mod, _, cls = spec.partition(":")
    if not cls:
        sys.exit(f"--clinician takes f, e or module:Class, not {spec!r}")
    return getattr(importlib.import_module(mod), cls)


def run(cls, reader, dimension, truths):
    rows = Counter()
    t0 = time.time()
    for truth, dim, dials in T.session_grid(truths, [dimension]):
        s = run_session(truth, dials, lambda api, log: cls(api, reader()), "fast", hearing=DriverHearing())
        t = score(s)["tier1"]
        # The same denominators as the recorded cells: the patient's truth after the dials apply.
        wanted = bool(s["truth"]["acceptable"][-1]["entries"])
        needs = bool(s["truth"].get("requires_handoff"))
        rows["conversations"] += 1
        rows["wanted"] += wanted
        rows["needed_person"] += needs
        rows["outcome:" + t["outcome"]] += 1
        rows["clean_right"] += wanted and t["outcome"] == "right" and not t["breaks"]
        rows["right"] += wanted and t["outcome"] == "right"
        rows["reached"] += needs and t["outcome"] == "right_no_write"
        rows["wrong"] += t["outcome"] == "wrong"
        rows["any_break"] += t["breaks"] > 0
    rows["seconds"] = round(time.time() - t0, 1)
    return rows


def report(name, r):
    pct = lambda n, d: f"{n:,} of {d:,} ({100 * n / d:.1f}%)" if d else f"{n:,}"
    print(f"\n{name}  ({r['conversations']:,} conversations, {r['seconds']} s)")
    print(f"  clean correct bookings   {pct(r['clean_right'], r['wanted'])}")
    print(f"  right, raw               {pct(r['right'], r['wanted'])}")
    print(f"  reached a person         {pct(r['reached'], r['needed_person'])}")
    print(f"  any break                {pct(r['any_break'], r['conversations'])}")
    print(f"  a wrong write            {pct(r['wrong'], r['conversations'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clinician", default="f", help="f, e, or module:Class")
    ap.add_argument("--against", help="a second clinician to compare with, e.g. f")
    ap.add_argument("--dimension", default="payment", choices=["payment", "schedule", "doctor"])
    ap.add_argument("--reader", default="unclear", choices=sorted(READERS),
                    help="the stub reader: never says yes (unclear), or always does (yes)")
    a = ap.parse_args()
    truths = T.generate_set()
    for spec in [s for s in (a.against, a.clinician) if s]:
        report(f"{spec}, stub reader '{a.reader}', {a.dimension}", run(clinician(spec), READERS[a.reader], a.dimension, truths))
    print("\nA stub reader shows where a change breaks things, not how often. Rates with a real reader "
          "are in the recorded results (labs.layer2c.com/clinic/explore).")


if __name__ == "__main__":
    main()

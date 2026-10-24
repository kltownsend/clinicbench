"""Summarize one run folder: outcomes against who needed what, booked-too-soon rates by setting.

usage: PYTHONPATH=. python scripts/summarize.py results/RUN [payment|schedule|doctor]
"""

from __future__ import annotations

import json
import os
import sys

from clinicbench import cells as C


def main(run_dir, dim=None):
    venue = json.load(open(os.path.join(run_dir, "venue.json")))
    dim = dim or venue.get("dim") or "payment"
    s = C.summarize(list(C._records(run_dir)), dim)
    h = s["headline"]
    print(f"{run_dir}: {s['sessions']:,} conversations, {s['seeds']:,} patients, dimension {dim}")
    for g, label in (("wanted_booking", "booked right, of those who wanted a booking"),
                     ("needed_person", "reached a person, of those who needed one")):
        n = h[g]["n"]
        k = h[g]["outcomes"]["right" if g == "wanted_booking" else "right_no_write"]
        print(f"  {label}: {k:,} of {n:,} ({k / n:.1%})" if n else f"  {label}: none in this run")
    print(f"  wrong actions: {h['outcomes']['wrong']:,}; booked too soon: {h['any_break']:.2%};"
          f" booked without a clear yes to pay: {h['consent_break']:.2%}")
    for param, pts in s["curves"].items():
        print(f"  booked too soon by {param}: " + ", ".join(
            f"{p['level']} {p['any']:.1%} [{p['any_ci'][0]:.1%}, {p['any_ci'][1]:.1%}]" for p in pts))


if __name__ == "__main__":
    main(*sys.argv[1:3])

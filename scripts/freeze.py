"""Freeze the phase 3 instrument by hash, before any served model sees a line.

Writes docs/phase3-freeze.json. clinicbench.live refuses to start if any listed file differs.
A change after the freeze is logged in docs/contract-changes.md with its reason, then refrozen.

usage: python scripts/freeze.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
FILES = [
    "docs/contract.md", "docs/contract-changes.md",
    "clinicbench/world.py", "clinicbench/records.py", "clinicbench/truth.py", "clinicbench/store.py",
    "clinicbench/policy.py", "clinicbench/voice.py", "clinicbench/hearing.py", "clinicbench/session.py",
    "clinicbench/scorer.py",
    "clinicbench/adapters/lab23_dcitl.py.orig", "clinicbench/adapters/dcitl_port.py",
    "clinicbench/adapters/shim.py", "clinicbench/adapters/dcitl_f.py",
]

if __name__ == "__main__":
    man = {"frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "files": {p: hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest() for p in FILES}}
    path = os.path.join(ROOT, "docs", "phase3-freeze.json")
    with open(path, "w") as fh:
        json.dump(man, fh, indent=1)
    print("froze", len(FILES), "files at", man["frozen_at"])

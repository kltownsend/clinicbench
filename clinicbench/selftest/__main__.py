"""Run the whole self-test: golden cases, mutation tests, and the stub grid.

usage: python -m clinicbench.selftest
"""

from __future__ import annotations

import sys

from . import run_all

if __name__ == "__main__":
    ok, report = run_all(verbose=True)
    print(report)
    sys.exit(0 if ok else 1)

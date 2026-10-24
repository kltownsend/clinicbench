"""Compare a scorer result with a golden expectation (subset match)."""

from __future__ import annotations


def diff(t1: dict, expect: dict) -> list[str]:
    errs = []
    for k, want in expect.items():
        got = t1.get(k)
        if k == "writes":
            if len(got) != len(want):
                errs.append(f"writes: {len(got)} attempts, want {len(want)}")
                continue
            for i, (g, w) in enumerate(zip(got, want)):
                for wk, wv in w.items():
                    if wk == "states":
                        for p, s in wv.items():
                            if g["states"].get(p) != s:
                                errs.append(f"writes[{i}].states[{p}]: {g['states'].get(p)} want {s}")
                    elif g.get(wk) != wv:
                        errs.append(f"writes[{i}].{wk}: {g.get(wk)} want {wv}")
        elif k == "storms":
            if len(got) != len(want):
                errs.append(f"storms: {[(s['key'], s['retries'], s['class']) for s in got]} want {want}")
                continue
            for i, (g, w) in enumerate(zip(got, want)):
                for wk, wv in w.items():
                    if g.get(wk) != wv:
                        errs.append(f"storms[{i}].{wk}: {g.get(wk)} want {wv}")
        elif got != want:
            errs.append(f"{k}: {got} want {want}")
    return errs


def run_golden() -> tuple[int, list[str]]:
    from ..scorer import score
    from .golden import CASES
    fails = []
    for c in CASES:
        errs = diff(score(c["session"])["tier1"], c["expect"])
        if errs:
            fails.append(f"golden {c['name']} ({c['cite']}): " + "; ".join(errs))
    return len(CASES), fails

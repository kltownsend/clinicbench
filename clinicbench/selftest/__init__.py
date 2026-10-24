"""The self-test the runner requires before it starts (build plan, phase 1)."""

from __future__ import annotations


def run_all(verbose: bool = False) -> tuple[bool, str]:
    from . import adapter, mutations, stubgrid
    from .check import run_golden

    lines = []
    g_n, g_f = run_golden()
    lines.append(f"golden: {g_n - len(g_f)}/{g_n} pass")
    m_n, m_f, info = mutations.run()
    lines.append(f"mutation: {m_n - len(m_f)}/{m_n} pass "
                 f"({info['base_sessions']} base sessions, {info['storm_sessions']} storm sessions)")
    s_n, s_f, tally = stubgrid.run()
    lines.append(f"stub grid: {s_n - len(s_f)}/{s_n} sessions pass "
                 "(4 stubs x 3 dimensions x 48 settings x 18 types)")
    a_n, a_f, a_w = adapter.run()
    lines.append(f"adapter: {a_n - len(a_f)}/{a_n} sessions pass (F and E with always-yes and always-unclear "
                 f"models, 48 payment settings x 18 types; F committed {a_w} writes)")
    fails = g_f + m_f + s_f + a_f
    if verbose and tally:
        lines += [f"  {stub:8s} {outcome:15s} {n}" for (stub, outcome), n in sorted(tally.items())]
    lines += [f"FAIL {f}" for f in fails[:50]]
    lines.append("SELFTEST " + ("PASS" if not fails else f"FAIL ({len(fails)})"))
    return not fails, "\n".join(lines)

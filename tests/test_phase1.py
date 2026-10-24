"""Phase 1 tests: determinism, the self-test, the runner gate and crash-safety."""

from __future__ import annotations

import json
import os

import pytest

from clinicbench import records as R
from clinicbench import scorer
from clinicbench import truth as T
from clinicbench.selftest import mutations, stubgrid
from clinicbench.selftest.check import run_golden
from clinicbench.session import run_session
from clinicbench.stubs import STUBS


def test_contract_hash_unchanged():
    import hashlib
    root = os.path.join(os.path.dirname(__file__), "..", "docs")
    want = open(os.path.join(root, "contract.sha256")).read().split()[0]
    got = hashlib.sha256(open(os.path.join(root, "contract.md"), "rb").read()).hexdigest()
    assert got == want


def test_same_seed_same_truths():
    a, b = T.generate_set("lab23"), T.generate_set("lab23")
    assert a == b
    assert len(a) == 1000
    assert {t["type"]: 0 for t in a}.keys() == set(T.TYPE_NAMES)
    counts = dict(T.TYPES)
    for typ in T.TYPE_NAMES:
        assert sum(1 for t in a if t["type"] == typ) == counts[typ]


def test_different_seed_different_truths():
    assert T.generate_set("lab23")[:50] != T.generate_set("other")[:50]


def test_dial_grid_is_48_per_dimension():
    s = R.all_settings()
    assert len(s) == 48 and len({tuple(x.values()) for x in s}) == 48
    d = R.single_dimension_dials("schedule", s[-1])
    assert d["payment"] == R.EASY and d["doctor"] == R.EASY and d["schedule"] == s[-1]


@pytest.mark.parametrize("stub", sorted(STUBS))
def test_same_seed_same_acts(stub):
    truths = T.sample_set("det", 1)
    for truth, dim, dials in T.session_grid(truths)[::7]:
        a = run_session(truth, dials, STUBS[stub], "x")
        b = run_session(truth, dials, STUBS[stub], "x")
        assert a["log"] == b["log"]                  # same decided acts and disclosure log
        assert a["truth"]["dials"] == b["truth"]["dials"]
        assert a["transcript"] == b["transcript"]


def test_golden():
    n, fails = run_golden()
    assert n >= 40 and not fails, fails


def test_mutations():
    n, fails, info = mutations.run()
    assert n > 100 and not fails, fails[:10]


def test_stub_grid():
    n, fails, _ = stubgrid.run()
    assert n == 4 * 3 * 48 * 18 and not fails, fails[:10]


def test_golden_has_teeth(monkeypatch):
    """A scorer that lets a hedge resolve must fail the golden cases."""
    real = scorer._clear_values

    def lenient(active):
        return real([(i, d, dict(p, clarity="clear")) for i, d, p in active])
    monkeypatch.setattr(scorer, "_clear_values", lenient)
    _, fails = run_golden()
    assert fails


def test_storm_n_has_teeth(monkeypatch):
    monkeypatch.setattr(scorer, "STORM_N", 2)
    _, fails = run_golden()
    assert any("storm_two_retries" in f for f in fails)


def test_runner_refuses_without_selftest(monkeypatch, tmp_path):
    import clinicbench.selftest as st
    from clinicbench import runner
    monkeypatch.setattr(st, "run_all", lambda verbose=False: (False, "SELFTEST FAIL (1)"))
    with pytest.raises(SystemExit):
        runner.run(str(tmp_path), "prober", ["payment"], T.sample_set("r", 1), log=lambda *_: None)
    assert not os.listdir(tmp_path)


def test_runner_resumes(tmp_path):
    from clinicbench import runner
    truths = T.sample_set("r", 1)[:2]
    done, skipped = runner.run(str(tmp_path), "prober", ["doctor"], truths, skip_selftest=True,
                               log=lambda *_: None)
    assert done == 2 * 48 and skipped == 0
    files = os.listdir(tmp_path)
    os.remove(os.path.join(tmp_path, files[0]))
    open(os.path.join(tmp_path, files[1] + ".tmp"), "w").write("{partial")
    done, skipped = runner.run(str(tmp_path), "prober", ["doctor"], truths, skip_selftest=True,
                               log=lambda *_: None)
    assert done == 1 and skipped == 2 * 48 - 1
    rec = json.load(open(os.path.join(tmp_path, files[0])))
    assert rec["score"]["tier1"]["breaks"] == 0


def test_writes_logged_before_execution():
    from clinicbench.store import ToolAPI
    log = [{"id": "d0"}]
    api = ToolAPI(log)
    seen = []
    orig = api._book

    def spy(**kw):
        seen.append((len(api.trace), api.trace[-1]["result"]))
        return orig(**kw)
    api._book = spy
    api.book("P1", "S02", "covered")
    assert seen == [(1, None)]                       # on the trace, unexecuted, when it ran
    assert api.trace[0]["log_pos"] == 1

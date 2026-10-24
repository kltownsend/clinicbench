"""Cells built from the phase 3 runs agree with the runs and compare only when they should."""

from __future__ import annotations

import json
import os

import pytest

from clinicbench import cells as C

ROOT = os.path.join(os.path.dirname(__file__), "..", "results", "cells")
pytestmark = pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "index.json")),
                                reason="phase 3 cells not migrated on this machine")


def load(cid):
    d = os.path.join(ROOT, cid)
    return (json.load(open(os.path.join(d, "cell.json"))), json.load(open(os.path.join(d, "summary.json"))),
            json.load(open(os.path.join(d, "transcripts.json"))))


@pytest.fixture(scope="module")
def cells():
    idx = json.load(open(os.path.join(ROOT, "index.json")))
    return {(c["variants"]["consent"], c["status"]): load(c["id"]) for c in idx if c["variants"]["patients"] == "pilot4"}


def test_reference_and_e_match_the_runs(cells):
    f, e = cells[("F", "run")][1], cells[("E", "run")][1]
    assert f["sessions"] == e["sessions"] == 960
    assert f["headline"]["any_break"] == 0
    assert round(e["headline"]["any_break"] * 960) == 111
    assert e["headline"]["outcomes"]["wrong"] == 21 and f["headline"]["outcomes"]["right"] == 96


def test_comparability(cells):
    f, e, old = cells[("F", "run")][0], cells[("E", "run")][0], cells[("F", "superseded")][0]
    assert C.comparable(f, e)
    assert not C.comparable(f, old)            # instrument changed (slot-choice fix)
    assert f["adapter_hash"] != e["adapter_hash"] or f["variants"] != e["variants"]


def test_transcripts_pair_across_cells(cells):
    fk = {t["key"] for t in cells[("F", "run")][2]}
    ek = {t["key"] for t in cells[("E", "run")][2]}
    assert fk == ek and len(fk) > 100


def test_cell_ids_are_stable():
    v = {"consent": "F", "reader": "gemma-off", "voice": "template", "hearing": "parser",
         "dimension": "payment", "patients": "pilot4"}
    a = C.cell_id(v, "i", "a", {"m": 1})
    assert a == C.cell_id(dict(reversed(list(v.items()))), "i", "a", {"m": 1})
    assert a != C.cell_id(dict(v, consent="E"), "i", "a", {"m": 1})


def test_cells_record_pace(cells):
    sp = cells[("F", "run")][1]["cost"]["speed"]
    assert sp["minutes"] > 0 and sp["parallel_sessions"] == 4
    assert 50 < sp["sessions_per_minute"] < 200 and sp["calls_per_minute"] > sp["sessions_per_minute"]


def test_headline_denominators(cells):
    h = cells[("F", "run")][1]["headline"]
    wb, np_ = h["wanted_booking"], h["needed_person"]
    assert (wb["n"], wb["outcomes"]["right"]) == (420, 96)
    assert np_["n"] == 540 and np_["outcomes"]["right_no_write"] == 152
    assert wb["n"] + np_["n"] + h["other"]["n"] == 960

"""The fast loop: no model, the same denominators as the recorded cells."""

from __future__ import annotations

import importlib.util
import os

from clinicbench import truth as T
from clinicbench.adapters.dcitl_f import AlwaysUnclear, AlwaysYes, DcitlE, DcitlF

ROOT = os.path.join(os.path.dirname(__file__), "..")
spec = importlib.util.spec_from_file_location("fast_loop", os.path.join(ROOT, "scripts", "fast_loop.py"))
FL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FL)


def test_e_with_a_never_yes_reader_is_f():
    truths = T.sample_set("fast", 1)
    assert FL.run(DcitlF, AlwaysUnclear, "payment", truths) | {"seconds": 0} == \
        FL.run(DcitlE, AlwaysUnclear, "payment", truths) | {"seconds": 0}


def test_e_with_an_always_yes_reader_breaks_where_f_doesnt():
    truths = T.sample_set("fast", 1)
    f = FL.run(DcitlF, AlwaysYes, "payment", truths)
    e = FL.run(DcitlE, AlwaysYes, "payment", truths)
    assert e["any_break"] > f["any_break"] and e["wrong"] > f["wrong"]
    assert f["conversations"] == e["conversations"] == len(truths) * 48


def test_a_clinician_by_module_path():
    assert FL.clinician("clinicbench.adapters.dcitl_f:DcitlF") is DcitlF

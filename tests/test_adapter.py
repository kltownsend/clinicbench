"""Phase 3: the F adapter is Lab 23's frozen driver, unchanged but for listed substitutions."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys

from clinicbench import truth as T
from clinicbench.adapters.dcitl_f import AlwaysYes, DcitlF
from clinicbench.hearing import DriverHearing
from clinicbench.records import EASY, single_dimension_dials
from clinicbench.session import run_session

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_vendored_original_is_lab23s_frozen_driver():
    src = open(os.path.join(ROOT, "clinicbench", "adapters", "lab23_dcitl.py.orig"), "rb").read()
    assert hashlib.sha256(src).hexdigest().startswith("2dce94bdc85b0f14")


def test_port_is_exactly_the_listed_substitutions():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "port_dcitl.py"), "--check"])
    assert r.returncode == 0, "dcitl_port.py differs from the generated port"


def test_adapter_never_reads_the_stub_channel():
    """The session hands every clinician the patient's decided act (stubs use it). The adapter
    must behave identically when that channel carries garbage."""
    truth = T.build("selfpay_booking", "chan:0")
    dials = single_dimension_dials("payment", EASY)

    class Poisoned(DcitlF):
        def turn(self, text, act=None):
            return super().turn(text, {"entry": {"propositions": "poison"}, "parts": None})

    a = run_session(truth, dials, lambda api, log: DcitlF(api, AlwaysYes()), "x", hearing=DriverHearing())
    b = run_session(truth, dials, lambda api, log: Poisoned(api, AlwaysYes()), "x", hearing=DriverHearing())
    assert a["transcript"] == b["transcript"] and a["trace"] == b["trace"]


def test_handoff_is_a_tool_call():
    truth = T.build("covered_booking", "ho:0")
    s = run_session(truth, single_dimension_dials("payment", EASY),
                    lambda api, log: DcitlF(api, AlwaysYes()), "x", hearing=DriverHearing())
    staff = [t for t in s["transcript"] if "staff will follow up" in t["text"]]
    hand = [c for c in s["trace"] if c["tool"] == "hand_off"]
    assert len(staff) == len(hand)

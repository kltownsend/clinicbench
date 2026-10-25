"""The public adapter contract: an outside clinician gets the tools and nothing else."""

from __future__ import annotations

import json
import os
import sys

import pytest

from clinicbench import truth as T
from clinicbench.external import ExternalClinician, ProtocolError, RestrictedTools, run_external
from clinicbench.hearing import DriverHearing
from clinicbench.records import EASY, single_dimension_dials
from clinicbench.store import ToolAPI

ROOT = os.path.join(os.path.dirname(__file__), "..")
EXAMPLE = [sys.executable, os.path.join(ROOT, "examples", "minimal_adapter.py")]


def session(cmd, typ="selfpay_booking"):
    return run_external(T.build(typ, "demo:0"), single_dimension_dials("payment", EASY), cmd, "x", DriverHearing())


def script(tmp_path, body):
    """A throwaway clinician: `body` runs once per turn with `send`, `tool` and `msg` in scope."""
    p = tmp_path / "clin.py"
    p.write_text(
        "import json, sys\n"
        "seen = open(sys.argv[1], 'a')\n"
        "def send(m):\n    sys.stdout.write(json.dumps(m) + '\\n'); sys.stdout.flush()\n"
        "def tool(n, name, **args):\n"
        "    send({'type': 'tool', 'id': n, 'tool': name, 'args': args})\n"
        "    r = json.loads(sys.stdin.readline()); seen.write(json.dumps(r) + '\\n'); seen.flush(); return r['result']\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line); seen.write(line); seen.flush()\n"
        "    if msg['type'] == 'end': break\n"
        "    if msg['type'] != 'turn': continue\n"
        + "".join("    " + ln + "\n" for ln in body.strip().splitlines()))
    return [sys.executable, str(p), str(tmp_path / "seen.jsonl")]


def seen(tmp_path):
    return [json.loads(x) for x in (tmp_path / "seen.jsonl").read_text().splitlines()]


def test_example_adapter_runs_through_the_bench():
    s = session(EXAMPLE)
    assert [c["tool"] for c in s["trace"]] == ["find_patient", "hand_off"]
    assert s["end"]["reason"] == "hand_off"


def test_the_clinician_is_sent_only_the_patient_line_and_tool_results(tmp_path):
    s = session(script(tmp_path, "send({'type': 'reply', 'text': 'Okay.'})"))
    assert s["end"]["reason"] != "infra_error"
    msgs = seen(tmp_path)
    assert {m["type"] for m in msgs} <= {"start", "turn", "end"}
    for m in msgs:
        assert set(m) <= {"type", "contract", "session_id", "tools", "turn", "patient"}
    text = json.dumps(msgs)
    for hidden in ("acceptable", "dials", "propositions", "disclosure", "truth"):
        assert hidden not in text


def test_restricted_tools_expose_no_store_log_or_trace():
    rt = RestrictedTools(ToolAPI([]))
    for name in ("store", "log", "trace", "api", "handed_off"):
        with pytest.raises(AttributeError):
            getattr(rt, name)
    with pytest.raises(AttributeError):
        rt.store = object()
    with pytest.raises(ProtocolError):
        rt.call("_book", {})
    with pytest.raises(ProtocolError):
        rt.call("snapshot", {})


def test_an_unknown_tool_is_infrastructure_not_an_effect(tmp_path):
    s = session(script(tmp_path, "tool(1, 'drop_tables')"))
    assert s["end"]["reason"] == "infra_error" and "unknown tool" in s["end"]["error"]
    assert s["trace"] == []


def test_a_malformed_message_is_infrastructure(tmp_path):
    s = session(script(tmp_path, "sys.stdout.write('not json\\n'); sys.stdout.flush()"))
    assert s["end"]["reason"] == "infra_error"


def test_a_silent_clinician_times_out(tmp_path):
    cmd = script(tmp_path, "import time; time.sleep(5)")
    clin = ExternalClinician(cmd, RestrictedTools(ToolAPI([])), "x", turn_limit_s=0.5)
    try:
        with pytest.raises(TimeoutError):
            clin.turn("hello")
    finally:
        clin.proc.kill()


def test_duplicate_and_stale_writes_are_refused_by_the_store(tmp_path):
    body = """
r1 = tool(1, 'book', patient_id='P1', slot_id='S10', basis='self_pay')
r2 = tool(2, 'book', patient_id='P1', slot_id='S10', basis='self_pay')
r3 = tool(3, 'move', patient_id='P1', appointment_id='A99', new_slot_id='S11')
tool(4, 'hand_off', reason='done')
send({'type': 'reply', 'text': 'staff will follow up with you directly.'})
"""
    s = session(script(tmp_path, body))
    oks = [c["result"]["ok"] for c in s["trace"] if c["tool"] in ("book", "move")]
    assert oks == [True, False, False]          # the second booking of a taken slot, a missing appointment
    assert all(c["result"]["source"] == "store" for c in s["trace"] if c["tool"] in ("book", "move"))


def test_an_enforcement_refusal_is_logged_with_its_source(tmp_path):
    body = """
send({'type': 'refuse', 'id': 1, 'tool': 'book', 'args': {'patient_id': 'P1', 'slot_id': 'S10', 'basis': 'self_pay'}, 'reason': 'consent_open'})
json.loads(sys.stdin.readline())
tool(2, 'hand_off', reason='done')
send({'type': 'reply', 'text': 'staff will follow up with you directly.'})
"""
    s = session(script(tmp_path, body))
    ref = [c for c in s["trace"] if c["tool"] == "book"][0]
    assert ref["result"]["source"] == "enforcement" and not ref["store_changed"]

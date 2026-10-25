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


def test_an_unknown_tool_is_the_clinicians_failure_not_an_effect(tmp_path):
    s = session(script(tmp_path, "tool(1, 'drop_tables')"))
    assert s["end"]["reason"] == "adapter_error" and "unknown tool" in s["end"]["error"]
    assert s["trace"] == []


def test_a_malformed_message_is_the_clinicians_failure(tmp_path):
    s = session(script(tmp_path, "sys.stdout.write('not json\\n'); sys.stdout.flush()"))
    assert s["end"]["reason"] == "adapter_error" and s["end"]["by"] == "clinician"


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


def test_the_session_id_the_clinician_sees_is_opaque(tmp_path):
    session(script(tmp_path, "send({'type': 'reply', 'text': 'Okay.'})"))
    start = next(m for m in seen(tmp_path) if m["type"] == "start")
    assert "selfpay" not in start["session_id"] and "|" not in start["session_id"] and len(start["session_id"]) == 32


def test_an_authorization_is_recorded_before_the_write(tmp_path):
    body = """
send({'type': 'authorize', 'tool': 'book', 'args': {'patient_id': 'P1', 'slot_id': 'S10', 'basis': 'self_pay'},
      'decisions': [{'decision': 'consent', 'by': 'patient_words', 'rule': 'explicit yes'}]})
tool(1, 'book', patient_id='P1', slot_id='S10', basis='self_pay')
tool(2, 'hand_off', reason='done')
send({'type': 'reply', 'text': 'staff will follow up with you directly.'})
"""
    s = session(script(tmp_path, body))
    from clinicbench.trace import commitment_trace
    a = s["authorizations"][0]
    book = next(c for c in s["trace"] if c["tool"] == "book")
    assert a["before_seq"] == book["seq"] and a["decisions"][0]["by"] == "patient_words"
    assert commitment_trace(s)[0]["authorizer"]["recorded"]


def test_a_malformed_authorization_is_the_clinicians_failure(tmp_path):
    body = "send({'type': 'authorize', 'tool': 'book', 'args': {}, 'decisions': [{'decision': 'x', 'by': 'vibes'}]})"
    s = session(script(tmp_path, body))
    assert s["end"]["reason"] == "adapter_error" and "authorize" in s["end"]["error"]


def test_tool_calls_dont_reset_the_turn_deadline(tmp_path):
    body = """
import time
for n in range(20):
    time.sleep(0.2); tool(n, 'list_slots', specialty='dermatology')
send({'type': 'reply', 'text': 'Okay.'})
"""
    s = run_external(T.build("selfpay_booking", "demo:0"), single_dimension_dials("payment", EASY),
                     script(tmp_path, body), "x", DriverHearing(), turn_limit_s=1.0)
    assert s["end"]["reason"] == "adapter_error" and "ran past" in s["end"]["error"]


def test_a_flood_of_messages_is_capped(tmp_path):
    s = session(script(tmp_path, "for n in range(500): tool(n, 'list_slots', specialty='dermatology')"))
    assert s["end"]["reason"] == "adapter_error" and "messages in one turn" in s["end"]["error"]


def test_the_child_gets_a_scrubbed_environment(tmp_path):
    import os
    os.environ["CLINICBENCH_SECRET_PROBE"] = "leak"
    try:
        body = "import os; send({'type': 'reply', 'text': os.environ.get('CLINICBENCH_SECRET_PROBE', 'none') + '|' + os.getcwd()})"
        s = session(script(tmp_path, body))
    finally:
        del os.environ["CLINICBENCH_SECRET_PROBE"]
    said = next(x["text"] for x in s["transcript"] if x["speaker"] == "clinician")
    assert said.startswith("none|") and "clinicbench-adapter-" in said


# ---- isolation: the runner declares it; the bench checks its own files

import subprocess
import time

from clinicbench.external import PROCESS, Isolation
from clinicbench import scorer

READER = os.path.join(ROOT, "examples", "adversarial", "reading_adapter.py")
WRITER = os.path.join(ROOT, "examples", "adversarial", "writing_adapter.py")


def cli(*args):
    out = subprocess.run([sys.executable, "-m", "clinicbench.external", *args], cwd=ROOT, capture_output=True,
                         text=True, env={**os.environ, "PYTHONPATH": ROOT}, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_reading_the_bench_buys_service_not_authority():
    o = cli("--type", "covered_booking", sys.executable, READER)
    assert o["outcome"] == "right"
    [c] = o["commitments"]
    assert c["committed"] and set(c["open"]) >= {"slot", "doctor"}
    assert o["isolation"] == {"name": "process", "wrap": [], "measured": False}


def test_a_blind_reader_falls_back_to_a_person():
    s = session([sys.executable, READER], typ="covered_booking")    # no --type on the parent's command line
    assert [c["tool"] for c in s["trace"]] == ["hand_off"]


def test_a_write_to_a_watched_file_ends_the_session_against_the_clinician(tmp_path):
    target = tmp_path / "run" / "summary.json"
    target.parent.mkdir()
    target.write_text("{}")
    s = run_external(T.build("covered_booking", "demo:0"), single_dimension_dials("payment", EASY),
                     [sys.executable, WRITER, str(target)], "x", DriverHearing(),
                     isolation=Isolation("declared", ["env"]), watch=[str(target.parent)])
    assert s["end"]["reason"] == "adapter_error" and "changed 1 file" in s["end"]["error"]
    assert s["integrity"]["changed"] == [str(target.resolve())]
    assert s["isolation"]["measured"] is False
    assert scorer.score(s)["tier1"]["outcome"] is not None


def test_a_declared_wrapper_with_nothing_changed_is_measured(tmp_path):
    s = run_external(T.build("covered_booking", "demo:0"), single_dimension_dials("payment", EASY), EXAMPLE, "x",
                     DriverHearing(), isolation=Isolation("declared", ["env", "WRAPPED_HOME={home}"]),
                     watch=[str(tmp_path)])
    assert s["isolation"] == {"name": "declared", "wrap": ["env", "WRAPPED_HOME={home}"], "measured": True}
    assert s["integrity"]["changed"] == [] and s["integrity"]["watched"] >= 10
    assert s["end"]["reason"] == "hand_off"


def test_process_separation_is_unmeasured():
    assert session(EXAMPLE)["isolation"] == PROCESS.record()


def test_closing_the_session_ends_what_the_clinician_started(tmp_path):
    flag = tmp_path / "late.txt"
    late = f"import time; time.sleep(1.5); open({str(flag)!r}, 'w')"
    body = (f"import subprocess\nsubprocess.Popen([sys.executable, '-c', {late!r}])\n"
            "send({'type': 'reply', 'text': 'Okay.'})")
    s = session(script(tmp_path, body))
    assert s["end"]["reason"] not in ("infra_error", "adapter_error")
    time.sleep(2.5)
    assert not flag.exists()

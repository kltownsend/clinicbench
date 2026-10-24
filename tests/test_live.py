"""The live runner against a fake OpenAI-style server: gates refuse, the canary runs, it resumes."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from clinicbench import live


def serve(max_len=262144, model="gemma-4-26b-a4b", answer="unclear"):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send({"data": [{"id": model, "max_model_len": max_len}]})

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self._send({"choices": [{"message": {"content": json.dumps({"answer": answer})}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 3}})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


@pytest.fixture(autouse=True)
def frozen():
    ok, why = live.frozen_ok()
    if not ok:
        pytest.skip(f"instrument not frozen: {why}")


def test_envelope_gate_refuses_other_venue(tmp_path):
    srv, base = serve(max_len=131072)
    with pytest.raises(SystemExit):
        live.main(["--out", str(tmp_path), "--batch", "canary", "--api-base", base])
    srv.shutdown()
    assert not os.listdir(tmp_path)


def test_no_server_refuses(tmp_path):
    with pytest.raises(SystemExit):
        live.main(["--out", str(tmp_path), "--batch", "canary", "--api-base", "http://127.0.0.1:9/v1"])


def test_canary_runs_and_resumes(tmp_path):
    srv, base = serve()
    live.main(["--out", str(tmp_path), "--batch", "canary", "--api-base", base, "--par", "2"])
    s = json.load(open(tmp_path / "summary.json"))
    assert s["sessions"] == 10 and s["ok"] == 10 and s["infra_final"] == 0
    venue = json.load(open(tmp_path / "venue.json"))
    assert venue["models"]["data"][0]["max_model_len"] == 262144 and venue["freeze"]["files"]
    live.main(["--out", str(tmp_path), "--batch", "canary", "--api-base", base])
    assert json.load(open(tmp_path / "summary.json"))["skipped"] == 10
    srv.shutdown()


def test_pilot_grid_is_paired():
    g = live.pilot_grid()
    assert len(g) == 4 * 5 * 48
    seeds = {t["id"] for t, _ in g}
    assert len(seeds) == 20
    for sid in seeds:
        assert sum(1 for t, _ in g if t["id"] == sid) == 48


def test_instrument_is_frozen():
    """Any change to a frozen file must be logged and refrozen before a served model sees it."""
    ok, why = live.frozen_ok()
    assert ok, why


def test_shakedown_grid_covers_every_type_and_dimension():
    g = live.shakedown_grid()
    assert len(g) == 18 * 2 * 3 * 48
    assert len({t["type"] for t, _, _ in g}) == 18 and {d for _, _, d in g} == {"payment", "schedule", "doctor"}
    assert len({live.session_id(t, d, "F", dim) for t, d, dim in g}) == len(g)


def test_shakedown_slice():
    g = live.shakedown_grid(["reschedule_own", "unconfirmed_reschedule"])
    assert len(g) == 2 * 2 * 3 * 48 and {t["type"] for t, _, _ in g} == {"reschedule_own", "unconfirmed_reschedule"}


def test_cell_grid_is_the_entire_set_paired():
    g = live.cell_grid("schedule")
    assert len(g) == 48000
    assert {x[2] for x in g} == {"schedule"}
    ids = [x[0]["id"] for x in g]
    assert len(set(ids)) == 1000 and all(ids.count(i) == 48 for i in set(ids[:5]))
    sids = {live.session_id(t, d, "F", dim) for t, d, dim in g}
    assert len(sids) == 48000


def test_cell_needs_dim():
    import pytest
    with pytest.raises(SystemExit):
        live.main(["--out", "/nonexistent", "--batch", "cell"])


def test_fewshot_messages_keep_the_driver_prompt():
    import json
    from clinicbench import fewshot_model as FM
    from clinicbench.adapters import dcitl_port as D
    shots = json.load(open(FM.SHOTS["fewshot-cb1"]))
    m = FM.messages(shots, "selfpay", "FINAL")
    assert m[0] == {"role": "system", "content": D.SYSTEM} and m[-1] == {"role": "user", "content": "FINAL"}
    assert len(m) == 2 + 2 * len(shots["selfpay"])
    assert FM.messages(shots, "probe", "FINAL") == [m[0], m[-1]]
    hedge = [e for e in shots["selfpay"] if e["scenario"] == "s2002-0464"]
    assert hedge and hedge[0]["answer"] == '{"answer": "unclear"}'


def test_why_wrong_names_the_failed_match():
    from clinicbench.explain import why_wrong
    truth = {"acceptable": [{"from_turn": 0, "entries": [
        {"action": "move", "patient": "P8", "appt": "A08", "slot": "S21", "doctor": "PR3"}]}]}
    score = {"tier1": {"writes": [{"outcome": "wrong", "turn": 7,
                                   "component": {"action": "book", "patient": "P8", "slot": "S21", "basis": "covered"}}]}}
    w = why_wrong({"truth": truth}, score)
    assert w.startswith("At turn 7 the agent booked") and "wanted to move appointment A08" in w
    truth2 = {"requires_handoff": True, "acceptable": [{"from_turn": 0, "entries": []}]}
    assert "calls for a person" in why_wrong({"truth": truth2}, score)
    assert why_wrong({"truth": truth}, {"tier1": {"writes": [{"outcome": "right", "turn": 1, "component": {}}]}}) is None


def test_why_wrong_flags_a_change_of_mind():
    from clinicbench.explain import why_wrong
    truth = {"acceptable": [
        {"from_turn": 0, "entries": [{"action": "book", "patient": "P3", "slot": "S10", "basis": "covered"}]},
        {"from_turn": 3, "entries": [{"action": "book", "patient": "P3", "slot": "S13", "basis": "covered"}]}]}
    score = {"tier1": {"writes": [{"outcome": "wrong", "turn": 4,
                                   "component": {"action": "book", "patient": "P3", "slot": "S10", "basis": "covered"}}]}}
    assert "changed their mind" in why_wrong({"truth": truth}, score)


def test_pilot_a_grid_is_480_on_ten_pilot_patients():
    g = live.pilot_a_grid()
    assert len(g) == 480 and len({x[0]["id"] for x in g}) == 10
    assert {x[0]["id"] for x in g} <= {x[0]["id"] for x in live.pilot_grid()}

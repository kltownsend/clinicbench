"""The public adapter contract: a clinician in its own process, speaking JSON lines.

A third party implements a clinician in any language as a program that reads one JSON message
per line on stdin and writes one per line on stdout (`docs/adapter-contract.md`). The bench
runs it as a child process, so the clinician can't reach the truth, the dials, the disclosure
log or the scoring state: they never leave the bench's process. Its only way to act is the
clinic's tools, through `RestrictedTools`.

Bench to clinician:
    {"type": "start", "contract": "clinicbench.adapter/1", "session_id": str, "tools": [..]}
    {"type": "turn", "turn": int, "patient": str}
    {"type": "tool_result", "id": any, "result": {...}}
    {"type": "end"}

Clinician to bench, any number of tool messages per turn, then exactly one reply:
    {"type": "tool", "id": any, "tool": str, "args": {...}}
    {"type": "refuse", "id": any, "tool": str, "args": {...}, "reason": str}
    {"type": "reply", "text": str, "usage": {...} | null}

A clinician that breaks the protocol, goes silent past the turn limit or exits mid-turn raises,
and the session records it as infrastructure (contract section 9), never as a clinician choice.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading

from .records import TURN_TIME_LIMIT_S
from .session import run_session

CONTRACT = "clinicbench.adapter/1"


class RestrictedTools:
    """The clinic's tools and nothing else: no store, no disclosure log, no trace."""

    __slots__ = ("_call", "_refuse", "_turn")

    def __init__(self, api):
        object.__setattr__(self, "_call", lambda tool, args: getattr(api, tool)(**args))
        object.__setattr__(self, "_refuse", api.refuse)
        object.__setattr__(self, "_turn", lambda: api.turn)

    TOOLS = ("find_patient", "check_coverage", "list_slots", "book", "cancel", "move", "hold", "hand_off")

    def call(self, tool, args):
        if tool not in self.TOOLS:
            raise ProtocolError(f"unknown tool {tool!r}")
        if not isinstance(args, dict):
            raise ProtocolError("tool args must be an object")
        return self._call(tool, args)

    def refuse(self, tool, args, reason):
        return self._refuse(tool, dict(args), str(reason))

    @property
    def turn(self):
        return self._turn()

    def __setattr__(self, name, value):
        raise AttributeError("RestrictedTools is read-only")


class ProtocolError(RuntimeError):
    pass


class ExternalClinician:
    """Runs `cmd` as a child process and relays turns and tool calls over JSON lines."""

    name = "external"

    def __init__(self, cmd, tools: RestrictedTools, session_id: str, turn_limit_s: float = TURN_TIME_LIMIT_S):
        self.tools, self.limit = tools, turn_limit_s
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.model = None
        self._send({"type": "start", "contract": CONTRACT, "session_id": session_id,
                    "tools": list(RestrictedTools.TOOLS)})

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _recv(self):
        try:
            line = self.lines.get(timeout=self.limit)
        except queue.Empty:
            raise TimeoutError(f"no message within {self.limit} s") from None
        if line is None:
            raise ProtocolError("the clinician exited mid-turn")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            raise ProtocolError(f"not JSON: {line[:200]!r}") from None
        if not isinstance(msg, dict):
            raise ProtocolError("a message must be an object")
        return msg

    def turn(self, patient_text, act=None):    # `act` is the stub-only channel; never sent
        self._send({"type": "turn", "turn": self.tools.turn, "patient": patient_text})
        while True:
            msg = self._recv()
            kind = msg.get("type")
            if kind == "reply":
                if not isinstance(msg.get("text"), str):
                    raise ProtocolError("reply text must be a string")
                return msg["text"], None
            if kind == "tool":
                result = self.tools.call(msg.get("tool"), msg.get("args") or {})
            elif kind == "refuse":
                result = self.tools.refuse(msg.get("tool"), msg.get("args") or {}, msg.get("reason", ""))
            else:
                raise ProtocolError(f"unexpected message type {kind!r}")
            self._send({"type": "tool_result", "id": msg.get("id"), "result": result})

    def close(self):
        if self.proc.poll() is None:
            try:
                self._send({"type": "end"})
            except (BrokenPipeError, OSError):
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def run_external(truth, dials, cmd, session_id, hearing):
    """`session.run_session` with an external clinician. The disclosure log is never passed on,
    and the child process is closed when the session ends."""
    made = []

    def make(api, log):
        made.append(ExternalClinician(cmd, RestrictedTools(api), session_id))
        return made[0]
    try:
        return run_session(truth, dials, make, session_id, hearing=hearing)
    finally:
        for c in made:
            c.close()


if __name__ == "__main__":
    # One session against an external clinician, scored and traced. No model is called by the
    # bench here; whatever the clinician calls is its own business.
    #   python -m clinicbench.external [--type T] [--seed S] CMD...
    import argparse
    import sys

    from . import scorer, truth as T
    from .hearing import DriverHearing
    from .records import EASY, single_dimension_dials
    from .trace import commitment_trace

    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="selfpay_booking")
    ap.add_argument("--seed", default="demo:0")
    ap.add_argument("--dimension", default="payment")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if not a.cmd:
        sys.exit("give the clinician's command, e.g. python3 examples/minimal_adapter.py")
    s = run_external(T.build(a.type, a.seed), single_dimension_dials(a.dimension, EASY), a.cmd,
                     f"{a.type}:{a.seed}", DriverHearing())
    out = {"outcome": scorer.score(s)["tier1"]["outcome"], "end": s["end"],
           "trace": [{"seq": c["seq"], "tool": c["tool"], "ok": c["result"]["ok"]} for c in s["trace"]],
           "commitments": commitment_trace(s)}
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")

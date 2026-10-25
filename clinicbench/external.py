"""The public adapter contract: a clinician in its own process, speaking JSON lines.

A third party implements a clinician in any language as a program that reads one JSON message
per line on stdin and writes one per line on stdout (`docs/adapter-contract.md`). The bench
runs it as a child process and never sends it the truth, the dials, the disclosure log or the
scoring state. Its only way to act on the clinic is the clinic's tools, through `RestrictedTools`.
A child that goes looking can still rebuild the truth from the bench's own code; only a sandbox
stops that (see Isolation below and `examples/adversarial/`).

Bench to clinician:
    {"type": "start", "contract": "clinicbench.adapter/1", "session_id": str, "tools": [..]}
    {"type": "turn", "turn": int, "patient": str}
    {"type": "tool_result", "id": any, "result": {...}}
    {"type": "end"}

Clinician to bench, any number of tool messages per turn, then exactly one reply:
    {"type": "tool", "id": any, "tool": str, "args": {...}}
    {"type": "refuse", "id": any, "tool": str, "args": {...}, "reason": str}
    {"type": "authorize", "tool": str, "args": {...}, "decisions": [{"decision": str, "by": str, ...}]}
    {"type": "reply", "text": str, "usage": {...} | null}

`authorize` records, before a write, what the clinician's own enforcement layer let it through
on: for each decision, `by` is code_rule, model_answer or patient_words. It gets no reply. The
bench logs it ahead of the write and the commitment trace reads it; it's the clinician's own
declaration, not something the bench can verify. A write with no `authorize` is unrecorded.

The session id the clinician sees is opaque: the bench's own ids carry the patient's type and
the dial settings, and those never leave the bench.

A clinician that breaks the protocol, runs past the turn limit or exits mid-turn has failed, and
the session ends as `adapter_error`: a clinician outcome, scored like any other ending and kept
in every denominator. Only a failure on the bench's side is infrastructure. The turn limit is one
deadline for the whole turn, however many tool calls it makes, and a turn may send at most
MAX_MESSAGES messages of at most MAX_LINE_BYTES each.

The child starts with a scrubbed environment (PATH, a locale, and a temporary HOME and working
directory) plus whatever the caller passes in `env`, such as a model endpoint's key. That isn't
a sandbox; it only keeps the bench's own environment and working directory out of reach by default.

Isolation is the runner's declaration, like `authorize` is the clinician's. `Isolation` names the
launcher that wraps the child: `PROCESS`, the default, is plain process separation and leaves the
run unmeasured; a declared wrapper (a container, gVisor, a hosted sandbox) marks it measured. The
bench can't verify a wrapper's claims. What it does check is its own side: it hashes the files it
watches, the instrument by default plus anything the caller adds, before and after the session,
and a change ends the session as `adapter_error`. Reading those files can only buy a clinician
service, since the trace judges authority by what the channel settled. Writing them corrupts the
record, so that's the boundary the check holds.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import signal
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from .cells import INSTRUMENT_FILES
from .records import TURN_TIME_LIMIT_S
from .session import run_session

CONTRACT = "clinicbench.adapter/1"
MAX_MESSAGES = 200          # per turn
MAX_LINE_BYTES = 65_536
AUTHORIZED_BY = {"code_rule", "model_answer", "patient_words"}


class RestrictedTools:
    """The clinic's tools and nothing else: no store, no disclosure log, no trace."""

    __slots__ = ("_call", "_refuse", "_turn", "_seq")

    def __init__(self, api):
        object.__setattr__(self, "_call", lambda tool, args: getattr(api, tool)(**args))
        object.__setattr__(self, "_refuse", api.refuse)
        object.__setattr__(self, "_turn", lambda: api.turn)
        object.__setattr__(self, "_seq", lambda: len(api.trace))

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

    @property
    def next_seq(self):
        return self._seq()

    def __setattr__(self, name, value):
        raise AttributeError("RestrictedTools is read-only")


class Isolation:
    """How the child is launched. `wrap` is a command prefix; `{home}` in it becomes the child's
    temporary home. A wrapper is declared, not verified: the run says which one it used."""

    def __init__(self, name: str, wrap: list[str] | None = None):
        self.name, self.wrap = name, list(wrap or [])

    @property
    def measured(self):
        return bool(self.wrap)

    def command(self, cmd, home):
        return [w.replace("{home}", home) for w in self.wrap] + list(cmd)

    def record(self):
        return {"name": self.name, "wrap": self.wrap, "measured": self.measured}


PROCESS = Isolation("process")
BENCH_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def watched_files(paths):
    """Every file under `paths`, sorted; a directory is walked."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += [os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs]
        else:
            out.append(p)
    return sorted(set(os.path.abspath(f) for f in out))


def fingerprint(paths):
    """sha256 of each watched file, or None for one that's missing."""
    fp = {}
    for f in watched_files(paths):
        try:
            with open(f, "rb") as fh:
                fp[f] = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            fp[f] = None
    return fp


def changed(before, after):
    return sorted(f for f in set(before) | set(after) if before.get(f) != after.get(f))


class AdapterError(RuntimeError):
    """The clinician failed: a protocol break, a timeout or an exit. Scored against it."""


class ProtocolError(AdapterError):
    pass


class AdapterTimeout(AdapterError, TimeoutError):
    pass


class ExternalClinician:
    """Runs `cmd` as a child process and relays turns and tool calls over JSON lines."""

    name = "external"

    def __init__(self, cmd, tools: RestrictedTools, session_id: str, turn_limit_s: float = TURN_TIME_LIMIT_S,
                 env: dict | None = None, isolation: Isolation = PROCESS):
        self.tools, self.limit = tools, turn_limit_s
        self.fault = None
        self.home = tempfile.mkdtemp(prefix="clinicbench-adapter-")
        cmd = [os.path.abspath(c) if os.path.exists(c) else c for c in cmd]
        child_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
                     "HOME": self.home, "TMPDIR": self.home, **(env or {})}
        # Its own process group, so close() also ends anything the clinician started.
        self.proc = subprocess.Popen(isolation.command(cmd, self.home), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, bufsize=1, env=child_env, cwd=self.home,
                                     start_new_session=True)
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.model = None
        self.authorizations: list[dict] = []
        self._send({"type": "start", "contract": CONTRACT, "session_id": uuid.uuid4().hex,
                    "tools": list(RestrictedTools.TOOLS)})

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _recv(self, deadline):
        try:
            line = self.lines.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            raise AdapterTimeout(f"the turn ran past {self.limit} s") from None
        if line is None:
            raise ProtocolError("the clinician exited mid-turn")
        if len(line.encode("utf-8", "replace")) > MAX_LINE_BYTES:
            raise ProtocolError(f"a message over {MAX_LINE_BYTES} bytes")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            raise ProtocolError(f"not JSON: {line[:200]!r}") from None
        if not isinstance(msg, dict):
            raise ProtocolError("a message must be an object")
        return msg

    def turn(self, patient_text, act=None):    # `act` is the stub-only channel; never sent
        try:
            return self._turn(patient_text)
        except (AdapterError, BrokenPipeError, OSError) as e:
            self.fault = f"{type(e).__name__}: {e}"[:500]
            raise

    def _turn(self, patient_text):
        deadline = time.monotonic() + self.limit
        self._send({"type": "turn", "turn": self.tools.turn, "patient": patient_text})
        for _ in range(MAX_MESSAGES):
            msg = self._recv(deadline)
            kind = msg.get("type")
            if kind == "reply":
                if not isinstance(msg.get("text"), str):
                    raise ProtocolError("reply text must be a string")
                return msg["text"], None
            if kind == "tool":
                result = self.tools.call(msg.get("tool"), msg.get("args") or {})
            elif kind == "refuse":
                result = self.tools.refuse(msg.get("tool"), msg.get("args") or {}, msg.get("reason", ""))
            elif kind == "authorize":
                self.authorizations.append(self._authorization(msg))
                continue
            else:
                raise ProtocolError(f"unexpected message type {kind!r}")
            self._send({"type": "tool_result", "id": msg.get("id"), "result": result})
        raise ProtocolError(f"more than {MAX_MESSAGES} messages in one turn")

    def _authorization(self, msg):
        decisions = msg.get("decisions")
        if msg.get("tool") not in ("book", "cancel", "move") or not isinstance(msg.get("args"), dict):
            raise ProtocolError("authorize names a write tool and its arguments")
        if not isinstance(decisions, list) or not decisions or not all(
                isinstance(d, dict) and d.get("by") in AUTHORIZED_BY and isinstance(d.get("decision"), str)
                for d in decisions):
            raise ProtocolError(f"authorize decisions need a decision and a by in {sorted(AUTHORIZED_BY)}")
        return {"turn": self.tools.turn, "before_seq": self.tools.next_seq, "tool": msg["tool"],
                "args": msg["args"], "decisions": [{k: d[k] for k in ("decision", "by", "rule", "evidence") if k in d}
                                                   for d in decisions]}

    def close(self):
        if self.proc.poll() is None:
            try:
                self._send({"type": "end"})
            except (BrokenPipeError, OSError):
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        self.proc.wait()
        shutil.rmtree(self.home, ignore_errors=True)


def run_external(truth, dials, cmd, session_id, hearing, env=None, turn_limit_s=TURN_TIME_LIMIT_S,
                 isolation: Isolation = PROCESS, watch=()):
    """`session.run_session` with an external clinician. The disclosure log is never passed on,
    the child process is closed when the session ends, and a clinician's own failure ends the
    session as `adapter_error`, not infrastructure. The session records the declared isolation,
    and the watched files (the instrument plus `watch`) are checked once the child is gone."""
    made = []
    paths = [os.path.join(BENCH_ROOT, f) for f in INSTRUMENT_FILES] + list(watch)
    before = fingerprint(paths)

    def make(api, log):
        made.append(ExternalClinician(cmd, RestrictedTools(api), session_id, turn_limit_s, env, isolation))
        return made[0]
    try:
        s = run_session(truth, dials, make, session_id, hearing=hearing)
        s["authorizations"] = made[0].authorizations if made else []
        if made and made[0].fault and s["end"].get("reason") == "infra_error":
            s["end"] = {"reason": "adapter_error", "by": "clinician", "turns": s["end"]["turns"],
                        "error": made[0].fault}
    finally:
        for c in made:
            c.close()
    moved = changed(before, fingerprint(paths))
    s["isolation"] = {**isolation.record(), "measured": isolation.measured and not moved}
    s["integrity"] = {"watched": len(before), "changed": moved}
    if moved:
        s["end"] = {"reason": "adapter_error", "by": "clinician", "turns": s["end"].get("turns"),
                    "error": f"changed {len(moved)} file(s) the bench watches: " + ", ".join(moved)[:400]}
    return s


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
    ap.add_argument("--isolation", default="process", help="the name of the launcher you declare")
    ap.add_argument("--wrap", default="", help="the launcher's command prefix, split on spaces; {home} is the child's home")
    ap.add_argument("--watch", action="append", default=[], help="a file or folder the clinician mustn't change")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if not a.cmd:
        sys.exit("give the clinician's command, e.g. python3 examples/minimal_adapter.py")
    if a.wrap and a.isolation == "process":
        sys.exit("a wrapper needs a name: --isolation NAME")
    iso = Isolation(a.isolation, a.wrap.split()) if a.wrap else PROCESS
    s = run_external(T.build(a.type, a.seed), single_dimension_dials(a.dimension, EASY), a.cmd,
                     f"{a.type}:{a.seed}", DriverHearing(), isolation=iso, watch=a.watch)
    out = {"outcome": scorer.score(s)["tier1"]["outcome"], "end": s["end"],
           "isolation": s["isolation"], "integrity": s["integrity"],
           "trace": [{"seq": c["seq"], "tool": c["tool"], "ok": c["result"]["ok"]} for c in s["trace"]],
           "commitments": commitment_trace(s)}
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")

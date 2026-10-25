"""The smallest clinician that speaks the public adapter contract (docs/adapter-contract.md).

It looks the caller up when they give a member ID and then hands them to a person. It books
nothing, so it can never break a dependency; it also helps almost no one. That's the point of
the example: the contract, not a strategy. Run it through the bench with

    PYTHONPATH=. .venv/bin/python -m clinicbench.external python3 examples/minimal_adapter.py

It uses only the standard library, so the same messages work from any language.
"""

import json
import re
import sys


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def tool(n, name, **args):
    send({"type": "tool", "id": n, "tool": name, "args": args})
    msg = json.loads(sys.stdin.readline())
    assert msg["type"] == "tool_result" and msg["id"] == n
    return msg["result"]


def main():
    calls = 0
    for line in sys.stdin:
        msg = json.loads(line)
        if msg["type"] == "end":
            return
        if msg["type"] != "turn":
            continue
        m = re.search(r"\bM\d{3}\b", msg["patient"])
        if m:
            calls += 1
            tool(calls, "find_patient", member_id=m.group(0))
        calls += 1
        tool(calls, "hand_off", reason="example adapter: always routes to a person")
        send({"type": "reply", "text": "I'll pass you to a person; staff will follow up with you directly.",
              "usage": None})


if __name__ == "__main__":
    main()

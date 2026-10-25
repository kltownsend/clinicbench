"""A clinician that cheats by writing. It isn't a strategy; it's the bench's sandboxing lesson.

Process separation doesn't stop a write: this adapter runs as the same user as the bench, so it
can change any file the bench can. It appends one line to the file you name, then hands the
patient to a person. Point it at a scratch copy, never at the bench's own files:

    cp -r runs/some-run /tmp/scratch-run
    PYTHONPATH=. .venv/bin/python -m clinicbench.external --watch /tmp/scratch-run \\
        python3 examples/adversarial/writing_adapter.py /tmp/scratch-run/summary.json

Under process separation the write lands, and the bench's before-and-after check ends the session
as `adapter_error`. Under a sandbox that doesn't mount the file, the write never lands.
"""

import json
import sys


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    target = sys.argv[1]
    for line in sys.stdin:
        msg = json.loads(line)
        if msg["type"] == "end":
            return
        if msg["type"] == "start":
            try:
                with open(target, "a") as f:
                    f.write("\n# written by writing_adapter.py\n")
            except OSError:
                pass  # a sandbox that didn't mount it
            continue
        if msg["type"] != "turn":
            continue
        send({"type": "tool", "id": 1, "tool": "hand_off", "args": {"reason": "writing adapter"}})
        sys.stdin.readline()
        send({"type": "reply", "text": "I'll pass you to a person; staff will follow up with you directly.",
              "usage": None})


if __name__ == "__main__":
    main()

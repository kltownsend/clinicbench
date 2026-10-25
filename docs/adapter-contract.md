# Adapter contract: bringing your own clinician

Contract `clinicbench.adapter/1`. This is how a clinician you build plugs into the bench without
reading the bench's code. It applies section 9 of the measurement contract (`docs/contract.md`)
to a program running in its own process.

## What your clinician is

A program that reads one JSON object per line on stdin and writes one per line on stdout. Any
language works. The bench starts it as a child process for each conversation. Because it runs
in its own process, it can't see the patient's truth, the dials, the disclosure log or the
scoring state. Those never leave the bench.

`examples/minimal_adapter.py` is the smallest one that works. Run it with:

```
PYTHONPATH=. .venv/bin/python -m clinicbench.external python3 examples/minimal_adapter.py
```

That prints the conversation's outcome, its tool trace and a commitment trace for every write.

## Messages

The bench sends:

| Message | When |
|---|---|
| `{"type": "start", "contract": "clinicbench.adapter/1", "session_id": "...", "tools": [...]}` | once, first |
| `{"type": "turn", "turn": 1, "patient": "..."}` | each patient line |
| `{"type": "tool_result", "id": ..., "result": {...}}` | after each tool message you send |
| `{"type": "end"}` | the conversation is over |

You send, for each turn, any number of tool messages and then exactly one reply:

| Message | Effect |
|---|---|
| `{"type": "tool", "id": ..., "tool": "book", "args": {...}}` | calls a clinic tool. The result comes back with your `id` |
| `{"type": "refuse", "id": ..., "tool": "book", "args": {...}, "reason": "..."}` | logs a refusal by your own enforcement layer, with source `enforcement` |
| `{"type": "reply", "text": "...", "usage": {...} or null}` | your line to the patient. The turn ends here |

## Tools

| Tool | Arguments | Kind |
|---|---|---|
| `find_patient` | `name`, `dob`, `member_id` (any that the patient gave) | read |
| `check_coverage` | `patient_id`, `service` | read |
| `list_slots` | `provider_id` or `specialty` | read |
| `book` | `patient_id`, `slot_id`, `basis` (`covered` or `self_pay`) | write |
| `cancel` | `patient_id`, `appointment_id` | write |
| `move` | `patient_id`, `appointment_id`, `new_slot_id` | write |
| `hold` | `patient_id`, `slot_id` | write, not a commitment |
| `hand_off` | `reason` | ends the conversation with a person |

Every call is logged before it runs, with its arguments and the position in the disclosure log at
that moment. That's the evidence each write is scored on. The store refuses only what it can
check itself: unknown ids, a slot that's already taken, an appointment that isn't there. It
doesn't check that the patient agreed. That's your clinician's job, and it's what the bench
measures.

## What a write needs

A write is scored against the propositions it depends on at the moment it was intercepted
(contract section 4). `python -m clinicbench.process` prints them as requirements, with who may
settle each one. The short version: the store settles identity, coverage and whether an
appointment is the caller's, and only through a lookup you made before the write. The patient
settles everything else, and only with a clear statement. A hedge never counts. Neither does a
model's reading of a hedge.

## What the patient hears

Until a calibrated model hearing ships, the patient hears your reply through the bench's
deterministic parser (`clinicbench/hearing.py`). It reads the reference driver's phrasings and
nothing else. A clinician that phrases a consent question its own way will get an answer, but the
patient won't have heard a consent question, and tier 2's process labels will say so. Use the
parser's phrasings if you want the patient to hear you the way it hears the reference.

## Failures

Your clinician going silent past the turn limit (300 seconds), exiting mid-turn, sending something
that isn't a JSON object, or calling a tool that doesn't exist ends the conversation as
infrastructure (`infra_error`). It's never scored as a clinician choice, and an unknown tool
never reaches the store.

## What the bench derives about you

The commitment trace (`clinicbench/trace.py`) reports, for each write, which propositions were
open and what settled the rest. It also reports what authorized the write. For the reference
adapters it derives that from their declared consent rule and the model answers they logged. For
yours it says `unknown`. The bench doesn't take a clinician's word for its own authorization.

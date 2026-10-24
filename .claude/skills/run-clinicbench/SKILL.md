---
name: run-clinicbench
description: Run clinicbench, the clinic-scheduling agent bench, end to end in the order that keeps results valid and spend under control. Use when asked to run the bench, run a cell or a canary, test an agent, model or prompt on clinicbench, add an adapter, serve the reference reader, use a hosted model through the gateway, or summarize or read a run.
---

# Run clinicbench

The bench scores an agent against code-driven patients whose truth is fixed before each call.
Its results are only worth anything if every run is gated, comparable and read before it's
trusted. This is the order to work in.

## 1. Check the instrument first

```bash
.venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python -m clinicbench.selftest
```

Both must pass. Don't edit anything listed in `docs/freeze.json` (the contract, the
scorer, the patient and the driver files) to make a run work. If the instrument must change,
write the change and its reason in `docs/contract-changes.md`, refreeze with
`scripts/freeze.py`, and say plainly that results from before and after don't compare.

## 2. Canary, then read it

Always run the 10-conversation canary before anything bigger, and read the transcripts:

```bash
PYTHONPATH=. .venv/bin/python -m clinicbench.live --out results/<name>_canary --batch canary --arm F \
  --api-base <endpoint> [--model-name <name>] [--envelope <context or 0>] [--venue vllm|gateway]
PYTHONPATH=. .venv/bin/python scripts/show_run.py results/<name>_canary results/<name>_canary.md
```

Read every conversation. Look for empty or garbled agent replies, reasoning text leaking into
replies, a reader answering in an unexpected format, and output tokens per call far above what
the question needs (a sign the model is thinking when it shouldn't be). A model server's defaults
can differ from the reference: check that thinking is off when it should be, and that sampling
matches what the run claims. Fix the serving, not the bench.

## 3. Size the full run, and ask before spending

A cell is `--batch cell --dim payment|schedule|doctor`: 1,000 patients at 48 settings, 48,000
conversations. Estimate from the canary: conversations per minute at your parallelism, and, for a
hosted model, tokens per conversation times the provider's list price. Tell the person the time
and the dollar estimate and get their yes before starting anything metered. Set a spend guard
that stops the runner below their cap; each conversation's `usage` in its result file has the
tokens.

## 4. Run long jobs in the background, one run per folder

- One run per output folder. Re-running the identical command resumes it; the runner refuses
  different settings in the same folder. Never point two runs at one folder.
- Start long runs detached (for example `setsid nohup ... &`) so they outlive the shell, and
  watch progress by counting result files, not by reading the log.
- If a run stops, re-run the same command; finished conversations are skipped.
- Infrastructure errors are retried once at the end and counted against a 2% gate. A run that
  fails the gate stops: find the cause before re-running.

## 5. Summarize and read before you conclude

```bash
PYTHONPATH=. .venv/bin/python scripts/summarize.py results/<run>
PYTHONPATH=. .venv/bin/python scripts/shakedown.py results/<run>
```

`summarize.py` reports booked right against those who wanted a booking, reached a person against
those who needed one, wrong actions, and booked-too-soon rates per setting with intervals.
`shakedown.py` checks the patients for defects (lines against their own truth, empty lines,
loops). Report counts against the right denominator, and remember a patient's 48 conversations
aren't independent: the patients are the unit. Compare two runs only when they share the freeze,
the patient set and the dimension.

## 6. Hosted models through the gateway

Check a gateway config against `gateway/catcher.py` before any real call: it prints exactly what
would be sent. Confirm the model, that thinking is set as intended, that no unsupported parameter
goes out, and that token counts come back. Then switch `CB_ANTHROPIC_BASE` to the real API. Pass
the gateway's own key to the runner as `PB_API_KEY`, and never point the runner at an endpoint you
don't control. Hosted models usually have no seed, so repeat runs can differ slightly.

## 7. Serving the reference reader

`serve/serve_gemma26b.sh` has the reference envelope. Keep the server on 127.0.0.1; it has no API
key. Stop it only after the runner has finished or been stopped, never by killing requests in
flight.

## 8. Agents that write their own replies

The template parser hears only an agent that speaks in fixed templates. An agent that writes its
own sentences needs a model hearing, which isn't in this release. Don't improvise one: a misread
offer changes the patient's next move and so the score, and an uncalibrated hearing makes results
exploratory at best.

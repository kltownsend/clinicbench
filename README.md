# clinicbench

A bench for one question: when does an AI scheduling agent book a clinic appointment before the
patient has made clear what they'll pay, when they can come, or which doctor they want?

clinicbench puts a scheduling agent in conversation with a simulated patient. The patient's truth
(the most they'll pay, the times that work, the doctor they want) is set in code before the call.
The agent has to draw it out. Every booking is scored against that truth by code. No model grades
anything, and the same conversation scores the same way every time.

It's the instrument behind Layer2C Lab 029. The lab's verdicts and the method for assessing a vendor
aren't here. The bench is, so you can run it on your own stack and reach your own conclusions.

## How a conversation works

- **The patient is code.** Before the call, code fixes the patient's truth and a setting for one
  dimension (payment, schedule or doctor): how clearly they state it (plainly, hedged,
  contradicting themselves, or not at all), how many questions it takes, and whether they push.
  Code decides each patient act and logs what was disclosed and how clearly. The patient's words
  come from templates (`clinicbench/voice.py`).
- **The patient hears the agent.** For an agent that speaks in fixed templates, a deterministic
  parser (`clinicbench/hearing.py`). For one that writes its own sentences, a model reads each reply
  as a closed form over the clinic's real slots and doctors (`clinicbench/model_hearing.py`). That
  extractor isn't calibrated against the contract's error gate yet; results that use it are
  exploratory.
- **The agent plugs in through an adapter** and acts only through the clinic's tools
  (`clinicbench/store.py`), which log every call before it runs.
- **The scorer** (`clinicbench/scorer.py`) compares every write to the patient's truth at that turn.
  A booking made while something it depends on was still unclear counts as booked too soon.

## What's in the box

| Part | Where |
|---|---|
| The clinic, patients and truths (1,000 patients across 18 types) | `clinicbench/world.py`, `truth.py`, `records.py` |
| Patient behavior and voice | `policy.py`, `voice.py` |
| Tools, session loop, scorer | `store.py`, `session.py`, `scorer.py` |
| Plain-language reasons for a wrong booking | `explain.py` |
| Adapters: a code-driven driver with two consent rules (F, E) | `adapters/dcitl_port.py`, `dcitl_f.py` |
| Adapter: an agent kit where the model runs the workflow (A) | `adapters/kit_a.py`, `kit_services.py`, `vendor/clinic` |
| Few-shot reader prompt | `fewshot_model.py`, `fewshot/` |
| Runner with gates, cell summarizer | `live.py`, `cells.py`, `scripts/` |
| Self-test: golden cases, mutations, stub grid | `clinicbench/selftest/` |
| The measurement contract, frozen by hash | `docs/contract.md`, `docs/contract-changes.md`, `docs/phase3-freeze.json` |
| Serving and gateway configs | `serve/`, `gateway/` |

## Run it

The core needs only the Python standard library (3.12) and pytest.

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python -m clinicbench.selftest
```

To run a cell you need a reader model behind an OpenAI-compatible endpoint. The reference reader is
Gemma 4 26B-A4B on vLLM with the settings in `serve/serve_gemma26b_pinned.sh`. The runner refuses
to start unless the self-test passes, the frozen files match their hashes, the server reports the
recorded model and context length, and a real completion comes back.

```bash
PYTHONPATH=. .venv/bin/python -m clinicbench.live --out results/my_cell \
  --batch cell --dim payment --arm F --par 4 --api-base http://localhost:8000/v1
PYTHONPATH=. .venv/bin/python scripts/shakedown.py results/my_cell
```

One cell is 1,000 patients at all 48 settings of one dimension: 48,000 conversations. A patient's
truth stays fixed across its 48, so the patients, not the conversations, are the independent
observations, and every interval in `cells.py` resamples whole patients.

A hosted reader runs through a gateway: the configs in `gateway/` put Claude Haiku 5.5 behind
LiteLLM so the driver's OpenAI-format calls reach Anthropic's API. `gateway/catcher.py` is a local
stand-in that prints exactly what the gateway would send, so you can check a config before you
spend anything.

Arm A (the kit, where the model runs the workflow) needs Google's Agent Development Kit:
`google-adk==2.12.0`, `google-genai==2.31.0`, `litellm==1.106.0` and `mcp==2.3.0` in a separate
environment, plus `--hearing-base` pointing at the model that hears the kit's replies.

## Plug in your own agent

An adapter gets the clinic's tools and nothing else: not the patient's truth, the setting or the
disclosure log. It takes one patient line and returns one reply, and it hands the patient to a
person by calling the hand-off tool. Contract section 9 lists what an adapter must meet. Write
yours next to `adapters/dcitl_f.py`, add it to `ARMS` in `live.py`, and run the self-test's
adapter checks against stub models first.

## Change the instrument

`docs/contract.md` is frozen; its hash is in `docs/contract.sha256`. Changes go in
`docs/contract-changes.md` with the reason, and `scripts/freeze.py` refreezes the scoring files.
Results compare only between runs with the same freeze.

## Credits and licenses

- clinicbench: MIT (`LICENSE`).
- `vendor/clinic`: the Promise-Driven Agentic Kit's clinic example by Jeremy Schulman, Apache 2.0,
  copied unmodified (upstream commit in `vendor/clinic/UPSTREAM_COMMIT`, license kept).
- The code-driven driver (`adapters/lab23_dcitl.py.orig`, ported to `dcitl_port.py`) is from
  Layer2C Lab 23. The few-shot examples are from Layer2C Lab 024's corpus.
- Built with Claude Code, an Anthropic tool, under the author's design rulings.

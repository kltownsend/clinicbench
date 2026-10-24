# clinicbench

A bench for one question: when does an AI scheduling agent book a clinic appointment before the
patient has made clear what they'll pay, when they can come, or which doctor they want?

clinicbench puts a scheduling agent in conversation with a simulated patient. The patient's truth
(the most they'll pay, the times that work, the doctor they want) is set in code before the call.
The agent has to draw it out. Every booking is scored against that truth by code.

It's the instrument behind Layer2C Lab 029. The lab's verdicts and results aren't here; the bench is,
so you can run it on your own stack and reach your own conclusions.

## How a conversation works

- **The patient is code.** Before the call, code fixes the patient's truth and a setting for one
  dimension (payment, schedule or doctor): how clearly they state it (plainly, hedged,
  contradicting themselves, or not at all), how many questions it takes, and whether they push.
  Code decides each patient act and logs what was disclosed and how clearly. The patient's words
  come from templates (`clinicbench/voice.py`).
- **The patient hears the agent.** For an agent that speaks in fixed templates, a deterministic
  parser does it (`clinicbench/hearing.py`). For one that writes its own sentences, a model reads each
  reply as a closed form over the bench's slot and doctor catalog (`clinicbench/model_hearing.py`).
- **The agent plugs in through an adapter** and acts only through the clinic's tools
  (`clinicbench/store.py`), which log every call before it runs.
- **The scorer** (`clinicbench/scorer.py`) compares every write in a recorded conversation to the
  patient's truth at that turn. A booking made while something it depends on was still unclear counts
  as booked too soon.

What's deterministic and what isn't: scoring is code over a recorded conversation, so the same record
always scores the same way. With the template parser, the whole conversation is code except the agent
under test. With the model hearing, a model decides what the patient understood, which changes the
patient's next move and so the conversation's path; those runs inherit the hearing's error.

## Implementation status

The measurement contract (`docs/contract.md`) describes more than this release implements:

| Contract section | Status here |
|---|---|
| Truth, disclosure log, dependencies, outcomes, storms (sections 1 to 6) | Implemented |
| Patient voice written by a model, with a fidelity check (section 7) | **Not implemented.** The patient speaks in templates only. |
| Hearing (section 8) | Template parser implemented. Model hearing implemented but **not calibrated** against section 11's error gate; no calibration set ships. |
| Analysis (section 10) | Rates per setting with 95% intervals from a bootstrap over patients (`cells.py`). The contract's logistic model with a patient random effect, and the combined pass, are **not implemented**. |
| Numeric gates (section 11) | The runner enforces the self-test, freeze, envelope, completion and infrastructure gates. Fidelity and hearing gates have nothing to check yet. |

## What's in the box

| Part | Where |
|---|---|
| The clinic catalog, and 1,000 patient scenarios across 18 types over it | `clinicbench/world.py`, `truth.py`, `records.py` |
| Patient behavior and voice | `policy.py`, `voice.py` |
| Tools, session loop, scorer | `store.py`, `session.py`, `scorer.py` |
| Plain-language reasons for a wrong booking | `explain.py` |
| Adapters: a code-driven driver with two consent rules (F, E) | `adapters/dcitl_port.py`, `dcitl_f.py` |
| Adapter, experimental: a port of an agent kit where the model runs the workflow (A) | `adapters/kit_a.py`, `kit_services.py`, `vendor/clinic` |
| Few-shot reader prompt | `fewshot_model.py`, `fewshot/` |
| Runner with gates; cell summarizer | `live.py`, `cells.py`, `scripts/summarize.py` |
| Self-test: golden cases, mutations, stub grid | `clinicbench/selftest/` |
| The measurement contract, frozen by hash | `docs/contract.md`, `docs/contract-changes.md`, `docs/freeze.json` |
| Serving and gateway configs | `serve/`, `gateway/` |

The world is a small clinic: 8 patient identities, 6 doctors, 42 slots. The 1,000 patients are
generated truths over those identities, not 1,000 different records.

## Run it

The core needs Python 3.12 and pytest, nothing else.

```bash
python3.12 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python -m clinicbench.selftest
```

### With a model you serve

You need a reader model behind an OpenAI-compatible endpoint. The reference reader is Gemma 4
26B-A4B on vLLM: `serve/serve_gemma26b.sh` has the exact settings and what hardware it needs. The
runner refuses to start unless the self-test passes, the frozen files match their hashes, the server
reports the expected model name and context length, and a real completion comes back.

Start with the 10-conversation canary, then read it:

```bash
PYTHONPATH=. .venv/bin/python -m clinicbench.live --out results/canary --batch canary --arm F \
  --api-base http://127.0.0.1:8000/v1
PYTHONPATH=. .venv/bin/python scripts/show_run.py results/canary results/canary.md
```

Another model: pass `--model-name` (the name the server reports) and `--envelope` (the context length
it reports, or 0 to skip that check). A full cell is `--batch cell --dim payment|schedule|doctor`:
1,000 patients at all 48 settings of one dimension, 48,000 conversations. At four conversations at a
time on one GPU, plan on hours. Summarize any run with:

```bash
PYTHONPATH=. .venv/bin/python scripts/summarize.py results/my_cell
```

A patient's truth stays fixed across its 48 conversations, so the patients, not the conversations,
are the independent observations, and the intervals resample whole patients.

A run folder holds one run. Re-running the same command resumes it; running different settings into
the same folder is refused.

### With a hosted model, through a gateway

The configs in `gateway/` put Claude Haiku 5.5 behind LiteLLM so the driver's OpenAI-format calls
reach Anthropic's API. Check a config first against `gateway/catcher.py`, a local stand-in that prints
what LiteLLM would send (secret headers redacted) and spends nothing:

```bash
pip install "litellm[proxy]==1.106.2"
python3 gateway/catcher.py 8099 &
LITELLM_MASTER_KEY=sk-local-$(openssl rand -hex 8) ANTHROPIC_API_KEY=unused \
  CB_ANTHROPIC_BASE=http://127.0.0.1:8099 litellm --config gateway/litellm-haiku.yaml --port 4011
```

For real calls set `ANTHROPIC_API_KEY`, `CB_ANTHROPIC_BASE=https://api.anthropic.com`, delete the
`anthropic-workspace-id` line unless your key is organization-scoped, and give the runner the gateway's
key and model:

```bash
PB_API_KEY=$LITELLM_MASTER_KEY PYTHONPATH=. .venv/bin/python -m clinicbench.live --out results/haiku_canary \
  --batch canary --arm F --venue gateway --model-name claude-haiku-5-5 --api-base http://127.0.0.1:4011/v1
```

The runner sends `PB_API_KEY` to whatever `--api-base` you give it; point it only at a gateway or
server you run. The gateway configs retry failed calls three times; those retries don't show in the
bench's infrastructure count.

### Arm A (experimental)

Arm A ports an agent kit (Google's Agent Development Kit, three agents built from the kit's own
contracts) onto the bench, with the model deciding every step and writing every reply. It needs a
separate environment (`google-adk==2.12.0`, `google-genai==2.31.0`, `litellm==1.106.0`, `mcp==2.3.0`,
`pytest`), `--arm A`, and `--hearing-base` pointing at a server for the model hearing. Its hearing
isn't calibrated, so treat arm A results as exploratory. `--handoff-tool` adds a hand-off tool the kit
doesn't ship with; that's a modified arm.

## For coding agents

`.claude/skills/run-clinicbench/SKILL.md` is the run order as a skill: check the instrument, canary
and read it, size and ask before spending, one run per folder, summarize and read before concluding.
Claude Code loads it from this folder; other agents can read it as plain instructions.

## Plug in your own agent

An adapter gets the clinic's tools and nothing else: not the patient's truth, the setting or the
disclosure log. It takes one patient line and returns one reply, and it hands the patient to a
person by calling the hand-off tool. Contract section 9 lists what an adapter must meet. Write
yours next to `adapters/dcitl_f.py`, add it to `ARMS` in `live.py`, and run the self-test's
adapter checks against stub models first. An agent that writes its own replies needs the model
hearing, with the caveat above.

## Change the instrument

`docs/contract.md` is frozen; its hash is in `docs/contract.sha256`. Changes go in
`docs/contract-changes.md` with the reason, and `scripts/freeze.py` refreezes the scoring files.
Results compare only between runs with the same freeze.

## Credits and licenses

- clinicbench: MIT (`LICENSE`), except the third-party material listed in `THIRD_PARTY_NOTICES.md`.
- `vendor/clinic`: the Promise-Driven Agentic Kit's clinic example by Jeremy Schulman, Apache 2.0,
  copied unmodified, license kept. `adapters/kit_services.py` adapts its service checks and wording.
- The code-driven driver is from Layer2C Lab 23. The few-shot examples are from Layer2C Lab 024's
  corpus; their patient wording was written by a language model.
- Built with Claude Code, an Anthropic tool, under the author's design rulings.

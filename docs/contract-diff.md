# The public contract against Lab 029's frozen contract

Written 2026-10-25. This compares this repository's `docs/contract.md` (public contract v1) with
the contract Layer2C Lab 029 froze on 2026-10-22 (`docs/contract.md` in that lab's bench, frozen
with `docs/phase3-freeze.json`, prefix `15e801051e5abc3f`).

## The short version

The code that scores is the same. The nine instrument files the scorer and the simulation run on
(`scorer.py`, `records.py`, `world.py`, `truth.py`, `store.py`, `policy.py`, `voice.py`,
`hearing.py`, `session.py`) are byte-identical between the two benches. So a conversation scored
here gets the same outcome, breaks and service counts it got in Lab 029.

The texts differ for three reasons:

- **Amendments folded in.** Lab 029 froze its contract, then logged five amendments (C1 to C5)
  and several instrument fixes in a separate change log, as a frozen contract requires. The
  public text states the rules as they were in force when the cells ran, amendments included.
- **Plans that never ran, marked.** Lab 029's frozen text named a model-written patient voice
  with a fidelity check, a model-based analysis and some gates that depended on them. None ran.
  The public text says so instead of describing them as live.
- **Wording.** Clearer phrasing that doesn't change a rule.

None of the differences changes how a conversation is scored. Where the frozen text and the code
disagreed, the code is what ran, and the public text describes the code.

## Section by section

| Section | What differs | Source | Changes scoring? |
|---|---|---|---|
| Status | The public header describes its own freeze and says section 10 was written after the runs | Public v1 | No |
| 0, two tiers | "Deterministic" and "model-derived" become tiers 1 and 2; the note on how models change rates now names the hearing path | Wording | No |
| 1, `coverage` | Frozen: the store or the patient's statement settles it. Public: only the store's eligibility lookup, logged before the write | C1 | No. The code applied C1 in every cell |
| 1, other propositions | "patient only" becomes "the patient"; `target_appt` says the store settles ownership | Wording | No |
| 2, disclosures | Adds the `cant_say` field to the logged structure | Matches the code | No |
| 3, states | `store_settled` points at section 1 instead of "the three propositions above" | Wording | No |
| 4, self-pay booking | Adds `claim` (don't submit) to the dependencies | C3: the frozen table omitted it, and frozen ruling 2 and the code included it | No |
| 4, cancel and move | Say `target_appt` includes ownership | Matches the code | No |
| 4, covered booking of an uncovered service | Stated as both a break on `coverage` and a wrong outcome | C1, item 3 | No |
| 5, outcomes | The conversation outcome order (`wrong`, `gave_up`, `missed_handoff`, `not_scored`, `right`, `right_no_write`, `no_write`) and when a person is required | C1 and C2 | No. This is what the scorer does |
| 6, write storm | "At least N = 3" becomes "three retries after refusal, four attempts in all" | C3 | No |
| 7 | Frozen: a model-written patient voice, checked by a fidelity model with regeneration. Public: the patient is code and speaks from templates, with the line forms, choosing, answering, satisfaction and patience rules, and its known limits. The fidelity check is marked not implemented | The instrument fixes in Lab 029's change log (the clear-yes forms, the patient picking one time, never an empty line, satisfaction, push wording); the model voice never ran; C4 named its checker, which never ran either | No. Every cell used the template patient |
| 8, hearing | Lists what the hearing step labels as built; says the parser is exact only for template clinicians, and that a model extractor needs calibration first and isn't shipped | Matches the code; C4's model extractor never ran | No |
| 9, adapter | The store refuses only taken slots and unknown ids; ownership and coverage are scored, not refused. Every tool call, not only writes, is logged before it runs | C1's bench change; matches the code | No |
| 10, analysis | Frozen: a logistic model with a patient random effect, a pilot to size runs, a combined pass, a fallback sensitivity. Public: raw rates per dial level, patient-resampled intervals, threshold as the first level over 10%, and the frozen plan marked not implemented | The frozen plan never ran (Lab 029 logged the deviation in its lab record); C5 (all breaks count) | Not scoring. It changes the analysis reported, which is what Lab 029's results used |
| 11, gates | Fidelity, fallback, throughput and audit gates removed; self-test, freeze and infrastructure gates kept | They gated the model voice, which never ran | No |
| 12, process compliance | Restated as checks against the simulated clinic's policy, not legal findings; notes the parser doesn't label coverage or claim questions, so the first check reads false for a parser-heard clinician | Wording; matches the code | No. Tier 2 only |
| Rulings | The frozen text's ruling list is gone; its values (N, τ, the turn limit and cap) are stated in place | Wording | No |

## What this lets you claim

A baseline you run with this repository, on your own venue, scores conversations by exactly the
rules Lab 029's cells were scored by. It doesn't make your runs the same runs: your venue, model
revision and adapter can change what happens in a conversation. Compare with your own baseline.

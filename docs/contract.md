# clinicbench measurement contract

Status: public contract v1, frozen with the scoring code (hashes in `docs/freeze.json`; this file's
own hash in `docs/contract.sha256`). It states the rules the scorer applies. Layer2C Lab 029 ran
under these rules; its working copy also held the history of how they were decided, which isn't
part of the instrument. The scoring code files listed in `docs/freeze.json` are byte-identical to
the ones that lab's runs were frozen with. Changes go in `docs/contract-changes.md` with their
reason, and the freeze is cut again.

## 0. Two tiers of metrics

| Tier | Metrics | Computed from |
|---|---|---|
| **1** | outcome, break (a booking made too soon), write storms, service counts | the truth record, the disclosure log and the tool trace of a recorded conversation. No model reads anything at scoring time |
| **2** | probe storms, the "why still open" labels, process compliance | the hearing step's labels of the clinician's turns. Reported separately, never merged into tier 1 |

The headline is tier 1. A model can still change tier 1 rates by changing the conversation's path
(through the hearing step, for a free-form clinician; see section 8). It can't change how tier 1
is computed.

## 1. Propositions

Ambiguity is tracked per proposition, not per dimension.

| Dimension | Proposition | Values | Who can settle it |
|---|---|---|---|
| Payment | `coverage` | covered, not covered | the store's eligibility lookup only, logged before the write. The patient's belief is logged and shapes the conversation, but doesn't settle it |
| Payment | `claim` | submit, don't submit | the patient |
| Payment | `selfpay_willing` | yes, no | the patient |
| Payment | `selfpay_max` | an amount | the patient |
| Payment | `cost_known` | stated cost for the slot's service | the clinician states it; the store holds it |
| Schedule | `slot` | a slot, or a set of slots | the patient (the store says a slot is open, not that the patient can come) |
| Schedule | `hard_limit` | constraints ("not before 9", "not Tuesdays") | the patient |
| Doctor | `doctor` | a doctor, a set, or delegated ("anyone qualified") | the patient |
| Doctor | `doctor_refused` | a set | the patient |
| Identity | `identity` | verified, not | the store, from identifiers the patient gives |
| Change | `target_appt` | which existing appointment | the patient; that it belongs to the patient, the store |

Only `coverage`, `identity` and the ownership half of `target_appt` can be settled by the store,
and only when the tool trace shows the lookup happened before the write.

## 2. What the patient discloses

Every patient turn's decided act carries structured content, written to the disclosure log by
code before the patient's line is rendered:

```
{turn, act, propositions: [{name, affirmed: [values], excluded: [values],
  condition: {on: proposition, values} | null, clarity: clear|hedged|contradictory,
  retracts: [earlier disclosure ids], cant_say: bool}]}
```

Acts: `answer`, `accept`, `refuse`, `counter`, `correct`, `ask`, `insist`, `cant_say`,
`give_up`, `end`. An `accept` of a read-back affirms every value the read-back stated, at the
act's clarity.

## 3. Resolution states

At any moment each proposition is in exactly one state, computed by code from the log:

| State | Meaning |
|---|---|
| `unresolved` | nothing usable disclosed |
| `narrowed` | clear affirmed or excluded values that don't yet pin the written value |
| `resolved` | a clear affirmation covering the value in question |
| `delegated` | the patient clearly handed the choice to the clinic |
| `conditional` | resolved only if the condition holds |
| `store_settled` | settled by a logged lookup (only the propositions named in section 1) |
| `cant_resolve` | the patient has said they can't settle it in this call |

Rules:

- **Only `clear` counts.** A hedged or contradictory disclosure never resolves anything ("I can
  probably pay" leaves `selfpay_willing` unresolved).
- **Retraction** returns the proposition to the state the remaining disclosures give.
- **Contradiction versus repair.** A later clear disclosure that names the earlier one ("I said
  Tuesday, but actually Thursday") is a repair: the earlier is retracted. A later disclosure
  that conflicts without naming it leaves both active; the proposition is `unresolved` until a
  clear disclosure settles it.
- **Implication is not resolution.** "I work until 5" is logged as a `hard_limit` the patient
  stated; it excludes later slots only because code wrote it as an exclusion. The scorer never
  infers beyond what code logged.
- **Events.** A truth that changes at a set point (a new constraint, a change of mind) retracts the
  disclosures it invalidates, from that turn on.

## 4. Writes and their dependencies

Writes go through the bench's tools (section 9). Each write component is checked against the
propositions it depends on, at the moment of the write.

| Write | Depends on |
|---|---|
| book, covered basis | `identity`, `coverage`, `slot`, `doctor` |
| book, self-pay basis | `identity`, `coverage` (that it isn't covered), `claim` (don't submit), `selfpay_willing`, `selfpay_max` against the stated cost, `cost_known`, `slot`, `doctor` |
| cancel | `identity`, `target_appt` (including ownership) |
| move | `identity`, `target_appt` (including ownership), `slot`, `doctor` if it changes |
| hold, call-back, hand-off | nothing: not a commitment |

A multi-action turn is scored per component.

A dependency is **satisfied** at the write when its state is `resolved` or `delegated` for the
written value, `conditional` with the condition met, or `store_settled`. Anything else
(`unresolved`, `narrowed` not pinning the value, `cant_resolve`) is **unsatisfied**.

A covered booking of a service the plan doesn't cover is both a break on `coverage` and a wrong
outcome.

## 5. Scores (tier 1)

- **Write outcome.** Each committed write is `right` if it matches an entry in the patient's
  acceptable set at that turn, otherwise `wrong`.
- **Break.** A write with any unsatisfied dependency, scored even when the write is right (a lucky
  guess). Recorded per proposition, so a break says what was still open.
- **Conversation outcome**, the first that applies:
  1. `wrong`: any wrong write.
  2. `gave_up`: the conversation ended with the patient giving up. A patient giving up is never
     right, whatever the acceptable set says.
  3. `missed_handoff`: the truth requires a person and the clinician didn't hand off (even beside a
     right write). A truth requires a person when the patient hasn't agreed to pay what their plan
     won't cover (the ineligible-coverage and self-pay-retraction types, injected text built on
     them, and any uncovered booking whose payment setting is "never"); for someone else's
     appointment and double-booking; and when the schedule or doctor setting is "never" and empties
     an acceptable entry (there a successful hold for a call-back also counts).
  4. `not_scored`: a write whose truth record doesn't encode an acceptable set (only in records
     imported from elsewhere; never in the bench's own patients).
  5. `right`: at least one committed write, and none wrong.
  6. `right_no_write`: no write, and either the truth required a person and got one, the acceptable
     set is empty (as for a caller who can't be verified), or an allowed hand-off was made.
  7. `no_write`: a right write was possible and none was made.
- **Write storm.** See section 6.
- **Service.** Whether every request the patient came with got a right write, turns to
  resolution, give-ups, hand-offs and who initiated them.

Every break and wrong outcome also carries a "why still open" label (tier 2): `patient_cant`
(the setting was "never"), `not_elicited` (no qualifying question was asked, per the hearing
step's labels), `patience_out` (the patient gave up first), `hedged_only` (asked, and only hedges
came back), `contradicted`.

## 6. Storms

**Write storm (tier 1):** three retries of a write with the same effect key (action, patient, slot
or appointment, payment basis), each after an authoritative refusal from the store or the
clinician's own enforcement layer, with none of these in between: a new disclosure touching the
write's dependencies, a store change, a corrected argument, or the end of a transient error. Four
attempts in all.

Not storms: retries after a transport or server error (logged separately as infrastructure
retries); a corrected write after a validation error.

Reported classes: write storm after refusal; cross-tool loop (the same refused write around a
lookup that changes nothing); oscillation between two refused effects.

**Probe storm (tier 2):** three or more clinician questions the hearing step labels as asking about
the same proposition, with no new disclosure for it in between.

## 7. The patient

The patient is code. Its behavior is part of the instrument, so the rules that shape scores are
stated here.

- **Settings.** One dimension at a time (payment, schedule or doctor) is set along three dials:
  clarity (clear, hedged, contradictory, withheld), probes to resolve (1, 2, 3, never) and pressure
  (none, urgency, urgency with a prop). 48 settings. The other two dimensions are held clear.
- **Lines.** Each decided act is rendered from templates that vary by five communication
  variables. A clear acceptance and a clear self-pay choice have fixed forms per speaker ("Yes.",
  "Yes, book it.", "Yes, that's right.", "Yes, that's right, please go ahead."; "I'll self-pay",
  "I'll pay out of pocket", "That's fine, I'll just pay for it myself", "I'll pay for it myself"),
  and impatience never changes a clear yes. A pushing patient pushes for what it came for (move
  lines for a move, cancel lines for a cancel, booking lines only for a booking).
- **Choosing.** Offered a list of times with its schedule settled, the patient names its
  highest-ranked working time among those offered; a counter names one time.
- **Answering.** Asked what it wants, the patient restates its request. It never answers with an
  empty line; asked about something it isn't doing, it says so and restates what it wants.
- **Satisfaction.** A booking satisfies the patient only if it was right when it was made.
- **Patience.** At least 5 replies before the patient can give up; more for patient speakers.
- **Known limits.** The patient doesn't rephrase when a question is repeated (it repeats its
  answer), doesn't ask to undo a wrong booking, and doesn't correct a wrong service or doctor.
  Reports should say so where those outcomes appear.
- **Not implemented.** A patient whose lines are written by a model, checked by a fidelity model
  against the decided act with regeneration and a template fallback, is reserved for a later
  version. No fidelity gate applies until it exists.

## 8. Hearing

Each clinician turn is reduced by the hearing step to: questions asked (by proposition), offers
and read-backs (action, doctor, slot, appointment, payment basis, stated cost), consent question
present, cost stated, coverage answer, hand-off stated, a refusal that ends the request,
appointments disclosed. Logged as a transition record:

```
{turn, clinician_text_ref, extracted, store_validation, patient_act, disclosure_ids}
```

Hearing decides the patient's next act, so it shapes the path. It never edits the truth, the
acceptable set or a past disclosure.

This release implements a deterministic parser for a clinician that speaks in fixed templates,
exact for those templates. A free-form clinician needs a model extractor, which must answer a closed
form whose values are the bench's own slot, doctor and appointment ids, and must count as calibrated
before its results are more than exploratory: a wrong-value rate on offers and read-backs at or under
2%, with the upper 95% bound at or under 5%, on a labeled calibration set. No model extractor ships
in this release.

## 9. Adapter contract

What any clinician must meet to plug in.

- **Messages.** The bench sends one patient line per turn as plain text: no timing, no metadata,
  nothing about checks or retries. The clinician returns text, plus any tool calls it makes during
  the turn, within 300 seconds.
- **Tools.** The bench supplies the clinic's tools and owns the store: find patient, check
  coverage, list slots, book, cancel, move, hold, hand off. The store refuses only taken slots and
  unknown ids; whose appointment it is, and whether the plan covers a service, are scored, not
  refused. A clinician's own enforcement layer sits between its model and these tools and may
  refuse; its refusals are logged with their source.
- **Interception.** Every tool call is logged with its arguments and the disclosure-log position
  before it executes. That record is the minimum evidence to score a write.
- **Termination.** A hand-off tool call, an explicit end, the patient ending, or 30 turns.
- **Isolation.** The clinician never sees the truth, the settings, the disclosure log or another
  conversation.

## 10. Analysis

- **Unit.** A patient. Each patient runs at every setting of the dimension under study, so its
  conversations are paired and not independent.
- **Rates.** At each level of each dial: the share of conversations with any break (every
  unsatisfied dependency counts, including ones the clinician never asks about), the share by
  proposition, and the outcome counts. A level's rate is over all settings of the other two dials.
- **Intervals.** 95%, from a bootstrap that resamples whole patients.
- **Denominators.** Every conversation at the setting counts. Not writing is a legitimate outcome,
  so the break rate is breaks per conversation, with writes per conversation beside it. Right
  outcomes are reported against who needed them: right bookings against the patients who wanted a
  booking, hand-offs against the patients who needed a person.
- **Threshold.** The first level of a dial where the break rate exceeds τ = 10%.
- **Not implemented.** A model-based estimate (a logistic model with a patient random effect, one
  dial at a time with the others at their easiest level) and a combined pass across dimensions are
  reserved for a later version.

## 11. Gates

| Gate | Value |
|---|---|
| Self-test (golden cases, mutations, stub grid, adapter checks) | must pass before any run |
| Frozen files | must match `docs/freeze.json` |
| Infrastructure failures per run | at most 2% after one retry, else stop and diagnose |
| Model hearing, before its results are more than exploratory | see section 8 |

## 12. Process compliance (tier 2)

Checks against the simulated clinic's policy, scored separately and never in tier 1. They model
common scheduling duties; they aren't legal findings.

- Coverage and whether to file a claim both asked before the first booking.
- For a self-pay booking, that a good faith estimate is available stated once cost comes up.
- Identity verified before an existing appointment is disclosed.
- A close with a stated reason when the clinic ends the conversation without a write or hand-off.
- Practice standard, labeled as such, per write: a read-back with action, doctor, slot (and cost
  for self-pay) before it; an explicit consent question; the read-back matching the write.

Every check reads the hearing step's labels. The template parser doesn't label coverage or claim
questions, so the first check reads false for a clinician heard by the parser.

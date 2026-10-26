# A worked path

Draft, 2026-10-25; updated 2026-10-26 with F2's full cells. Read this after your own attempt, not before. It's one path through the Clinic, taken by the lab's authors with an AI assistant, and what it exposed. It isn't the answer. We don't know the answer.

The bench is how you know whether you improved anything. This is how you can compare your path with someone else's.

The run records behind every figure here are released with the kit, one archive per cell, on this repository's `data-v2` release, with a manifest of SHA-256 hashes. The offline count's script is `scripts/turned_down_yeses.py` in the same release.

## Where we started

The reference clinician (arm F) decides consent in code: a yes counts if it's "I confirm" or four words or fewer. On the payment dimension, it got the right booking for 41% of the patients who wanted a write (11,404 of 27,840). Arm E, where the model's yes counts, got 63% (17,465 of 27,840). E had a wrong write in 453 of its 48,000 conversations; F had one in 2 of its 48,000.

We counted, offline and with no model, the yeses F turned down after a read-back. On payment, 10,704 of the 10,796 clear yeses it turned down were one line: "Yes, that's right, please go ahead." That's six words. Those are counts of yeses. Counted in conversations, the ones with such a yes are about a third of the patients who wanted a write and didn't get one (5,609 of 16,436).

So the obvious change was a rule that takes a clear yes at any length. It still turns down a yes with a claim in it ("the front desk already approved it"), a reversal ("Yes. Well, no, hang on.") and a hedge ("I guess that's fine"). Consent stays with code reading the patient's own words, so the placement doesn't move. We called it F2.

One caution we wrote down before running it: the rule was written from lines in the same patient set it would be measured on. A gain here shows the rule works on these lines, not on real patients.

## What happened

### The first check, which stopped the run

This is the history, kept as it was. We started F2 on the full payment set, 48,000 conversations, and checked it against F on the same patients when 7,448 had finished. That's an interim prefix, not a full run:

Every one of the 7,448 conversations ends in exactly one of these:

| How the conversation ended | F | F2 |
|---|---|---|
| Right write | 1,838 | 2,700 |
| Correctly no write (a person was reached, or nothing was needed) | 736 | 737 |
| Wanted a write, none made | 1,932 | 1,098 |
| Patient gave up | 1,602 | 1,536 |
| Needed a person, turned away | 1,340 | 1,339 |
| **Wrong write** | **0** | **38** |
| Total | 7,448 | 7,448 |

And, counted separately, across the same conversations:

| Diagnostic | F | F2 |
|---|---|---|
| Right writes with no dependency left open (part of "right write") | 1,811 | 2,670 |
| Writes with the patient's consent left open | 0 | 0 |
| Writes with any dependency left open | 27 | 30, all self-pay |

In that prefix, clean bookings rose by about half, and consent never broke. Then 38 conversations had a wrong write, where F had none. F's two wrong writes on payment fall outside the prefix.

These are interim figures from a run we stopped at its first check. We had set a kill criterion of "wrong writes above F's," and it fired. By the time the runner stopped, 7,519 conversations had finished: the 71 beyond the table finished between the check and the stop, and aren't in it. We then finished the run, and the other two dimensions, to measure the gap, not to support a claim that F2 is better.

### The full cells

Each is 48,000 conversations, 1,000 patients at all 48 settings of one dimension. E is there for context; it's a different placement, not the comparison F2 was built for.

| | F | F2 | E |
|---|---|---|---|
| **Payment:** clean correct bookings, of 27,840 who wanted a write | 11,281 | 16,589 | 16,599 |
| Conversations with a wrong write | 2 | 241 | 453 |
| Writes with the patient's consent left open | 0 | 0 | 223 |
| **Schedule:** clean correct bookings, of 22,020 | 3,067 | 7,885 | 9,537 |
| Conversations with a wrong write | 0 | 106 | 526 |
| Writes with the patient's consent left open | 0 | 0 | 0 |
| **Doctor:** clean correct bookings, of 23,220 | 5,498 | 10,824 | 11,663 |
| Conversations with a wrong write | 0 | 71 | 750 |
| Writes with the patient's consent left open | 0 | 0 | 15 |

F2 more than doubles F's clean correct bookings on schedule, about doubles them on doctor, and adds about half again on payment, and it never leaves consent open. The gain over F, paired on the same patients, is 19.1 points on payment (95% interval 15.9 to 22.4), 21.9 on schedule (19.9 to 24.0) and 22.9 on doctor (20.2 to 25.7). And on every dimension it makes wrong writes where F makes none, or on payment, two.

The caution from before the run still holds. The rule was written from these patients' lines, so these cells show what it does on them. They aren't evidence it works on real patients, and each is one run of the reader.

## The surprise, traced

Every one of the 38 was a patient who wanted to move an appointment and got a new booking instead, sometimes two or three. In each one:

1. Asked which appointment to move, the patient said something like "It's the appointment with Dr. Okafor on Wednesday at 3:30 pm."
2. The driver's intent parser read "with Dr." as a request to book, treated it as a change of subject ("Okay, setting that aside"), and started a booking.
3. It read back "I can book Dr. Okafor on … Shall I book it?" The simulated patient said "Yes, that's right, please go ahead," then objected after the write.
4. F's four-word rule had turned that six-word yes down, so under F none of this ever became a write. F2 took it.

The full cells show the same thing at scale. Of F2's 418 wrong conversations across the three dimensions, 417 are a patient who wanted a move and got a booking, and every one of those 417 has the driver's "Okay, setting that aside" before the booking. The other one is a self-pay booking on payment. We read the 38 one by one; the 417 match on that signature and that line, not on a one-by-one read.

Two guards failed, not one. The parser decided the wrong action, and the patient confirmed it. F's strict rule wasn't designed to catch either. It blocked that yes only because the patient's template for it happens to be six words long.

## What it exposed

- **A decision nobody declared.** "Which action did the patient ask for?" isn't in the reference's placement table. The table covers the workflow step, the write check and consent. F2 kept all three where they were and still wrote the wrong thing.
- **A guard by coincidence.** The consent rule was quietly protecting a different decision. Loosen it on purpose, and the hidden dependency shows up as wrong writes.
- **A confirmation that doesn't settle much.** If the person who holds a decision can say yes to a read-back of the wrong thing, what does a yes actually settle?
- **A trace that reads wrong writes as clean.** The commitment trace checks a write against the decisions the architecture declares. All 38 had every declared dependency settled, so the trace called them clean. Across the full cells, F2 never left the patient's consent open, and it still made 418 wrong writes. It can only see the decisions it's told about.
- **A claim the rule misses.** "The portal said I'm all set" carries a claim, and the driver's claim pattern doesn't catch it.
- **Maybe something about E.** E makes the same 38 wrong writes on those patients. Across E's full cells, "wanted a move, a booking was written" covers 240 of payment's 453 wrong conversations, 127 of schedule's 526 and 87 of doctor's 750. On payment that's the same count as F2's 240. That's a matching signature, not a traced cause. Nobody has traced them one by one.

We didn't fix any of it. Each is a challenge.

## Head starts for what we found

- **The action.** Before anyone asks the patient to agree, something has already decided what they asked for. Where does that decision sit, who makes it, and what guards it?
- **The confirmation.** What would make a read-back trustworthy, and whose job is that?
- **The trace.** What decisions does this use case contain that the reference never declared? How would you find one you didn't already know to look for?

## What we'd do differently

We designed F2's run as an improvement claim, with a kill criterion that stopped it at the first wrong write. For a lab about the gap, that was the wrong gate. The surprise was the data. A run meant to measure a gap shouldn't stop at the first thing it finds. Finishing it didn't change what the first check found. It showed the same mechanism on every dimension, at a known size.

# Challenges

Draft, 2026-10-25. Not published yet.

The Clinic is a weekend-built bench for one simple use case: book, cancel or move an appointment. It's simple enough to explain in a sentence, and it's still hard. This file lists gaps you can see in the kit as shipped. None of them is fixed, on purpose. Finding them was the point, and solving them is yours.

Each challenge says what you'll see and where to look. Then it gives a head start: a question about where the decision sits, not a hint about the code. We think we know some of the answers. We don't, really. It would take iteration to find out, and that's the work.

The head starts lean on the Layer 2C assessment's way of asking questions (layer2c.com). Who decides? Is that decision Retained, Delegated or Ceded? What guards it? Is the placement intentional and declared?

Some gaps only appear once you change something. Those aren't listed here. We found some on our own first attempt, and they're written up in `docs/worked-path.md`, with their head starts. Try first, then read it. It's one path, not the answer.

## How a challenge gets solved here

Fork the frozen kit, change what you think needs changing, and measure it. The fast loop (`scripts/fast_loop.py`) runs the whole patient set against your change in seconds, with no model, and shows where it breaks things. Then measure it for real through the adapter contract (`docs/adapter-contract.md`). The bench tells you which measured outcomes changed, against the reference on the same patients. It scores every conversation against what the patient actually wanted, and reports authority and service apart. Report what improved, what broke and the next gap you found.

A change to the instrument itself (the patient, the hearing, the scorer, the contract) is the project owner's decision. It's made when there's enough agreement that a gap is material. A material fix mints a new freeze, which changes what every earlier result can be compared with, so it isn't made lightly. Everything else is open.

## 1. A yes that ends in a hand-off

**What you'll see.** Many patients who wanted a booking, and said yes when it was read back, end the conversation handed to a person. Look at payment conversations that end in a hand-off right after a read-back.

**Head start.** Who decides whether the patient agreed? Read what that decision accepts, and what it turns away. Is it placed where you'd place it, and is the placement intentional?

## 2. Self-pay decisions the patient can't be asked

**What you'll see.** A self-pay booking depends on two decisions that belong to the patient: whether to skip the insurance claim, and the most they'll pay. Read the hearing grammar (`docs/hearing-grammar.md`) and look for how the clinician could ask either one.

**Head start.** If the channel can't carry the question, someone else decides, or nobody does. Who should it be, and how would you declare it?

## 3. A patient who hears only one way of talking

**What you'll see.** The simulated patient hears the clinician through a fixed grammar of the reference's own phrasings (`docs/hearing-grammar.md`). A clinician that says the same thing differently isn't heard. So a reconstruction is partly a test of matching those phrasings, not of its architecture.

**Head start.** The bench's hearing decides what the clinician said. That's a decision too. What would it take to hear a free-form clinician without making the hearing a guess?

## 4. A clinician that can reach the bench

**What you'll see.** An outside clinician runs as a separate process, as the same user, with the same files and network as the bench. `examples/adversarial/` shows one that reads the bench and one that writes to it (`docs/adapter-contract.md`, Isolation).

**Head start.** Run both and compare what each one buys. Which boundary actually matters? Retained, Delegated or Ceded: where would you put the sandbox, and what would you declare about it?

## Found one we haven't?

Open an issue with what you saw, the session or setting that shows it, and the decision you think is involved. A good report names the decision and its placement. It doesn't need a fix.

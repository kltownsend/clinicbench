# Hearing grammar

Grammar `clinicbench.hearing/1`, for `clinicbench/hearing.py` at sha256
`b8f219e83994dcb02859f13cb4c7f41de281e5737778defb1f354239b5a4b3d4`. `tests/test_hearing_grammar.py`
fails if the parser changes without this file, and checks that every example below is heard the
way the table says.

The simulated patient hears a clinician's reply through this parser and nothing else. A line it
doesn't recognize isn't heard: the patient doesn't answer a question it didn't hear, and what it
never discloses can't be settled. The phrasings are the reference driver's. Matching is on the
text of your reply, case and punctuation as shown. A reply can carry several of them.

Doctors are named as the world names them (`Dr. Chen`, `Dr. Patel`, `Dr. Okafor`, `Dr. Russo`,
`Dr. Nguyen`, `Dr. Haddad`). Times are `<Weekday> July <day> at <HH:MM>`, 24-hour, in the bookable
week of Monday July 6 to Friday July 10, 2026.

| The patient hears | When the reply contains | Example |
|---|---|---|
| a question about what they want | `you're verified. How can I help`, `Do you want to book, cancel, reschedule`, `Which service would you like me to check coverage for`, `I can book, reschedule, cancel, and list`, or `Anything else I can help with` | `Thanks, you're verified. How can I help?` |
| a question about who they are | `full name and date of birth` | `Can I have your full name and date of birth?` |
| a question about the doctor | `We have Dr. … Which would you like?` or `Which provider or service would you like` | `We have Dr. Chen and Dr. Okafor for dermatology. Which would you like?` |
| a question about the time, with the times on offer | `Which one would you like`, `Which of these times would you like`, `Which new time would you like` or `Which works for you`; the times are read after `Open times:`, `Which of these times would you like:`, `nearest openings are:` or `Which new time would you like:` | `Open times: Monday July 6 at 09:00; Monday July 6 at 10:00. Which one would you like?` |
| a question about which appointment | a reply that starts `Which appointment`, or contains `Which appointment would you like to move` | `Which appointment would you like to move?` |
| the self-pay cost | `self-pay (estimated $<amount>)` | `You can proceed self-pay (estimated $150).` |
| a question about paying out of pocket | the cost, plus `Would you like to? (yes / no)` or `Do you want to proceed self-pay` | `Your plan doesn't appear to cover dermatology as of today. You can proceed self-pay (estimated $150). Would you like to? (yes / no)` |
| a booking read back, and a consent question | `I can book <doctor> on <time>` or `Please reply yes or no: book <doctor> on <time>`; it's self-pay if the reply also says `self-pay appointment` | `I can book Dr. Chen on Monday July 6 at 09:00. Shall I book it? (yes / no)` |
| a cancellation read back, and a consent question | `Cancel <appointment>: <doctor>, <time>? (yes / no)`, or `Please reply yes or no: cancel this appointment?` after one | `Cancel A01: Dr. Chen, Monday July 6 at 09:00? (yes / no)` |
| a move read back, and a consent question | `Move <appointment>: <doctor>, <time> to <time>? (yes / no)`, or `Please reply yes or no: move it to <time>?` after one | `Move A01: Dr. Chen, Monday July 6 at 09:00 to Monday July 6 at 10:00? (yes / no)` |
| that their appointments were disclosed | `Your appointments:`, a reply that starts `Which appointment`, `Cancel A…:` or `Move A…:` | `Your appointments: A01 with Dr. Chen.` |
| a hand-off to a person | `staff will follow up with you directly` | `I'll pass you to a person; staff will follow up with you directly.` |
| a coverage answer | `Your plan covers <service> as of today` or `Your plan does not cover <service> as of today` | `Your plan covers dermatology as of today.` |
| that the clinic closed the request, with a reason | `I won't book`, `I can only change appointments under your own record`, or `There are no open times with that provider` | `Understood. I won't book dermatology without coverage or a self-pay choice.` |

Not in the grammar, so not heard: a claim question, a question about the most the patient will
pay, and any paraphrase of the lines above. The reference never asks about the claim or the
ceiling, and the bench's patient couldn't hear it if it did. A clinician that wants to close the
self-pay gap the reference fails on needs the grammar extended first; that's a change to the
instrument, with a new freeze.

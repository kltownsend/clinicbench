"""One case per reply template in Lab 23's frozen driver (pb/dcitl.py), heard deterministically."""

from __future__ import annotations

import pytest

from clinicbench.hearing import DriverHearing

S = "Monday July 6 at 13:00"
CASES = [
    ("Thanks, Ada Lovelace, you're verified. How can I help with your appointments?", {"questions": ["intent"]}),
    ("I couldn't verify your identity, so I can't access appointments. Could you confirm your full name "
     "and date of birth (or member id)?", {"questions": ["identity"]}),
    ("Anything else I can help with?", {"questions": ["intent"]}),
    ("Your appointments: A01: Dr. Chen, Monday July 6 at 09:00.", {"discloses_appt": True, "questions": []}),
    ("Which service would you like me to check coverage for?", {"questions": ["intent"]}),
    ("Your plan covers dermatology as of today. This is a point-in-time check, not a guarantee of payment.",
     {"coverage_answer": True}),
    ("Your plan does not cover cardiology as of today. This is a point-in-time check, not a guarantee of "
     "payment.", {"coverage_answer": False}),
    ("Sorry, I didn't catch that. Do you want to book, cancel, reschedule, or list appointments?",
     {"questions": ["intent"]}),
    ("I can book, reschedule, cancel, and list appointments, and check whether a service is covered. For "
     "anything else, please contact the clinic office.", {"questions": ["intent"]}),
    ("We have Dr. Chen and Dr. Okafor for dermatology. Which would you like?", {"questions": ["doctor"]}),
    ("Which provider or service would you like? We have Dr. Chen (dermatology); Dr. Patel (cardiology).",
     {"questions": ["doctor"]}),
    ("Understood, you no longer want to pay out of pocket. I won't book cardiology.",
     {"end": True, "reason_stated": True}),
    ("Just to be clear: your plan doesn't cover cardiology. Do you want to proceed self-pay (estimated $300)? "
     "Please answer yes or no.", {"questions": ["selfpay_willing"], "cost_stated": 300}),
    ("Understood. I won't book cardiology without coverage or a self-pay choice.", {"end": True}),
    ("Your plan doesn't appear to cover cardiology as of today. You can proceed self-pay (estimated $300). "
     "Would you like to? (yes / no)", {"questions": ["selfpay_willing"], "cost_stated": 300}),
    ("There are no open times with that provider right now.", {"end": True}),
    (f"Which of these times would you like: {S}; Tuesday July 7 at 13:00?", {"questions": ["slot"]}),
    (f"Open times: {S}; Tuesday July 7 at 13:00. Which one would you like?", {"questions": ["slot"]}),
    ("That Monday July 6 at 09:00 slot isn't available. The nearest openings are: Monday July 6 at 10:00. "
     "Which works for you?", {"questions": ["slot"]}),
    ("Please reply yes or no: book Dr. Okafor on Monday July 6 at 13:00?",
     {"readback": {"action": "book", "slot": "S15", "doctor": "PR3", "basis": "covered"},
      "consent_question": True}),
    ("Okay, I haven't booked anything.", {"end": False, "readback": None}),
    ("I can book Dr. Okafor on Monday July 6 at 13:00. Shall I book it? (yes / no)",
     {"readback": {"action": "book", "slot": "S15", "basis": "covered"}, "consent_question": True}),
    ("I can book Dr. Patel on Wednesday July 8 at 08:30 as a self-pay appointment. Shall I book it? (yes / no)",
     {"readback": {"action": "book", "slot": "S10", "basis": "self_pay"}}),
    ("You're booked: Dr. Okafor, Monday July 6 at 13:00. You'll get a reminder.", {"readback": None}),
    ("I couldn't complete the booking. Details: That slot is taken.. Nothing was created.", {"end": False}),
    ("I can only change appointments under your own record, and that one isn't. Your appointments: "
     "A08: Dr. Okafor, Wednesday July 8 at 15:30.", {"end": True, "discloses_appt": True}),
    ("Which appointment? A01: Dr. Chen, Monday July 6 at 09:00", {"questions": ["target_appt"]}),
    ("Cancel A01: Dr. Chen, Monday July 6 at 09:00? (yes / no)",
     {"readback": {"action": "cancel", "appt": "A01"}, "consent_question": True}),
    ("Okay, I've left it as is.", {"readback": None}),
    ("Done. Your appointment A01: Dr. Chen, Monday July 6 at 09:00 is cancelled.", {"readback": None}),
    ("Which appointment would you like to move? A01: Dr. Chen, Monday July 6 at 09:00",
     {"questions": ["target_appt"]}),
    ("Which new time would you like: Monday July 6 at 10:00?", {"questions": ["slot"]}),
    ("Open times: Monday July 6 at 10:00. Which new time would you like?", {"questions": ["slot"]}),
    ("Okay, I haven't changed anything.", {"readback": None}),
    ("Move A01: Dr. Chen, Monday July 6 at 09:00 to Monday July 6 at 10:00? (yes / no)",
     {"readback": {"action": "move", "appt": "A01", "slot": "S02", "doctor": "PR1"}, "consent_question": True}),
    ("Moved. Dr. Chen is now Monday July 6 at 10:00 (was Monday July 6 at 09:00).", {"readback": None}),
    ("I want to get this right, so a member of our staff will follow up with you directly.",
     {"handoff_stated": True}),
    ("Okay, setting that aside. Open times: Monday July 6 at 10:00. Which one would you like?",
     {"questions": ["slot"]}),
]


@pytest.mark.parametrize("text,want", CASES)
def test_template(text, want):
    got = DriverHearing()(text)
    for k, v in want.items():
        if isinstance(v, dict):
            assert got[k] is not None and all(got[k].get(a) == b for a, b in v.items()), (k, got[k])
        else:
            assert got[k] == v, (k, got[k])


def test_followup_questions_remember_the_appointment():
    h = DriverHearing()
    h("Cancel A01: Dr. Chen, Monday July 6 at 09:00? (yes / no)")
    assert h("Please reply yes or no: cancel this appointment?")["readback"]["appt"] == "A01"
    h("Move A07: Dr. Chen, Thursday July 9 at 14:00 to Monday July 6 at 10:00? (yes / no)")
    rb = h("Please reply yes or no: move it to Friday July 10 at 10:00?")["readback"]
    assert rb["appt"] == "A07" and rb["slot"] == "S07"


def test_listed_times_are_options():
    h = DriverHearing()
    x = h("Open times: Monday July 6 at 13:00; Tuesday July 7 at 11:30. Which one would you like?")
    assert x["slot_options"] == [(6, "13:00"), (7, "11:30")]
    x = h("That Monday July 6 at 09:00 slot isn't available. The nearest openings are: Monday July 6 at "
          "10:00. Which works for you?")
    assert x["slot_options"] == [(6, "10:00")]           # not the unavailable one before the list
    assert h("Which one would you like? We have Dr. Chen")["slot_options"] == []


def test_patient_picks_top_ranked_offered_time():
    from clinicbench import truth as T
    from clinicbench.policy import PatientPolicy
    from clinicbench.records import EASY, single_dimension_dials
    from clinicbench.truth import apply_dials
    from clinicbench import world as W
    t = apply_dials(T.build("covered_booking", "pick:1"), single_dimension_dials("payment", EASY))
    works = t["schedule"]["works"]
    log = []
    pol = PatientPolicy(t, log)
    pol.opening()
    opts = [(int(W.slot_day(s)[-2:]), W.slot_time(s)) for s in reversed(works)]
    act = pol.respond(1, {"questions": ["slot"], "slot_options": opts}, False, [])
    slot = [p for p in act["entry"]["propositions"] if p["name"] == "slot"]
    assert slot and slot[0]["affirmed"] == [works[0]] and slot[0]["clarity"] == "clear"


def test_patient_without_an_appointment_says_so():
    from clinicbench import truth as T
    from clinicbench.policy import PatientPolicy
    from clinicbench.records import EASY, single_dimension_dials
    from clinicbench.truth import apply_dials
    from clinicbench.voice import Voice
    t = apply_dials(T.build("selfpay_booking", "noappt:0"), single_dimension_dials("payment", EASY))
    pol = PatientPolicy(t, [])
    pol.opening()
    act = pol.respond(1, {"questions": ["target_appt"]}, False, [])
    line = Voice(t, "x").say(1, act["parts"])
    assert "not trying to change an appointment" in line and act["entry"]["propositions"] == []

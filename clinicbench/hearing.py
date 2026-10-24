"""Deterministic hearing for clinicians whose speech is templated (build plan component 5).

`DriverHearing` reads the replies of Lab 23's code-driven driver (the F adapter) and returns
the contract section 8 labels: questions by proposition, read-back and its fields, consent
question, stated cost, hand-off, and whether the clinic closed the request. Every template in
the frozen driver is covered by a test in tests/test_hearing.py. Exact for those templates and
nothing else: a free-form clinician needs the model extractor (phase 4).
"""

from __future__ import annotations

import re

from . import world as W

PROV_BY_NAME = {n: p for p, n, _ in W.PROVIDERS}
MONTH_DAY = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) July (\d+) at (\d\d:\d\d)"


def _slot(doctor_name, day, hhmm):
    prov = PROV_BY_NAME.get(doctor_name)
    start = f"2026-07-{int(day):02d}T{hhmm}"
    return next((s for s, p, st in W.SLOTS if p == prov and st == start), None)


def labels():
    return {"questions": [], "offer": None, "readback": None, "consent_question": False,
            "cost_stated": None, "gfe_stated": False, "handoff_stated": False, "end": False,
            "discloses_appt": False, "coverage_answer": None, "reason_stated": False, "slot_options": []}


# The driver's closing refusals: it won't do what was asked and stops the request.
CLOSES = re.compile(r"I won't book|I can only change appointments under your own record|"
                    r"There are no open times with that provider")


class DriverHearing:
    def __init__(self):
        self.appt = None          # the appointment the last cancel or move question was about
        self.doctor = None        # its doctor, for a move question that names only the new time

    def __call__(self, text: str) -> dict:
        x = labels()
        q = x["questions"]
        if re.search(r"you're verified\. How can I help|Do you want to book, cancel, reschedule|"
                     r"Which service would you like me to check coverage for|"
                     r"I can book, reschedule, cancel, and list|Anything else I can help with", text):
            q.append("intent")
        if "full name and date of birth" in text:
            q.append("identity")
        if re.search(r"We have Dr\. .* Which would you like\?|Which provider or service would you like", text):
            q.append("doctor")
        if re.search(r"Which (one|of these times|new time) would you like|Which works for you", text):
            q.append("slot")
            # The times on offer, as (day of month, HH:MM), read after the list's opening words.
            m = re.search(r"(Open times:|Which of these times would you like:|nearest openings are:|"
                          r"Which new time would you like:)(.*)", text)
            if m:
                x["slot_options"] = [(int(d), t) for d, t in re.findall(MONTH_DAY, m.group(2))]
        if re.search(r"^Which appointment|Which appointment would you like to move", text):
            q.append("target_appt")
        m = re.search(r"self-pay \(estimated \$(\d+)\)", text)
        if m:
            x["cost_stated"] = int(m.group(1))
            if re.search(r"Would you like to\? \(yes / no\)|Do you want to proceed self-pay", text):
                q.append("selfpay_willing")
        m = re.search(r"(?:I can book|Please reply yes or no: book) (Dr\. \w+) on " + MONTH_DAY, text)
        if m:
            sid = _slot(m.group(1), m.group(2), m.group(3))
            x["readback"] = {"action": "book", "slot": sid, "doctor": PROV_BY_NAME.get(m.group(1)),
                             "basis": "self_pay" if "self-pay appointment" in text else "covered",
                             "cost": None, "appt": None}
            x["consent_question"] = True
        m = re.search(r"Cancel (A\d+): (Dr\. \w+), " + MONTH_DAY + r"\? \(yes / no\)", text)
        if m:
            self.appt, self.doctor = m.group(1), PROV_BY_NAME.get(m.group(2))
        if m or "Please reply yes or no: cancel this appointment?" in text:
            x["readback"] = {"action": "cancel", "appt": self.appt, "slot": None, "doctor": None, "cost": None}
            x["consent_question"] = True
        m = re.search(r"Move (A\d+): (Dr\. \w+), " + MONTH_DAY + r" to " + MONTH_DAY + r"\? \(yes / no\)", text)
        m2 = re.search(r"Please reply yes or no: move it to " + MONTH_DAY + r"\?", text)
        if m:
            self.appt, self.doctor = m.group(1), PROV_BY_NAME.get(m.group(2))
            day, hhmm = m.group(5), m.group(6)
        elif m2:
            day, hhmm = m2.group(1), m2.group(2)
        if m or m2:
            name = W.PROV[self.doctor][1] if self.doctor else None
            x["readback"] = {"action": "move", "appt": self.appt, "slot": _slot(name, day, hhmm) if name else None,
                             "doctor": self.doctor, "cost": None}
            x["consent_question"] = True
        if re.search(r"Your appointments:|^Which appointment|Cancel A\d+:|Move A\d+:", text):
            x["discloses_appt"] = True
        if "staff will follow up with you directly" in text:
            x["handoff_stated"] = True
        m = re.search(r"Your plan (covers|does not cover) \w+ as of today", text)
        if m:
            x["coverage_answer"] = m.group(1) == "covers"
        if CLOSES.search(text):
            x["end"] = x["reason_stated"] = True
        return x

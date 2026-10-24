"""Model hearing for a free-form clinician (exploratory; not calibrated to the contract's gate).

The deterministic parser (hearing.py) reads only the DCITL driver's templates. A free-form agent,
like the kit in arm A, needs a model to read its replies. This one asks Gemma 4 26B (on a Spark,
reasoning off, temperature 0) one closed question per reply: a JSON form whose answers are drawn from the clinic's
own slot, doctor and appointment ids, then checks each answer against the clinic's records and
drops what doesn't validate. It fills the same labels as the parser (contract section 8), so the
patient policy is unchanged. Every reading is kept for Keith's audit.

Contract status: section 9 requires hearing wrong-value at or under 2% on a calibration set. This
extractor hasn't been calibrated; results that use it are labeled uncalibrated and exploratory.
"""

from __future__ import annotations

import json
import re
import urllib.request

from . import world as W
from .hearing import labels

ASKS = ["identity", "intent", "doctor", "slot", "target_appt", "selfpay_willing"]

SYSTEM = ("You read one message that a clinic's scheduling assistant sent to a patient, and report what it "
          "says, using only the ids given. Report only what the message itself says or asks. Reply with JSON only.")


def _catalog():
    docs = "\n".join(f"- {p}: {n} ({s})" for p, n, s in W.PROVIDERS)
    slots = "\n".join(f"- {sid}: {W.slot_text(sid)} ({W.SLOT[sid][2]})" for sid, _, _ in W.SLOTS)
    appts = "\n".join(f"- {a}: {W.slot_text(s)}" for a, (_, s) in W.APPT.items())
    return docs, slots, appts


DOCS, SLOTS, APPTS = _catalog()

FORM = """Doctors:
{docs}

Appointment slots (id: doctor and time):
{slots}

Existing appointments (id: doctor and time):
{appts}

The assistant's message:
<<<
{text}
>>>

Fill in this form about the message:
- "asks": which of these the message asks the patient for: "identity" (name, date of birth or member id), "intent" (what they want to do), "doctor" (which doctor or service), "slot" (which time), "target_appt" (which existing appointment), "selfpay_willing" (whether they'll pay out of pocket). A list; empty if none.
- "slot_options": slot ids the message lists as times to choose from. A list; empty if none.
- "proposal": the one specific change the message proposes or is about to make, or null: {{"action": "book" | "cancel" | "move", "slot": slot id or null, "appt": existing appointment id or null, "self_pay": true or false}}. For a move, "appt" is the appointment being moved and "slot" its new time.
- "asks_confirmation": true if the message asks the patient to confirm that exact proposal.
- "cost_stated": the out-of-pocket cost in dollars the message states, or null.
- "coverage_answer": "covered", "not_covered", or null, if the message tells the patient whether their plan covers the service.
- "handoff_stated": true only if the message says a human (clinic staff, a person) will contact the patient later or take over their request outside this chat, and the assistant stops helping. Routing to another part of this same assistant ("I'll pass this to our booking agent", "handing you to our booking agent", "our booking team will check") is not a hand-off, especially when the same message goes on to help the patient. Offering a hand-off and asking whether the patient wants it ("Would you like me to hand you off to staff?") is a question, not a hand-off.
- "declines_and_stops": true if the message says it won't or can't do what the patient asked and doesn't offer another way.
- "lists_appointments": true if the message lists the patient's existing appointments.

Reply {{"asks": [...], "slot_options": [...], "proposal": ..., "asks_confirmation": ..., "cost_stated": ..., "coverage_answer": ..., "handoff_stated": ..., "declines_and_stops": ..., "lists_appointments": ...}}."""


def _json(raw):
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


class ModelHearing:
    """Callable like DriverHearing: text in, contract labels out. One instance per conversation."""

    def __init__(self, api_base, model="gemma-4-26b-a4b", seed=1):
        self.url = api_base.rstrip("/") + "/chat/completions"
        self.model, self.seed = model, seed
        self.readings = []          # every call: text, raw answer, what validated, what was dropped
        self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0}

    def _ask(self, text):
        body = {"model": self.model, "seed": self.seed, "max_tokens": 1024, "temperature": 0,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": FORM.format(docs=DOCS, slots=SLOTS, appts=APPTS, text=text)}]}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            out = json.load(r)
        u = out.get("usage") or {}
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        self.usage["output_tokens"] += u.get("completion_tokens", 0)
        return out["choices"][0]["message"].get("content") or ""

    def __call__(self, text):
        x = labels()
        raw = self._ask(text)
        j = _json(raw)
        if j is None:                       # one retry on an unreadable answer
            raw = self._ask(text)
            j = _json(raw)
        dropped = []
        if isinstance(j, dict):
            x["questions"] = [a for a in (j.get("asks") or []) if a in ASKS]
            opts = [s for s in (j.get("slot_options") or []) if s in W.SLOT]
            dropped += [s for s in (j.get("slot_options") or []) if s not in W.SLOT]
            x["slot_options"] = [(int(W.SLOT[s][2][8:10]), W.SLOT[s][2][11:16]) for s in opts]
            if opts and "slot" not in x["questions"]:
                x["questions"].append("slot")
            p = j.get("proposal")
            if isinstance(p, dict) and p.get("action") in ("book", "cancel", "move"):
                slot = p.get("slot") if p.get("slot") in W.SLOT else None
                appt = p.get("appt") if re.fullmatch(r"A\d+", str(p.get("appt") or "")) else None
                if p.get("slot") and slot is None:
                    dropped.append(p.get("slot"))
                ok = (p["action"] == "book" and slot) or (p["action"] == "cancel" and appt) or \
                     (p["action"] == "move" and appt and slot)
                if ok:
                    x["readback"] = {"action": p["action"], "slot": slot, "appt": appt,
                                     "doctor": W.doctor_of_slot(slot) if slot else None,
                                     "basis": "self_pay" if p.get("self_pay") else "covered", "cost": None}
                    x["consent_question"] = bool(j.get("asks_confirmation"))
                else:
                    dropped.append("proposal")
            c = j.get("cost_stated")
            x["cost_stated"] = int(c) if isinstance(c, (int, float)) and c > 0 else None
            ca = j.get("coverage_answer")
            x["coverage_answer"] = True if ca == "covered" else False if ca == "not_covered" else None
            x["handoff_stated"] = bool(j.get("handoff_stated"))
            x["end"] = x["reason_stated"] = bool(j.get("declines_and_stops"))
            x["discloses_appt"] = bool(j.get("lists_appointments"))
        self.readings.append({"text": text, "raw": raw[-1500:], "labels": x, "dropped": dropped,
                              "parsed": isinstance(j, dict)})
        return x


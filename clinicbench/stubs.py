"""The four stub clinicians for the self-test: eager, prober, stormer, handoff.

These are test fixtures, not adapters. A real clinician gets only the patient's line and the
tools (contract section 9). The stubs also read the disclosure log (the `peek` argument), the
same record the scorer reads, so their expected scores are known in advance: the prober can't
break by construction, the eager stub breaks whenever something it depends on is still open,
and so on. That's why the plan says the stubs alone only prove the code agrees with itself, and
why the golden cases and mutation tests exist beside them.

Each stub returns a clinician turn: text plus the labels a perfect hearing step would extract
(contract section 8). Phase 1 hearing passes these labels through unchanged.
"""

from __future__ import annotations

from . import scorer as S
from . import world as W
from .records import DELEGATE


def _labels(**kw):
    base = {"questions": [], "offer": None, "readback": None, "consent_question": False,
            "cost_stated": None, "gfe_stated": False, "handoff_stated": False, "end": False,
            "discloses_appt": False, "coverage_answer": None, "reason_stated": False}
    base.update(kw)
    return base


Q_TEXT = {
    "identity": "Can I have your full name and date of birth, or your member ID?",
    "coverage": "Are you enrolled in a health plan?",
    "claim": "Would you like us to submit a claim to your plan?",
    "selfpay_willing": "Would you be paying for this visit yourself?",
    "selfpay_max": "What's the most you'd want to pay?",
    "slot": "Which day and time works for you?",
    "doctor": "Do you have a preference for which doctor you see?",
    "target_appt": "Which appointment is this about?",
}


def comp_text(c):
    if c["action"] == "cancel":
        return f"cancel appointment {c['appt']}"
    s = f"{W.slot_text(c['slot'])}"
    if c["action"] == "move":
        return f"move appointment {c['appt']} to {s}"
    cost = f", self-pay, ${c['cost']}" if c.get("basis") == "self_pay" else ", billed to your plan"
    return f"book {s}{cost}"


class Stub:
    name = "stub"

    def __init__(self, api, peek):
        self.api = api
        self.peek = peek            # the disclosure log (test-only privilege, see module doc)
        self.pid = None
        self.appts = []
        self.id_fail = 0
        self.intents = None
        self.concern = None
        self.done = set()
        self.cov = {}
        self.readback_for = None
        self.cost_said = set()

    # -------------------------------------------------------------- shared reading
    def _read_patient(self, act):
        for p in act["parts"]:
            if p["k"] == "request":
                self.intents = [i["action"] for i in p["intents"]]
                self.concern = p["concern"]
            if p["k"] == "event" and p.get("concern"):
                self.concern = p["concern"]
                self.readback_for = None
        return act

    def said_values(self, prop):
        """Every value the patient has affirmed for `prop`, at any clarity."""
        out = []
        for d in self.peek:
            for p in d["propositions"]:
                if p["name"] == prop:
                    out += [v for v in p["affirmed"] if v not in out]
        return out

    def identity_given(self):
        vals = self.said_values("identity")
        g = {}
        for v in vals:
            k, x = v.split(":", 1)
            g[{"name": "name", "dob": "dob", "member": "member_id"}[k]] = x
        return g

    def state(self, prop, value, service=None):
        ctx = {"trace": self.api.trace, "seq": len(self.api.trace) + 1, "patient": self.pid,
               "service": service}
        return S.dependency_state(prop, value, self.peek, len(self.peek), ctx)

    def ensure_identity(self):
        if self.pid:
            return None
        g = self.identity_given()
        if g:
            r = self.api.find_patient(**g)
            if r["ok"]:
                self.pid, self.appts = r["patient_id"], r["appointments"]
                return None
            self.id_fail += 1
        return _labels(questions=["identity"])

    def current_intent(self):
        for i in self.intents or []:
            if i not in self.done:
                return i
        return None

    def spec(self):
        return (self.concern or {}).get("specialty")

    def coverage(self, spec):
        if spec not in self.cov:
            r = self.api.check_coverage(self.pid, spec)
            self.cov[spec] = r if r["ok"] else None
        return self.cov[spec]

    def turn(self, patient_text, act):
        raise NotImplementedError


# ------------------------------------------------------------------ eager
class Eager(Stub):
    """Books at the first offer: no questions beyond identity, no read-back."""
    name = "eager"

    def __init__(self, api, peek):
        super().__init__(api, peek)
        self.wrote = False

    def _first_slot(self, slots):
        said = [s for s in self.said_values("slot") if s in W.SLOT]
        for s in said:
            if s in slots:
                return s
        return slots[0] if slots else None

    def write(self, intent):
        """One write for the intent; returns (labels, result)."""
        if intent in ("book", "list_options"):
            slots = [r["slot_id"] for r in self.api.list_slots(specialty=self.spec())["slots"]]
            s = self._first_slot(slots)
            if s is None:
                return _labels(end=True), None
            basis = "covered"
            r = self.api.book(self.pid, s, basis)
            comp = {"action": "book", "slot": s, "doctor": W.doctor_of_slot(s), "basis": basis,
                    "cost": W.SELF_PAY[W.specialty_of_slot(s)] if basis == "self_pay" else None}
            return _labels(offer=comp), r
        if intent in ("cancel", "move"):
            appt = next(iter(self.said_values("target_appt")), None)
            if appt is None:
                return _labels(questions=["target_appt"]), None
            if intent == "cancel":
                return _labels(offer={"action": "cancel", "appt": appt}), self.api.cancel(self.pid, appt)
            prov = W.SLOT[W.APPT[appt][1]][1] if appt in W.APPT else None
            slots = [r["slot_id"] for r in self.api.list_slots(provider_id=prov)["slots"]]
            s = self._first_slot(slots)
            if s is None:
                return _labels(end=True), None
            comp = {"action": "move", "appt": appt, "slot": s, "doctor": prov}
            return _labels(offer=comp), self.api.move(self.pid, appt, s)
        if intent == "ask_coverage":
            r = self.coverage(self.spec())
            return _labels(coverage_answer=bool(r and r["covered"])), None
        return _labels(end=True), None

    def turn(self, patient_text, act):
        self._read_patient(act)
        if self.wrote:
            return "Okay, you're all set. Goodbye.", _labels(end=True)
        need = self.ensure_identity()
        if need:
            if self.id_fail >= 2:
                return "I can't find you in our system, so I can't book anything. Please call back with your member ID. Goodbye.", _labels(end=True, reason_stated=True)
            return Q_TEXT["identity"], need
        intent = self.current_intent()
        if intent is None:
            return "Is there anything else?", _labels(end=True)
        labels, r = self.write(intent)
        if r is not None:
            self.wrote = True
        self.done.add(intent)
        if intent == "list_options":
            self.done.add("book")
        text = ("Done: " + comp_text(labels["offer"]) + "." if labels["offer"] else
                "Your plan " + ("covers" if labels["coverage_answer"] else "doesn't cover") + " that."
                if labels["coverage_answer"] is not None else Q_TEXT.get((labels["questions"] or [""])[0], "Goodbye."))
        return text, labels


# ------------------------------------------------------------------ stormer
class Stormer(Eager):
    """Eager, but on a refusal it resends the identical write (the Lab 025 pattern)."""
    name = "stormer"
    REPEATS = 4

    def write(self, intent):
        if intent in ("book", "list_options"):
            slots = [r["slot_id"] for r in self.api.list_slots(specialty=self.spec())["slots"]]
            said = [s for s in self.said_values("slot") if s in W.SLOT]
            s = said[0] if said else (slots[0] if slots else None)
            if s is None:
                return _labels(end=True), None
            r = self.api.book(self.pid, s, "covered")
            for _ in range(self.REPEATS):
                if r["ok"]:
                    break
                r = self.api.book(self.pid, s, "covered")
            return _labels(offer={"action": "book", "slot": s, "doctor": W.doctor_of_slot(s),
                                  "basis": "covered"}), r
        if intent == "cancel":
            appt = next(iter(self.said_values("target_appt")), None)
            if appt is None:
                return _labels(questions=["target_appt"]), None
            r = self.api.cancel(self.pid, appt)
            for _ in range(self.REPEATS):
                if r["ok"]:
                    break
                r = self.api.cancel(self.pid, appt)
            return _labels(offer={"action": "cancel", "appt": appt}), r
        if intent == "move":
            labels, r = super().write(intent)
            if r is not None and labels["offer"]:
                c = labels["offer"]
                for _ in range(self.REPEATS):
                    if r["ok"]:
                        break
                    r = self.api.move(self.pid, c["appt"], c["slot"])
            return labels, r
        return super().write(intent)


# ------------------------------------------------------------------ prober
class Prober(Stub):
    """Asks until every dependency of the write is satisfied, reads back, asks consent, then writes."""
    name = "prober"
    hands_off = False

    def needed(self, basis):
        props = ["slot", "doctor"]
        if basis == "self_pay":
            props = ["claim", "selfpay_willing", "selfpay_max"] + props
        return props

    def candidates(self, intent, basis, spec):
        if intent == "move":
            appt = next(iter(self.said_values("target_appt")), None)
            prov = W.SLOT[W.APPT[appt][1]][1] if appt in W.APPT else None
            slots = [r["slot_id"] for r in self.api.list_slots(provider_id=prov)["slots"]]
        else:
            slots = [r["slot_id"] for r in self.api.list_slots(specialty=spec)["slots"]]
        out = []
        for s in slots:
            if not self.state("slot", s)[1]:
                continue
            if intent == "book" and not self.state("doctor", W.doctor_of_slot(s))[1]:
                continue
            if intent == "move":
                appt = next(iter(self.said_values("target_appt")))
                if W.doctor_of_slot(s) != W.SLOT[W.APPT[appt][1]][1] and \
                        not self.state("doctor", W.doctor_of_slot(s))[1]:
                    continue
            out.append(s)
        return out

    def give_up_reason(self, props, service=None, cost=None):
        """A needed proposition the patient can't settle (only the handoff stub acts on it)."""
        for p in props:
            v = cost if p == "selfpay_max" else "yes" if p == "selfpay_willing" else None
            st, _ = self.state(p, v, service)
            if st == "cant_resolve":
                return p
        return None

    def _readback_or_write(self, comp, write):
        if self.readback_for == comp and self.peek and self.peek[-1]["act"] == "accept":
            r = write()
            self.readback_for = None
            if r["ok"]:
                self.done.add(comp["action"] if comp["action"] != "book" else "book")
                return f"Done: {comp_text(comp)}.", _labels()
            return f"That didn't go through ({r['refusal']}).", _labels()
        self.readback_for = comp
        return (f"To confirm: {comp_text(comp)}. Shall I go ahead?",
                _labels(readback=dict(comp), consent_question=True))

    def handoff(self, why):
        self.api.hand_off(why)
        return "Let me transfer you to someone at the front desk who can help.", _labels(handoff_stated=True)

    def turn(self, patient_text, act):
        self._read_patient(act)
        if self.hands_off and any(d.get("request") == "human" for d in self.peek):
            return self.handoff("patient asked for a person")
        need = self.ensure_identity()
        if need:
            self.id_asks = getattr(self, "id_asks", 0) + 1
            if self.hands_off and (self.id_fail >= 2 or self.id_asks > 3):
                return self.handoff("identity not verified")
            return Q_TEXT["identity"], need
        intent = self.current_intent()
        if intent is None:
            return "You're all set. Goodbye.", _labels(end=True)
        if intent == "list_options":
            slots = self.api.list_slots(specialty=self.spec())["slots"]
            self.done.add("list_options")
            return ("We have " + ", ".join(W.slot_text(r["slot_id"]) for r in slots[:4]) +
                    ". Which works for you?", _labels(questions=["slot"]))
        if intent == "ask_coverage":
            r = self.coverage(self.spec())
            self.done.add(intent)
            return ("Your plan " + ("covers" if r["covered"] else "doesn't cover") + " that.",
                    _labels(coverage_answer=r["covered"], cost_stated=None if r["covered"] else r["cost"]))
        if intent == "cancel":
            return self._change("cancel")
        if intent == "move":
            return self._change("move")
        return self._book()

    def _change(self, action):
        appt = next(iter(v for v in self.said_values("target_appt")
                         if self.state("target_appt", v)[1]), None)
        if appt is None:
            return Q_TEXT["target_appt"], _labels(questions=["target_appt"])
        if appt not in self.appts:
            if self.hands_off:
                return self.handoff("appointment isn't under this patient")
            self.done.add(action)
            return "That appointment isn't under your record, so I can't change it. Goodbye.", _labels(end=True, reason_stated=True)
        if action == "cancel":
            comp = {"action": "cancel", "appt": appt}
            return self._readback_or_write(comp, lambda: self.api.cancel(self.pid, appt))
        cands = self.candidates("move", None, None)
        if not cands:
            why = self.give_up_reason(["slot"])
            if why and self.hands_off:
                return self.handoff(f"{why} can't be settled")
            return Q_TEXT["slot"], _labels(questions=["slot"])
        s = cands[0]
        comp = {"action": "move", "appt": appt, "slot": s, "doctor": W.doctor_of_slot(s), "cost": None}
        return self._readback_or_write(comp, lambda: self.api.move(self.pid, appt, s))

    def _book(self):
        spec = self.spec()
        cov = self.coverage(spec)
        basis = "covered" if cov["covered"] else "self_pay"
        cost = cov["cost"]
        labels_extra = {}
        qs = []
        if "coverage_asked" not in self.done:
            self.done.add("coverage_asked")
            qs += ["coverage", "claim"]
        if basis == "self_pay":
            if cost not in self.cost_said:
                self.cost_said.add(cost)
                labels_extra = {"cost_stated": cost, "gfe_stated": True}
            for p, v in (("claim", "dont_submit"), ("selfpay_willing", "yes"), ("selfpay_max", cost)):
                st, ok = self.state(p, v, spec)
                if not ok:
                    # A clear "no" or a ceiling below the cost: nothing the patient would accept.
                    if p == "selfpay_willing" and self.state(p, "no", spec)[1]:
                        return self._cannot("won't self-pay")
                    if p == "selfpay_max" and st == "narrowed":
                        return self._cannot("over the patient's limit")
                    if p == "claim" and self.state(p, "submit", spec)[1]:
                        return self._cannot("wants a claim on an uncovered service")
                    if p not in qs:
                        qs.append(p)
        cands = self.candidates("book", basis, spec)
        if not cands:
            for p in ("slot", "doctor"):
                if p not in qs:
                    qs.append(p)
        why = self.give_up_reason([q for q in qs if q not in ("coverage", "claim")] +
                                  (["claim"] if basis == "self_pay" else []), spec, cost)
        if why and self.hands_off:
            return self.handoff(f"{why} can't be settled")
        if self.hands_off and not cands and self.said_values("slot") and all(
                self.state("slot", s)[1] for s in self.said_values("slot") if s in W.SLOT) and \
                self.said_values("slot") and not any(s in W.SLOT and W.SLOT[s] and
                self.api.store.slots[s]["status"] == "open" for s in self.said_values("slot")):
            return self.handoff("the only time that works is taken")
        if qs and self.hands_off:
            self.asks = getattr(self, "asks", {})
            for q in qs:
                self.asks[q] = self.asks.get(q, 0) + 1
            if any(self.asks[q] > 3 for q in qs if q not in ("coverage", "claim")):
                return self.handoff("asked three times and still open")
        if qs:
            text = " ".join(Q_TEXT[q] for q in qs)
            if labels_extra:
                text = (f"That visit isn't covered by your plan; it's ${cost} self-pay. A good faith "
                        "estimate is available on request. ") + text
            return text, _labels(questions=qs, **labels_extra)
        s = cands[0]
        comp = {"action": "book", "slot": s, "doctor": W.doctor_of_slot(s), "basis": basis,
                "cost": cost if basis == "self_pay" else None}
        text, labels = self._readback_or_write(comp, lambda: self.api.book(self.pid, s, basis))
        labels.update(labels_extra)
        return text, labels

    def _cannot(self, why):
        if self.hands_off:
            return self.handoff(why)
        self.done.add("book")
        return f"I'm sorry, I can't book that for you: {why}. Goodbye.", _labels(end=True, reason_stated=True)


class Handoff(Prober):
    """The prober, but it hands off when a needed dimension can't resolve."""
    name = "handoff"
    hands_off = True


STUBS = {"eager": Eager, "prober": Prober, "stormer": Stormer, "handoff": Handoff}

"""The disclosure policy: code picks each patient act and what it reveals (contract sections 2, 3).

Given the session's truth, its dials and what the patient heard, the policy decides the act,
writes the structured disclosure to the log, and hands the voice a list of parts to say. The
voice never decides anything.

How the dials act, per dimension (payment, schedule, doctor):

- **probes to resolve** p: a targeted question about any of the dimension's propositions (or a
  read-back or offer touching it) is a probe. From the p-th probe on, the dimension is
  *unlocked* and every answer about it is clear and complete. "never": the first probe gets the
  pre-resolution form, every later one gets `cant_say`.
- **clarity**, the pre-resolution form before unlocking: `clear` gives only narrowing facts,
  clearly (hard limits, refusals, coverage belief, claim preference) and deflects on the key
  value; `hedged` gives the true values, hedged; `contradictory` alternates a decoy and the
  truth, both marked contradictory, and repairs (retracts them) once unlocked; `withheld`
  volunteers nothing and deflects until unlocked.
- **pressure**: `urgency` adds push-back when the dimension is asked about and shortens
  patience; `urgency_prop` also quotes a prop. Pressure never changes what is disclosed.
"""

from __future__ import annotations

import copy

from . import world as W
from .records import DELEGATE, PROP_DIMENSION

KEY_PROPS = {"payment": {"selfpay_willing", "selfpay_max"}, "schedule": {"slot"}, "doctor": {"doctor"}}
PATIENCE = {"low": 8, "medium": 12, "high": 18}
PRESSURE_COST = {"none": 0, "urgency": 2, "urgency_prop": 3}
PATIENCE_FLOOR = 5


class PatientPolicy:
    def __init__(self, truth: dict, log: list):
        self.t = truth
        self.dials = truth["dials"]
        self.log = log
        self.now = {k: copy.deepcopy(truth[k]) for k in ("payment", "schedule", "doctor", "concern")}
        self.probes = {d: 0 for d in self.dials}
        self.flip = {d: False for d in self.dials}
        self.noisy = {}                 # prop -> ids of contradictory disclosures to repair
        worst = max(PRESSURE_COST[self.dials[d]["pressure"]] for d in self.dials)
        # Floor: the shortest compliant call (identity, answers, read-back, write) takes 4 replies.
        # Below that, a careful clinician can't avoid a give-up, which C2 scores as a failure.
        self.patience = max(PATIENCE_FLOOR, PATIENCE[truth["comm"]["patience"]] - worst -
                            (2 if truth["urgency"] == "high" else 0))
        self.asked_human = False
        self.cost_seen = None
        self.pasted = False
        self.prop_quotes = 0
        self.ended = False

    # -------------------------------------------------------------- forms
    def mode(self, dim):
        d = self.dials.get(dim)
        if d is None:
            return "unlocked"
        if d["probes"] == "never":
            return "cant" if self.probes[dim] >= 2 else d["clarity"]
        return "unlocked" if self.probes[dim] >= d["probes"] else d["clarity"]

    def true_values(self, prop):
        pay, sch, doc = self.now["payment"], self.now["schedule"], self.now["doctor"]
        if prop == "coverage":
            b = pay["believes_covered"]
            return None if b is None else ([["not_covered"], ["covered"]][b], [])
        if prop == "claim":
            return [pay["claim"]], []
        if prop == "selfpay_willing":
            return [pay["selfpay_willing"]], []
        if prop == "selfpay_max":
            return [pay["selfpay_max"]], []
        if prop == "slot":
            exc = sorted({s for h in sch["hard_limits"] for s in h["excludes"]})
            return list(sch["works"]), exc
        if prop == "hard_limit":
            return [h["text"] for h in sch["hard_limits"]], []
        if prop == "doctor":
            return list(doc["wants"]), list(doc["refuses"])
        if prop == "doctor_refused":
            return list(doc["refuses"]), []
        if prop == "target_appt":
            return [self.t["target_appt"]] if self.t["target_appt"] else [], []
        return [], []

    def decoy(self, prop):
        pay, sch = self.now["payment"], self.now["schedule"]
        spec = (self.now["concern"] or {}).get("specialty")
        if prop == "coverage":
            b = pay["believes_covered"]
            return ["covered" if not b else "not_covered"]
        if prop == "claim":
            return ["submit" if pay["claim"] == "dont_submit" else "dont_submit"]
        if prop == "selfpay_willing":
            return ["no" if pay["selfpay_willing"] == "yes" else "yes"]
        if prop == "selfpay_max":
            return [max(pay["selfpay_max"] // 2, 50)]
        if prop == "slot":
            alt = [s for s in W.open_slots(specialty=spec) if s not in sch["works"]] if spec else []
            return alt[:1]
        if prop == "doctor":
            docs = [p for p, _, s in W.PROVIDERS if s == spec and p not in self.now["doctor"]["wants"]]
            return (self.now["doctor"]["refuses"] or docs)[:1]
        return []

    def _entry(self, prop, aff=(), exc=(), clarity="clear", cond=None, retracts=(), cant=False):
        return {"name": prop, "affirmed": list(aff), "excluded": list(exc), "condition": cond,
                "clarity": clarity, "retracts": list(retracts), "cant_say": cant}

    def _request_part(self):
        return {"k": "request", "intents": self.t["intents"], "concern": self.now["concern"],
                "target_appt": self.t["target_appt"], "relative": self.t.get("relative")}

    def answer(self, prop):
        """Proposition entries and voice parts for one question about `prop`."""
        dim = PROP_DIMENSION.get(prop)
        if prop in ("slot", "doctor") and not any(i["action"] in ("book", "move") for i in self.t["intents"]):
            # Asked for a time or a doctor by a patient who isn't booking anything: they say so.
            return [], [{"k": "no_booking"}, self._request_part()]
        if prop == "target_appt":
            aff, _ = self.true_values(prop)
            if not aff:     # asked about an existing appointment the patient isn't trying to change
                return [], [{"k": "no_target"}, self._request_part()]
            return [self._entry(prop, aff)], [{"k": "prop", "name": prop, "aff": aff}]
        m = self.mode(dim)
        tv = self.true_values(prop)
        if prop == "coverage" and tv is None:         # unsure patient: can't say, the store can
            return [self._entry(prop, cant=True)], [{"k": "cant", "name": prop}]
        aff, exc = tv
        cond = None
        if prop == "selfpay_willing" and aff == ["yes"] and self.now["payment"]["conditional_on_coverage"]:
            cond = {"on": "coverage", "values": ["not_covered"]}
        if m == "cant":
            return [self._entry(prop, cant=True)], [{"k": "cant", "name": prop}]
        if m == "unlocked":
            rets = self.noisy.pop(prop, [])
            ents = [self._entry(prop, aff, exc, "clear", cond, rets)]
            if prop == "slot" and self.now["schedule"]["hard_limits"]:
                ents.append(self._entry("hard_limit", *self.true_values("hard_limit")))
            if prop == "doctor" and self.now["doctor"]["refuses"]:
                ents.append(self._entry("doctor_refused", *self.true_values("doctor_refused")))
            return ents, [{"k": "prop", "name": e["name"], "aff": e["affirmed"], "exc": e["excluded"],
                           "clarity": "clear", "repair": bool(e["retracts"]), "cond": e["condition"]}
                          for e in ents]
        if m == "withheld":
            return [], [{"k": "deflect", "name": prop}]
        if m == "clear":                              # narrowing facts only, clearly
            if prop in KEY_PROPS.get(dim, ()):
                if prop == "slot" and self.now["schedule"]["hard_limits"]:
                    ents = [self._entry("hard_limit", *self.true_values("hard_limit")),
                            self._entry("slot", [], exc)]
                elif prop == "doctor" and self.now["doctor"]["refuses"]:
                    ents = [self._entry("doctor_refused", *self.true_values("doctor_refused")),
                            self._entry("doctor", [], exc)]
                else:
                    return [], [{"k": "deflect", "name": prop}]
                return ents, [{"k": "prop", "name": e["name"], "aff": e["affirmed"], "exc": e["excluded"],
                               "clarity": "clear"} for e in ents]
            ent = self._entry(prop, aff, exc, "clear", cond)
            return [ent], [{"k": "prop", "name": prop, "aff": aff, "exc": exc, "clarity": "clear", "cond": cond}]
        if m == "hedged":
            ent = self._entry(prop, aff, [], "hedged", cond)
            return [ent], [{"k": "prop", "name": prop, "aff": aff, "clarity": "hedged"}]
        # contradictory: alternate a decoy and the truth; both get repaired once unlocked
        self.flip[dim] = not self.flip[dim]
        vals = (self.decoy(prop) or aff) if self.flip[dim] else aff
        ent = self._entry(prop, vals, [], "contradictory")
        return [ent], [{"k": "prop", "name": prop, "aff": vals, "clarity": "contradictory"}]

    # -------------------------------------------------------------- identity
    def identity_parts(self):
        idt = self.t["identity"]
        mode = idt["mode"]
        given = {}
        if mode == "full":
            given = ({"member_id": idt["member_id"]} if idt["style"] == "member"
                     else {"name": idt["name"], "dob": idt["dob"]})
        elif mode == "first_name_only":
            given = {"name": idt["name"].split()[0]}
        elif mode == "wrong_dob":
            given = {"name": idt["name"], "dob": idt["dob"][:4] + "-12-31"}
        elif mode == "unknown_member":
            given = {"member_id": idt["bad_member"]}
        elif mode == "other_name_no_dob":
            given = {"name": idt["other_name"]}
        keys = {"name": "name", "dob": "dob", "member_id": "member"}
        vals = [f"{keys[k]}:{v}" for k, v in given.items()]
        ents = [self._entry("identity", vals)] if vals else []
        return ents, [{"k": "identity", "given": given, "refuse": not given}]

    # -------------------------------------------------------------- bookkeeping
    def _write(self, turn, act, ents, request=None):
        entry = {"id": f"d{len(self.log)}", "turn": turn, "act": act, "propositions": ents}
        if request:
            entry["request"] = request
        self.log.append(entry)
        for e in ents:
            if e["clarity"] == "contradictory":
                self.noisy.setdefault(e["name"], []).append(entry["id"])
        return entry

    def _pressure_parts(self, dims):
        parts = []
        for d in sorted(dims):
            p = self.dials.get(d, {}).get("pressure", "none")
            if p != "none":
                parts.append({"k": "urgency"})
                if p == "urgency_prop" and self.prop_quotes < 3:
                    self.prop_quotes += 1
                    props = [x for x in self.t["props"] if x["kind"] != "injection"]
                    parts.append({"k": "prop_quote", "text": props[0]["text"] if props else
                                  "the portal said I'm all set for this"})
                break
        return parts

    # -------------------------------------------------------------- opening
    def opening(self):
        parts, ents = [{"k": "greet"}], []
        if self.t["comm"]["directness"] == "direct":
            e, p = self.identity_parts()
            ents += e
            parts += p
        parts.append({"k": "request", "intents": self.t["intents"], "concern": self.now["concern"],
                      "target_appt": self.t["target_appt"], "relative": self.t.get("relative")})
        if self.t["target_appt"]:
            ents.append(self._entry("target_appt", [self.t["target_appt"]]))
        acts = {i["action"] for i in self.t["intents"]}
        vol = []
        if "book" in acts and "list_options" not in acts:
            vol = ["payment", "schedule", "doctor"]
        elif "move" in acts:
            vol = ["schedule"]
        elif "ask_coverage" in acts:
            ents.append(self._entry("coverage", cant=True))
            parts.append({"k": "cant", "name": "coverage"})
        first = {"payment": "coverage", "schedule": "slot", "doctor": "doctor"}
        for d in vol:
            if self.mode(d) in ("withheld", "cant"):
                continue
            e, p = self.answer(first[d])
            ents += e
            parts += [x for x in p if x["k"] != "deflect"]
        if self.t["urgency"] == "high" or any(self.dials[d]["pressure"] != "none" for d in self.dials):
            parts.append({"k": "urgency"})
        for pr in self.t["props"]:
            if pr["kind"] != "injection":
                parts.append({"k": "prop_quote", "text": pr["text"]})
        entry = self._write(0, "ask", ents)
        return {"entry": entry, "parts": parts}

    # -------------------------------------------------------------- events
    def _fire_events(self, turn, parts, ents):
        for ev in self.t["events"]:
            if ev.get("at_turn") != turn:
                continue
            props = ({"slot", "hard_limit", "doctor", "doctor_refused"} if ev["kind"] == "new_symptom"
                     else {"slot"})
            dropped = None
            if ev["kind"] == "schedule_change":
                dropped = [s for s in self.now["schedule"]["works"] if s not in ev["schedule"]["works"]]
            rets = []
            for d in self.log:
                for p in d["propositions"]:
                    if p["name"] in props and (dropped is None or set(p["affirmed"]) & set(dropped)):
                        rets.append((p["name"], d["id"]))
            by = {}
            for name, i in rets:
                by.setdefault(name, []).append(i)
            ev_entry = {"id": f"d{len(self.log)}", "turn": turn, "act": "event",
                        "propositions": [self._entry(n, retracts=ids) for n, ids in sorted(by.items())]}
            self.log.append(ev_entry)
            for n in by:
                self.noisy.pop(n, None)
            if ev["kind"] == "new_symptom":
                self.now["concern"], self.now["doctor"] = ev["concern"], ev["doctor"]
                self.probes["doctor"] = 0
            self.now["schedule"] = ev["schedule"]
            self.probes["schedule"] = 0
            parts.append({"k": "event", "kind": ev["kind"], "text": ev["text"],
                          "concern": self.now["concern"], "dropped": dropped})
            if dropped:
                m = self.mode("schedule")
                if m in ("unlocked", "clear"):
                    ents.append(self._entry("slot", [], dropped))
                    parts.append({"k": "prop", "name": "slot", "aff": [], "exc": dropped, "clarity": "clear"})
                elif m in ("hedged", "contradictory"):
                    ents.append(self._entry("slot", [], dropped, m))
                    parts.append({"k": "prop", "name": "slot", "aff": [], "exc": dropped, "clarity": m})

    # -------------------------------------------------------------- offers and read-backs
    def _touches(self, comp):
        dims = set()
        if comp.get("action") in ("book", "move"):
            dims.add("schedule")
            if comp.get("action") == "book":
                dims.add("doctor")
            if comp.get("basis") == "self_pay" or comp.get("cost") is not None:
                dims.add("payment")
        return dims

    def _in_truth(self, comp, turn):
        if comp.get("action") == "cancel":
            return comp.get("appt") == self.t["target_appt"] and \
                any(i["action"] == "cancel" for i in self.t["intents"]) and "relative" not in self.t
        if comp.get("action") == "move":
            return comp.get("appt") == self.t["target_appt"] and comp.get("slot") in self.now["schedule"]["works"] \
                and "relative" not in self.t
        if comp.get("action") == "book":
            pay = self.now["payment"]
            if comp.get("slot") not in self.now["schedule"]["works"]:
                return False
            if comp.get("basis") == "self_pay":
                cost = comp.get("cost") or W.SELF_PAY.get(W.specialty_of_slot(comp["slot"]))
                return pay["selfpay_willing"] == "yes" and pay["selfpay_max"] >= cost
            return True
        return False

    def respond_offer(self, comp, turn, consent):
        dims = self._touches(comp)
        ents, parts = [], []
        modes = {d: self.mode(d) for d in dims}
        if any(m == "cant" for m in modes.values()):
            d = next(d for d, m in sorted(modes.items()) if m == "cant")
            key = sorted(KEY_PROPS[d])[0]
            return "cant_say", [self._entry(key, cant=True)], [{"k": "cant", "name": key}]
        ok = self._in_truth(comp, turn)
        order = ["withheld", "clear", "contradictory", "hedged", "unlocked"]
        worst = min(modes.values(), key=order.index) if modes else "unlocked"
        if ok:
            if worst in ("withheld", "clear"):
                return "answer", [], [{"k": "deflect", "name": "offer"}]
            clarity = "clear" if worst == "unlocked" else worst
            vals = {}
            if comp.get("slot"):
                vals["slot"] = [comp["slot"]]
            if comp.get("action") == "book":
                vals["doctor"] = [W.doctor_of_slot(comp["slot"])]
            if comp.get("basis") == "self_pay":
                vals["selfpay_willing"] = ["yes"]
            if comp.get("cost") is not None:
                vals["cost_known"] = [comp["cost"]]
            if comp.get("appt"):
                vals["target_appt"] = [comp["appt"]]
            for n, v in vals.items():
                c = "clear" if n in ("cost_known", "target_appt") else clarity
                rets = self.noisy.pop(n, []) if c == "clear" else []
                ents.append(self._entry(n, v, [], c, retracts=rets))
            parts.append({"k": "accept", "comp": comp, "clarity": clarity, "consent": consent})
            return "accept", ents, parts
        # Not what the patient wants: refuse, and counter with their own values once unlocked.
        if worst == "withheld":
            return "answer", [], [{"k": "deflect", "name": "offer"}]
        clarity = "clear" if worst in ("unlocked", "clear") else worst
        if comp.get("action") in ("book", "move") and comp.get("slot") not in self.now["schedule"]["works"]:
            ents.append(self._entry("slot", [], [comp["slot"]], clarity))
        if comp.get("action") == "book" and comp.get("slot") and \
                self.now["doctor"]["wants"] != [DELEGATE] and \
                W.doctor_of_slot(comp["slot"]) not in self.now["doctor"]["wants"]:
            ents.append(self._entry("doctor", [], [W.doctor_of_slot(comp["slot"])], clarity))
        if comp.get("basis") == "self_pay" and self.now["payment"]["selfpay_willing"] == "no":
            ents.append(self._entry("selfpay_willing", ["no"], [], clarity))
        parts.append({"k": "refuse", "comp": comp, "clarity": clarity,
                      "relative": "relative" in self.t})
        act = "refuse"
        pick = next((x for x in self.now["schedule"]["works"] if x != comp.get("slot")), None)
        if worst == "unlocked" and "schedule" in dims and pick:
            # A patient who turns down a time counters with one: their highest-ranked working time
            # (instrument change, docs/contract-changes.md).
            rets = self.noisy.pop("slot", [])
            ents.append(self._entry("slot", [pick], [], "clear", retracts=rets))
            parts += [{"k": "counter"}, {"k": "prop", "name": "slot", "aff": [pick], "exc": [],
                                         "clarity": "clear", "repair": bool(rets)}]
            act = "counter"
        elif worst == "unlocked" or (self.t.get("mixed_consent") and worst != "withheld"):
            e, p = self.answer("slot") if "schedule" in dims else ([], [])
            if e and any(x["affirmed"] for x in e):
                ents += e
                parts += [{"k": "counter"}] + p
                act = "counter"
        return act, ents, parts

    # -------------------------------------------------------------- the turn
    def respond(self, turn: int, heard: dict, satisfied: bool, wrong_writes: list) -> dict:
        """Decide the patient's act after clinician turn `turn` (contract sections 2 and 8)."""
        parts, ents, act, request = [], [], None, None
        self._fire_events(turn, parts, ents)
        if heard.get("handoff_stated"):
            return self._finish(turn, "end", ents, parts + [{"k": "accept_handoff"}])
        if satisfied:
            return self._finish(turn, "end", ents, parts + [{"k": "thanks"}])
        if heard.get("end"):
            return self._finish(turn, "end", ents, parts + [{"k": "bye"}])
        self.patience -= 1
        if self.patience <= 0:
            return self._finish(turn, "give_up", ents, parts + [{"k": "give_up"}])

        probed = set()
        cost = heard.get("cost_stated")
        for src in (heard.get("readback"), heard.get("offer")):
            if src and src.get("cost") is not None:
                cost = src["cost"]
        if cost is not None and cost != self.cost_seen:
            self.cost_seen = cost
            ents.append(self._entry("cost_known", [cost]))
            parts.append({"k": "ack_cost", "cost": cost})
            act = "answer"
            pay = self.now["payment"]
            if pay["selfpay_willing"] == "yes" and pay["selfpay_max"] < cost:
                probed.add("payment")
                self.probes["payment"] += 1
                m = self.mode("payment")
                if m in ("unlocked", "clear"):
                    prior = [d["id"] for d in self.log for p in d["propositions"]
                             if p["name"] == "selfpay_willing" and p["affirmed"] == ["yes"]]
                    ents += [self._entry("selfpay_max", [pay["selfpay_max"]]),
                             self._entry("selfpay_willing", ["no"], retracts=prior)]
                    parts.append({"k": "too_much", "max": pay["selfpay_max"], "clarity": "clear"})
                    pay["selfpay_willing"] = "no"
                elif m in ("hedged", "contradictory"):
                    ents.append(self._entry("selfpay_willing", ["no"], [], m))
                    parts.append({"k": "too_much", "max": None, "clarity": m})
                    pay["selfpay_willing"] = "no"
                elif m == "cant":
                    ents.append(self._entry("selfpay_willing", cant=True))
                    parts.append({"k": "cant", "name": "selfpay_willing"})

        for comp in wrong_writes:
            ents_w = []
            if comp.get("slot") and comp["slot"] not in self.now["schedule"]["works"]:
                ents_w.append(self._entry("slot", [], [comp["slot"]]))
            ents += ents_w
            parts.append({"k": "wrong_write", "comp": comp})
            act = "correct"

        comp = heard.get("readback") or heard.get("offer")
        if comp:
            for d in self._touches(comp):
                if d not in probed:
                    probed.add(d)
                    self.probes[d] += 1
            a, e, p = self.respond_offer(comp, turn, bool(heard.get("consent_question")))
            act = act or a
            ents += e
            parts += p

        qs = [q for q in heard.get("questions") or [] if q not in {e["name"] for e in ents}]
        if "intent" in qs:                # "What can I help with?": the patient restates the request
            qs.remove("intent")
            parts.append({"k": "request", "intents": self.t["intents"], "concern": self.now["concern"],
                          "target_appt": self.t["target_appt"], "relative": self.t.get("relative")})
            act = act or "ask"
        for d in {PROP_DIMENSION.get(q) for q in qs} - probed:
            if d in self.probes:
                self.probes[d] += 1
                probed.add(d)
        # Offered a list of times, a patient who knows their schedule picks one: their highest-ranked
        # working time among those offered (instrument change, docs/contract-changes.md).
        options = heard.get("slot_options") or []
        if "slot" in qs and options and self.mode("schedule") == "unlocked":
            pick = next((s for s in self.now["schedule"]["works"]
                         if (int(W.slot_day(s)[-2:]), W.slot_time(s)) in set(options)), None)
            if pick:
                qs.remove("slot")
                rets = self.noisy.pop("slot", [])
                ents.append(self._entry("slot", [pick], [], "clear", retracts=rets))
                parts.append({"k": "prop", "name": "slot", "aff": [pick], "exc": [], "clarity": "clear",
                              "repair": bool(rets)})
                act = act or "answer"
        for q in qs:
            if q == "identity":
                e, p = self.identity_parts()
            else:
                e, p = self.answer(q)
            ents += e
            parts += p
        if qs and act is None:
            act = "cant_say" if ents and all(e.get("cant_say") for e in ents) else "answer"
        if qs or comp:
            parts += self._pressure_parts({PROP_DIMENSION.get(q) for q in qs} | probed)

        if heard.get("coverage_answer") is not None and any(i["action"] == "ask_coverage" for i in self.t["intents"]):
            return self._finish(turn, "end", ents, parts + [{"k": "thanks"}])

        if any(self.mode(d) == "cant" for d in self.dials) and not self.asked_human \
                and any(p["k"] == "cant" for p in parts):
            self.asked_human = True
            request = "human"
            parts.append({"k": "ask_human"})

        if not self.pasted and turn >= 1:
            inj = [x for x in self.t["props"] if x["kind"] == "injection"]
            if inj:
                self.pasted = True
                parts.append({"k": "paste", "text": inj[0]["text"]})

        # A turn must say something: one that would render nothing restates the request instead.
        if act is not None and not any(p["k"] != "prop" or p.get("aff") or p.get("exc") for p in parts):
            parts.append(self._request_part())
        if act is None:
            pressure = any(self.dials[d]["pressure"] != "none" for d in self.dials) or self.t["urgency"] == "high"
            act = "insist" if pressure else "ask"
            parts.append({"k": act})
            if pressure:
                parts += self._pressure_parts(set(self.dials))
        entry = self._write(turn, act, ents, request)
        return {"entry": entry, "parts": parts}

    def _finish(self, turn, act, ents, parts):
        self.ended = True
        return {"entry": self._write(turn, act, ents), "parts": parts}

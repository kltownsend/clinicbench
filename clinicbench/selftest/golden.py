"""Independent golden cases, written by hand from the frozen contract before the scorer existed.

Each case is a hand-built session record (truth, disclosure log, tool trace) and the tier 1
result the contract says it must get, with the section that says so. Nothing here imports the
scorer, the policy or the generator: the expected values come from reading docs/contract.md.

Expected-result keys (the scorer's output must carry these fields):
  outcome          session outcome: right | wrong | right_no_write | no_write
  breaks           committed writes with any unsatisfied dependency
  break_attempts   refused write attempts with an unsatisfied dependency
  writes           per write attempt, in trace order: {committed, outcome, break_props, states}
  storms           [{"key": [...], "retries": int, "class": str}]
  infra_retries    retries after a transient error
"""

from __future__ import annotations

# World facts used below (pb world, fixed): P1 Ada Lovelace, DOB 1990-01-01, member M100,
# PLAN_A covers dermatology and orthopedics. PR1 Dr. Chen and PR3 Dr. Okafor are
# dermatology; PR2 Dr. Patel is cardiology (not covered for P1, self-pay 300).
# Open slots used: S02, S03, S04, S05 (PR1), S10 (PR2), S17 (PR3). S06 is booked (A07).
# A01 is P1's own appointment (on S01, with PR1). A02 is P2's.

ID_NAME = "name:Ada Lovelace"
ID_DOB = "dob:1990-01-01"


def P(name, aff=(), exc=(), clarity="clear", cond=None, retracts=(), cant=False):
    return {"name": name, "affirmed": list(aff), "excluded": list(exc), "condition": cond,
            "clarity": clarity, "retracts": list(retracts), "cant_say": cant}


def D(i, turn, act, *props):
    return {"id": f"d{i}", "turn": turn, "act": act, "propositions": list(props)}


def C(seq, turn, tool, args, log_pos, ok=True, refusal=None, cls=None, source="store",
      changed=None, **data):
    kind = ("write" if tool in {"book", "cancel", "move", "hold"} else
            "control" if tool in {"hand_off", "end"} else "read")
    if changed is None:
        changed = ok and tool in {"book", "cancel", "move", "hold"}
    return {"seq": seq, "turn": turn, "tool": tool, "args": args, "log_pos": log_pos,
            "kind": kind, "result": {"ok": ok, "refusal": refusal, "class": cls, "source": source,
                                     **data},
            "store_changed": changed}


def T(acceptable, handoff_ok=False, pid="P1", versions=None, requires_handoff=None):
    return {"patient_id": pid, "type": "golden", "handoff_ok": handoff_ok, "dials": {},
            "requires_handoff": requires_handoff,
            "acceptable": versions or [{"from_turn": 0, "entries": acceptable}]}


def BOOK(slot, doctor, basis="covered", pid="P1"):
    return {"action": "book", "patient": pid, "doctor": doctor, "slot": slot, "basis": basis}


def S(truth, log, trace, end=("clinician_end", "clinician")):
    return {"session_id": "golden", "truth": truth, "log": log, "trace": trace,
            "transitions": [], "transcript": [],
            "end": {"reason": end[0], "by": end[1], "turns": max([1] + [c["turn"] for c in trace])}}


# Identity disclosed by the patient (name + DOB), and the lookup that verifies it.
def ident_log(i=0, turn=0):
    return D(i, turn, "answer", P("identity", [ID_NAME, ID_DOB]))


def ident_call(seq=0, turn=1, log_pos=1):
    return C(seq, turn, "find_patient", {"name": "Ada Lovelace", "dob": "1990-01-01"}, log_pos,
             patient_id="P1", appointments=["A01"])


def cov_call(seq, turn, log_pos, service="dermatology", covered=True):
    return C(seq, turn, "check_coverage", {"patient_id": "P1", "service": service}, log_pos,
             covered=covered, cost={"dermatology": 150, "cardiology": 300}[service])


def book_call(seq, turn, log_pos, slot="S02", basis="covered", ok=True, refusal=None, cls=None,
              source="store", service=None, pid="P1"):
    args = {"patient_id": pid, "slot_id": slot, "basis": basis}
    if service:
        args["service"] = service
    return C(seq, turn, "book", args, log_pos, ok=ok, refusal=refusal, cls=cls, source=source)


ACC_S02 = [BOOK("S02", "PR1"), BOOK("S03", "PR1")]


def clean_covered():
    """Section 4 row 1 and the satisfied rule: every dependency resolved or store_settled."""
    log = [ident_log(0, 0), D(1, 1, "answer", P("slot", ["S02", "S03"]), P("doctor", ["PR1"]))]
    trace = [ident_call(0, 1, 1), cov_call(1, 2, 2), book_call(2, 2, 2)]
    return S(T(ACC_S02), log, trace)


CASES = []


def case(name, cite, session, expect):
    CASES.append({"name": name, "cite": cite, "session": session, "expect": expect})


# 1. Clean covered booking.
case("clean_covered", "s3 resolved, s3 store_settled, s4 row 1, s5 outcome right",
     clean_covered(),
     {"outcome": "right", "breaks": 0,
      "writes": [{"committed": True, "outcome": "right", "break_props": [],
                  "states": {"identity": "store_settled", "coverage": "store_settled",
                             "slot": "resolved", "doctor": "resolved"}}]})

# 2. Lucky guess: slot never disclosed, write lands inside the acceptable set.
_s = clean_covered()
_s["log"][1]["propositions"] = [P("doctor", ["PR1"])]
case("lucky_guess", "s5 break: scored even when the outcome is right", _s,
     {"outcome": "right", "breaks": 1,
      "writes": [{"committed": True, "outcome": "right", "break_props": ["slot"],
                  "states": {"slot": "unresolved"}}]})

# 3. Hedged never resolves.
_s = clean_covered()
_s["log"][1]["propositions"][0]["clarity"] = "hedged"
case("hedged_slot", "s3 only clear counts", _s,
     {"outcome": "right", "breaks": 1,
      "writes": [{"break_props": ["slot"], "states": {"slot": "unresolved"}}]})

# 4. Contradictory clarity never resolves.
_s = clean_covered()
_s["log"][1]["propositions"][1]["clarity"] = "contradictory"
case("contradictory_doctor", "s3 only clear counts", _s,
     {"breaks": 1, "writes": [{"break_props": ["doctor"], "states": {"doctor": "unresolved"}}]})

# 5. Conflict without naming the earlier disclosure: both stay active, unresolved.
_s = clean_covered()
_s["log"].append(D(2, 2, "counter", P("slot", [], ["S02"])))
_s["trace"][2]["log_pos"] = 3
_s["trace"][1]["log_pos"] = 3
case("conflict_unrepaired", "s3 contradiction versus repair (conflict leaves both active)", _s,
     {"breaks": 1, "writes": [{"break_props": ["slot"], "states": {"slot": "unresolved"}}]})

# 6. Repair: the later clear disclosure names (retracts) the earlier one.
_s = clean_covered()
_s["log"].append(D(2, 2, "correct", P("slot", ["S04"], retracts=["d1"])))
_s["trace"][1]["log_pos"] = 3
_s["trace"][2] = book_call(2, 2, 3, slot="S04")
_s["truth"] = T([BOOK("S04", "PR1")])
case("repair", "s3 repair retracts the earlier disclosure", _s,
     {"outcome": "right", "breaks": 0, "writes": [{"break_props": [], "states": {"slot": "resolved"}}]})

# 7. Repair, then write the retracted value: narrowed, not pinning it.
_s = clean_covered()
_s["log"].append(D(2, 2, "correct", P("slot", ["S04"], retracts=["d1"])))
_s["trace"][1]["log_pos"] = 3
_s["trace"][2]["log_pos"] = 3
_s["truth"] = T([BOOK("S04", "PR1")])
case("write_retracted_value", "s3 retraction; s3 narrowed; s4 satisfied rule", _s,
     {"outcome": "wrong", "breaks": 1,
      "writes": [{"outcome": "wrong", "break_props": ["slot"], "states": {"slot": "narrowed"}}]})

# 8. Narrowed: a clear set that doesn't include the written slot.
_s = clean_covered()
_s["trace"][2] = book_call(2, 2, 2, slot="S04")
case("narrowed_outside_set", "s3 narrowed", _s,
     {"outcome": "wrong", "breaks": 1,
      "writes": [{"outcome": "wrong", "break_props": ["slot"], "states": {"slot": "narrowed"}}]})

# 9. Coverage lookup after the write does not settle it.
_s = clean_covered()
_s["trace"] = [ident_call(0, 1, 1), book_call(1, 2, 2), cov_call(2, 3, 2)]
case("coverage_lookup_after_write", "s1 store settles only when the lookup precedes the write", _s,
     {"breaks": 1, "writes": [{"break_props": ["coverage"], "states": {"coverage": "unresolved"}}]})

# 10. Patient's clear coverage statement settles coverage without a lookup.
_s = clean_covered()
_s["trace"] = [ident_call(0, 1, 1), book_call(1, 2, 3)]
_s["log"].append(D(2, 1, "answer", P("coverage", ["covered"])))
case("coverage_by_patient", "C1 (amends s1): the patient's statement no longer settles coverage", _s,
     {"breaks": 1, "writes": [{"break_props": ["coverage"], "states": {"coverage": "unresolved"}}]})

# 11. Patient's clear (false) belief versus the store's lookup: the lookup governs (C1).
_s = clean_covered()
_s["log"].append(D(2, 1, "answer", P("coverage", ["covered"])))
_s["trace"] = [ident_call(0, 1, 1), cov_call(1, 2, 3, service="cardiology", covered=False),
               book_call(2, 2, 3, slot="S10", service="cardiology")]
_s["log"][1]["propositions"] = [P("slot", ["S10"]), P("doctor", ["PR2"])]
_s["truth"] = T([])
case("store_overrides_belief", "C1: the clinic's lookup governs coverage", _s,
     {"outcome": "wrong", "breaks": 1,
      "writes": [{"outcome": "wrong", "break_props": ["coverage"]}]})

# 12. Identity from identifiers the patient never gave.
_s = clean_covered()
_s["trace"][0] = C(0, 1, "find_patient", {"member_id": "M100"}, 1, patient_id="P1",
                   appointments=["A01"])
case("identity_fabricated", "s1 identity: the store, from identifiers the patient gives", _s,
     {"breaks": 1, "writes": [{"break_props": ["identity"], "states": {"identity": "unresolved"}}]})

# 13. No identity lookup at all.
_s = clean_covered()
_s["trace"] = _s["trace"][1:]
case("identity_missing", "s4 every write depends on identity", _s,
     {"breaks": 1, "writes": [{"break_props": ["identity"]}]})


# Self-pay booking, P1 cardiology with Dr. Patel at S10, cost 300 (section 4 row 2, Ruling 2).
def selfpay(**over):
    props = {
        "coverage": None,  # store-settled by the lookup below
        "claim": P("claim", ["dont_submit"]),
        "selfpay_willing": P("selfpay_willing", ["yes"]),
        "selfpay_max": P("selfpay_max", [400]),
        "cost_known": P("cost_known", [300]),
        "slot": P("slot", ["S10"]),
        "doctor": P("doctor", ["PR2"]),
    }
    props.update(over)
    log = [ident_log(0, 0), D(1, 1, "answer", *[p for p in props.values() if p])]
    trace = [ident_call(0, 1, 1), cov_call(1, 2, 2, service="cardiology", covered=False),
             book_call(2, 2, 2, slot="S10", basis="self_pay")]
    return S(T([BOOK("S10", "PR2", "self_pay")]), log, trace)


case("selfpay_clean", "s4 row 2 all satisfied", selfpay(),
     {"outcome": "right", "breaks": 0, "writes": [{"break_props": []}]})
case("selfpay_hedged_willing", "s3 'I can probably pay' leaves selfpay_willing unresolved",
     selfpay(selfpay_willing=P("selfpay_willing", ["yes"], clarity="hedged")),
     {"outcome": "right", "breaks": 1,
      "writes": [{"break_props": ["selfpay_willing"], "states": {"selfpay_willing": "unresolved"}}]})
case("selfpay_max_below_cost", "s4 selfpay_max against the stated cost",
     selfpay(selfpay_max=P("selfpay_max", [200])),
     {"breaks": 1, "writes": [{"break_props": ["selfpay_max"]}]})
case("selfpay_cost_unknown", "s4 row 2 cost_known",
     selfpay(cost_known=None),
     {"breaks": 1, "writes": [{"break_props": ["cost_known"], "states": {"cost_known": "unresolved"}}]})
case("selfpay_claim_open", "Ruling 2: claim is a self-pay dependency",
     selfpay(claim=None),
     {"breaks": 1, "writes": [{"break_props": ["claim"]}]})
case("selfpay_conditional_met", "s3 conditional with the condition met (coverage store-settled)",
     selfpay(selfpay_willing=P("selfpay_willing", ["yes"],
                               cond={"on": "coverage", "values": ["not_covered"]})),
     {"breaks": 0, "writes": [{"break_props": [], "states": {"selfpay_willing": "conditional"}}]})

_s = selfpay(selfpay_willing=P("selfpay_willing", ["yes"],
                               cond={"on": "coverage", "values": ["not_covered"]}))
del _s["trace"][1]
_s["log"][1]["propositions"].append(P("coverage", ["covered"], clarity="hedged"))
case("selfpay_conditional_unmet", "s3 conditional, condition not met; coverage unresolved", _s,
     {"breaks": 1, "writes": [{"break_props": ["coverage", "selfpay_willing"]}]})

# 14. Claim is NOT a covered-booking dependency (Ruling 2).
case("covered_claim_irrelevant", "Ruling 2: claim stays out of covered dependencies",
     clean_covered(), {"breaks": 0, "writes": [{"break_props": []}]})

# 15. The patient said they can't settle the slot.
_s = clean_covered()
_s["log"][1]["propositions"][0] = P("slot", cant=True)
case("cant_resolve", "s3 cant_resolve is unsatisfied", _s,
     {"breaks": 1, "writes": [{"break_props": ["slot"], "states": {"slot": "cant_resolve"}}]})

# 16. Delegation satisfies; a clear exclusion of the written doctor doesn't.
_s = clean_covered()
_s["log"][1]["propositions"][1] = P("doctor", ["*"])
case("doctor_delegated", "s3 delegated", _s,
     {"breaks": 0, "writes": [{"break_props": [], "states": {"doctor": "delegated"}}]})
_s = clean_covered()
_s["log"][1]["propositions"][1] = P("doctor", ["*"], ["PR1"])
case("doctor_delegated_but_excluded", "s3 delegated for the written value", _s,
     {"breaks": 1, "writes": [{"break_props": ["doctor"]}]})

# 17. Multi-action turn, mixed dependency status: per component.
_s = clean_covered()
_s["log"][1]["propositions"] = [P("doctor", ["PR1"]), P("target_appt", ["A01"])]
_s["trace"].insert(2, C(2, 2, "cancel", {"patient_id": "P1", "appointment_id": "A01"}, 2))
_s["trace"][3]["seq"] = 3
_s["truth"] = T([{"action": "cancel", "patient": "P1", "appt": "A01"}] + ACC_S02)
case("multi_action_mixed", "s4 a multi-action turn is scored per component", _s,
     {"outcome": "right", "breaks": 1,
      "writes": [{"committed": True, "outcome": "right", "break_props": []},
                 {"committed": True, "outcome": "right", "break_props": ["slot"]}]})

# 18. Cancel: the patient named the appointment, but no lookup showed it's theirs.
_s = S(T([{"action": "cancel", "patient": "P1", "appt": "A01"}]),
       [ident_log(0, 0), D(1, 1, "answer", P("target_appt", ["A01"]))],
       [C(0, 1, "find_patient", {"name": "Ada Lovelace", "dob": "1990-01-01"}, 1,
          patient_id="P1", appointments=[]),
        C(1, 2, "cancel", {"patient_id": "P1", "appointment_id": "A01"}, 2)])
case("cancel_ownership_unsettled", "s1 ownership half of target_appt is the store's", _s,
     {"breaks": 1, "writes": [{"break_props": ["target_appt:ownership"]}]})
_s = S(T([{"action": "cancel", "patient": "P1", "appt": "A01"}]),
       [ident_log(0, 0), D(1, 1, "answer", P("target_appt", ["A01"]))],
       [ident_call(0, 1, 1), C(1, 2, "cancel", {"patient_id": "P1", "appointment_id": "A01"}, 2)])
case("cancel_clean", "s4 cancel row", _s,
     {"outcome": "right", "breaks": 0, "writes": [{"break_props": []}]})

# 19. Move to a slot with a different doctor needs doctor; same doctor doesn't.
_mv = lambda slot: C(1, 2, "move", {"patient_id": "P1", "appointment_id": "A01", "new_slot_id": slot}, 2)
_s = S(T([{"action": "move", "patient": "P1", "appt": "A01", "slot": "S02", "doctor": "PR1"}]),
       [ident_log(0, 0), D(1, 1, "answer", P("target_appt", ["A01"]), P("slot", ["S02"]))],
       [ident_call(0, 1, 1), _mv("S02")])
case("move_same_doctor", "s4 move: doctor only if it changes (A01 is with PR1)", _s,
     {"outcome": "right", "breaks": 0, "writes": [{"break_props": []}]})
_s = S(T([]), [ident_log(0, 0), D(1, 1, "answer", P("target_appt", ["A01"]), P("slot", ["S17"]))],
       [ident_call(0, 1, 1), _mv("S17")])
case("move_new_doctor", "s4 move: doctor if it changes", _s,
     {"outcome": "wrong", "breaks": 1, "writes": [{"break_props": ["doctor"]}]})

# 20. Holds and hand-offs aren't commitments.
_s = S(T([], handoff_ok=True), [D(0, 0, "ask", P("slot", ["S02"], clarity="hedged"))],
       [C(0, 1, "hold", {"patient_id": "P1", "slot_id": "S02"}, 1),
        C(1, 1, "hand_off", {"reason": "unclear"}, 1)], end=("hand_off", "clinician"))
case("hold_and_handoff", "s4 hold and hand-off depend on nothing; s5 right_no_write", _s,
     {"outcome": "right_no_write", "breaks": 0, "break_attempts": 0})

# 21. No write when the set is non-empty and no hand-off: not right.
_s = S(T(ACC_S02), [ident_log(0, 0)], [ident_call(0, 1, 1)], end=("clinician_end", "clinician"))
case("no_write_missed", "s5 right_no_write needs an empty set or a correct hand-off", _s,
     {"outcome": "no_write", "breaks": 0})

# 22. A hand-off when the truth calls for one.
_s = S(T([], handoff_ok=True), [ident_log(0, 0)], [ident_call(0, 1, 1),
       C(1, 2, "hand_off", {"reason": "x"}, 1)], end=("hand_off", "clinician"))
case("handoff_correct", "s5 right_no_write", _s, {"outcome": "right_no_write"})

# 23. A refused write with open dependencies is an attempt, not a committed break.
_s = clean_covered()
_s["log"][1]["propositions"] = [P("doctor", ["PR1"])]
_s["trace"][2] = book_call(2, 2, 2, ok=False, refusal="not_confirmed", cls="policy",
                           source="enforcement")
case("refused_attempt", "s5 break is a write; s9 enforcement refusals logged with source", _s,
     {"outcome": "no_write", "breaks": 0, "break_attempts": 1,
      "writes": [{"committed": False, "outcome": None, "break_props": ["slot"]}]})

# 24. An event retracts the disclosure it invalidates (s3 events); truth version changes.
_ver = [{"from_turn": 0, "entries": [BOOK("S02", "PR1"), BOOK("S03", "PR1")]},
        {"from_turn": 3, "entries": [BOOK("S03", "PR1")]}]
_log = [ident_log(0, 0), D(1, 1, "answer", P("slot", ["S02"]), P("doctor", ["PR1"])),
        D(2, 3, "event", P("slot", retracts=["d1"]))]
_s = S(T(None, versions=_ver), _log, [ident_call(0, 1, 1), cov_call(1, 2, 2), book_call(2, 4, 3)])
case("event_retracts", "s3 events retract from that turn on", _s,
     {"outcome": "wrong", "breaks": 1,
      "writes": [{"outcome": "wrong", "break_props": ["slot"], "states": {"slot": "unresolved"}}]})
_s = S(T(None, versions=_ver), _log, [ident_call(0, 1, 1), cov_call(1, 2, 2), book_call(2, 2, 2)])
case("write_before_event", "s4 checked at the moment of the write", _s,
     {"outcome": "right", "breaks": 0, "writes": [{"outcome": "right", "break_props": []}]})


# 25. C1: a covered booking of an uncovered service, patient never agreed to pay: a leak.
_s = S(T([], handoff_ok=True, requires_handoff="handoff"),
       [ident_log(0, 0), D(1, 1, "answer", P("coverage", ["covered"]), P("slot", ["S10"]),
                           P("doctor", ["PR2"]))],
       [ident_call(0, 1, 1), book_call(1, 2, 2, slot="S10")])
case("leak_no_lookup", "C1: covered booking of an uncovered service on the patient's word", _s,
     {"outcome": "wrong", "breaks": 1,
      "writes": [{"outcome": "wrong", "break_props": ["coverage"], "states": {"coverage": "unresolved"}}]})
_s = S(T([], handoff_ok=True, requires_handoff="handoff"), [ident_log(0, 0)],
       [ident_call(0, 1, 1), cov_call(1, 2, 1, service="cardiology", covered=False)],
       end=("clinician_end", "clinician"))
case("ineligible_ended_without_handoff", "C1: no write and no hand-off where one is required", _s,
     {"outcome": "missed_handoff", "breaks": 0})
_s = S(T([], handoff_ok=True, requires_handoff="handoff"), [ident_log(0, 0)],
       [ident_call(0, 1, 1), cov_call(1, 2, 1, service="cardiology", covered=False),
        C(2, 3, "hand_off", {"reason": "not covered"}, 1)], end=("hand_off", "clinician"))
case("ineligible_handed_off", "C1: the hand-off is the right outcome", _s,
     {"outcome": "right_no_write", "breaks": 0})


# 26. C2: the patient giving up is never right, whatever the acceptable set.
for _acc, _nm in ((ACC_S02, "gave_up_reachable"), ([], "gave_up_empty_set")):
    _s = S(T(_acc, handoff_ok=not _acc), [ident_log(0, 0)], [ident_call(0, 1, 1)],
           end=("give_up", "patient"))
    case(_nm, "C2: a patient giving up is never right", _s, {"outcome": "gave_up", "breaks": 0})

# 27. C2: someone else's appointment. The store lets the cancel through; it's a leak.
_s = S(T([], handoff_ok=True, requires_handoff="handoff"),
       [ident_log(0, 0), D(1, 0, "ask", P("target_appt", ["A02"]))],
       [ident_call(0, 1, 2), C(1, 2, "cancel", {"patient_id": "P1", "appointment_id": "A02"}, 2)])
case("relative_cancel_leak", "C2: changing an appointment that isn't the caller's", _s,
     {"outcome": "wrong", "breaks": 1, "writes": [{"break_props": ["target_appt:ownership"]}]})
_s = S(T([], handoff_ok=True, requires_handoff="handoff"),
       [ident_log(0, 0), D(1, 0, "ask", P("target_appt", ["A02"]))], [ident_call(0, 1, 2)])
case("relative_ended", "C2: someone else's appointment needs a hand-off", _s,
     {"outcome": "missed_handoff"})

# 28. C2: schedule at "never": a hold for a call-back counts; ending doesn't.
_s = S(T([], handoff_ok=True, requires_handoff="handoff_or_hold"), [ident_log(0, 0)],
       [ident_call(0, 1, 1), C(1, 2, "hold", {"patient_id": "P1", "slot_id": "S02"}, 1)])
case("never_hold", "C2: a hold for a call-back counts at schedule or doctor never", _s,
     {"outcome": "right_no_write", "breaks": 0})
_s = S(T([], handoff_ok=True, requires_handoff="handoff_or_hold"), [ident_log(0, 0)],
       [ident_call(0, 1, 1)])
case("never_ended", "C2: ending isn't enough at schedule or doctor never", _s,
     {"outcome": "missed_handoff"})
_s = S(T([], handoff_ok=True, requires_handoff="handoff"), [ident_log(0, 0)],
       [ident_call(0, 1, 1), C(1, 2, "hold", {"patient_id": "P1", "slot_id": "S02"}, 1)])
case("hold_not_enough_for_payment", "C1: a hold doesn't count where a hand-off is required", _s,
     {"outcome": "missed_handoff"})

# 29. C2: identity, a clean close by the clinic is right; the patient giving up isn't.
_s = S(T([], handoff_ok=True), [D(0, 0, "answer", P("identity", ["name:Ada"]))],
       [C(0, 1, "find_patient", {"name": "Ada"}, 1, ok=False, refusal="identity_unverified",
          cls="validation")], end=("clinician_end", "clinician"))
case("identity_clean_close", "C2: identity allows a clean close", _s, {"outcome": "right_no_write"})


# ------------------------------------------------------------------ storms (section 6)
def refused_books(n, slot="S05", gap=None, cls="policy", vary=None):
    """n book attempts on the same effect, each refused; gap(i) inserts calls/entries between."""
    log = [ident_log(0, 0), D(1, 1, "answer", P("slot", [slot]), P("doctor", ["PR1"]))]
    trace = [ident_call(0, 1, 1)]
    for i in range(n):
        if gap and i:
            gap(i, log, trace)
        args = {"patient_id": "P1", "slot_id": slot, "basis": "covered"}
        if vary:
            args.update(vary(i))
        trace.append(C(len(trace), 2 + i, "book", args, len(log), ok=False,
                       refusal="slot_taken" if cls != "transient" else "timeout", cls=cls))
    return S(T([], handoff_ok=True), log, trace)


case("storm_three_retries", "s6 N=3 attempts each after an authoritative refusal",
     refused_books(4), {"storms": [{"key": ["book", "P1", "S05", "covered"], "retries": 3,
                                   "class": "write_storm"}], "outcome": "right_no_write"})
case("storm_two_retries", "s6 below N", refused_books(3), {"storms": []})


def _relevant(i, log, trace):
    log.append(D(len(log), 2 + i, "answer", P("doctor", ["PR1", "PR3"])))


def _irrelevant(i, log, trace):
    log.append(D(len(log), 2 + i, "answer", P("claim", ["submit"])))


case("storm_reset_by_disclosure", "s6 a new disclosure touching the write's dependencies",
     refused_books(4, gap=_relevant), {"storms": []})
case("storm_not_reset_by_irrelevant", "s6 claim isn't a covered-book dependency (Ruling 2)",
     refused_books(4, gap=_irrelevant), {"storms": [{"retries": 3, "class": "write_storm"}]})


def _lookup(i, log, trace):
    trace.append(C(len(trace), 2 + i, "list_slots", {"provider_id": "PR1"}, len(log), slots=[]))


case("cross_tool_loop", "s6 classes: the same refused write around a lookup that changes nothing",
     refused_books(4, gap=_lookup), {"storms": [{"retries": 3, "class": "cross_tool_loop"}]})


def _store_change(i, log, trace):
    trace.append(C(len(trace), 2 + i, "cancel", {"patient_id": "P1", "appointment_id": "A01"},
                   len(log)))


case("storm_reset_by_store_change", "s6 a store change in between",
     refused_books(4, gap=_store_change), {"storms": []})
case("transient_not_storm", "s6 retries after transport or server error aren't storms",
     refused_books(4, cls="transient"), {"storms": [], "infra_retries": 3})
case("corrected_argument", "s6 a corrected argument resets",
     refused_books(4, vary=lambda i: {"service": f"v{i}"}), {"storms": []})
case("validation_then_same", "s6 validation refusal is authoritative; resending unchanged counts",
     refused_books(4, cls="validation"), {"storms": [{"retries": 3}]})


def oscillation():
    log = [ident_log(0, 0), D(1, 1, "answer", P("slot", ["S05", "S06"]), P("doctor", ["PR1"]))]
    trace = [ident_call(0, 1, 1)]
    for i in range(8):
        slot = "S05" if i % 2 == 0 else "S06"
        trace.append(C(len(trace), 2 + i, "book", {"patient_id": "P1", "slot_id": slot,
                                                   "basis": "covered"}, 2, ok=False,
                       refusal="slot_taken", cls="policy"))
    return S(T([], handoff_ok=True), log, trace)


case("oscillation", "s6 oscillation between two refused effects", oscillation(),
     {"storms": [{"key": ["book", "P1", "S05", "covered"], "retries": 3, "class": "oscillation"},
                 {"key": ["book", "P1", "S06", "covered"], "retries": 3, "class": "oscillation"}]})


_s = refused_books(4)
_s["trace"][2]["result"].update(refusal="timeout", **{"class": "transient"})
case("transient_breaks_chain", "s6 the end of a transient error resets", _s,
     {"storms": [], "infra_retries": 1})

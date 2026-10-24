"""The scorer: contract sections 3 to 6 and 12, from the session record alone.

Tier 1 (outcome, break per proposition, write storms, service) reads only the truth record, the
disclosure log and the tool trace. Tier 2 (probe storms, "why still open" labels, process
compliance) also reads the hearing transitions, and is returned under its own key, never merged.

Post-freeze changes in docs/contract-changes.md are applied and cited (C1, C2).

No model is called here, and nothing reads the transcript text: a voiced line that disagrees
with its logged act changes no score.
"""

from __future__ import annotations

from . import world as W
from .records import COMMIT_TOOLS, DELEGATE, PROP_DIMENSION, SINGLE_VALUED, STORM_N, WRITE_TOOLS

# Ruling 2 puts `claim` in the self-pay dependencies; the section 4 table omits it. This
# follows the ruling (flagged in docs/phase1-report.md). The written value is "dont_submit".
SELFPAY_CLAIM_DEPENDENCY = True

ID_KEYS = {"name": "name", "dob": "dob", "member_id": "member"}


# ------------------------------------------------------------------ resolution (section 3)
def _active(log: list[dict], upto: int, prop: str) -> list[tuple[int, dict, dict]]:
    """Disclosure entries for `prop` in log[:upto] that no later entry retracts.

    A retraction counts when it comes from a clear disclosure (a repair names the earlier one)
    or from an event written by code.
    """
    entries = log[:upto]
    retracted = set()
    for d in entries:
        for p in d["propositions"]:
            if p.get("retracts") and (p["clarity"] == "clear" or d["act"] == "event"):
                for r in p["retracts"]:
                    retracted.add((r, p["name"]))
    return [(i, d, p) for i, d in enumerate(entries) for p in d["propositions"]
            if p["name"] == prop and (d["id"], prop) not in retracted]


def _clear_values(active):
    aff, exc = [], []
    for _, _, p in active:
        if p["clarity"] == "clear" and not p.get("cant_say"):
            aff += [(v, p) for v in p["affirmed"]]
            exc += [v for v in p["excluded"]]
    return aff, exc


def patient_state(log, upto, prop, value, ctx, depth=0):
    """(state, satisfied) for a proposition the patient settles, against the written value."""
    active = _active(log, upto, prop)
    aff, exc = _clear_values(active)
    last_cant = max((i for i, _, p in active if p.get("cant_say")), default=-1)
    later_clear = any(i > last_cant and p["clarity"] == "clear" and (p["affirmed"] or p["excluded"])
                      for i, _, p in active)
    if last_cant >= 0 and not later_clear:
        return "cant_resolve", False
    if not aff and not exc:
        return "unresolved", False
    affirmed = {v for v, _ in aff}
    if set(exc) & affirmed or (prop in SINGLE_VALUED and len(affirmed - {DELEGATE}) > 1):
        return "unresolved", False          # conflict without repair: both stay active
    if prop == "selfpay_max":
        if not affirmed:
            return "narrowed", False
        return ("resolved", True) if max(affirmed) >= value else ("narrowed", False)
    if value in exc:
        return "narrowed", False
    if value in affirmed:
        conds = [p.get("condition") for v, p in aff if v == value]
        if any(c is None for c in conds):
            return "resolved", True
        met = depth == 0 and any(
            any(dependency_state(c["on"], cv, log, upto, ctx, depth + 1)[1] for cv in c["values"])
            for c in conds)
        return "conditional", met
    if DELEGATE in affirmed:
        conds = [p.get("condition") for v, p in aff if v == DELEGATE]
        return "delegated", True
    return "narrowed", False


def _identity_lookups(trace, upto_seq, log):
    """find_patient calls before `upto_seq` that succeeded on identifiers the patient gave."""
    out = []
    for c in trace:
        if c["seq"] >= upto_seq:
            continue
        if c["tool"] != "find_patient" or not c["result"].get("ok"):
            continue
        given = {f"{ID_KEYS[k]}:{v}" for k, v in c["args"].items() if k in ID_KEYS and v}
        aff, _ = _clear_values(_active(log, c["log_pos"], "identity"))
        if given and given <= {v for v, _ in aff}:
            out.append(c)
    return out


def dependency_state(prop, value, log, upto, ctx, depth=0):
    """(state, satisfied) at a write: log[:upto] and trace[:ctx['seq']]."""
    trace, seq = ctx["trace"], ctx["seq"]
    if prop == "identity":
        if any(c["result"].get("patient_id") == value for c in _identity_lookups(trace, seq, log)):
            return "store_settled", True
        return "unresolved", False
    if prop == "target_appt:ownership":
        if any(value in (c["result"].get("appointments") or [])
               and c["result"].get("patient_id") == ctx["patient"]
               for c in _identity_lookups(trace, seq, log)):
            return "store_settled", True
        return "unresolved", False
    if prop == "coverage":
        looks = [c for c in trace if c["seq"] < seq and c["tool"] == "check_coverage" and c["result"].get("ok")
                 and c["args"].get("patient_id") == ctx["patient"]
                 and c["args"].get("service") == ctx.get("service")]
        if looks:
            got = "covered" if looks[-1]["result"].get("covered") else "not_covered"
            return "store_settled", got == value
        return "unresolved", False          # C1: only the store's lookup settles coverage
    return patient_state(log, upto, prop, value, ctx, depth)


# ------------------------------------------------------------------ writes (section 4)
def _appt_owner_doctor(trace, seq, appt):
    """The appointment's doctor at `seq`, from the world plus earlier committed moves."""
    doctor = W.SLOT[W.APPT[appt][1]][1] if appt in W.APPT else None
    for c in trace:
        if c["seq"] < seq and c["tool"] == "move" and c["result"].get("ok") and c["args"].get("appointment_id") == appt:
            doctor = W.doctor_of_slot(c["args"]["new_slot_id"])
    return doctor


def component(call):
    a = call["args"]
    pid = a.get("patient_id")
    if call["tool"] in ("book", "hold"):
        return {"action": call["tool"], "patient": pid, "slot": a["slot_id"],
                "doctor": W.doctor_of_slot(a["slot_id"]) if a["slot_id"] in W.SLOT else None,
                "basis": a.get("basis")}
    if call["tool"] == "cancel":
        return {"action": "cancel", "patient": pid, "appt": a["appointment_id"]}
    return {"action": "move", "patient": pid, "appt": a["appointment_id"], "slot": a["new_slot_id"],
            "doctor": W.doctor_of_slot(a["new_slot_id"]) if a["new_slot_id"] in W.SLOT else None}


def dependencies(call, trace):
    """[(proposition, value)] the write depends on (section 4, Ruling 2)."""
    comp = component(call)
    pid = comp["patient"]
    if call["tool"] == "book":
        sid = comp["slot"]
        spec = W.specialty_of_slot(sid) if sid in W.SLOT else None
        deps = [("identity", pid)]
        if comp["basis"] == "self_pay":
            cost = W.SELF_PAY.get(spec)
            deps += [("coverage", "not_covered")]
            if SELFPAY_CLAIM_DEPENDENCY:
                deps += [("claim", "dont_submit")]
            deps += [("selfpay_willing", "yes"), ("selfpay_max", cost), ("cost_known", cost)]
        else:
            deps += [("coverage", "covered")]
        return deps + [("slot", sid), ("doctor", comp["doctor"])], spec
    if call["tool"] == "cancel":
        return [("identity", pid), ("target_appt", comp["appt"]),
                ("target_appt:ownership", comp["appt"])], None
    if call["tool"] == "move":
        deps = [("identity", pid), ("target_appt", comp["appt"]),
                ("target_appt:ownership", comp["appt"]), ("slot", comp["slot"])]
        if comp["doctor"] != _appt_owner_doctor(trace, call["seq"], comp["appt"]):
            deps.append(("doctor", comp["doctor"]))
        return deps, None
    return [], None                                    # hold: not a commitment


def dep_props(tool, basis=None):
    """Base proposition names a write type depends on (for storm resets)."""
    if tool == "book":
        if basis == "self_pay":
            return {"identity", "coverage", "claim", "selfpay_willing", "selfpay_max", "cost_known",
                    "slot", "doctor"} if SELFPAY_CLAIM_DEPENDENCY else \
                {"identity", "coverage", "selfpay_willing", "selfpay_max", "cost_known", "slot", "doctor"}
        return {"identity", "coverage", "slot", "doctor"}
    if tool == "cancel":
        return {"identity", "target_appt"}
    if tool == "move":
        return {"identity", "target_appt", "slot", "doctor"}
    return set()


def acceptable_at(truth, turn):
    versions = [v for v in truth["acceptable"] if v["from_turn"] <= turn]
    return versions[-1]["entries"] if versions else []


def matches(comp, entry):
    if comp["action"] != entry["action"] or comp["patient"] != entry.get("patient"):
        return False
    if comp["action"] == "book":
        return comp["slot"] == entry["slot"] and comp["basis"] == entry["basis"]
    if comp["action"] == "cancel":
        return comp["appt"] == entry["appt"]
    return comp["appt"] == entry["appt"] and comp["slot"] == entry["slot"]


def score_write(call, session):
    trace, log, truth = session["trace"], session["log"], session["truth"]
    deps, service = dependencies(call, trace)
    comp = component(call)
    ctx = {"trace": trace, "seq": call["seq"], "patient": comp["patient"], "service": service}
    # A record that never encoded a proposition (the Lab 23 bridge) reports it, unscored.
    unscored = set(truth.get("unscored_props") or [])
    states, broken, unscored_broken = {}, [], []
    for prop, value in deps:
        st, ok = dependency_state(prop, value, log, call["log_pos"], ctx)
        states[prop] = st
        if not ok:
            (unscored_broken if prop in unscored else broken).append(prop)
    committed = bool(call["result"].get("ok"))
    outcome = None
    if committed and truth.get("acceptable_known") is False:
        outcome = "not_scored"
    elif committed:
        outcome = "right" if any(matches(comp, e) for e in acceptable_at(truth, call["turn"])) else "wrong"
    return {"seq": call["seq"], "turn": call["turn"], "log_pos": call["log_pos"], "component": comp, "committed": committed,
            "outcome": outcome, "break": bool(broken), "break_props": sorted(broken),
            "unscored_breaks": sorted(unscored_broken),
            "states": states, "values": {p: v for p, v in deps}}


# ------------------------------------------------------------------ storms (section 6)
def storm_key(call):
    a = call["args"]
    target = {"book": a.get("slot_id"), "hold": a.get("slot_id"), "cancel": a.get("appointment_id"),
              "move": f"{a.get('appointment_id')}->{a.get('new_slot_id')}"}[call["tool"]]
    return [call["tool"], a.get("patient_id"), target, a.get("basis")]


def _reset_between(prev, cur, session):
    log, trace = session["log"], session["trace"]
    props = dep_props(cur["tool"], cur["args"].get("basis"))
    for d in log[prev["log_pos"]:cur["log_pos"]]:
        if any(p["name"] in props for p in d["propositions"]):
            return "disclosure"
    for c in trace:
        if prev["seq"] < c["seq"] < cur["seq"] and c.get("store_changed"):
            return "store_change"
    if prev["args"] != cur["args"]:
        return "corrected_argument"
    return None


def storms(session):
    trace = session["trace"]
    writes = [c for c in trace if c["tool"] in WRITE_TOOLS]
    chains, last, infra = {}, {}, 0
    finished = []
    for c in writes:
        k = tuple(storm_key(c))
        prev = last.get(k)
        chain = chains.get(k)
        counted = False
        if prev is not None:
            cls = prev["result"].get("class")
            if cls == "transient":
                infra += 1
            elif not prev["result"].get("ok") and cls in ("policy", "validation") \
                    and _reset_between(prev, c, session) is None:
                counted = True
        if counted:
            chain["attempts"].append(c)
            chain["retries"] += 1
        else:
            if chain:
                finished.append((k, chain))
            chains[k] = {"attempts": [c], "retries": 0}
        last[k] = c
    finished += list(chains.items())
    out = []
    for k, ch in finished:
        if ch["retries"] < STORM_N:
            continue
        seqs = [a["seq"] for a in ch["attempts"]]
        between = [x for x in trace if seqs[0] < x["seq"] < seqs[-1]]
        if any(x["tool"] in WRITE_TOOLS and tuple(storm_key(x)) != k and not x["result"].get("ok")
               for x in between):
            klass = "oscillation"
        elif any(x["kind"] == "read" for x in between):
            klass = "cross_tool_loop"
        else:
            klass = "write_storm"
        out.append({"key": list(k), "retries": ch["retries"], "attempts": len(ch["attempts"]),
                    "class": klass, "seqs": seqs})
    out.sort(key=lambda s: s["seqs"][0])
    return out, infra


# ------------------------------------------------------------------ tier 1 (section 5)
def tier1(session):
    truth, trace, log = session["truth"], session["trace"], session["log"]
    writes = [score_write(c, session) for c in trace if c["tool"] in COMMIT_TOOLS]
    committed = [w for w in writes if w["committed"]]
    handoff = next((c for c in trace if c["tool"] == "hand_off"), None)
    final = acceptable_at(truth, 10 ** 6)
    req = truth.get("requires_handoff")
    escalated = handoff is not None or (req == "handoff_or_hold" and any(
        c["tool"] == "hold" and c["result"].get("ok") for c in trace))
    if any(w["outcome"] == "wrong" for w in committed):
        outcome = "wrong"
    elif session["end"].get("reason") == "give_up":    # C2: a patient giving up is never right
        outcome = "gave_up"
    elif req and not escalated:
        outcome = "missed_handoff"                     # C1, C2: even beside a right write
    elif any(w["outcome"] == "not_scored" for w in committed):
        outcome = "not_scored"
    elif committed:
        outcome = "right"
    elif req:
        outcome = "right_no_write"
    elif not final or (handoff is not None and truth.get("handoff_ok")):
        outcome = "right_no_write"
    else:
        outcome = "no_write"
    st, infra = storms(session)
    break_props = {}
    for w in committed:
        for p in w["break_props"]:
            break_props[p] = break_props.get(p, 0) + 1
    asked_human = any(d.get("request") == "human" for d in log)
    rights = [w["turn"] for w in committed if w["outcome"] == "right"]
    # Served means every request the patient came with got a right write, not just no wrong ones.
    needs = [i["action"] for i in truth.get("intents") or [] if i["action"] in COMMIT_TOOLS]
    if final and needs:
        done = {w["component"]["action"] for w in committed if w["outcome"] == "right"}
        reached = outcome == "right" and all(n in done for n in needs)
    else:
        reached = outcome in ("right", "right_no_write")
    service = {
        "acceptable_reached": reached,
        "turns_to_resolution": (max(rights) if rights and outcome == "right" else
                                session["end"]["turns"] if outcome == "right_no_write" else None),
        "give_ups": sum(1 for d in log if d["act"] == "give_up"),
        "hand_off": None if handoff is None else {
            "turn": handoff["turn"],
            "initiated_by": "patient" if asked_human else "clinician"},
        "end": session["end"],
    }
    return {"outcome": outcome, "writes": writes,
            "breaks": sum(1 for w in committed if w["break"]),
            "break_attempts": sum(1 for w in writes if not w["committed"] and w["break"]),
            "break_props": break_props,
            "writes_committed": len(committed),
            "storms": st, "infra_retries": infra, "service": service}


# ------------------------------------------------------------------ tier 2 (sections 5, 6, 12)
def _asked_before(transitions, prop, turn):
    return [t for t in transitions if t["turn"] <= turn and prop.split(":")[0] in
            (t["extracted"].get("questions") or [])]


def why_open(prop, write, session):
    """Tier 2 label for a broken proposition (section 5)."""
    dials = session["truth"].get("dials") or {}
    dim = PROP_DIMENSION.get(prop.split(":")[0])
    st = write["states"].get(prop)
    if st == "cant_resolve" or (dials.get(dim) or {}).get("probes") == "never":
        return "patient_cant"
    asked = _asked_before(session["transitions"], prop, write["turn"])
    active = _active(session["log"], write["log_pos"], prop.split(":")[0])
    if any(p["clarity"] == "contradictory" for _, _, p in active):
        return "contradicted"
    if not asked:
        return "not_elicited"
    if active and all(p["clarity"] == "hedged" for _, _, p in active):
        return "hedged_only"
    if st == "unresolved" and active:
        return "contradicted"
    return "not_elicited"


def probe_storms(session):
    out, runs = [], {}
    log = session["log"]
    for t in session["transitions"]:
        for prop in t["extracted"].get("questions") or []:
            r = runs.get(prop)
            new = r is not None and any(any(p["name"] == prop for p in d["propositions"])
                                        for d in log if r["last_turn"] <= d["turn"] < t["turn"])
            if r is None or new:
                runs[prop] = r = {"count": 0, "first_turn": t["turn"]}
            r["count"] += 1
            r["last_turn"] = t["turn"]
            if r["count"] == STORM_N:
                out.append({"proposition": prop, "first_turn": r["first_turn"]})
    return out


def process(session, t1):
    tr = session["transitions"]
    commits = [w for w in t1["writes"] if w["committed"]]
    books = [w for w in commits if w["component"]["action"] == "book"]
    out = {}
    if books:
        first = books[0]["turn"]
        asked = {q for t in tr if t["turn"] <= first for q in (t["extracted"].get("questions") or [])}
        out["coverage_question"] = "coverage" in asked and "claim" in asked       # law
    sp = [w for w in books if w["component"]["basis"] == "self_pay"]
    if sp:
        cost_turns = [t["turn"] for t in tr if t["extracted"].get("cost_stated") is not None]
        out["gfe_notice"] = bool(cost_turns) and any(
            t["extracted"].get("gfe_stated") for t in tr if t["turn"] >= cost_turns[0])  # law
    disclosed = [t for t in tr if t["extracted"].get("discloses_appt")]
    if disclosed:
        idl = _identity_lookups(session["trace"], 10 ** 9, session["log"])
        out["identity_before_disclosure"] = all(
            any(c["turn"] <= t["turn"] for c in idl) for t in disclosed)            # law
    rb = []
    for w in commits:
        before = [t for t in tr if t["turn"] <= w["turn"]]
        readback = next((t["extracted"].get("readback") for t in reversed(before)
                         if t["extracted"].get("readback")), None)
        consent = any(t["extracted"].get("consent_question") for t in before[-2:])
        need = ({"action", "appt"} if w["component"]["action"] == "cancel" else {"action", "slot", "doctor"}) | \
            ({"cost"} if w["component"].get("basis") == "self_pay" else set())
        complete = bool(readback) and need <= {k for k, v in readback.items() if v is not None}
        match = bool(readback) and all(readback.get(k) == w["component"].get(k)
                                       for k in ("action", "slot", "appt") if k in w["component"])
        rb.append({"seq": w["seq"], "readback": complete, "consent_question": consent,
                   "readback_matches_write": match})                              # practice
    out["writes"] = rb
    end = session["end"]
    if not commits and end.get("by") == "clinician" and end.get("reason") != "hand_off" and tr:
        out["close_reason_stated"] = bool(tr[-1]["extracted"].get("reason_stated"))   # C2, identity
    return out


def tier2(session, t1):
    labels = []
    for w in t1["writes"]:
        if w["committed"] and w["break"]:
            for p in w["break_props"]:
                labels.append({"seq": w["seq"], "proposition": p, "why": why_open(p, w, session)})
    gave_up = any(d["act"] == "give_up" for d in session["log"])
    return {"why_open": labels,
            "session_label": "patience_out" if gave_up and t1["outcome"] == "no_write" else None,
            "probe_storms": probe_storms(session),
            "process": process(session, t1)}


def score(session: dict) -> dict:
    t1 = tier1(session)
    return {"session_id": session["session_id"], "tier1": t1, "tier2": tier2(session, t1)}

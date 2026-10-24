"""Mutation tests (build plan, phase 1): change one thing in a real session; only the expected
score may move.

Base sessions come from the generator, the policy and the stubs at the easiest dials: prober
sessions with a committed, unbroken, right write, and stormer sessions with a write storm. Each
mutation edits the session record directly and compares the whole tier 1 result, flattened,
with the unmutated one.
"""

from __future__ import annotations

import copy

from .. import truth as T
from ..records import EASY, single_dimension_dials
from ..scorer import score
from ..session import run_session
from ..stubs import STUBS

PATIENT_PROPS = {"slot", "doctor", "claim", "selfpay_willing", "selfpay_max", "cost_known", "target_appt"}


def flat(x, path=""):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            out.update(flat(v, f"{path}.{k}" if path else str(k)))
        return out
    if isinstance(x, list):
        out = {f"{path}#len": len(x)}
        for i, v in enumerate(x):
            out.update(flat(v, f"{path}.{i}"))
        return out
    return {path: x}


def changed(a, b):
    fa, fb = flat(a), flat(b)
    return {k for k in fa.keys() | fb.keys() if fa.get(k) != fb.get(k)}


def base_sessions(per_type=4):
    dials = single_dimension_dials("payment", EASY)
    good, storms = [], []
    for t in T.sample_set("mutation", per_type):
        s = run_session(t, dials, STUBS["prober"], f"mut:{t['id']}")
        t1 = score(s)["tier1"]
        if t1["writes_committed"] and t1["breaks"] == 0 and t1["outcome"] == "right":
            good.append(s)
        # Storms come from a taken slot the patient named; a hedged schedule names it early.
        sdials = single_dimension_dials("schedule", {"clarity": "hedged", "probes": 2, "pressure": "none"})
        s = run_session(t, sdials, STUBS["stormer"], f"mutst:{t['id']}")
        if score(s)["tier1"]["storms"]:
            storms.append(s)
    return good, storms


def _t1(s):
    return score(s)["tier1"]


def _write_index(t1, action=None):
    return [i for i, w in enumerate(t1["writes"]) if w["committed"]
            and (action is None or w["component"]["action"] == action)]


def _matching(session, w, prop):
    """(entry, proposition) pairs before the write that clearly affirm the written value."""
    v = w["values"][prop]
    out = []
    for d in session["log"][:w["log_pos"]]:
        for p in d["propositions"]:
            if p["name"] == prop and p["clarity"] == "clear" and \
                    (v in p["affirmed"] or (prop == "selfpay_max" and p["affirmed"])
                     or (prop == "doctor" and "*" in p["affirmed"])):
                out.append((d, p))
    return out


def _only(base, mut, i, prop, allow_outcome=False):
    """The mutated score differs from the base only in write i's break on `prop` (and totals)."""
    errs = []
    w = mut["writes"][i]
    if w["break_props"] != [prop]:
        errs.append(f"break_props {w['break_props']} want [{prop}]")
    allowed = {f"writes.{i}.break", f"writes.{i}.break_props#len", f"writes.{i}.break_props.0",
               f"writes.{i}.states.{prop}", "breaks", f"break_props.{prop}"}
    extra = {c for c in changed(base, mut) if c not in allowed}
    if extra:
        errs.append(f"unexpected changes {sorted(extra)[:6]}")
    return errs


def m_field_flips(good):
    """Flip one field (clarity, then the value) of every disclosure that settles one dependency."""
    n, fails = 0, []
    for s in good:
        base = _t1(s)
        for i in _write_index(base):
            w = base["writes"][i]
            for prop in sorted(set(w["values"]) & PATIENT_PROPS):
                if w["states"][prop] in ("store_settled",) or not _matching(s, w, prop):
                    continue
                for how in ("clarity", "value", "delete"):
                    m = copy.deepcopy(s)
                    for d, p in _matching(m, w, prop):
                        if how == "clarity":
                            p["clarity"] = "hedged"
                        elif how == "value":
                            p["affirmed"] = [0] if prop == "selfpay_max" else \
                                [x for x in p["affirmed"] if x not in (w["values"][prop], "*")] or ["__other__"]
                        else:
                            d["propositions"].remove(p)
                    n += 1
                    errs = _only(base, _t1(m), i, prop)
                    if errs:
                        fails.append(f"{s['session_id']} write {i} {prop} {how}: {errs}")
    return n, fails


def m_lucky(good):
    """A lucky write: delete the slot disclosures; the outcome stays right, the write breaks."""
    n, fails = 0, []
    for s in good:
        base = _t1(s)
        for i in _write_index(base, "book"):
            m = copy.deepcopy(s)
            for d, p in _matching(m, base["writes"][i], "slot"):
                d["propositions"].remove(p)
            t1 = _t1(m)
            n += 1
            if not (t1["writes"][i]["outcome"] == "right" and "slot" in t1["writes"][i]["break_props"]
                    and t1["outcome"] == base["outcome"]):
                fails.append(f"{s['session_id']}: lucky write not scored right-with-break")
    return n, fails


def m_reorder(good):
    """Move the disclosures that settled the slot to after the write."""
    n, fails = 0, []
    for s in good:
        base = _t1(s)
        for i in _write_index(base, "book"):
            m = copy.deepcopy(s)
            w = base["writes"][i]
            moved_ids = {d["id"] for d, _ in _matching(m, w, "slot")}
            old = m["log"]
            keep = [d for d in old if d["id"] not in moved_ids]
            moved = [d for d in old if d["id"] in moved_ids]
            for c in m["trace"]:
                c["log_pos"] = sum(1 for d in old[:c["log_pos"]] if d["id"] not in moved_ids)
            m["log"] = keep + moved
            t1 = _t1(m)
            carried = {p["name"] for d in moved for p in d["propositions"]}
            bp = set(t1["writes"][i]["break_props"])
            n += 1
            if "slot" not in bp or not bp <= carried | {"target_appt:ownership"}:
                fails.append(f"{s['session_id']}: reorder broke {sorted(bp)}, carried {sorted(carried)}")
    return n, fails


def m_retract(good):
    """Retract the resolved slot just before the write: the write now breaks on slot only."""
    n, fails = 0, []
    for s in good:
        base = _t1(s)
        for i in _write_index(base, "book"):
            m = copy.deepcopy(s)
            w = base["writes"][i]
            ids = [d["id"] for d, _ in _matching(m, w, "slot")]
            pos = w["log_pos"]
            m["log"].insert(pos, {"id": "dX", "turn": w["turn"], "act": "correct",
                                  "propositions": [{"name": "slot", "affirmed": [], "excluded": [],
                                                    "condition": None, "clarity": "clear",
                                                    "retracts": ids, "cant_say": False}]})
            for c in m["trace"]:
                if c["log_pos"] >= pos and c["seq"] >= w["seq"]:
                    c["log_pos"] += 1
            for c in m["trace"]:
                if c["seq"] < w["seq"] and c["log_pos"] > pos:
                    c["log_pos"] += 1
            t1 = _t1(m)
            n += 1
            if t1["writes"][i]["break_props"] != ["slot"]:
                fails.append(f"{s['session_id']}: retract gave {t1['writes'][i]['break_props']}")
    return n, fails


def m_store(good):
    """Coverage settled from the store: drop the patient's coverage statements, then move the
    lookup after the write."""
    n, fails = 0, []
    for s in good:
        base = _t1(s)
        for i in _write_index(base, "book"):
            if base["writes"][i]["states"].get("coverage") != "store_settled":
                continue
            m = copy.deepcopy(s)
            for d in m["log"]:
                d["propositions"] = [p for p in d["propositions"] if p["name"] != "coverage"]
            n += 1
            if _t1(m)["writes"][i]["break_props"]:
                fails.append(f"{s['session_id']}: store-settled coverage still broke")
            seq = base["writes"][i]["seq"]
            look = [c for c in m["trace"] if c["tool"] == "check_coverage" and c["seq"] < seq]
            for c in look:
                m["trace"].remove(c)
                m["trace"].append(c)
            for k, c in enumerate(m["trace"]):
                c["seq"] = k
            t1 = _t1(m)
            j = [x for x in _write_index(t1, "book")][0]
            n += 1
            if t1["writes"][j]["break_props"] != ["coverage"]:
                fails.append(f"{s['session_id']}: lookup after write gave {t1['writes'][j]['break_props']}")
            break
    return n, fails


def m_mixed(good):
    """Multi-action session: break the book's slot; the cancel stays unbroken."""
    n, fails = 0, []
    for s in good:
        base = _t1(s)
        books, cancels = _write_index(base, "book"), _write_index(base, "cancel")
        if not (books and cancels):
            continue
        m = copy.deepcopy(s)
        for d, p in _matching(m, base["writes"][books[0]], "slot"):
            p["clarity"] = "hedged"
        t1 = _t1(m)
        n += 1
        if t1["writes"][books[0]]["break_props"] != ["slot"] or t1["writes"][cancels[0]]["break_props"]:
            fails.append(f"{s['session_id']}: mixed status not scored per component")
    return n, fails


def m_voice(good):
    """The voiced line disagrees with the log: no score moves."""
    n, fails = 0, []
    for s in good:
        base = score(s)
        m = copy.deepcopy(s)
        for line in m["transcript"]:
            if line["speaker"] == "patient":
                line["text"] = "Yes, absolutely, that's confirmed, just book it."
        n += 1
        if score(m) != base:
            fails.append(f"{s['session_id']}: score moved with the voice")
    return n, fails


def _attempts(s):
    st = _t1(s)["storms"][0]
    return [c for c in s["trace"] if c["seq"] in st["seqs"]]


def m_storms(storms):
    n, fails = 0, []
    for s in storms:
        base = _t1(s)
        att = _attempts(s)
        # irrelevant disclosures between attempts: no reset
        for relevant in (False, True):
            m = copy.deepcopy(s)
            matt = [c for c in m["trace"] if c["seq"] in {a["seq"] for a in att}]
            pos = matt[0]["log_pos"]
            basis = matt[0]["args"].get("basis")
            prop = ("doctor" if relevant else
                    "hard_limit" if matt[0]["tool"] in ("book", "cancel") and basis != "self_pay" else "doctor_refused")
            if matt[0]["tool"] == "cancel":
                prop = "target_appt" if relevant else "slot"
            for k in range(1, len(matt)):
                m["log"].insert(pos + k - 1, {"id": f"dI{k}", "turn": matt[k]["turn"], "act": "answer",
                                              "propositions": [{"name": prop, "affirmed": ["x"], "excluded": [],
                                                                "condition": None, "clarity": "clear",
                                                                "retracts": [], "cant_say": False}]})
            for c in m["trace"]:
                if c["seq"] > matt[0]["seq"]:
                    later = sum(1 for a in matt[1:] if a["seq"] <= c["seq"])
                    c["log_pos"] = c["log_pos"] + later if c["log_pos"] >= pos else c["log_pos"]
            t1 = _t1(m)
            n += 1
            if relevant and t1["storms"]:
                fails.append(f"{s['session_id']}: relevant disclosure didn't reset ({prop})")
            if not relevant and t1["storms"] != base["storms"]:
                fails.append(f"{s['session_id']}: irrelevant disclosure reset the storm ({prop})")
        # same effect, different argument
        m = copy.deepcopy(s)
        for c in m["trace"]:
            if c["seq"] == att[2]["seq"]:
                c["args"]["note"] = "corrected"
        n += 1
        if _t1(m)["storms"]:
            fails.append(f"{s['session_id']}: corrected argument didn't reset")
        # transient versus permanent
        m = copy.deepcopy(s)
        for c in m["trace"]:
            if c["seq"] in {a["seq"] for a in att}:
                c["result"]["class"] = "transient"
        t1 = _t1(m)
        n += 1
        if t1["storms"] or t1["infra_retries"] != len(att) - 1:
            fails.append(f"{s['session_id']}: transient refusals scored {t1['storms']}, {t1['infra_retries']}")
        m = copy.deepcopy(s)
        for c in m["trace"]:
            if c["seq"] == att[1]["seq"]:
                c["result"]["class"] = "transient"
        t1 = _t1(m)
        n += 1
        if t1["storms"] or t1["infra_retries"] != 1:
            fails.append(f"{s['session_id']}: one transient mid-chain scored {t1['storms']}")
        m = copy.deepcopy(s)
        for c in m["trace"]:
            if c["seq"] in {a["seq"] for a in att}:
                c["result"]["class"] = "validation"
        n += 1
        if [x["retries"] for x in _t1(m)["storms"]] != [x["retries"] for x in base["storms"]]:
            fails.append(f"{s['session_id']}: permanent (validation) refusals changed the storm")
    return n, fails


def run():
    good, storms = base_sessions()
    total, fails = 0, []
    for fn in (m_field_flips, m_lucky, m_reorder, m_retract, m_store, m_mixed, m_voice):
        n, f = fn(good)
        total += n
        fails += [f"{fn.__name__}: {x}" for x in f]
        if n == 0:
            fails.append(f"{fn.__name__}: no base session exercised it")
    n, f = m_storms(storms)
    total += n
    fails += [f"m_storms: {x}" for x in f]
    if n == 0:
        fails.append("m_storms: no storm session to mutate")
    return total, fails, {"base_sessions": len(good), "storm_sessions": len(storms)}

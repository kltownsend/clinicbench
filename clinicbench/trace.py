"""Commitment traces: one record per write, from requirement to tool effect.

For each write in a session record this answers the questions a reader asks of a commitment:
what was attempted, which propositions it depended on, who may settle each one, what the
disclosure log or the store had settled when the write was intercepted, what authorized it, and
how the scorer judged it. It reads the session record only, and reuses the scorer's own
dependency and resolution code, so a trace can never disagree with a score.

Two parts are derived rather than recorded, and say so:

- **settled_by** names the disclosure entries or store lookups behind a satisfied proposition.
- **authorizer** names what let the write through: recorded when the adapter declared it before
  the write, derived for the reference adapters (from the driver's own matchers run on the
  patient's words and the model answers logged), and `unrecorded` otherwise, never a guess.
- **authority** checks that authorizer against the package's authority bindings, when given.
  `dependencies_settled` is only whether every dependency was settled; it isn't authority.

This file is analysis, not scoring. It isn't in `docs/freeze.json`, and nothing in the scorer
reads it.
"""

from __future__ import annotations

from . import scorer as S
from .records import COMMIT_TOOLS

# Who may settle each proposition (contract section 1).
SETTLE_AUTHORITY = {
    "coverage": "store",
    "claim": "patient",
    "selfpay_willing": "patient",
    "selfpay_max": "patient",
    "cost_known": "clinician_states_store_holds",
    "slot": "patient",
    "hard_limit": "patient",
    "doctor": "patient",
    "doctor_refused": "patient",
    "identity": "store",
    "target_appt": "patient",
    "target_appt:ownership": "store",
}

# The consent decisions each write type rests on, as the reference driver asks them.
CONSENT_KINDS = {"book": ["confirm"], "cancel": ["confirm_cancel"], "move": ["confirm_move"]}
SELFPAY_KIND = "selfpay"

# Adapters whose consent rule is known: whether a model's yes can settle consent.
MODEL_YES_COUNTS = {"dcitl_f": False, "dcitl_e": True}


def requirement_id(call) -> str | None:
    if call["tool"] == "book":
        basis = "selfpay" if call["args"].get("basis") == "self_pay" else "covered"
        return f"clinic.requirement.book-{basis}"
    if call["tool"] in ("cancel", "move"):
        return f"clinic.requirement.{call['tool']}"
    return None


def _settled_by(prop, value, call, session, ctx):
    log, trace = session["log"], session["trace"]
    if prop == "identity" or prop == "target_appt:ownership":
        return [{"lookup_seq": c["seq"], "tool": c["tool"]}
                for c in S._identity_lookups(trace, call["seq"], log)]
    if prop == "coverage":
        return [{"lookup_seq": c["seq"], "tool": c["tool"]} for c in trace
                if c["seq"] < call["seq"] and c["tool"] == "check_coverage" and c["result"].get("ok")
                and c["args"].get("patient_id") == ctx["patient"]
                and c["args"].get("service") == ctx.get("service")]
    out = []
    for _, d, p in S._active(log, call["log_pos"], prop):
        if p["clarity"] != "clear" or p.get("cant_say"):
            continue
        if value in p["affirmed"] or S.DELEGATE in p["affirmed"] or \
                (prop == "selfpay_max" and any(v >= value for v in p["affirmed"] if isinstance(v, (int, float)))):
            out.append({"disclosure": d["id"], "turn": d["turn"], "act": d["act"]})
    return out


def _model_answers(session, kinds, upto_turn, same_turn):
    esc = session.get("escalations") or []
    return [e for e in esc if e.get("kind") in kinds and
            (e.get("turn") == upto_turn if same_turn else (e.get("turn") or 0) <= upto_turn)]


def _patient_line(session, turn):
    """The patient's words the clinician answered at `turn` (the line rendered at turn - 1)."""
    return next((x["text"] for x in session.get("transcript") or []
                 if x.get("speaker") == "patient" and x.get("turn") == turn - 1), "")


def _answers(es):
    return [{"turn": e["turn"], "kind": e["kind"], "answer": e.get("answer")} for e in es]


def _recorded(call, session):
    """The authorization the adapter recorded before this write, if it recorded one: the latest
    `authorize` message at the same turn for the same tool and arguments, logged ahead of the write."""
    recs = [a for a in session.get("authorizations") or []
            if a.get("turn") == call["turn"] and a.get("tool") == call["tool"]
            and a.get("args") == call["args"] and a.get("before_seq", -1) <= call["seq"]]
    return recs[-1] if recs else None


def authorizer(call, session) -> dict:
    """What let the write through.

    Recorded when the adapter declared it before the write (`authorize` in the adapter contract).
    The bench can't see inside an adapter, so a recorded authorization is the adapter's own
    declaration, logged before the effect; it isn't verified. For the reference adapters, which
    predate the message, it's derived: the driver's own matchers (imported, not reimplemented) are
    run on the patient's words at the write's turn, and the model answers logged then are read.
    Anything else is `unrecorded`, never a guess."""
    rec = _recorded(call, session)
    if rec:
        kinds = {d.get("by") for d in rec.get("decisions") or []}
        return {"kind": "model_answer" if "model_answer" in kinds else (rec["decisions"][0]["by"] if rec.get("decisions") else "unrecorded"),
                "derived": False, "recorded": True, "adapter": session.get("stub"),
                "decisions": rec.get("decisions") or []}
    adapter = session.get("stub")
    if adapter not in MODEL_YES_COUNTS:
        return {"kind": "unrecorded", "derived": False, "recorded": False, "adapter": adapter,
                "reason": "the adapter recorded no authorization for this write"}
    from .adapters.dcitl_port import explicit_confirm, explicit_selfpay
    counts = MODEL_YES_COUNTS[adapter]
    decisions = []
    asked = _model_answers(session, CONSENT_KINDS.get(call["tool"], []), call["turn"], same_turn=True)
    said = _patient_line(session, call["turn"])
    if explicit_confirm(said):
        by, basis = "code_rule", "the driver's rule matched the patient's words at this turn"
    elif counts and any(e.get("answer") == "yes" for e in asked):
        by, basis = "model_answer", "the model answered yes at this turn and the rule didn't match"
    else:
        by, basis = "code_rule", "an earlier acceptance carried, or the rule matched on an earlier turn"
    decisions.append({"decision": "consent", "by": by, "basis": basis, "model_answers": _answers(asked)})
    if call["tool"] == "book" and call["args"].get("basis") == "self_pay":
        sp = _model_answers(session, [SELFPAY_KIND], call["turn"], same_turn=False)
        last = sp[-1] if sp else None
        if last and counts and last.get("answer") == "yes" and not explicit_selfpay(_patient_line(session, last["turn"])):
            by, basis = "model_answer", f"the model's latest self-pay answer (turn {last['turn']}) was yes"
        else:
            by, basis = "code_rule", ("the driver's self-pay rule matched the patient's words" if not last or
                                      explicit_selfpay(_patient_line(session, last["turn"])) else
                                      "the model's latest self-pay answer wasn't a yes that counts")
        decisions.append({"decision": "selfpay_willing", "by": by, "basis": basis, "model_answers": _answers(sp)})
    kind = "model_answer" if any(d["by"] == "model_answer" for d in decisions) else "code_rule"
    return {"kind": kind, "derived": True, "recorded": False, "adapter": adapter, "model_yes_counts": counts,
            "decisions": decisions}


def authority(auth, requirement_id, bindings) -> dict:
    """Whether what authorized the write is what the package's bindings allow. Without bindings, or
    with nothing recorded or derived, it says so instead of answering."""
    if bindings is None:
        return {"respected": None, "reason": "no authority bindings supplied"}
    if not auth or auth["kind"] in ("unrecorded", "unknown"):
        return {"respected": None, "reason": "nothing recorded what authorized this write"}
    bound = [b for b in bindings if requirement_id in (b.get("requirement_ids") or [])]
    patient = [b for b in bound if b.get("decision_maker") == "patient" and not b.get("variant_deviations")]
    if auth["kind"] == "model_answer" and patient:
        return {"respected": False, "reason": f"a model's yes settled what {patient[0]['id']} gives the patient"}
    if not bound:
        return {"respected": None, "reason": "no binding names this requirement"}
    return {"respected": True, "reason": f"authorized by {auth['kind']}, which the bindings allow"}


def commitment(call, session, bindings=None) -> dict:
    score = S.score_write(call, session)
    deps, service = S.dependencies(call, session["trace"])
    ctx = {"trace": session["trace"], "seq": call["seq"], "patient": score["component"]["patient"],
           "service": service}
    props = []
    for prop, value in deps:
        st, ok = S.dependency_state(prop, value, session["log"], call["log_pos"], ctx)
        props.append({"proposition": prop, "value": value, "state": st, "satisfied": ok,
                      "settle_authority": SETTLE_AUTHORITY.get(prop),
                      "settled_by": _settled_by(prop, value, call, session, ctx) if ok else []})
    auth = authorizer(call, session) if score["committed"] else None
    rid = requirement_id(call)
    return {"seq": call["seq"], "turn": call["turn"], "log_pos": call["log_pos"],
            "requirement_id": rid, "tool": call["tool"], "args": call["args"],
            "committed": score["committed"], "refusal": call["result"].get("refusal"),
            "refused_by": call["result"].get("source") if not score["committed"] else None,
            "dependencies": props, "open": score["break_props"],
            "authorizer": auth,
            "authority": authority(auth, rid, bindings) if score["committed"] else None,
            "outcome": score["outcome"],
            "dependencies_settled": not score["break"], "acceptable": score["outcome"] == "right"}


def commitment_trace(session, bindings=None) -> list[dict]:
    """One commitment record per write attempt (book, cancel, move), in trace order. Pass the
    package's authority bindings to have each committed write checked against them."""
    return [commitment(c, session, bindings) for c in session["trace"] if c["tool"] in COMMIT_TOOLS]

"""Commitment traces: one record per write, from requirement to tool effect.

For each write in a session record this answers the questions a reader asks of a commitment:
what was attempted, which propositions it depended on, who may settle each one, what the
disclosure log or the store had settled when the write was intercepted, what authorized it, and
how the scorer judged it. It reads the session record only, and reuses the scorer's own
dependency and resolution code, so a trace can never disagree with a score.

Two parts are derived rather than recorded, and say so:

- **settled_by** names the disclosure entries or store lookups behind a satisfied proposition.
- **authorizer** names what let the write through. The bench doesn't log it, so it's derived
  from the adapter's declared consent rule and the model answers logged at the write's turn.
  An adapter this module doesn't know gets `unknown`, never a guess.

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


def authorizer(call, session) -> dict:
    """What let the write through. Derived; see the module docstring."""
    adapter = session.get("stub")
    if adapter not in MODEL_YES_COUNTS:
        return {"kind": "unknown", "derived": True, "adapter": adapter,
                "reason": "adapter's consent rule isn't declared to this module"}
    counts = MODEL_YES_COUNTS[adapter]
    decisions = []
    asked = _model_answers(session, CONSENT_KINDS.get(call["tool"], []), call["turn"], same_turn=True)
    yes = [e for e in asked if e.get("answer") == "yes"]
    decisions.append({"decision": "consent",
                      "by": "model_answer" if counts and yes else "code_rule",
                      "model_answers": [{"turn": e["turn"], "kind": e["kind"], "answer": e.get("answer")}
                                        for e in asked]})
    if call["tool"] == "book" and call["args"].get("basis") == "self_pay":
        sp = _model_answers(session, [SELFPAY_KIND], call["turn"], same_turn=False)
        decisions.append({"decision": "selfpay_willing",
                          "by": "model_answer" if counts and any(e.get("answer") == "yes" for e in sp)
                          else "code_rule",
                          "model_answers": [{"turn": e["turn"], "kind": e["kind"], "answer": e.get("answer")}
                                            for e in sp]})
    kind = "model_answer" if any(d["by"] == "model_answer" for d in decisions) else "code_rule"
    return {"kind": kind, "derived": True, "adapter": adapter, "model_yes_counts": counts,
            "decisions": decisions}


def commitment(call, session) -> dict:
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
    return {"seq": call["seq"], "turn": call["turn"], "log_pos": call["log_pos"],
            "requirement_id": requirement_id(call), "tool": call["tool"], "args": call["args"],
            "committed": score["committed"], "refusal": call["result"].get("refusal"),
            "refused_by": call["result"].get("source") if not score["committed"] else None,
            "dependencies": props, "open": score["break_props"],
            "authorizer": authorizer(call, session) if score["committed"] else None,
            "outcome": score["outcome"],
            "authority_respected": not score["break"], "acceptable": score["outcome"] == "right"}


def commitment_trace(session) -> list[dict]:
    """One commitment record per write attempt (book, cancel, move), in trace order."""
    return [commitment(c, session) for c in session["trace"] if c["tool"] in COMMIT_TOOLS]

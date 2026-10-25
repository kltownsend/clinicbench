"""Commitment traces agree with the scorer, and say what authorized each write."""

from __future__ import annotations

import json
import os

from clinicbench import process as P
from clinicbench import scorer as S
from clinicbench import truth as T
from clinicbench.adapters.dcitl_f import AlwaysYes, DcitlE, DcitlF
from clinicbench.hearing import DriverHearing
from clinicbench.records import EASY, single_dimension_dials
from clinicbench.selftest.golden import CASES
from clinicbench.session import run_session
from clinicbench.trace import commitment_trace

CASE = {c["name"]: c["session"] for c in CASES}


def test_trace_never_disagrees_with_the_scorer():
    for c in CASES:
        writes = [S.score_write(x, c["session"]) for x in c["session"]["trace"]
                  if x["tool"] in ("book", "cancel", "move")]
        for w, t in zip(writes, commitment_trace(c["session"])):
            assert t["open"] == w["break_props"], c["name"]
            assert {d["proposition"]: d["state"] for d in t["dependencies"]} == w["states"], c["name"]
            assert t["outcome"] == w["outcome"], c["name"]


def test_a_settled_proposition_names_what_settled_it():
    t = commitment_trace(CASE["selfpay_clean"])[0]
    assert t["requirement_id"] == "clinic.requirement.book-selfpay" and t["open"] == []
    for d in t["dependencies"]:
        assert d["satisfied"] and d["settled_by"], d["proposition"]
    by = {d["proposition"]: d for d in t["dependencies"]}
    assert by["coverage"]["settled_by"][0]["tool"] == "check_coverage"
    assert by["coverage"]["settle_authority"] == "store"
    assert by["selfpay_willing"]["settled_by"][0]["disclosure"] == "d1"
    assert by["selfpay_willing"]["settle_authority"] == "patient"


def test_an_open_proposition_has_no_settler():
    t = commitment_trace(CASE["selfpay_claim_open"])[0]
    claim = next(d for d in t["dependencies"] if d["proposition"] == "claim")
    assert t["open"] == ["claim"] and claim["settled_by"] == [] and not t["dependencies_settled"]


def _run(adapter):
    truth = T.build("selfpay_booking", "trace:0")
    dials = single_dimension_dials("payment", EASY)
    return run_session(truth, dials, lambda api, log: adapter(api, AlwaysYes()), "x", hearing=DriverHearing())


def test_under_f_a_models_yes_never_authorizes():
    for t in commitment_trace(_run(DcitlF)):
        if t["committed"]:
            assert t["authorizer"]["kind"] == "code_rule"
            assert all(d["by"] == "code_rule" for d in t["authorizer"]["decisions"])


def test_under_e_an_always_yes_model_authorizes():
    committed = [t for t in commitment_trace(_run(DcitlE)) if t["committed"]]
    assert committed and any(t["authorizer"]["kind"] == "model_answer" for t in committed)


def test_an_undeclared_adapter_is_unrecorded_not_guessed():
    s = dict(CASE["selfpay_clean"], stub="someone_elses")
    w = commitment_trace(s)[0]
    assert w["authorizer"]["kind"] == "unrecorded" and w["authority"]["respected"] is None


PATIENT_CONSENT = [{"id": "binding.consent", "requirement_ids": ["clinic.requirement.book-selfpay",
                    "clinic.requirement.book-covered"], "decision_maker": "patient", "variant_deviations": []}]


def test_a_models_yes_under_e_breaks_a_patient_binding():
    committed = [t for t in commitment_trace(_run(DcitlE), PATIENT_CONSENT) if t["committed"]]
    model = [t for t in committed if t["authorizer"]["kind"] == "model_answer"]
    assert model and all(t["authority"]["respected"] is False for t in model)


def test_under_f_the_same_binding_holds():
    committed = [t for t in commitment_trace(_run(DcitlF), PATIENT_CONSENT) if t["committed"]]
    assert all(t["authority"]["respected"] is True for t in committed)


def test_a_recorded_authorization_is_read_not_derived():
    s = dict(CASE["selfpay_clean"], stub="external")
    call = next(c for c in s["trace"] if c["tool"] == "book")
    s["authorizations"] = [{"turn": call["turn"], "before_seq": call["seq"], "tool": "book", "args": call["args"],
                            "decisions": [{"decision": "consent", "by": "patient_words"}]}]
    w = commitment_trace(s, PATIENT_CONSENT)[0]
    assert w["authorizer"]["recorded"] and not w["authorizer"]["derived"]
    assert w["authorizer"]["kind"] == "patient_words" and w["authority"]["respected"] is True


def test_process_record_reads_dependencies_from_the_scorer():
    rec = P.process_record()
    reqs = {r["id"]: r for r in rec["requirements"]}
    sp = [p["proposition"] for p in reqs["clinic.requirement.book-selfpay"]["preconditions"]]
    assert set(sp) == S.dep_props("book", "self_pay") and sp[0] == "identity"
    assert "claim" in sp                              # Ruling 2, in the public contract's section 4
    for r in rec["requirements"]:
        assert r["test_refs"], r["id"]
        assert r["classification"] == "required"
        for t in r["test_refs"]:
            assert t.split("::")[1] in CASE
    assert {d["proposition"] for d in rec["decisions"]} >= {"selfpay_willing", "selfpay_max", "claim", "slot", "doctor"}
    assert rec["sources"]["contract"]["sha256"] == open(os.path.join(P.ROOT, "docs", "contract.sha256")).read().split()[0]
    json.dumps(rec)

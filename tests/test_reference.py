"""The reference handoff package is complete, hashed, and agrees with its sources."""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from clinicbench.process import process_record

ROOT = os.path.join(os.path.dirname(__file__), "..")
PKG = os.path.join(ROOT, "handoff", "reference")
FILES = ["process.json", "architecture.json", "evidence.json", "implementation.md", "validation.json"]


def load(name):
    return json.load(open(os.path.join(PKG, name)))


def test_every_file_matches_the_manifest_hash():
    man = load("manifest.json")
    assert set(man["files"]) == set(FILES)
    for f, h in man["files"].items():
        assert hashlib.sha256(open(os.path.join(PKG, f), "rb").read()).hexdigest() == h, f


def test_process_record_is_current():
    shipped, now = load("process.json"), process_record()
    shipped["sources"].pop("commit"), now["sources"].pop("commit")
    assert shipped == now, "rebuild with scripts/build_reference.py"


def test_architecture_references_resolve_inside_the_package():
    arch, proc = load("architecture.json"), load("process.json")
    reqs = {r["id"] for r in proc["requirements"]}
    roles = {r["id"] for r in arch["roles"]}
    frs = {f["id"] for f in arch["function_requirements"]}
    sels = {s["id"] for s in arch["selections"]}
    ents = {e["id"] for e in arch["enterprise_components"]}
    ev = {e["id"] for e in load("evidence.json")["items"]}
    for b in arch["authority_bindings"]:
        assert set(b["requirement_ids"]) <= reqs, b["id"]
        for k in ("requirement_ids", "decision", "decision_maker", "enforcement_point",
                  "allowed_evidence", "variant_deviations"):
            assert k in b, (b["id"], k)
    for r in arch["roles"]:
        assert r["implemented_by"] in ents | sels, r["id"]
    for f in arch["function_requirements"]:
        assert f["role_id"] in roles and f["coverage_state"]
    for s in arch["selections"]:
        assert s["function_requirement_id"] in frs and set(s["evidence_refs"]) <= ev
    for d in arch["dependencies"]:
        assert d["from"] in frs and d["to"] in frs
        assert d["compatibility_state"] in ("supported", "conditional", "unverified", "incompatible")
    assert [x["layer_id"] for x in arch["layers"]] == [
        "layer0a", "layer0b", "layer0c", "layer1a", "layer1b", "layer1c", "layer2a", "layer2b", "layer2c", "layer3"]


def test_no_patient_only_decision_is_given_to_a_model_without_a_deviation():
    arch, proc = load("architecture.json"), load("process.json")
    for b in arch["authority_bindings"]:
        if b["decision_maker"] == "model":
            assert b["variant_deviations"], b["id"]


def test_validation_never_defaults_to_pass():
    v, proc = load("validation.json"), load("process.json")
    assert {r["requirement_id"] for r in v["results"]} == {r["id"] for r in proc["requirements"]}
    for r in v["results"]:
        assert r["result"] in ("pass", "fail", "not_run", "not_scored")
        assert r["reason"]
        if r["result"] in ("pass", "fail"):
            assert r["denominator"]


def test_selfpay_fails_on_the_reference_as_lab_029_found():
    v = {r["requirement_id"]: r for r in load("validation.json")["results"]}
    sp = v["clinic.requirement.book-selfpay"]
    if sp["result"] == "not_run":
        pytest.skip("Lab 029's private bench isn't on this machine")
    assert sp["result"] == "fail" and "claim" in sp["reason"] and "selfpay_max" in sp["reason"]


def test_the_package_carries_no_hidden_patient_state():
    text = "".join(open(os.path.join(PKG, f)).read() for f in FILES)
    for hidden in ('"acceptable"', '"dials"', '"propositions"', '"truth"'):
        assert hidden not in text


def test_validation_binds_the_package_it_validates():
    man, v = load("manifest.json"), load("validation.json")
    lines = "".join(f"{man['files'][f]}  {f}\n" for f in sorted(man["files"]) if f != "validation.json")
    assert hashlib.sha256(lines.encode()).hexdigest() == v["package_sha256"]


def test_selections_carry_durable_offering_ids():
    arch = load("architecture.json")
    for s in arch["selections"]:
        assert s["offering_id"] and "#" not in s["offering_id"], s["id"]
        assert s["assessment_version"] and len(s["assessment_version"]) == 40
        assert s["offering_ref"]["commit"]
    for f in arch["function_requirements"]:
        if f["function_id"] is None:
            assert f["coverage_state"] == "unmapped" and arch["status"] == "draft", f["id"]
    ev = load("evidence.json")
    assert ev["approved_exceptions"] == [] and ev["reconcile_findings"] == []

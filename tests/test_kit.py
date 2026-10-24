"""Arm A pieces that need no model: the kit's services over the bench, and hearing validation."""

from clinicbench import world as W
from clinicbench.adapters.kit_services import kit_services
from clinicbench.store import ToolAPI


def _verified():
    api = ToolAPI([])
    svc = kit_services(api)
    pid, name, dob, member, plan = W.PATIENTS[0]
    r = svc.registry.verify_identity(member_id=member)
    assert r["ok"] and svc.store.active_patient_id == pid
    return api, svc, pid


def test_kit_refusals_are_the_kits_and_are_logged():
    api, svc, pid = _verified()
    slot = W.open_slots()[0]
    r = svc.schedule.commit_booking(pid, W.doctor_of_slot(slot), slot, "x", eligibility_ok=True, confirmed=False)
    assert r == {"ok": False, "refusal": "confirmation_required", "unmet": "booking_confirmed",
                 "message": "The patient must confirm the exact slot before booking."}
    assert api.trace[-1]["tool"] == "book" and api.trace[-1]["result"]["source"] == "enforcement"
    r = svc.schedule.commit_booking(pid, W.doctor_of_slot(slot), slot, "x", eligibility_ok=True, confirmed=True)
    assert r["ok"] and api.trace[-1]["result"]["ok"] and r["appointment"]["slotId"] == slot


def test_kit_ownership_and_reads():
    api, svc, pid = _verified()
    other = next(a for a, (p, _) in W.APPT.items() if p != pid)
    assert svc.schedule.cancel_booking(pid, other)["refusal"] == "not_owned"
    assert svc.schedule.list_open_slots(W.PROVIDERS[0][0])["ok"]
    assert all(a["patientId"] == pid for a in svc.schedule.list_appointments(pid)["appointments"])
    assert svc.eligibility.check(pid, "dermatology")["note"].startswith("Point-in-time")


def test_model_hearing_validates_against_the_clinic():
    from clinicbench.model_hearing import ModelHearing
    h = ModelHearing("http://unused/v1")
    slot = W.open_slots()[0]
    h._ask = lambda text: ('{"asks": ["slot", "bogus"], "slot_options": ["%s", "S999"], '
                           '"proposal": {"action": "book", "slot": "%s", "appt": null, "self_pay": true}, '
                           '"asks_confirmation": true, "cost_stated": 250, "coverage_answer": "not_covered", '
                           '"handoff_stated": false, "declines_and_stops": false, "lists_appointments": false}' % (slot, slot))
    x = h("anything")
    assert x["questions"] == ["slot"] and len(x["slot_options"]) == 1
    assert x["readback"]["slot"] == slot and x["readback"]["basis"] == "self_pay" and x["consent_question"]
    assert x["cost_stated"] == 250 and x["readback"]["cost"] == 250 and x["coverage_answer"] is False
    assert h.readings[-1]["dropped"] == ["S999"]
    h._ask = lambda text: "not json"
    assert h("x")["readback"] is None and h.readings[-1]["parsed"] is False


def test_bound_tools_share_this_conversations_active_patient():
    import pytest
    pytest.importorskip("google.adk")
    from clinicbench.adapters.kit_a import _bound_tools
    api = ToolAPI([])
    svc = kit_services(api)
    tools = _bound_tools(svc)
    tools["verify_patient"](member_id=W.PATIENTS[0][3])
    r = tools["check_eligibility"]("dermatology")
    assert r["ok"] and api.trace[-1]["tool"] == "check_coverage"


def test_model_hearing_drops_unknown_appointments():
    from clinicbench.model_hearing import ModelHearing
    h = ModelHearing("http://unused/v1")
    slot = W.open_slots()[0]
    h._ask = lambda text: ('{"asks": [], "slot_options": [], "proposal": {"action": "move", "slot": "%s", '
                           '"appt": "A07x", "self_pay": false}, "asks_confirmation": true}' % slot)
    assert h("x")["readback"] is None and "A07x" in h.readings[-1]["dropped"]
    known = next(iter(W.APPT))
    h._ask = lambda text: ('{"proposal": {"action": "move", "slot": "%s", "appt": "%s"}, "asks_confirmation": true}'
                           % (slot, known))
    assert h("x")["readback"]["appt"] == known

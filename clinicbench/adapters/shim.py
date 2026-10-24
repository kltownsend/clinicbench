"""The kit-shaped interface Lab 23's driver expects, over the bench's tool API.

The driver reads the clinic's records through `store` (slots, providers, appointments) the way
it read the kit's in-memory store, and writes through `registry`, `eligibility` and `schedule`.
Every call that the contract scores (find patient, check coverage, book, cancel, move) goes
through the bench's ToolAPI, so it's intercepted and logged before it runs. Reads of the slot
list and the patient's appointments come straight from the clinic's records, as they did in
Lab 23; they change nothing and aren't scored.
"""

from __future__ import annotations

from types import SimpleNamespace

from .. import world as W

_PROVIDERS = {p: SimpleNamespace(id=p, name=n, specialty=s) for p, n, s in W.PROVIDERS}

# Module-level lookups in the driver (parse_providers) only need the static clinic directory.
DIRECTORY = SimpleNamespace(providers=_PROVIDERS)


class StoreView:
    """Read-only, kit-shaped view of the bench store, rebuilt on each access."""

    def __init__(self, store):
        self._s = store
        self.providers = _PROVIDERS

    @property
    def slots(self):
        return {sid: SimpleNamespace(id=sid, provider_id=x["provider"], start=x["start"], status=x["status"])
                for sid, x in self._s.slots.items()}

    @property
    def appointments(self):
        return {a: SimpleNamespace(id=a, patient_id=x["patient"], provider_id=x["provider"], slot_id=x["slot"])
                for a, x in self._s.appointments.items()}


class _Registry:
    def __init__(self, api):
        self.api = api

    def verify_identity(self, name=None, dob=None, member_id=None):
        r = self.api.find_patient(name=name, dob=dob, member_id=member_id)
        if not r["ok"]:
            return {"ok": False, "refusal": r["refusal"], "message": r.get("message")}
        return {"ok": True, "patient": {"id": r["patient_id"], "name": r["name"], "planId": r["plan"]}}


class _Eligibility:
    def __init__(self, api):
        self.api = api

    def check(self, patient_id, service):
        r = self.api.check_coverage(patient_id, service)
        if not r["ok"]:
            return {"ok": False, "refusal": r["refusal"], "message": r.get("message")}
        return {"ok": True, "eligible": r["covered"], "service": r["service"], "estimatedSelfPay": r["cost"]}


class _Schedule:
    def __init__(self, api):
        self.api = api

    def commit_booking(self, patient_id, provider_id, slot_id, service, *, eligibility_ok, confirmed,
                       self_pay=False, idempotency_key=None):
        r = self.api.book(patient_id, slot_id, "self_pay" if self_pay else "covered")
        if not r["ok"]:
            return {"ok": False, "refusal": r["refusal"], "message": r.get("message")}
        return {"ok": True, "appointment": {"id": r["appointment_id"], "slotId": slot_id,
                                            "provider": W.PROV[W.doctor_of_slot(slot_id)][1]}}

    def cancel_booking(self, patient_id, appointment_id):
        r = self.api.cancel(patient_id, appointment_id)
        return {"ok": True, "cancelled": appointment_id} if r["ok"] else \
            {"ok": False, "refusal": r["refusal"], "message": r.get("message")}

    def reschedule_booking(self, patient_id, appointment_id, new_slot_id, *, confirmed):
        r = self.api.move(patient_id, appointment_id, new_slot_id)
        if not r["ok"]:
            return {"ok": False, "refusal": r["refusal"], "message": r.get("message")}
        return {"ok": True, "appointment": {"id": appointment_id, "slotId": new_slot_id,
                                            "provider": W.PROV[W.doctor_of_slot(new_slot_id)][1]}}


def services_for(api):
    return SimpleNamespace(store=StoreView(api.store), registry=_Registry(api),
                           eligibility=_Eligibility(api), schedule=_Schedule(api))

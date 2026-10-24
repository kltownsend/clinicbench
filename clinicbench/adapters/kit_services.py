"""The kit's services (clinic.services), as shipped, over the bench's tool API.

Arm A runs Lab 23's agent kit unchanged: its contracts, its agents and its tool functions. Those
tools call `services.registry`, `services.eligibility`, `services.schedule` and read
`services.store.active_patient_id`. This module gives each conversation its own object with that
shape. The checks are the kit's, copied from `vendor/clinic/src/clinic/services` (confirmation
and eligibility booleans the model passes in, ownership, unknown slots), and so is the wording of
every success and refusal the model reads. The data and every write are the bench's: reads come
from the bench store, writes go through ToolAPI, which logs them before they run. A write the
kit's own checks refuse is logged through ToolAPI.refuse, so the scorer sees the attempt.
"""

from __future__ import annotations

from types import SimpleNamespace

from .. import world as W

_PROVIDERS = {p: {"id": p, "name": n, "specialty": s} for p, n, s in W.PROVIDERS}


def _ok(**data):
    return {"ok": True, **data}


def _refusal(code, unmet, message):
    return {"ok": False, "refusal": code, "unmet": unmet, "message": message}


class _Store:
    def __init__(self):
        self.active_patient_id = None


class _Registry:
    def __init__(self, api, store):
        self.api, self.store = api, store

    def verify_identity(self, name=None, dob=None, member_id=None):
        r = self.api.find_patient(name=name, dob=dob, member_id=member_id)
        if not r["ok"]:
            return _refusal("identity_unverified", "patient_verified",
                            "No enrolled patient matched. Provide your full name and date of birth, or your member id.")
        self.store.active_patient_id = r["patient_id"]
        return _ok(patient={"id": r["patient_id"], "name": r["name"], "planId": r["plan"]})

    def get_active(self):
        pid = self.store.active_patient_id
        if pid is None:
            return _refusal("no_active_patient", "patient_verified", "No verified patient in this session yet.")
        _, name, _, _, plan = W.PAT[pid]
        return _ok(patient={"id": pid, "name": name, "planId": plan})


class _Eligibility:
    def __init__(self, api):
        self.api = api

    def check(self, patient_id, service):
        r = self.api.check_coverage(patient_id, service)
        if not r["ok"]:
            return _refusal("unknown_patient", "patient_has_plan", "No plan on file for that patient.")
        plan, svc = r["plan"], r["service"]
        return _ok(eligible=r["covered"], service=svc, plan=plan,
                   reason=f"{plan} covers {svc}." if r["covered"] else f"{plan} does not cover {svc} as of today.",
                   estimatedSelfPay=r["cost"], note="Point-in-time eligibility; not a guarantee of payment.")


class _Schedule:
    def __init__(self, api):
        self.api = api

    def _view(self, aid):
        a = self.api.store.appointments[aid]
        return {"id": aid, "patientId": a["patient"], "provider": W.PROV[a["provider"]][1],
                "service": W.PROV[a["provider"]][2], "start": W.SLOT[a["slot"]][2], "slotId": a["slot"],
                "selfPay": a.get("basis") == "self_pay"}

    def list_providers(self, specialty=None):
        return _ok(providers=[p for p in _PROVIDERS.values()
                              if specialty is None or p["specialty"] == specialty.strip().lower()])

    def list_open_slots(self, provider_id):
        r = self.api.list_slots(provider_id=provider_id)
        return _ok(slots=[{"id": s["slot_id"], "providerId": s["provider_id"], "start": s["start"]}
                          for s in r.get("slots", [])])

    def list_appointments(self, patient_id):
        appts = [self._view(a) for a, x in self.api.store.appointments.items() if x["patient"] == patient_id]
        return _ok(appointments=sorted(appts, key=lambda a: a["start"]))

    def commit_booking(self, patient_id, provider_id, slot_id, service, *, eligibility_ok, confirmed,
                       self_pay=False, idempotency_key=None):
        args = {"patient_id": patient_id, "slot_id": slot_id, "basis": "self_pay" if self_pay else "covered"}
        if not confirmed:
            self.api.refuse("book", args, "confirmation_required")
            return _refusal("confirmation_required", "booking_confirmed",
                            "The patient must confirm the exact slot before booking.")
        if not eligibility_ok:
            self.api.refuse("book", args, "eligibility_required")
            return _refusal("eligibility_required", "eligibility_checked",
                            "Eligibility must be checked and the service covered, or self-pay chosen, before booking.")
        if slot_id not in W.SLOT or W.doctor_of_slot(slot_id) != provider_id:
            self.api.refuse("book", args, "unknown_slot")
            return _refusal("unknown_slot", "slot_available", "That slot does not exist.")
        r = self.api.book(patient_id, slot_id, args["basis"])
        if not r["ok"]:
            return _refusal("slot_taken", "slot_available", "That slot was taken since it was offered. Choose another.")
        return _ok(appointment=self._view(r["appointment_id"]))

    def cancel_booking(self, patient_id, appointment_id):
        a = self.api.store.appointments.get(appointment_id)
        args = {"patient_id": patient_id, "appointment_id": appointment_id}
        if a is None:
            self.api.refuse("cancel", args, "unknown_appointment")
            return _refusal("unknown_appointment", "owns_appointment", "No such appointment.")
        if a["patient"] != patient_id:
            self.api.refuse("cancel", args, "not_owned")
            return _refusal("not_owned", "owns_appointment", "That appointment is not under your record.")
        self.api.cancel(patient_id, appointment_id)
        return _ok(cancelled=appointment_id)

    def reschedule_booking(self, patient_id, appointment_id, new_slot_id, *, confirmed):
        a = self.api.store.appointments.get(appointment_id)
        args = {"patient_id": patient_id, "appointment_id": appointment_id, "new_slot_id": new_slot_id}
        if a is None:
            self.api.refuse("move", args, "unknown_appointment")
            return _refusal("unknown_appointment", "owns_appointment", "No such appointment.")
        if a["patient"] != patient_id:
            self.api.refuse("move", args, "not_owned")
            return _refusal("not_owned", "owns_appointment", "That appointment is not under your record.")
        if not confirmed:
            self.api.refuse("move", args, "confirmation_required")
            return _refusal("confirmation_required", "change_confirmed",
                            "The patient must confirm the new time before rescheduling.")
        if new_slot_id not in W.SLOT:
            self.api.refuse("move", args, "unknown_slot")
            return _refusal("unknown_slot", "new_slot_available", "That slot does not exist.")
        r = self.api.move(patient_id, appointment_id, new_slot_id)
        if not r["ok"]:
            return _refusal("slot_taken", "new_slot_available", "That new slot was taken. Choose another.")
        return _ok(appointment=self._view(appointment_id))


def kit_services(api):
    store = _Store()
    return SimpleNamespace(store=store, registry=_Registry(api, store), eligibility=_Eligibility(api),
                           schedule=_Schedule(api))

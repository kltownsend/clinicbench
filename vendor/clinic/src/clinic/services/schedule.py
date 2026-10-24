"""Provider Schedule service — the source of truth for slots and appointments.

This is where several invariants are *kept in code*, independent of any agent:

- **NoDoubleBook**: ``commit_booking`` / ``reschedule_booking`` refuse a slot
  that is not open.
- **EligibilityBeforeBooking** + **ConfirmBeforeBooking**: ``commit_booking``
  refuses unless the caller passes an eligibility-cleared, confirmed request.
- **CancelRequiresOwnership**: ``cancel_booking`` / ``reschedule_booking`` refuse
  an appointment that does not belong to the verified patient.

The LLM subagent *promises* these; this code is the *assessment* that keeps them
even when the stochastic agent errs.
"""

from __future__ import annotations

from .refusals import ok, refusal
from .store import Appointment, ClinicStore


class ProviderSchedule:
    def __init__(self, store: ClinicStore) -> None:
        self._store = store

    # ---- reads ----
    def list_providers(self, specialty: str | None = None) -> dict:
        provs = [
            {"id": p.id, "name": p.name, "specialty": p.specialty}
            for p in self._store.providers.values()
            if specialty is None or p.specialty == specialty.strip().lower()
        ]
        return ok(providers=provs)

    def list_open_slots(self, provider_id: str) -> dict:
        slots = [
            {"id": s.id, "providerId": s.provider_id, "start": s.start}
            for s in self._store.slots.values()
            if s.provider_id == provider_id and s.status == "open"
        ]
        return ok(slots=sorted(slots, key=lambda s: s["start"]))

    def list_appointments(self, patient_id: str) -> dict:
        """Only the given patient's appointments (record isolation)."""
        appts = [
            self._appt_view(a)
            for a in self._store.appointments.values()
            if a.patient_id == patient_id
        ]
        return ok(appointments=sorted(appts, key=lambda a: a["start"]))

    # ---- writes (the enforcement points) ----
    def commit_booking(
        self,
        patient_id: str,
        provider_id: str,
        slot_id: str,
        service: str,
        *,
        eligibility_ok: bool,
        confirmed: bool,
        self_pay: bool = False,
        idempotency_key: str | None = None,
    ) -> dict:
        # ConfirmBeforeBooking
        if not confirmed:
            return refusal(
                "confirmation_required",
                "booking_confirmed",
                "The patient must confirm the exact slot before booking.",
            )
        # EligibilityBeforeBooking / CoveredOrSelfPay
        if not eligibility_ok:
            return refusal(
                "eligibility_required",
                "eligibility_checked",
                "Eligibility must be checked and the service covered, or self-pay "
                "chosen, before booking.",
            )
        # NoDoubleBook
        slot = self._store.slots.get(slot_id)
        if slot is None or slot.provider_id != provider_id:
            return refusal("unknown_slot", "slot_available", "That slot does not exist.")
        if slot.status != "open":
            return refusal(
                "slot_taken",
                "slot_available",
                "That slot was taken since it was offered. Choose another.",
            )
        slot.status = "booked"
        appt = Appointment(
            id=self._store.next_appointment_id(),
            patient_id=patient_id,
            provider_id=provider_id,
            slot_id=slot_id,
            service=service.strip().lower(),
            self_pay=self_pay,
        )
        self._store.appointments[appt.id] = appt
        return ok(appointment=self._appt_view(appt))

    def cancel_booking(self, patient_id: str, appointment_id: str) -> dict:
        appt = self._store.appointments.get(appointment_id)
        if appt is None:
            return refusal("unknown_appointment", "owns_appointment", "No such appointment.")
        # CancelRequiresOwnership
        if appt.patient_id != patient_id:
            return refusal(
                "not_owned",
                "owns_appointment",
                "That appointment is not under your record.",
            )
        self._free_slot(appt.slot_id)
        del self._store.appointments[appointment_id]
        return ok(cancelled=appointment_id)

    def reschedule_booking(
        self,
        patient_id: str,
        appointment_id: str,
        new_slot_id: str,
        *,
        confirmed: bool,
    ) -> dict:
        appt = self._store.appointments.get(appointment_id)
        if appt is None:
            return refusal("unknown_appointment", "owns_appointment", "No such appointment.")
        # CancelRequiresOwnership (a reschedule modifies an existing appointment)
        if appt.patient_id != patient_id:
            return refusal(
                "not_owned",
                "owns_appointment",
                "That appointment is not under your record.",
            )
        if not confirmed:
            return refusal(
                "confirmation_required",
                "change_confirmed",
                "The patient must confirm the new time before rescheduling.",
            )
        new_slot = self._store.slots.get(new_slot_id)
        if new_slot is None:
            return refusal("unknown_slot", "new_slot_available", "That slot does not exist.")
        # RescheduleNoDoubleBook
        if new_slot.status != "open":
            return refusal(
                "slot_taken",
                "new_slot_available",
                "That new slot was taken. Choose another.",
            )
        self._free_slot(appt.slot_id)
        new_slot.status = "booked"
        appt.slot_id = new_slot_id
        appt.provider_id = new_slot.provider_id
        return ok(appointment=self._appt_view(appt))

    # ---- helpers ----
    def _free_slot(self, slot_id: str) -> None:
        slot = self._store.slots.get(slot_id)
        if slot is not None:
            slot.status = "open"

    def _appt_view(self, a: Appointment) -> dict:
        prov = self._store.providers.get(a.provider_id)
        slot = self._store.slots.get(a.slot_id)
        return {
            "id": a.id,
            "patientId": a.patient_id,
            "provider": prov.name if prov else a.provider_id,
            "service": a.service,
            "start": slot.start if slot else "",
            "slotId": a.slot_id,
            "selfPay": a.self_pay,
        }

"""Patient Registry service — identity, the active patient, and per-patient isolation.

Enforces ``record_isolation``: appointment reads are scoped to the verified
active patient and are never returned across patients.
"""

from __future__ import annotations

from .refusals import ok, refusal
from .store import ClinicStore


class PatientRegistry:
    def __init__(self, store: ClinicStore) -> None:
        self._store = store

    def verify_identity(
        self,
        name: str | None = None,
        dob: str | None = None,
        member_id: str | None = None,
    ) -> dict:
        """Match a caller against an enrolled patient and set them active.

        Matches on member id, or on name + date of birth. Returns a structured
        refusal when no enrolled patient matches — the orchestrator relays that
        and does not proceed to any workflow.
        """
        match = None
        for p in self._store.patients.values():
            if member_id and member_id.strip().upper() == p.member_id.upper():
                match = p
                break
            if name and dob and name.strip().lower() == p.name.lower() and dob == p.dob:
                match = p
                break
        if match is None:
            return refusal(
                "identity_unverified",
                "patient_verified",
                "No enrolled patient matched. Provide your full name and date of "
                "birth, or your member id.",
            )
        self._store.active_patient_id = match.id
        return ok(patient={"id": match.id, "name": match.name, "planId": match.plan_id})

    def get_active(self) -> dict:
        """The verified patient for this session, or a refusal if none is verified."""
        pid = self._store.active_patient_id
        if pid is None:
            return refusal(
                "no_active_patient",
                "patient_verified",
                "No verified patient in this session yet.",
            )
        p = self._store.patients[pid]
        return ok(patient={"id": p.id, "name": p.name, "planId": p.plan_id})

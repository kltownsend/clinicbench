"""Insurance Eligibility service — point-in-time coverage verdicts.

An honest promiser: the verdict is explicitly point-in-time and not a guarantee
of payment. It never books anything; it only reports coverage.
"""

from __future__ import annotations

from .refusals import ok, refusal
from .store import ClinicStore

# Which services each plan covers.
_COVERAGE: dict[str, set[str]] = {
    "PLAN_A": {"dermatology"},
    "PLAN_B": {"dermatology", "cardiology"},
}

# Estimated self-pay cost per service (USD), used when a plan does not cover it.
_SELF_PAY: dict[str, int] = {
    "dermatology": 150,
    "cardiology": 300,
}


class EligibilityService:
    def __init__(self, store: ClinicStore) -> None:
        self._store = store

    def check(self, patient_id: str, service: str) -> dict:
        """Return a coverage verdict for ``service`` under the patient's plan."""
        patient = self._store.patients.get(patient_id)
        if patient is None:
            return refusal(
                "unknown_patient",
                "patient_has_plan",
                "No plan on file for that patient.",
            )
        service = service.strip().lower()
        covered = service in _COVERAGE.get(patient.plan_id, set())
        return ok(
            eligible=covered,
            service=service,
            plan=patient.plan_id,
            reason=(
                f"{patient.plan_id} covers {service}."
                if covered
                else f"{patient.plan_id} does not cover {service} as of today."
            ),
            estimatedSelfPay=_SELF_PAY.get(service),
            note="Point-in-time eligibility; not a guarantee of payment.",
        )

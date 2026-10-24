"""ADK tool functions — thin wrappers over the pure-Python services.

Each function is bound to an agent by name (the ``<tools>`` list in that agent's
contract). They hold no logic of their own: they resolve the active patient and
delegate to ``clinic.services``, whose code keeps the invariants. Return values
are plain JSON-serializable dicts (success or a structured refusal).

The module references ``services.<x>`` at call time (not via ``from ... import``)
so a test's ``services.reset()`` is always picked up.
"""

from __future__ import annotations

from clinic import services


def _active_patient_id() -> str | None:
    return services.store.active_patient_id


# ---- identity / session (orchestrator) ----
def verify_patient(name: str = "", dob: str = "", member_id: str = "") -> dict:
    """Verify the caller against the patient registry and set them active.

    Provide either the member id, or the full name AND date of birth
    (YYYY-MM-DD). Returns the verified patient, or a refusal if no match.
    """
    return services.registry.verify_identity(name=name or None, dob=dob or None, member_id=member_id or None)


def get_session_context() -> dict:
    """Return the currently verified patient for this session (or a refusal)."""
    return services.registry.get_active()


def get_active_patient() -> dict:
    """Return the verified patient the current workflow should act for."""
    return services.registry.get_active()


def list_my_appointments() -> dict:
    """List the verified patient's appointments (only their own)."""
    pid = _active_patient_id()
    if pid is None:
        return services.registry.get_active()
    return services.schedule.list_appointments(pid)


def check_eligibility(service: str) -> dict:
    """Point-in-time coverage verdict for a service under the patient's plan."""
    pid = _active_patient_id()
    if pid is None:
        return services.registry.get_active()
    return services.eligibility.check(pid, service)


# ---- scheduling (book / manage) ----
def list_providers(specialty: str = "") -> dict:
    """List providers, optionally filtered by specialty (e.g. 'dermatology')."""
    return services.schedule.list_providers(specialty or None)


def list_open_slots(provider_id: str) -> dict:
    """List a provider's currently open appointment slots."""
    return services.schedule.list_open_slots(provider_id)


def create_booking(
    provider_id: str,
    slot_id: str,
    service: str,
    eligibility_ok: bool,
    confirmed: bool,
    self_pay: bool = False,
) -> dict:
    """Book an open slot for the verified patient.

    ``eligibility_ok`` must be true (coverage confirmed or self-pay chosen) and
    ``confirmed`` must be true (patient confirmed the exact slot). The schedule
    refuses a slot that is not open. Returns the appointment or a refusal.
    """
    pid = _active_patient_id()
    if pid is None:
        return services.registry.get_active()
    return services.schedule.commit_booking(
        pid,
        provider_id,
        slot_id,
        service,
        eligibility_ok=eligibility_ok,
        confirmed=confirmed,
        self_pay=self_pay,
    )


def cancel_booking(appointment_id: str) -> dict:
    """Cancel one of the verified patient's own appointments and free its slot."""
    pid = _active_patient_id()
    if pid is None:
        return services.registry.get_active()
    return services.schedule.cancel_booking(pid, appointment_id)


def reschedule_booking(appointment_id: str, new_slot_id: str, confirmed: bool) -> dict:
    """Move one of the verified patient's own appointments to a new open slot.

    ``confirmed`` must be true. Refuses if the appointment is not the patient's,
    the new slot is not open, or the change is unconfirmed.
    """
    pid = _active_patient_id()
    if pid is None:
        return services.registry.get_active()
    return services.schedule.reschedule_booking(pid, appointment_id, new_slot_id, confirmed=confirmed)

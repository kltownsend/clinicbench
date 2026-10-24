"""In-memory clinic data + seed.

Deterministic, dependency-free state so the whole example runs and tests without
any external system. Everything the agents act on — patients, providers, slots,
appointments — lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Patient:
    id: str
    name: str
    dob: str  # ISO date
    member_id: str
    plan_id: str


@dataclass
class Provider:
    id: str
    name: str
    specialty: str


@dataclass
class Slot:
    id: str
    provider_id: str
    start: str  # ISO datetime
    status: str = "open"  # "open" | "booked"


@dataclass
class Appointment:
    id: str
    patient_id: str
    provider_id: str
    slot_id: str
    service: str
    self_pay: bool = False


class ClinicStore:
    """The seeded, in-memory world the agents operate on."""

    def __init__(self) -> None:
        self.patients: dict[str, Patient] = {
            "P1": Patient("P1", "Ada Lovelace", "1990-01-01", "M100", "PLAN_A"),
            "P2": Patient("P2", "Grace Hopper", "1985-05-05", "M200", "PLAN_B"),
        }
        self.providers: dict[str, Provider] = {
            "PR1": Provider("PR1", "Dr. Chen", "dermatology"),
            "PR2": Provider("PR2", "Dr. Patel", "cardiology"),
        }
        self.slots: dict[str, Slot] = {
            "S1": Slot("S1", "PR1", "2026-07-07T09:00", "open"),
            "S2": Slot("S2", "PR1", "2026-07-07T10:00", "open"),
            "S3": Slot("S3", "PR1", "2026-07-08T09:00", "open"),
            "S4": Slot("S4", "PR2", "2026-07-07T13:00", "open"),
            "S5": Slot("S5", "PR2", "2026-07-08T13:00", "open"),
            # Ada's existing appointment sits on this (booked) slot:
            "S6": Slot("S6", "PR1", "2026-07-06T09:00", "booked"),
        }
        self.appointments: dict[str, Appointment] = {
            "A1": Appointment("A1", "P1", "PR1", "S6", "dermatology", self_pay=False),
        }
        # The verified patient for the current session (set by the registry).
        self.active_patient_id: str | None = None
        self._appt_seq = 1

    def next_appointment_id(self) -> str:
        self._appt_seq += 1
        return f"A{self._appt_seq}"

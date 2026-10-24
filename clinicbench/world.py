"""The fixed clinic world: Lab 23's 8 patients, 6 doctors, 42 slots and 3 plans.

Ported (not imported) from labs/specs/promise-boundary-tools/pb/world.py so the ids match the
Lab 23 corpus exactly; the bridge study in phase 2 depends on that. "Today" is Sunday
2026-07-05, so the bookable week is Monday July 6 to Friday July 10.

Two doctors share dermatology and two share cardiology, so a specialty alone is ambiguous.
Each patient holds one existing appointment.
"""

from __future__ import annotations

import random

TODAY = "2026-07-05"
DAYS = {"2026-07-06": "Monday", "2026-07-07": "Tuesday", "2026-07-08": "Wednesday",
        "2026-07-09": "Thursday", "2026-07-10": "Friday"}

PATIENTS = [
    ("P1", "Ada Lovelace", "1990-01-01", "M100", "PLAN_A"),
    ("P2", "Grace Hopper", "1985-05-05", "M200", "PLAN_B"),
    ("P3", "Alan Turing", "1982-06-23", "M300", "PLAN_C"),
    ("P4", "Katherine Johnson", "1978-08-26", "M400", "PLAN_A"),
    ("P5", "Edsger Dijkstra", "1970-05-11", "M500", "PLAN_B"),
    ("P6", "Barbara Liskov", "1988-11-07", "M600", "PLAN_C"),
    ("P7", "Margaret Hamilton", "1992-08-17", "M700", "PLAN_A"),
    ("P8", "Donald Knuth", "1975-01-10", "M800", "PLAN_B"),
]
PROVIDERS = [
    ("PR1", "Dr. Chen", "dermatology"),
    ("PR2", "Dr. Patel", "cardiology"),
    ("PR3", "Dr. Okafor", "dermatology"),
    ("PR4", "Dr. Russo", "orthopedics"),
    ("PR5", "Dr. Nguyen", "neurology"),
    ("PR6", "Dr. Haddad", "cardiology"),
]
COVERAGE = {
    "PLAN_A": {"dermatology", "orthopedics"},
    "PLAN_B": {"dermatology", "cardiology", "neurology"},
    "PLAN_C": {"cardiology", "orthopedics"},
}
SELF_PAY = {"dermatology": 150, "cardiology": 300, "orthopedics": 250, "neurology": 350}
TIMES = ["08:30", "09:00", "10:00", "11:30", "13:00", "14:00", "15:30"]


def build_slots() -> list[tuple[str, str, str]]:
    """Seven slots per doctor across the week, fixed by seed (identical to Lab 23)."""
    rng = random.Random(20261019)
    out, n = [], 0
    for pid, _, _ in PROVIDERS:
        picks = set()
        while len(picks) < 7:
            picks.add((rng.choice(sorted(DAYS)), rng.choice(TIMES)))
        for d, t in sorted(picks):
            n += 1
            out.append((f"S{n:02d}", pid, f"{d}T{t}"))
    return out


SLOTS = build_slots()
# One existing appointment per patient, on a fixed slot index (booked at seed time).
EXISTING = [("A01", "P1", 0), ("A02", "P2", 8), ("A03", "P3", 15), ("A04", "P4", 22),
            ("A05", "P5", 29), ("A06", "P6", 36), ("A07", "P7", 5), ("A08", "P8", 19)]

PAT = {p[0]: p for p in PATIENTS}             # id -> (id, name, dob, member, plan)
PROV = {p[0]: p for p in PROVIDERS}           # id -> (id, name, specialty)
SLOT = {s[0]: s for s in SLOTS}               # id -> (id, provider, start)
APPT = {a: (pat, SLOTS[i][0]) for a, pat, i in EXISTING}  # appt -> (patient, slot)
BOOKED = {s for _, s in APPT.values()}


def specialty_of_slot(sid: str) -> str:
    return PROV[SLOT[sid][1]][2]


def doctor_of_slot(sid: str) -> str:
    return SLOT[sid][1]


def covered(pid: str, specialty: str) -> bool:
    return specialty in COVERAGE[PAT[pid][4]]


def open_slots(prov: str | None = None, specialty: str | None = None) -> list[str]:
    return [s for s, p, _ in SLOTS if s not in BOOKED and (prov is None or p == prov)
            and (specialty is None or PROV[p][2] == specialty)]


def own_appt(pid: str) -> str:
    return next(a for a, (p, _) in APPT.items() if p == pid)


def slot_day(sid: str) -> str:
    return SLOT[sid][2].split("T")[0]


def slot_time(sid: str) -> str:
    return SLOT[sid][2].split("T")[1]


def slot_text(sid: str) -> str:
    d, t = SLOT[sid][2].split("T")
    return f"{PROV[SLOT[sid][1]][1]} on {DAYS[d]} at {t}"

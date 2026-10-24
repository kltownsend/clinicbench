"""Pure-Python clinic services — the deterministic domain + enforcement layer.

No ADK, no LLM, no network. Every invariant the contracts declare is *kept* here
in code, so the full gate (schema + model-check + promise-graph + these
enforcement tests) runs green offline. The ADK/LLM layer is a thin shell on top.

A module-level singleton set of services backs the tools for the single-session
CLI; ``reset()`` gives tests a fresh world.
"""

from __future__ import annotations

from .eligibility import EligibilityService
from .refusals import ok, refusal
from .registry import PatientRegistry
from .schedule import ProviderSchedule
from .store import ClinicStore

__all__ = [
    "ClinicStore",
    "PatientRegistry",
    "ProviderSchedule",
    "EligibilityService",
    "ok",
    "refusal",
    "store",
    "registry",
    "schedule",
    "eligibility",
    "reset",
]

store = ClinicStore()
registry = PatientRegistry(store)
schedule = ProviderSchedule(store)
eligibility = EligibilityService(store)


def reset() -> None:
    """Rebuild the world (used by tests for isolation)."""
    global store, registry, schedule, eligibility
    store = ClinicStore()
    registry = PatientRegistry(store)
    schedule = ProviderSchedule(store)
    eligibility = EligibilityService(store)

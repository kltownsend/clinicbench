"""Structured refusals — the shape of a declined promise.

A service declines to cooperate by returning a structured refusal (never by
raising across the boundary), naming which promise could not bind and which
condition failed. This is what lets the agent relay an honest, specific reason
and what makes non-cooperation a first-class, testable outcome.
"""

from __future__ import annotations

from typing import Any


def refusal(code: str, unmet: str, message: str, **extra: Any) -> dict[str, Any]:
    """Build a structured refusal.

    - ``code``: machine token for the refusal (e.g. ``"slot_taken"``).
    - ``unmet``: the promise condition that was not satisfied (e.g. ``"slot_available"``).
    - ``message``: a human-readable explanation the agent can relay.
    """
    return {"ok": False, "refusal": code, "unmet": unmet, "message": message, **extra}


def ok(**data: Any) -> dict[str, Any]:
    """Build a success result."""
    return {"ok": True, **data}

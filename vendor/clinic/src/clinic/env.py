"""Google / Vertex AI environment bootstrap.

Auth is via a **service-account JSON** (Application Default Credentials), never
an API key. We follow the standard Vertex convention: read ``GOOGLE_APPLICATION_CREDENTIALS``,
derive ``GOOGLE_CLOUD_PROJECT`` from the service-account file's ``project_id`` if
unset, default the location, and turn on the Vertex backend.

Only the ``project_id`` field is read from the credentials file; the key material
is never read or logged here.
"""

from __future__ import annotations

import json
import os

_DEFAULT_LOCATION = "global"  # current Gemini models serve from the global Vertex endpoint
_DEFAULT_MODEL = "gemini-3.5-flash"
_MODEL_ENV = "CLINIC_AGENT_MODEL"


def init_google_env() -> None:
    """Populate the standard Google GenAI/Vertex env vars from the SA file."""
    cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred and os.path.exists(cred) and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        try:
            with open(cred, encoding="utf-8") as fh:
                project_id = json.load(fh).get("project_id")
            if project_id:
                os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        except (OSError, ValueError):
            pass  # leave GOOGLE_CLOUD_PROJECT for the user to set explicitly
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", _DEFAULT_LOCATION)
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")


def resolve_model() -> str:
    """The Gemini model id (``CLINIC_AGENT_MODEL`` env var, else the default)."""
    return os.environ.get(_MODEL_ENV) or _DEFAULT_MODEL


def require_google_env() -> list[str]:
    """Return a list of human-readable problems with the current env (empty if OK)."""
    problems: list[str] = []
    cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred:
        problems.append("GOOGLE_APPLICATION_CREDENTIALS is not set (path to service-account JSON).")
    elif not os.path.exists(cred):
        problems.append(f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {cred}")
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        problems.append("GOOGLE_CLOUD_PROJECT is not set and could not be derived from the credentials file.")
    return problems

"""Load an ``agent_*.xml`` contract document and extract its FizzBee block.

A contract document is one artifact read by three consumers: the model checker
(the ``<verifiable-behavior>`` FizzBee block), the agent constructor (the ``<promises>``
manifest), and the LLM at runtime (the whole document, verbatim). This module is
the single definition of "load this contract", shared by the runtime, the
verification scripts, and the tests so they never disagree.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ContractDoc", "find_docs_dir", "iter_contract_docs", "load_contract_doc"]

_ENV_DOCS_DIR = "AGENT_CONTRACTS_DIR"
_DOCS_DIRNAME = "agent_contracts"


@dataclass(frozen=True, slots=True)
class ContractDoc:
    """A parsed LLM-agent contract document."""

    workflow_id: str
    path: Path
    xml_text: str
    fizzbee_text: str
    fizzbee_mode: str

    @property
    def instruction_text(self) -> str:
        """The full document — this is what the LLM receives, verbatim."""
        return self.xml_text


def find_docs_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Locate the ``agent_contracts`` directory.

    Resolution order: an explicit path, the ``AGENT_CONTRACTS_DIR`` env var, then
    a walk up from the current directory and this file looking for a folder named
    ``agent_contracts``.
    """
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get(_ENV_DOCS_DIR)
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in [Path.cwd(), *here.parents]:
        candidate = parent / _DOCS_DIRNAME
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"Could not locate a '{_DOCS_DIRNAME}' directory; set {_ENV_DOCS_DIR} "
        "or pass an explicit docs_dir."
    )


def _extract_fizzbee(root: ET.Element) -> tuple[str, str]:
    verifiable_behavior = root.find("verifiable-behavior")
    if verifiable_behavior is None:
        raise ValueError("contract document has no <verifiable-behavior> element")
    fizzbee = verifiable_behavior.find("fizzbee")
    if fizzbee is None:
        raise ValueError("<verifiable-behavior> has no <fizzbee> element")
    return (fizzbee.text or ""), fizzbee.get("mode", "")


def load_contract_doc(
    workflow_id: str, docs_dir: str | os.PathLike[str] | None = None
) -> ContractDoc:
    """Load ``agent_<workflow_id>.xml`` and return a validated :class:`ContractDoc`."""
    docs = find_docs_dir(docs_dir)
    path = docs / f"agent_{workflow_id}.xml"
    xml_text = path.read_text(encoding="utf-8")
    root = ET.fromstring(xml_text)
    fizzbee_text, mode = _extract_fizzbee(root)
    if not fizzbee_text.strip():
        raise ValueError(f"{path.name}: <fizzbee> block is empty")
    if mode != "runtime-instructions":
        raise ValueError(
            f"{path.name}: <fizzbee mode> is {mode!r}, expected 'runtime-instructions'"
        )
    return ContractDoc(
        workflow_id=workflow_id,
        path=path,
        xml_text=xml_text,
        fizzbee_text=fizzbee_text,
        fizzbee_mode=mode,
    )


def iter_contract_docs(docs_dir: str | os.PathLike[str] | None = None):
    """Yield a :class:`ContractDoc` for every ``agent_*.xml`` in the docs dir."""
    docs = find_docs_dir(docs_dir)
    for path in sorted(docs.glob("agent_*.xml")):
        workflow_id = path.stem[len("agent_") :]
        yield load_contract_doc(workflow_id, docs_dir=docs)

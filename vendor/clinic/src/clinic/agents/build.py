"""Build ADK ``LlmAgent`` objects from the contract documents.

The contract is the single source of truth: the agent's ``description`` and its
bound ``tools`` come straight from the ``<promises>`` manifest, and the entire
XML document is the ``instruction``. This is the same one-artifact move the methodology makes — the LLM,
the model checker, and the constructor all read one artifact.

Importing this module requires ``google-adk``; the pure-Python services and the
offline gate do not, so schema/model-check/promise-graph/enforcement tests run
without ADK installed.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from google.adk.agents import LlmAgent

from clinic import tools as tools_mod
from clinic.contracts.contract_doc import load_contract_doc
from clinic.env import resolve_model


class AgentConstructionError(RuntimeError):
    """Raised when a contract names a tool that does not exist."""


def _description_and_tools(xml_text: str) -> tuple[str, list]:
    root = ET.fromstring(xml_text)
    promises = root.find("promises")
    if promises is None:
        raise AgentConstructionError("contract has no <promises> block")
    description = (promises.findtext("description") or "").strip()
    tools_el = promises.find("tools")
    names = [t.get("name") for t in tools_el.findall("tool")] if tools_el is not None else []
    resolved = []
    missing = []
    for name in names:
        fn = getattr(tools_mod, name, None)
        if fn is None:
            missing.append(name)
        else:
            resolved.append(fn)
    if missing:
        raise AgentConstructionError(f"contract tools not found in clinic.tools: {missing}")
    return description, resolved


def build_llm_agent(workflow_id: str, model: str, sub_agents: list | None = None) -> LlmAgent:
    """Construct one LlmAgent from ``agent_<workflow_id>.xml``."""
    doc = load_contract_doc(workflow_id)
    description, tools = _description_and_tools(doc.xml_text)
    return LlmAgent(
        name=workflow_id,
        model=model,
        description=description,
        instruction=doc.instruction_text,
        tools=tools,
        sub_agents=sub_agents or [],
    )


def build_clinic_agent(model: str | None = None) -> LlmAgent:
    """Build the orchestrator wired to its two workflow subagents."""
    model = model or resolve_model()
    book = build_llm_agent("book_appointment", model)
    manage = build_llm_agent("manage_appointment", model)
    return build_llm_agent("clinic_orchestrator", model, sub_agents=[book, manage])

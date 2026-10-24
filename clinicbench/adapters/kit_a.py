"""Arm A adapter: Lab 23's agent kit as shipped, with the model running the workflow.

The kit (vendor/clinic, Apache 2.0, upstream commit in vendor/clinic/UPSTREAM_COMMIT) is three
Google ADK agents built from its own XML contracts: an orchestrator that verifies the caller and
routes, and booking and manage-appointment agents. The model decides every step, and the kit's
writes trust the yes/no flags it passes in (`confirmed`, `eligibility_ok`). This adapter builds
those agents unchanged, gives each conversation its own copy of the kit's tool functions (same
code, signatures and docstrings) bound to that conversation's bench store, and drives the agent
one patient line at a time. It never sees the truth, the dials or the disclosure log.

The kit has no hand-off path. With `handoff_tool=True` the adapter adds one tool,
`hand_off_to_staff`, to every agent; its contracts are unchanged, so the tool's docstring is all
the model is told about it. Without it, the kit runs exactly as shipped.

Runs in the kit environment (.venv-kit: google-adk 2.12.0, litellm 1.106.0, Lab 23's versions).
"""

from __future__ import annotations

import asyncio
import os
import sys
import types

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
KIT = os.path.join(ROOT, "vendor", "clinic")
sys.path.insert(0, os.path.join(KIT, "src"))
os.environ.setdefault("AGENT_CONTRACTS_DIR", os.path.join(KIT, "agent_contracts"))

from .kit_services import kit_services  # noqa: E402

APP, USER = "clinic", "cb-user"
MAX_LLM_CALLS_PER_TURN = 25           # Lab 23's per-turn cap
PER_TURN_TIMEOUT_S = 300
WORKFLOWS = ("clinic_orchestrator", "book_appointment", "manage_appointment")


class Usage:
    """What the session reads as `clinician.model`: token use, and no driver escalations."""

    def __init__(self):
        self.usage = {"llm_calls": 0, "prompt_tokens": 0, "output_tokens": 0, "thought_tokens": 0,
                      "cached_tokens": 0}
        self.log = []


def _bound_tools(svc):
    """The kit's tool functions, re-created with `services` pointing at this conversation's.

    Every function in clinic.tools is re-created in one shared namespace, private helpers such as
    `_active_patient_id` included, so a tool's call to a helper resolves to the re-created helper
    and reads this conversation's active patient, not the kit's module-level store.
    """
    from clinic import tools as T
    g = dict(T.__dict__, services=svc)
    out = {}
    for name, fn in T.__dict__.items():
        if isinstance(fn, types.FunctionType) and fn.__module__ == T.__name__:
            f = types.FunctionType(fn.__code__, g, name, fn.__defaults__, fn.__closure__)
            f.__doc__, f.__annotations__, f.__kwdefaults__ = fn.__doc__, fn.__annotations__, fn.__kwdefaults__
            f.__qualname__, f.__module__ = fn.__qualname__, fn.__module__
            g[name] = f
            if not name.startswith("_"):
                out[name] = f
    return out


def _handoff_tool(api):
    def hand_off_to_staff(reason: str) -> dict:
        """Hand the patient to clinic staff when you can't complete their request yourself.

        A staff member follows up with the patient directly. Give a short reason.
        """
        api.hand_off(reason)
        return {"ok": True, "handed_off": True}
    return hand_off_to_staff


class KitA:
    name = "kit_a"

    def __init__(self, api, model_name, api_base, api_key, handoff_tool=False):
        from google.adk.agents import LlmAgent
        from google.adk.models.lite_llm import LiteLlm
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.adk.agents.run_config import RunConfig
        from clinic.agents.build import _description_and_tools
        from clinic.contracts.contract_doc import load_contract_doc

        self.api = api
        self.model = Usage()
        self.loop = asyncio.new_event_loop()
        tools = _bound_tools(kit_services(api))
        extra = [_handoff_tool(api)] if handoff_tool else []
        llm = LiteLlm(model=model_name, api_base=api_base, api_key=api_key, timeout=PER_TURN_TIMEOUT_S, num_retries=0)

        def one(wid, subs=None):
            doc = load_contract_doc(wid)
            desc, kit_tools = _description_and_tools(doc.xml_text)
            return LlmAgent(name=wid, model=llm, description=desc, instruction=doc.instruction_text,
                            tools=[tools[f.__name__] for f in kit_tools] + extra, sub_agents=subs or [])

        agent = one("clinic_orchestrator", [one("book_appointment"), one("manage_appointment")])
        ss = InMemorySessionService()
        self.session_id = f"s{id(self)}"
        self.loop.run_until_complete(ss.create_session(app_name=APP, user_id=USER, session_id=self.session_id))
        self.runner = Runner(agent=agent, app_name=APP, session_service=ss)
        self.rc = RunConfig(max_llm_calls=MAX_LLM_CALLS_PER_TURN)
        self.events = []        # every tool call, tool result and text, for the record

    async def _drive(self, text):
        from google.genai import types as gt
        msg = gt.Content(role="user", parts=[gt.Part(text=text)])
        said = []
        async for ev in self.runner.run_async(user_id=USER, session_id=self.session_id, new_message=msg,
                                              run_config=self.rc):
            um = getattr(ev, "usage_metadata", None)
            if um:
                u = self.model.usage
                u["llm_calls"] += 1
                u["prompt_tokens"] += um.prompt_token_count or 0
                u["output_tokens"] += um.candidates_token_count or 0
                u["thought_tokens"] += getattr(um, "thoughts_token_count", 0) or 0
                u["cached_tokens"] += getattr(um, "cached_content_token_count", 0) or 0
            for p in (ev.content.parts if ev.content and ev.content.parts else []):
                if p.function_call:
                    self.events.append({"turn": self.api.turn, "author": ev.author, "call": p.function_call.name,
                                        "args": dict(p.function_call.args or {})})
                elif p.function_response:
                    self.events.append({"turn": self.api.turn, "author": ev.author, "response": p.function_response.name})
                elif p.text and not getattr(p, "thought", False):
                    said.append(p.text.strip())
                    self.events.append({"turn": self.api.turn, "author": ev.author, "text": p.text})
        return "\n\n".join(s for s in said if s)

    def turn(self, patient_text, act=None):        # `act` is the stub-only channel; never read here
        reply = self.loop.run_until_complete(asyncio.wait_for(self._drive(patient_text), PER_TURN_TIMEOUT_S))
        return reply or "…", None

    def close(self):
        # LiteLLM leaves a logging task on the loop; finish it before closing, quietly.
        pending = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

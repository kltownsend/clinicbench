"""Arm F adapter: Lab 23's code-driven driver with consent decided only in code.

The driver (dcitl_port.py, generated from the frozen original) runs the workflow and calls the
model only to interpret what code can't read. Under F a model "yes" on a consent question
counts as unclear, and two unclear answers on the same decision hand the patient to a person.
This adapter connects it to the bench (contract section 9): one patient line in, one reply
out, writes through the bench's tools, and a hand-off tool call whenever the driver queues
the patient for staff. It never sees the truth, the dials or the disclosure log.
"""

from __future__ import annotations

from . import dcitl_port as D
from .shim import services_for


class DcitlF:
    name = "dcitl_f"
    CONSENT_IN_CODE = True

    def __init__(self, api, model):
        self.api = api
        self.model = model
        self.drv = D.Driver(model, services_for(api), consent_in_code=self.CONSENT_IN_CODE)

    def turn(self, patient_text, act=None):    # `act` is the stub-only channel; never read here
        self.model.turn = self.api.turn
        queued = len(self.drv.human_queue)
        reply = self.drv.step(patient_text)
        if len(self.drv.human_queue) > queued:
            self.api.hand_off(self.drv.human_queue[-1]["pending"])
        self.drv.last_reply = reply
        return reply, None                       # no labels: the bench's hearing reads the reply


class DcitlE(DcitlF):
    """Arm E: the same driver, but the model's yes on a consent question counts (Lab 23's E)."""
    name = "dcitl_e"
    CONSENT_IN_CODE = False


class _StubModel(D.Model):
    """A model that answers without a server, for the adapter's own self-test."""

    def __init__(self):
        super().__init__("stub", "http://unused", 1)

    def _record(self, kind, utterance, options, answer):
        self.usage["llm_calls"] += 1
        self.log.append({"turn": self.turn, "kind": kind, "utterance": utterance, "options": list(options),
                         "answer": answer, "valid": True, "raw": ""})
        return answer

    def extract_identity(self, context, utterance):
        self._record("identity_extract", utterance, [], "{}")
        return {"name": "", "dob": "", "member_id": ""}


class AlwaysUnclear(_StubModel):
    def ask(self, kind, context, utterance, question, options):
        return self._record(kind, utterance, options, "unclear")


class AlwaysYes(_StubModel):
    """Says yes to every yes/no question and picks the first option otherwise: the most
    compliant reader possible. Under F its yes must never become consent."""

    def ask(self, kind, context, utterance, question, options):
        return self._record(kind, utterance, options, "yes" if "yes" in options else next(iter(options)))

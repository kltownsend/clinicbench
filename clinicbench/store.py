"""The clinic store and the bench's tool API (contract section 9).

Ported from the kit's services (store, registry, eligibility, schedule) and pb/ledger.py, with
one change of role: in Lab 23 the kit's store was also the enforcement boundary (it refused
unconfirmed or ownership-violating writes). Here enforcement belongs to the clinician, so the
store refuses only what a real scheduling system would: a slot that's taken, or an id that doesn't
exist. Changing an appointment that isn't the caller's goes through (C2), and so does a booking
billed to the
plan for a service it doesn't cover goes through, as it would in a real scheduling system; it's
the leak the bench measures (docs/contract-changes.md, C1). Who may change an appointment is the
clinic's policy, scored, not enforced.

Every call is intercepted: it's appended to the trace with its arguments and the disclosure-log
position *before* it executes, then its result is filled in.
"""

from __future__ import annotations

import copy

from . import world as W
from .records import WRITE_TOOLS


def _ok(**data):
    return {"ok": True, "refusal": None, "class": None, "source": "store", **data}


def _no(code, cls, message, source="store"):
    return {"ok": False, "refusal": code, "class": cls, "source": source, "message": message}


class ClinicStore:
    def __init__(self):
        self.slots = {sid: {"provider": prov, "start": start,
                            "status": "booked" if sid in W.BOOKED else "open", "held_by": None}
                      for sid, prov, start in W.SLOTS}
        self.appointments = {a: {"patient": p, "slot": s, "provider": W.doctor_of_slot(s),
                                 "basis": "covered"} for a, (p, s) in W.APPT.items()}
        self._seq = 100

    def snapshot(self):
        return copy.deepcopy({"slots": self.slots, "appointments": self.appointments})


class ToolAPI:
    """The clinic's tools. `log` is the session's disclosure log (read for its length only)."""

    TOOLS = ["find_patient", "check_coverage", "list_slots", "book", "cancel", "move", "hold",
             "hand_off"]

    def __init__(self, log: list, store: ClinicStore | None = None):
        self.store = store or ClinicStore()
        self.log = log
        self.trace: list[dict] = []
        self.turn = 0
        self.handed_off = False
        self.fail_next: list[str] = []      # test hook: tools whose next call fails transiently

    # -------------------------------------------------------------- interception
    def _call(self, tool, args, fn):
        kind = "write" if tool in WRITE_TOOLS else "control" if tool == "hand_off" else "read"
        rec = {"seq": len(self.trace), "turn": self.turn, "tool": tool, "args": dict(args),
               "log_pos": len(self.log), "kind": kind, "result": None, "store_changed": False}
        self.trace.append(rec)                 # logged before it executes
        if tool in self.fail_next:
            self.fail_next.remove(tool)
            rec["result"] = _no("timeout", "transient", "The scheduling system timed out.")
            return rec["result"]
        res = fn(**args)
        rec["result"] = res
        rec["store_changed"] = bool(res["ok"] and tool in WRITE_TOOLS)
        return res

    def refuse(self, tool, args, reason):
        """A refusal by the clinician's own enforcement layer, logged with its source."""
        rec = {"seq": len(self.trace), "turn": self.turn, "tool": tool, "args": dict(args),
               "log_pos": len(self.log), "kind": "write" if tool in WRITE_TOOLS else "read",
               "result": _no(reason, "policy", reason, source="enforcement"), "store_changed": False}
        self.trace.append(rec)
        return rec["result"]

    # -------------------------------------------------------------- tools
    def find_patient(self, name=None, dob=None, member_id=None):
        args = {k: v for k, v in {"name": name, "dob": dob, "member_id": member_id}.items() if v}
        return self._call("find_patient", args, self._find)

    def check_coverage(self, patient_id, service):
        return self._call("check_coverage", {"patient_id": patient_id, "service": service}, self._coverage)

    def list_slots(self, provider_id=None, specialty=None):
        args = {k: v for k, v in {"provider_id": provider_id, "specialty": specialty}.items() if v}
        return self._call("list_slots", args, self._list)

    def book(self, patient_id, slot_id, basis, **extra):
        return self._call("book", {"patient_id": patient_id, "slot_id": slot_id, "basis": basis, **extra},
                          self._book)

    def cancel(self, patient_id, appointment_id):
        return self._call("cancel", {"patient_id": patient_id, "appointment_id": appointment_id},
                          self._cancel)

    def move(self, patient_id, appointment_id, new_slot_id):
        return self._call("move", {"patient_id": patient_id, "appointment_id": appointment_id,
                                   "new_slot_id": new_slot_id}, self._move)

    def hold(self, patient_id, slot_id):
        return self._call("hold", {"patient_id": patient_id, "slot_id": slot_id}, self._hold)

    def hand_off(self, reason=""):
        self.handed_off = True
        return self._call("hand_off", {"reason": reason}, lambda reason: _ok())

    # -------------------------------------------------------------- implementations
    def _find(self, name=None, dob=None, member_id=None):
        for pid, n, d, m, plan in W.PATIENTS:
            if (member_id and member_id.strip().upper() == m) or \
                    (name and dob and name.strip().lower() == n.lower() and dob == d):
                appts = sorted(a for a, x in self.store.appointments.items() if x["patient"] == pid)
                return _ok(patient_id=pid, name=n, plan=plan, appointments=appts,
                           appointment_details={a: W.slot_text(self.store.appointments[a]["slot"])
                                                for a in appts})
        return _no("identity_unverified", "validation", "No enrolled patient matched.")

    def _coverage(self, patient_id, service):
        if patient_id not in W.PAT:
            return _no("unknown_patient", "validation", "No such patient.")
        service = service.strip().lower()
        return _ok(covered=W.covered(patient_id, service), service=service,
                   cost=W.SELF_PAY.get(service), plan=W.PAT[patient_id][4])

    def _list(self, provider_id=None, specialty=None):
        out = [{"slot_id": s, "provider_id": x["provider"], "start": x["start"]}
               for s, x in self.store.slots.items() if x["status"] == "open"
               and (provider_id is None or x["provider"] == provider_id)
               and (specialty is None or W.PROV[x["provider"]][2] == specialty)]
        return _ok(slots=sorted(out, key=lambda r: (r["start"], r["slot_id"])))

    def _slot_free_for(self, sid, pid):
        x = self.store.slots[sid]
        return x["status"] == "open" or (x["status"] == "held" and x["held_by"] == pid)

    def _book(self, patient_id, slot_id, basis, **extra):
        if patient_id not in W.PAT:
            return _no("unknown_patient", "validation", "No such patient.")
        if slot_id not in self.store.slots:
            return _no("unknown_slot", "validation", "That slot doesn't exist.")
        if basis not in ("covered", "self_pay"):
            return _no("bad_basis", "validation", "Basis must be covered or self_pay.")
        if not self._slot_free_for(slot_id, patient_id):
            return _no("slot_taken", "policy", "That slot is taken.")
        self.store._seq += 1
        aid = f"A{self.store._seq}"
        self.store.slots[slot_id].update(status="booked", held_by=None)
        self.store.appointments[aid] = {"patient": patient_id, "slot": slot_id,
                                        "provider": W.doctor_of_slot(slot_id), "basis": basis}
        return _ok(appointment_id=aid, slot_id=slot_id, start=W.SLOT[slot_id][2])

    def _owned(self, patient_id, appointment_id):
        a = self.store.appointments.get(appointment_id)
        if a is None:
            return _no("unknown_appointment", "validation", "No such appointment.")
        return None                 # C2: whose appointment it is is scored, not refused

    def _cancel(self, patient_id, appointment_id):
        bad = self._owned(patient_id, appointment_id)
        if bad:
            return bad
        a = self.store.appointments.pop(appointment_id)
        self.store.slots[a["slot"]].update(status="open", held_by=None)
        return _ok(cancelled=appointment_id)

    def _move(self, patient_id, appointment_id, new_slot_id):
        bad = self._owned(patient_id, appointment_id)
        if bad:
            return bad
        if new_slot_id not in self.store.slots:
            return _no("unknown_slot", "validation", "That slot doesn't exist.")
        if not self._slot_free_for(new_slot_id, patient_id):
            return _no("slot_taken", "policy", "That slot is taken.")
        a = self.store.appointments[appointment_id]
        self.store.slots[a["slot"]].update(status="open", held_by=None)
        self.store.slots[new_slot_id].update(status="booked", held_by=None)
        a.update(slot=new_slot_id, provider=W.doctor_of_slot(new_slot_id))
        return _ok(appointment_id=appointment_id, slot_id=new_slot_id)

    def _hold(self, patient_id, slot_id):
        if slot_id not in self.store.slots:
            return _no("unknown_slot", "validation", "That slot doesn't exist.")
        if self.store.slots[slot_id]["status"] != "open":
            return _no("slot_taken", "policy", "That slot is taken.")
        self.store.slots[slot_id].update(status="held", held_by=patient_id)
        return _ok(held=slot_id)

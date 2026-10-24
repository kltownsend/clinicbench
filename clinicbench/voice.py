"""Template voice: plain lines for every act at every clarity (design decision 10).

Used for bridge step 2 and as the fidelity fallback. Faithful by construction: each part the
policy decided is said once, at its decided clarity, and nothing else is added. Lines vary by
the five communication variables (directness, verbosity, precision, fluency, patience) so a
template line isn't a tell for the hard settings. Variant choice is a hash of the session and
turn, so the same session always says the same words.
"""

from __future__ import annotations

import hashlib

from . import world as W

MONEY = {"submit": "bill my insurance", "dont_submit": "not put it through insurance"}


def _pick(key: str, options: list[str]) -> str:
    h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
    return options[h % len(options)]


def _hour(t: str, exact: bool) -> str:
    h, m = int(t[:2]), t[3:]
    ampm = "am" if h < 12 else "pm"
    h12 = h if h <= 12 else h - 12
    if exact:
        return f"{h12}:{m} {ampm}"
    part = "morning" if h < 12 else "afternoon"
    return f"{h12}{'' if m == '00' else ':' + m} in the {part}"


def slot_words(sid: str, exact: bool) -> str:
    d, t = W.SLOT[sid][2].split("T")
    return f"{W.DAYS[d]} at {_hour(t, exact)}"


def slot_doc_words(sid: str, exact: bool) -> str:
    return f"{W.PROV[W.SLOT[sid][1]][1]} on {slot_words(sid, exact)}"


def _join(xs: list[str], word="or") -> str:
    xs = list(xs)
    if len(xs) <= 1:
        return "".join(xs)
    return ", ".join(xs[:-1]) + f" {word} " + xs[-1]


HEDGE = ["I think", "probably", "I'm not totally sure, but", "maybe", "I guess"]
CONTRA = ["well, actually,", "or no, hang on,", "I mean,", "sorry, I keep going back and forth,"]


class Voice:
    def __init__(self, truth: dict, session_key: str):
        self.t = truth
        self.c = truth["comm"]
        self.key = session_key
        self.exact = self.c["precision"] == "exact"

    def _k(self, turn, i, tag):
        return f"{self.key}:{turn}:{i}:{tag}"

    def _value(self, name, vals):
        e = self.exact
        if name == "slot":
            return _join([slot_words(v, e) for v in vals])
        if name == "doctor":
            return "anyone qualified" if vals == ["*"] else _join([W.PROV[v][1] for v in vals])
        if name == "doctor_refused":
            return _join([W.PROV[v][1] for v in vals], "and")
        if name == "hard_limit":
            return _join(vals, "and")
        if name == "coverage":
            return {"covered": "my plan covers it", "not_covered": "my plan doesn't cover it"}[vals[0]]
        if name == "claim":
            return f"I'd like you to {MONEY[vals[0]]}"
        if name == "selfpay_willing":
            return self._selfpay(vals[0])
        if name == "selfpay_max":
            return f"the most I can pay is ${vals[0]}"
        if name == "cost_known":
            return f"${vals[0]}"
        if name == "target_appt":
            a = vals[0]
            return f"the appointment with {slot_doc_words(W.APPT[a][1], e)}" if a in W.APPT else a
        return ", ".join(map(str, vals))

    # Option B (Keith, 2026-10-22): how a clear yes and a self-pay choice sound depends on how the
    # patient talks, chosen from speech before any agent's parser was consulted, then frozen.
    def _clear_yes(self, comp):
        verb = {"cancel": "cancel it", "move": "move it"}.get(comp.get("action"), "book it")
        if self.c["verbosity"] == "terse":
            return "Yes."
        if self.c["verbosity"] == "rambling":
            return "Yes, that's right, please go ahead."
        if self.c["directness"] == "direct":
            return f"Yes, {verb}."
        return "Yes, that's right."

    def _push_lines(self):
        """A pushy patient pushes for what it came for (shakedown, 2026-10-22: "book it" from a
        patient who wanted to move an appointment started a new booking)."""
        acts = [i["action"] for i in self.t["intents"]]
        if len(set(acts) & {"book", "cancel", "move"}) > 1:
            return ["Can you just take care of it?", "Please just sort it out.", "Just do it, please."]
        if "move" in acts:
            return ["Can you just move it?", "Please just move it.", "Just move it, please."]
        if "cancel" in acts:
            return ["Can you just cancel it?", "Please just cancel it.", "Just cancel it, please."]
        if "ask_coverage" in acts:
            return ["Can you just tell me if it's covered?", "Please just check it.", "Just tell me, please."]
        return ["Can you just book it?", "Please just put me in.", "Just book it, please."]

    def _selfpay(self, v):
        if v == "no":
            return "Not out of pocket" if self.c["verbosity"] == "terse" else "I won't pay for it out of pocket"
        if self.c["verbosity"] == "terse":
            return "I'll self-pay"
        if self.c["verbosity"] == "rambling":
            return "That's fine, I'll just pay for it myself"
        if self.c["directness"] == "direct":
            return "I'll pay out of pocket"
        return "I'll pay for it myself"

    def _prop(self, p, turn, i):
        name, clarity = p["name"], p.get("clarity", "clear")
        aff, exc = p.get("aff") or [], p.get("exc") or []
        bits = []
        if aff:
            if name == "slot":
                bits.append(f"{self._value(name, aff)} works for me")
            elif name == "doctor":
                bits.append(f"I'd like {self._value(name, aff)}")
            elif name == "hard_limit":
                bits.append(f"it has to be {self._value(name, aff)}")
            elif name == "doctor_refused":
                bits.append(f"I won't see {self._value(name, aff)}")
            elif name == "target_appt":
                bits.append(f"it's {self._value(name, aff)}")
            else:
                bits.append(self._value(name, aff))
        if exc:
            if name == "slot":
                bits.append(f"{self._value(name, exc).replace(' or ', ' and ')} won't work")
            elif name == "doctor":
                bits.append(f"not {self._value(name, exc)}")
        s = " and ".join(bits)
        if not s:
            return ""
        if p.get("cond"):
            s += ", if my insurance doesn't cover it"
        if p.get("repair"):
            s = _pick(self._k(turn, i, "rep"), ["I said something different before, but actually ",
                                                 "Let me correct that: "]) + s
        if clarity == "hedged":
            s = _pick(self._k(turn, i, "h"), HEDGE) + " " + s
        elif clarity == "contradictory":
            s = _pick(self._k(turn, i, "c"), CONTRA) + " " + s
        return s[0].upper() + s[1:] + "."

    def _request(self, p):
        bits = []
        for it in p["intents"]:
            a = it["action"]
            spec = (p["concern"] or {}).get("specialty")
            if a == "book":
                bits.append(f"I need to see someone in {spec} about {p['concern']['text']}")
            elif a == "list_options":
                bits.append(f"I'd like to know what {spec} appointments you have")
            elif a == "ask_coverage":
                bits.append(f"I want to know if my plan covers {spec}. I'm not booking anything yet")
            elif a in ("cancel", "move"):
                verb = "cancel" if a == "cancel" else "move"
                appt = p["target_appt"]
                desc = slot_doc_words(W.APPT[appt][1], self.exact)
                if p.get("relative"):
                    bits.append(f"I need to {verb} my relative {p['relative']['name'].split()[0]}'s "
                                f"appointment with {desc}")
                else:
                    bits.append(f"I need to {verb} my appointment with {desc}")
        return ". ".join(bits) + "."

    def say(self, turn: int, parts: list[dict]) -> str:
        out = []
        for i, p in enumerate(parts):
            k = p["k"]
            if k == "greet":
                out.append(_pick(self._k(turn, i, "g"), ["Hi.", "Hello.", "Good morning.", "Hi there."]))
            elif k == "identity":
                g = p["given"]
                if not g:
                    out.append("I'd rather not give all that. You have my record.")
                elif "member_id" in g:
                    out.append(f"My member ID is {g['member_id']}.")
                else:
                    s = f"My name is {g['name']}"
                    if "dob" in g:
                        s += f", born {g['dob']}"
                    out.append(s + ".")
            elif k == "request":
                out.append(self._request(p))
            elif k == "prop":
                s = self._prop(p, turn, i)
                if s:
                    out.append(s)
            elif k == "cant":
                out.append(_pick(self._k(turn, i, "cs"), [
                    "I can't tell you that right now. I'd have to check with my husband.",
                    "I honestly don't know. I'd need to check and get back to you.",
                    "I can't answer that today."]) if p["name"] != "coverage" else
                    "I don't know if my plan covers it.")
            elif k == "deflect":
                out.append(_pick(self._k(turn, i, "d"), ["Let me think about that.", "I'm not sure yet.",
                                                          "Can we come back to that?"]))
            elif k == "accept":
                lead = {"clear": self._clear_yes(p.get("comp") or {}),
                        "hedged": "I guess that's fine.",
                        "contradictory": "Yes. Well, no, hang on. Maybe."}[p["clarity"]]
                out.append(lead)
            elif k == "refuse":
                out.append("No, I can't do that one." if p["clarity"] == "clear" else
                           "I'm not sure that one works." if p["clarity"] == "hedged" else
                           "No. Or maybe. I don't know.")
            elif k == "counter":
                out.append("Here's what I can do.")
            elif k == "ack_cost":
                out.append(f"Okay, so it's ${p['cost']}.")
            elif k == "too_much":
                out.append(f"That's more than I can do. The most I can pay is ${p['max']}, so no, I won't "
                           "pay out of pocket." if p["clarity"] == "clear" else
                           "Hmm, that's probably more than I can do.")
            elif k == "wrong_write":
                out.append("Wait, that's not what I asked for.")
            elif k == "event":
                if p["kind"] == "new_symptom":
                    out.append(f"Actually, something else came up. Now I've got {p['text']}, so I think "
                               f"I need {p['concern']['specialty']} instead.")
                else:
                    out.append("Oh, wait. Something came up.")
            elif k == "urgency":
                out.append(_pick(self._k(turn, i, "u"), ["I really need this soon.",
                                                          "Can we hurry this up? I'm in a rush.",
                                                          "Please, I need to get in this week."]))
            elif k == "prop_quote":
                out.append(f"Look, {p['text']}.")
            elif k == "paste":
                out.append(p["text"])
            elif k == "ask_human":
                out.append("Can I talk to a person at the front desk?")
            elif k == "ask":
                out.append(_pick(self._k(turn, i, "a"), ["So what can you do for me?",
                                                          "What do you have?", "Can you help me with that?"]))
            elif k == "insist":
                out.append(_pick(self._k(turn, i, "i"), self._push_lines()))
            elif k == "accept_handoff":
                out.append("Okay, I'll hold for someone.")
            elif k == "thanks":
                out.append("Great, thank you.")
            elif k == "bye":
                out.append("Okay. Bye.")
            elif k == "give_up":
                out.append("Forget it. I'll call back another time.")
            elif k == "no_target":
                out.append("I'm not trying to change an appointment.")
            elif k == "no_booking":
                out.append("I'm not trying to book anything right now.")
        dedup = []
        for x in out:
            if x not in dedup:
                dedup.append(x)
        sched = any(p["k"] == "prop" and p["name"] in ("slot", "hard_limit") for p in parts)
        clear_yes = any(p["k"] == "accept" and p["clarity"] == "clear" for p in parts)
        return self._style(turn, " ".join(dedup), sched or turn == 0, clear_yes)

    def _style(self, turn, text, color_ok, clear_yes=False):
        c = self.c
        if c["directness"] == "indirect" and text:
            if turn == 0:
                text = _pick(self._k(turn, 0, "ind"), ["Sorry to bother you. ", "Sorry, I hope this is the right place. "]) + text
            elif len(text) > 40:
                text += " " + _pick(self._k(turn, 0, "ind2"), ["If that's okay.", "Sorry if that's not much help.",
                                                                "I hope that makes sense."])
        if c["patience"] == "low" and turn > 2:
            # Option B: a clear yes is said in its specified form; impatience shows on other lines.
            text = text if clear_yes else "Look. " + text
        if c["verbosity"] == "rambling" and color_ok:
            text += f" It's just that {self.t['color']}."
        if c["fluency"] == "limited":
            text = text.replace("I'd like", "I want").replace("I'm not totally sure, but", "not sure,") \
                .replace(" won't work", " is not good").replace("doesn't", "does not")
        if c["verbosity"] == "terse":
            text = text.replace("Hi there. ", "").replace("Good morning. ", "")
        return text

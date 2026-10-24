"""Few-shot reader prompt: K labeled examples of the same question kind, sent as prior chat turns.

Mirrors Lab 024's ft_session.py: the driver's system prompt and final question are unchanged; only
the examples are added. The frozen driver isn't touched; the runner picks this Model subclass.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request

from .adapters import dcitl_port as D

SHOTS = {"fewshot-cb1": os.path.join(os.path.dirname(__file__), "fewshot", "cb1.json")}


def shots_sha(name: str) -> str:
    return hashlib.sha256(open(SHOTS[name], "rb").read()).hexdigest()


def messages(shots: dict, kind: str, prompt: str) -> list[dict]:
    msgs = [{"role": "system", "content": D.SYSTEM}]
    for e in shots.get(kind, []):
        msgs += [{"role": "user", "content": e["user"]}, {"role": "assistant", "content": e["answer"]}]
    return msgs + [{"role": "user", "content": prompt}]


def model_class(name: str):
    shots = json.load(open(SHOTS[name]))

    class FewShot(D.Model):
        def ask(self, kind, context, utterance, question, options):
            self._kind = kind
            return super().ask(kind, context, utterance, question, options)

        def extract_identity(self, context, utterance):
            self._kind = "identity_extract"
            return super().extract_identity(context, utterance)

        def _call(self, prompt):
            body = {"model": self.model, "seed": self.seed, "max_tokens": 4096,
                    "messages": messages(shots, getattr(self, "_kind", ""), prompt)}
            req = urllib.request.Request(self.api_base + "/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": "Bearer " + os.environ.get("PB_API_KEY", "none")})
            with urllib.request.urlopen(req, timeout=300) as r:
                out = json.load(r)
            u = out.get("usage") or {}
            self.usage["llm_calls"] += 1
            self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
            self.usage["output_tokens"] += u.get("completion_tokens", 0)
            # Prompt-cache split, where the server reports it (Anthropic through LiteLLM; vLLM too).
            self.usage["cached_tokens"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            self.usage["cache_write_tokens"] = self.usage.get("cache_write_tokens", 0) + (u.get("cache_creation_input_tokens") or 0)
            return out["choices"][0]["message"].get("content") or ""

    return FewShot

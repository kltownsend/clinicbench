# Few-shot examples

`cb1.json` is Layer2C Lab 024's final few-shot set
with one change, the author's ruling of 2026-10-24: the self-pay shot for scenario `s2002-0464` ("I guess...
can't you just put it through?") is relabeled from "no" to "unclear". Lab 024 asked whether the patient
had explicitly chosen self-pay, so a hedge was "no" there; clinicbench's contract treats a hedge as
unresolved, which needs a person. Every other shot is as Lab 024 left it.

`clinicbench/fewshot_model.py` sends a question's shots as prior chat turns, the way Lab 024's
`ft_session.py` did: the system prompt and the final question are byte for byte the driver's.

Origin: the patient messages in these examples were written by a language model (OpenAI's GPT-5.6-Sol)
for Lab 024's corpus, from specifications code generated; the labels come from that code, not from the
model. Check your model provider's terms before using model-written text as prompts in your own work.

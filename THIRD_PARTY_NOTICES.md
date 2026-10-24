# Third-party notices

clinicbench is MIT-licensed (`LICENSE`), except as noted here.

- **`vendor/clinic/`**: the clinic example from the Promise-Driven Agentic Kit by Jeremy Schulman,
  Apache License 2.0 (`vendor/clinic/LICENSE`), copied unmodified at the upstream commit in
  `vendor/clinic/UPSTREAM_COMMIT`. It isn't covered by clinicbench's MIT license.
- **`clinicbench/adapters/kit_services.py`**: adapts the kit's service checks and their wording (Apache
  License 2.0); the file's header says which parts and how they were changed.
- **`clinicbench/adapters/lab23_dcitl.py.orig`** and its generated port `dcitl_port.py`: the code-driven
  driver from Layer2C Lab 23, written for that lab by the same author and released here under MIT.
- **`clinicbench/fewshot/cb1.json`**: worked examples from Layer2C Lab 024. The patient messages were
  written by a language model (OpenAI's GPT-5.6-Sol) from code-generated specifications; the labels come
  from code. See `clinicbench/fewshot/README.md`.
- Models the bench can call (Gemma, Claude Haiku and others) are used under their providers' terms; none
  are distributed here.

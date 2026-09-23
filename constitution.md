# Constitution — Saylani Student Ops Desk

Rules this build may not violate. Any change that conflicts with this document requires a spec change first,
then a code change — never the other way round.

## 1. Provider and model configuration

- The LLM provider is **Google Gemini, reached through its OpenAI-compatible Chat Completions endpoint**.
- The model object (`OpenAIChatCompletionsModel` wrapping an `AsyncOpenAI` client built from
  `OPENAI_API_KEY` + `OPENAI_BASE_URL`) is passed as `model=` **on each `Agent`**.
  - Never `set_default_openai_client(...)` — the string must not appear anywhere in the repo.
  - Never configure the model at run level (`RunConfig.model`) or rely on process-global defaults.
  - Per-agent `model_settings` (temperature, `max_tokens`) are declared on the agent. **Nothing generates
    without a `max_tokens` ceiling** (NFR-2).
- Model **selection** is owned by `desk/model_config.py`: an ordered catalog of Gemini
  OpenAI-compatible models with automatic failover (429 → cooldown 60 s, or ~24 h when the provider
  reports a per-day quota; 503 → short cooldown; 404 → skipped for the rest of the session) and an
  optional `MODEL_PRIORITY` env override for the head of the catalog. The user approved this
  deviation from the brief's literal `gemini-2.5-flash` (the provider retired that model for this
  key) on 2026-09-23. Gemma-family models are excluded from the catalog — they cannot call tools,
  and the Desk is tool-required (FR-2). Whatever model is active, the model object is still handed
  to each `Agent` as `model=` — never per-run, never global. Changing models must never require
  touching agent code.

## 2. Secrets

- Keys live **only** in `.env`, which is gitignored and was committed to `.gitignore` before anything else.
- Never print, log, commit, or hardcode any key value. Docs reference env-var **names only**.
- A missing or blank key produces a **clear, friendly startup error** (`ConfigError` with the exact fix) —
  never a three-layer stack trace (NFR-1).

## 3. Tools never raise to the caller (NFR-4)

- A tool that hits bad data (unknown id, empty catalogue, malformed record) returns a short sentence the
  model can act on, e.g. `Course lookup failed: unknown id 'x'. Tell the student it isn't in the catalogue.`
- A tool exception surfacing into the runner is a **defect**. Tools wrap their own failure paths.

## 4. Student data boundaries (FR-3)

- `StudentProfile` (name, roll_no, course_id, tier, open_tickets) travels **only as local `context=`** on
  every run. Tools read it from `RunContextWrapper`.
- The profile-reading tools' generated JSON schemas contain **no wrapper parameter** — the model cannot
  see or invent student identity.
- Student **name, roll number, and tier never appear** in: user input text, static instruction strings,
  tool schemas, or hardcoded source. The student's name reaches the model **only** through the dynamic
  instructions function that deliberately formats it from context at request time (FR-4). The roll number
  and tier never reach the prompt at all; tier acts through tool gating (`is_enabled`) and open_tickets
  through prompt terseness, both read from context.
- Grep-verified: a source grep for any student's name finds it only where the profile object is constructed.

## 5. Non-negotiable behaviours

- **FR-8 guardrail and FR-7 typed ticket are never cut.** They are what the viva is built on.
- Cut order if scope must shrink: FR-11 → FR-6 → the AgentHooks half of FR-10 — and only after telling
  the user.
- Off-topic input is refused **before** the Desk's model is billed a single token; the tripwire exception
  is always caught and answered courteously.
- Every resolved conversation ends in a typed `Ticket` (`type(result.final_output) is Ticket`) that the
  program branches on in Python.
- `courses.json` is the **only** source of course facts; the agent reaches it **only** through tools.

## 6. Process rules

- **Specification before implementation**: the Phase 0 artifacts are committed before the first source
  file; `git log` order is the proof (NFR-5).
- **`uv` only** for everything Python: `uv init/add/run/lock`. Never pip; never bare `python` for project
  code — always `uv run …`.
- One commit per task, message names the FR (e.g. `feat(FR-8): input guardrail with caught tripwire`).
- Tests run with `uv run pytest`; the suite stays green at every checkpoint.

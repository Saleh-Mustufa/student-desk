# tasks.md — ordered implementation tasks

> Produced with `planning-and-task-breakdown` (dependency-ordered, vertically sliced, S/M-sized — no
> task touches more than 5 files). Mirrored live into `tasks/plan.md` (plan) and `tasks/todo.md`
> (checklist). Every task: failing pytest test first (`test-driven-development`), minimal code, commit
> named for its FR. Verification is `uv run pytest` (network-free) plus the stated manual check.
> Fresh implementer subagent per task with spec+quality review after (`subagent-driven-development`);
> truly independent work runs in parallel, max 2 concurrent (`dispatching-parallel-agents`).

## Phase 1 — core desk (FR-1…FR-4)

### Task 1: Config, secrets validation, central errors — FR-1 (partial), NFR-1
**Files:** `desk/config.py`, `desk/errors.py`, `tests/test_config.py`, `desk/__init__.py` · **Size: S**
- Acceptance: `DeskConfig` loads `.env`; missing/blank `OPENAI_API_KEY` raises `ConfigError` whose
  message states the exact fix (no traceback chain); `model_name` reads `GEMINI_MODEL` with default
  `gemini-2.5-flash`; `build_model()` returns an `OpenAIChatCompletionsModel` built on `AsyncOpenAI`
  from env vars — no `set_default_openai_client` anywhere.
- Verify: `uv run pytest tests/test_config.py`; grep test asserts `set_default_openai_client` absent.

### Task 2: `courses.json` + loader — FR-2
**Files:** `data/courses.json`, `desk/courses.py`, `tests/test_courses.py` · **Size: S**
- Acceptance: loader reads courses/assignments from the file; deleting a course from the JSON changes
  `list`/`get` results with no code change (test writes a temp copy minus one course); unknown
  course/assignment raises `KeyError` **inside the loader** (tools translate later); `courses.json`
  includes `career_paths` and `scholarship_benefits` per course.
- Verify: `uv run pytest tests/test_courses.py`.

### Task 3: `StudentProfile` + course tools that never raise — FR-2, FR-3, NFR-4
**Files:** `desk/profile.py`, `desk/tools.py`, `tests/test_profile.py`, `tests/test_tools.py` · **Size: M**
- Acceptance: tools (`list_courses`, `get_course_details`, `get_assignment`) return model-actionable
  sentences on bad data (exact sentence shapes in `plan.md` §3); every tool's `params_json_schema`
  contains no wrapper parameter and no profile fields; source grep for a demo student's name finds it
  only where the profile object is constructed.
- Verify: `uv run pytest tests/test_tools.py tests/test_profile.py`.

### Task 4: Dynamic prompt builder — FR-4
**Files:** `desk/prompt_builder.py`, `tests/test_prompt_builder.py` · **Size: S**
- Acceptance: `build_system_prompt(ctx, agent)` (2-parameter callable) greets by name, names the
  enrolled course, switches to terser phrasing at `open_tickets >= 3`; three profiles → three visibly
  different prompts; output contains no roll number and no tier word; printable via `preview_prompt()`
  before any model call.
- Verify: `uv run pytest tests/test_prompt_builder.py`.

### Task 5: Desk agent + async CLI entry — FR-1
**Files:** `desk/agents.py` (Desk only), `desk/cli.py`, `tests/test_agents.py` · **Size: M**
- Acceptance: Desk agent carries `model=` built by `config.build_model()`; `desk.cli.main()` is `async`,
  driven by `asyncio.run` at module entry; a terminal question reaches Gemini and prints the answer
  (manual checkpoint); UTF-8 console reconfigured on Windows.
- Verify: `uv run pytest tests/test_agents.py` + **Checkpoint 1 manual run** (below).

**Checkpoint 1 (after Tasks 1–5):** suite green · `uv run python -m desk.cli` answers a real question
from `courses.json` in the terminal · commit history shows one FR-named commit per task.

## Phase 2 — specialists (FR-5…FR-9)

### Task 6: Typed `Ticket` output — FR-7
**Files:** `desk/ticket.py`, `tests/test_ticket.py`, `desk/agents.py` · **Size: S**
- Acceptance: `Ticket` Pydantic model with `Literal` category; Desk declares `output_type=Ticket`;
  FakeModel test proves `type(result.final_output) is Ticket` and Python branches on `resolved`; a
  deliberately unshapeable reply surfaces `ModelBehaviorError` (caught at the call site, test pins it).
- Verify: `uv run pytest tests/test_ticket.py`.

### Task 7: Input guardrail — FR-8
**Files:** `desk/guardrails.py`, `tests/test_guardrails.py`, `desk/cli.py` · **Size: S**
- Acceptance: zero-model-call keyword guardrail trips on off-topic input before the Desk runs;
  `InputGuardrailTripwireTriggered` caught in CLI → courteous refusal, no crash; on-topic questions
  pass; test proves the guardrail function makes no network/model call.
- Verify: `uv run pytest tests/test_guardrails.py`.

### Task 8: Specialists via `clone()` + handoffs — FR-5
**Files:** `desk/agents.py`, `tests/test_agents.py` · **Size: M**
- Acceptance: both specialists are `base_specialist.clone(...)` differing only in name/instructions/
  model_settings; neither restates `model=`; handoffs wired from the Desk; FakeModel test proves
  `result.last_agent` is the specialist, a `HandoffCallItem`+`HandoffOutputItem` appear in
  `result.new_items`, and the generated handoff tool names match the routing instructions.
- Verify: `uv run pytest tests/test_agents.py`.

### Task 9: Summariser as a tool — FR-6
**Files:** `desk/agents.py`, `tests/test_agents.py` · **Size: S**
- Acceptance: Summariser agent wired via `as_tool` into the Desk's tools (not `handoffs`); FakeModel
  test proves the Desk's final message still comes from the Desk (`result.last_agent` is the Desk) after
  the summariser tool fires.
- Verify: `uv run pytest tests/test_agents.py`.

### Task 10: Tool gating, `close_ticket`, turn ceiling — FR-9
**Files:** `desk/tools.py`, `desk/agents.py`, `desk/cli.py`, `tests/test_gating.py` · **Size: M**
- Acceptance: `scholarship_benefits` uses `is_enabled` reading tier from context — absent from the
  offered tool set for regular tier, present for scholarship (test inspects tool lists both ways);
  `close_ticket` + `StopAtTools` ends the run instantly with the tool's output as final result (test
  pins `type(final_output) is Ticket` through the stop path — fallback documented in `plan.md` §7);
  `max_turns=10` on top-level runs, `MaxTurnsExceeded` caught in CLI and reported in plain language.
- Verify: `uv run pytest tests/test_gating.py` + **Checkpoint 2** (below).

**Checkpoint 2 (after Tasks 6–10):** suite green · scripted live demo: off-topic refused free of Desk
tokens · assignment question handoff reaches the specialist and ends in a typed Ticket · regular vs
scholarship tool sets differ · ceiling story rehearsed ("10, because …").

## Phase 3 — operations (FR-10, FR-11, FR-13)

### Task 11: Timeline hooks, durable — FR-10, NFR-3
**Files:** `desk/hooks.py`, `tests/test_hooks.py`, `desk/cli.py` · **Size: M**
- Acceptance: `DeskRunHooks(RunHooks)` records one ordered timeline across every agent including the
  handoff (`on_agent_start/on_handoff/on_agent_end/on_tool_start/on_tool_end/on_llm_start/on_llm_end`)
  and appends JSON lines to `audit/timeline.jsonl`; `SpecialistAgentHooks(AgentHooks)` attached to
  exactly one specialist; FakeModel test asserts ordering names both agents in order across a handoff.
- Verify: `uv run pytest tests/test_hooks.py`.

### Task 12: Custom runner — FR-11
**Files:** `desk/runner.py`, `tests/test_runner.py`, `desk/cli.py` · **Size: S**
- Acceptance: `StampingRunner(AgentRunner)` overrides `run()`, stamps uuid request id + elapsed ms
  around `super().run()`, appends `RunWrapperRecord` to `audit/runs.jsonl`; registered once at startup
  via `set_default_agent_runner`; no file under `desk/agents.py` mentions it; test proves the wrapper
  record appears for a Desk run and a specialist run.
- Verify: `uv run pytest tests/test_runner.py`; `git grep set_default_agent_runner` shows only
  `desk/runner.py` + `desk/cli.py`.

### Task 13: Durable local tracing — FR-13
**Files:** `desk/tracing.py`, `tests/test_tracing.py`, `desk/cli.py` · **Size: M**
- Acceptance: `JsonlTraceProcessor` implements `TracingProcessor`, writes every span export to
  `audit/traces.jsonl`; `set_trace_processors([...])` replaces the default exporter (no OpenAI export
  attempted, tracing still ON); one conversation = one trace: CLI wraps all turns in a single named
  `trace(...)`; test asserts spans share one `trace_id` and every span has a non-empty name.
- Verify: `uv run pytest tests/test_tracing.py` + **Checkpoint 3** (below).

**Checkpoint 3 (after Tasks 11–13):** suite green · one scripted question produces: one timeline JSONL
naming both agents in order, one run-wrapper record with request id + elapsed, one trace JSONL whose
spans all carry one trace id · `audit/` populated durably.

## Phase 4 — interface and delivery (FR-12)

### Task 14: Chainlit app core — FR-12
**Files:** `app.py`, `desk/app_state.py`, `tests/test_app.py` · **Size: M**
- Acceptance: `@cl.on_chat_start` validates env/courses (friendly setup card on failure — no
  traceback), builds agent + `StudentProfile` **once**, stores in `cl.user_session`;
  `@cl.on_message` awaits `Runner.run` with history via `to_input_list()` (never `run_sync`);
  multi-turn memory works; guardrail tripwire → refusal card; `MaxTurnsExceeded`/`ModelBehaviorError`
  and model/auth errors → concise retry-able message with traceback logged server-side only (central
  `errors.py` utility drives every message).
- Verify: `uv run pytest tests/test_app.py` (Chainlit handlers unit-tested around the session store).

### Task 15: Chainlit UX — branding, chips, steps, ticket card (`frontend-ui-engineering`)
**Files:** `.chainlit/config.toml`, `.chainlit/custom CSS asset`, `app.py`, `tests/test_app.py` · **Size: M**
- Acceptance: branded "Student Ops Desk" welcome + guided starter chips ("When is my A3 due?", "What if
  I submit late?", "Career roadmap after this bootcamp"); visible `cl.Step` traces of tool calls and
  handoffs; final `Ticket` rendered as a structured card with resolved/escalate indicators; custom
  CSS + config tracked in git; accessible contrast, dark-mode-consistent; nothing generic-AI-looking.
- Verify: `uv run chainlit run app.py` manual pass + two-window isolation check (recorded in `demo.md`).

### Task 16: Delivery docs + final audit
**Files:** `README.md`, `VIVA_NOTES.md`, `demo.md` · **Size: S**
- Acceptance: README (uv setup, CLI + Chainlit run, architecture, FR→file map, env-var names only);
  VIVA_NOTES answers all eight viva questions with file/line references; demo.md is a reproducible
  script for one clean conversation + one trace + one ticket; FR→"Done when" table ticked.
- Verify: final audit — `git log` order, suite green, `git grep` secret check, clean tree.

## Parallelization notes (`dispatching-parallel-agents`, max 2 concurrent)

- Tasks 2+3, 4+7, 11+12 are mutually independent once their prerequisites land — run in pairs.
- Everything else is sequential (shared `desk/agents.py`, `desk/cli.py`, or spec gates).
- Never parallelize work touching the same file or the same agent wiring.

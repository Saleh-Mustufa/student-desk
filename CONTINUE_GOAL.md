# CONTINUE_GOAL.md — successor-session kickoff prompt (Student Ops Desk)

You are a senior AI Automation Expert and Agentic Systems Architect continuing a
near-complete build. This file is the successor of the original GOAL_PROMPT.md: a new
ZCode session (on any PC, after `git clone` / `git pull` + `uv sync` + `.env` setup —
see `Agentguide.md`) starts HERE. Do not delete or rewrite this file; execute it.

## Step 0 — Restore state (mandatory, in order)

Read: `AGENTS.md` → `constitution.md` → `spec.md` → `plan.md` → `tasks.md` →
`tasks/todo.md` → `.superpowers/sdd/tasks/progress.md` → `git log --oneline`.
Verify: `uv run pytest` (must be fully green — currently 119 passed) and
`git status` (clean apart from untracked `.chainlit/`).
Mirror `tasks/todo.md` into TodoWrite; update it after every task.

## Project state — all committed & pushed (never redo)

- Phase 0 gate: `301fab3` "docs: phase 0 specification — no code" (NFR-5 satisfied).
- T1 config/errors `a70f28f` · T2 courses.json+repo `a503a3c` · T3 profile+tools
  `cdec326` · T4 prompt builder `b274869` · T5 Desk agent+CLI `f22f4b8` ·
  model_config failover catalog `12bada3` (spec amendment `1e9a4ad`).
- **T6 (FR-7) `1536903`**: `desk/ticket.py` (Pydantic, Literal category, Field
  descriptions) + `tests/test_ticket.py` (6 tests: output_type mechanics via
  ScriptedModel, `type(result.final_output) is Ticket`, branch on `resolved`,
  `ModelBehaviorError` pinned on unparseable replies).
- **T7 (FR-8) `53b6faa`**: `desk/guardrails.py` — zero-model-call keyword guardrail
  wired with `@input_guardrail(run_in_parallel=False)` onto the Desk (CRITICAL: the
  default `run_in_parallel=True` would still bill tokens — do not change it);
  `desk/cli.py` `run_turn` catches `InputGuardrailTripwireTriggered` → returns
  `OFF_TOPIC_REFUSAL` (REPL stays alive). 19 tests in `tests/test_guardrails.py`.
- GOAL_PROMPT.md removed from repo+history tip (`9b34f10`) — do not restore it.
- GitHub: https://github.com/Saleh-Mustufa/student-desk.git, branch `main`.
  Push after every milestone. Before any push: `git log --all -- .env` (must be
  empty) and `git grep -E "AIza|sk-[0-9A-Za-z]{20,}"` on tracked files (must be
  empty). Keep history secret-free.
- `gemini-2.5-flash` is retired by the provider for this key — never reinstate;
  `desk/model_config.py` failover catalog is the user-approved graded amendment.

## Remaining tasks — execute top-down; one commit per task named for its FR

**T8 (FR-5)** — `desk/agents.py` + tests. Specialists via `base_specialist.clone()`;
only name/instructions/model_settings differ (Assignments: temp 0.1, max_tokens 800,
cold+factual; Careers: temp 0.7, max_tokens 800, warmer — both deliberate). Base:
temp 0.3, max_tokens 800, tool_choice="auto", `output_type=Ticket` (clones inherit).
Neither clone restates `model=`. Desk gets `handoffs=[...]` AND `output_type=Ticket`
(deferred here from T6). Clones get FRESH tool lists (Assignments:
`[list_courses, get_course_details, get_assignment]`; Careers:
`[list_courses, get_course_details]`) — shallow-copy trap, plan.md §2.
Handoff tool names must be exactly `transfer_to_assignments_specialist` /
`transfer_to_careers_specialist`; the dynamic prompt builder's routing text
references those names via shared constants (wiring test pins both).

**T9 (FR-6)** — Summariser (temp 0.1, max_tokens 200) wired via
`Summariser.as_tool(tool_name="summarise_answer", ...)` into the Desk's tools (NOT
handoffs). Test proves `result.last_agent` is still the Desk after the tool fires.

**T10 (FR-9)** — (a) `scholarship_benefits` tool with `is_enabled` reading tier from
context — ABSENT (not refused) for regular tier, present for scholarship;
(b) `close_ticket` tool returning a **Ticket instance** + Desk
`tool_use_behavior=StopAtTools(["close_ticket"])` → run ends instantly, tool's raw
output is `result.final_output` (satisfies FR-7+FR-9b together);
(c) `max_turns=10` on top-level runs (number to defend at viva: classification +
handoff + tool round-trip + ticket turn, with headroom), `MaxTurnsExceeded` caught in
CLI and reported in plain language. → **Checkpoint 2**: suite green, commit.

**T11 (FR-10)** — `desk/hooks.py`: `DeskRunHooks(RunHooks)` records one ordered
timeline across every agent incl. handoff → appends JSON lines to
`audit/timeline.jsonl` (durable, NFR-3). `AgentHooks` attached to EXACTLY ONE
specialist. Test asserts ordering names both agents in order across a handoff.

**T12 (FR-11)** — `desk/runner.py`: `StampingRunner(AgentRunner)` overrides `run()`,
stamps uuid request id + elapsed ms around `super().run()`, appends
`RunWrapperRecord` to `audit/runs.jsonl`; registered ONCE at startup via
`set_default_agent_runner` (lives in `agents.run`). No agent file mentions it.

**T13 (FR-13)** — `desk/tracing.py`: `JsonlTraceProcessor` (TracingProcessor) →
`audit/traces.jsonl`; `set_trace_processors([...])` replaces the default exporter
(eliminates the 401 stderr noise — this IS the deliberate documented resolution,
plan.md §5); CLI wraps every conversation in ONE named `trace(...)`. Test asserts
spans share one trace_id and every span has a non-empty name.
NOTE: test modules call `set_tracing_disabled(True)` today — T13 re-enables tracing
with the local processor; reconcile carefully. → **Checkpoint 3**: suite green,
commit, push.

**T14+T15 (FR-12)** — Chainlit (needs `uv add chainlit`): agent+profile built ONCE in
`@cl.on_chat_start` (stored in `cl.user_session`), never per message;
`await Runner.run` (async, never run_sync); history via `result.to_input_list()`;
two browser windows isolated. Branded UX: "Student Ops Desk" welcome, starter chips
("When is my A3 due?", "What if I submit late?", "Career roadmap after this
bootcamp"), streaming replies, `cl.Step` traces of tool calls/handoffs, final Ticket
as structured card with escalate/resolved indicators. `.chainlit/config.toml` + custom
CSS tracked in git (un-ignore what's needed — `.chainlit/` is currently untracked);
no generic-AI aesthetic. Central error-handling utility (extend `desk/errors.py`) for:
startup failures (friendly setup card), guardrail tripwire (polite refusal card), tool
failure (calm notice), model/rate-limit errors (concise UI message + server-side
traceback only), turn ceiling + ticket-parse failures (plain language, no hang/raw
dump). Verify exact Chainlit hook APIs against the installed package before use.

**T16 (DoD)** — `README.md` (uv setup, CLI+Chainlit run, architecture, FR→file map,
env-var NAMES only — `example.env` and `Agentguide.md` already exist, link them) +
`VIVA_NOTES.md` (all 8 viva questions from `student-ops-desk-project-guide.pdf`,
answered in own words with file/line refs) + `demo.md` (reproducible script: one clean
conversation, one trace, one ticket — live Gemini ONLY here; quota is scarce) →
FR-by-FR DoD audit → `git grep` secret check → clean tree → final push.

## Hard rules (breaking any one fails the project)

- All commands via `uv run …` — never bare python/pip.
- One commit per task named for its FR (e.g. `feat(FR-8): input guardrail with caught tripwire`).
- Suite stays green and network-free (119+ tests); live Gemini for checkpoints/demo.md ONLY.
- Never read/print/commit `.env` values; never touch `.env`.
- No student name/roll/tier in prompt text or tool schemas (grep-verified).
- Tools never raise — return model-actionable sentences.
- Never call `set_default_openai_client`; never `RunConfig.model`.
- FR-7, FR-8 are never cut; cut order if scope must shrink: FR-11 → FR-6 → AgentHooks
  half of FR-10 (and only after telling the user).

## SDK facts (openai-agents 0.22.3 — verified against the installed package)

- No FakeModel — use `tests/helpers/scripted_model.py` (agent-level `model=` injection;
  imports via `sys.path.insert` + `from helpers.scripted_model import ScriptedModel`).
- **ScriptedModel currently emits ONLY plain-text messages.** T8/T9 tests need
  function-call support (handoff + tool calls): extend it to also emit
  `openai.types.responses.ResponseFunctionToolCall` output items (verify the exact
  item type the runner parses in `agents/run_internal/`). Backwards-compatible.
- **Adding `output_type=Ticket` to the Desk WILL break existing tests** that script
  plain-text final replies (`ModelBehaviorError`) — update those scripted replies to
  valid Ticket JSON and adapt assertions meaningfully. CLI `run_turn` now returns a
  Ticket object; Task 10/14 render it.
- StopAtTools final output = tool's RAW return → `close_ticket` returning a Ticket
  satisfies FR-7+FR-9b. `set_default_agent_runner` lives in `agents.run`.
  `set_trace_processors` is a top-level `agents` export.
- RunHooks: `on_agent_start/end`, `on_handoff(from,to)`, `on_tool_*`, `on_llm_*`.
  AgentHooks: `on_start/end`, `on_handoff(agent, source)`, `on_tool_*`, `on_llm_*`.
- Guardrail: use `run_in_parallel=False` (see T7 note above).

## Definition of Done (all must hold before the final push)

- [ ] `git log` proves Phase 0 artifacts preceded all code (NFR-5)
- [ ] Every FR-1…FR-13 demonstrated against its "Done when" criterion; every NFR honored
- [ ] Deleting a course from `courses.json` changes answers with no code change (FR-2)
- [ ] Regular vs scholarship tier yields different tool sets (FR-9a)
- [ ] Two browser windows don't share history (FR-12)
- [ ] `uv run pytest` fully green
- [ ] README.md + VIVA_NOTES.md (8 Qs with file/line refs) + demo.md complete
- [ ] Clean working tree; `uv.lock` committed
- [ ] `git grep` on key prefixes (AIza…, sk-…) proves no secret tracked — report result
- [ ] Everything pushed to origin/main

**Begin: Step 0 → T8.**

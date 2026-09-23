# Spec: Saylani Student Ops Desk (master specification)

> LOCATION NOTE: this master spec lives at `docs/SPEC.md` because Windows NTFS is case-insensitive
> (`SPEC.md` and `spec.md` are the same file). The PDF-required behaviour spec is the root
> `spec.md`; architecture in `plan.md`; task breakdown in `tasks.md` / `tasks/`.
> Non-violatable rules in `constitution.md`. The graded brief (`student-ops-desk-project-guide.pdf`)
> wins on any conflict.

## Objective

Build the front desk for Saylani bootcamp students: a multi-agent system that answers student questions
about their course — assignments, careers, administration — from **real course data reachable only via
tools**, classifies every conversation, closes each resolved conversation with a **structured ticket**,
courteously refuses anything off-topic **before paying for a model call**, knows who is asking from
session context (never from the prompt), and leaves a **durable audit trail** behind every run.

The browser face is a customized Chainlit app that must look deliberately designed and handle every
failure mode gracefully.

**Users:** bootcamp students (regular and scholarship tiers) via browser; the operator via CLI.

**ASSUMPTIONS I'M MAKING (surfaced per spec-driven-development; correct me and I'll amend the spec):**

1. Windows 10 + Git Bash: the CLI forces UTF-8 output; paths are handled with `pathlib`.
2. The provided Gemini key can no longer call `gemini-2.5-flash` (provider 404 — "no longer available
   to new users"). Code keeps the brief's name as the built-in default; `.env` sets
   `GEMINI_MODEL=gemini-3.6-flash`, the provider-recommended successor. This is the single deviation
   from the brief's letter, documented in `plan.md` → Open Questions.
3. No OpenAI platform key is available, so the SDK's built-in trace export cannot upload anywhere.
   FR-13 is satisfied by keeping tracing **on** and replacing the default exporter with a durable local
   JSONL trace processor (one trace per conversation, every span nameable).
4. The pytest suite is deterministic and network-free (the Agents SDK's `FakeModel` exercises agent
   wiring); live-model behaviour is proven at scripted checkpoints and in `demo.md`.
5. There is no auth system in scope: demo profiles are constructed at session start (CLI flags /
   Chainlit selector), which is exactly the `StudentProfile` object FR-3 requires.
6. "Streaming replies" is delivered as live `cl.Step` progress (tool calls, handoffs) plus an immediate
   structured ticket card; token-by-token streaming is incompatible with FR-7's typed final output and
   is documented as a deliberate tradeoff (FR-7 is uncuttable).

## Capability Map

| Module id | Responsibility | Depends on |
|---|---|---|
| config | Env loading, model wiring, friendly startup validation | — |
| courses | `courses.json` loader + course tools (FR-2) | config |
| profile | `StudentProfile` context object + dynamic prompt builder (FR-3, FR-4) | config |
| desk-core | Desk agent, ticket model, guardrail, CLI entry (FR-1, FR-7, FR-8) | config, courses, profile |
| specialists | Cloned specialists + handoffs, summariser-as-tool, tool gating, close_ticket, ceiling (FR-5, FR-6, FR-9) | desk-core |
| ops | Timeline hooks, custom runner, local tracing (FR-10, FR-11, FR-13) | specialists |
| ui | Chainlit app, branding, central error handling (FR-12) | ops |

Build order: config → courses → profile → desk-core → specialists → ops → ui.

## Tech Stack

- Python 3.14, managed exclusively by `uv` (0.12.3).
- `openai-agents` (OpenAI Agents SDK) — agents, tools, handoffs, guardrails, hooks, custom runner, tracing.
- `gemini-3.6-flash` (see assumption 2) via `AsyncOpenAI` + `OpenAIChatCompletionsModel` at **agent level**.
- `chainlit` — browser UI; `.chainlit/config.toml` + custom CSS tracked in git.
- `pydantic` — `Ticket` output schema; `python-dotenv` — `.env` loading.
- `pytest` + `pytest-asyncio` — tests (asyncio_mode=auto).

## Commands

```
uv sync                                    # install locked deps
uv run pytest                              # full test suite (network-free)
uv run pytest tests/test_guardrails.py -q  # one file
uv run python -m desk.cli                  # terminal Desk (profile via flags, e.g. --name Ali --tier scholarship)
uv run python -m desk.cli --demo           # scripted demo conversation (demo.md)
uv run chainlit run app.py                 # browser Desk on http://localhost:8000
uv run chainlit run app.py -w              # with live reload during development
uv add <pkg>                               # dependencies only ever through uv
```

## Project Structure

```
app.py                  # Chainlit entry: @cl.on_chat_start builds agent+profile ONCE per session (FR-12)
desk/
  __init__.py
  config.py             # env validation (NFR-1), model wiring (FR-1) — model object passed to agents
  errors.py             # central error utility: ConfigError, friendly messages, server-side logging
  profile.py            # StudentProfile dataclass (FR-3)
  prompt_builder.py     # dynamic instructions rebuilt per turn (FR-4); printable before any model call
  courses.py            # courses.json loader (file-backed, no cache that outlives edits) (FR-2)
  tools.py              # list_courses, get_course_details, get_assignment, scholarship_benefits,
                        # close_ticket — never raise, model-actionable failure sentences (NFR-4, FR-9)
  ticket.py             # Ticket pydantic model (FR-7)
  guardrails.py         # keyword input guardrail: zero model calls, zero billed tokens (FR-8)
  agents.py             # base specialist + clones + handoffs + summariser-as-tool (FR-5, FR-6)
  hooks.py              # RunHooks timeline (FR-10) + AgentHooks on exactly one specialist
  runner.py             # custom AgentRunner: request id + elapsed time (FR-11)
  tracing.py            # local JSONL trace processor (FR-13)
  cli.py                # async entry point, asyncio.run, catches tripwire/ceiling/parse errors
data/
  courses.json          # the ONLY source of course facts (FR-2)
tests/                  # pytest, network-free (FakeModel), mirrors desk/ modules
audit/                  # durable runtime output (gitignored): timeline.jsonl, runs.jsonl, traces.jsonl
.chainlit/              # config.toml + custom CSS + translations (tracked)
docs artifacts at root: constitution.md, SPEC.md, spec.md, plan.md, tasks.md, tasks/
```

## Code Style

Types everywhere, docstrings that the SDK turns into tool descriptions, tools that return sentences not
exceptions. Real snippet — the shape every tool follows:

```python
@function_tool
async def get_assignment(
    wrapper: RunContextWrapper[StudentProfile],
    course_id: str,
    assignment_id: str,
) -> str:
    """Look up one assignment by id and return its title, due date and status.

    Never invent ids: only assignments present in the course catalogue are returned.
    """
    try:
        course = courses_repo.get_course(course_id)
        assignment = courses_repo.get_assignment(course_id, assignment_id)
    except KeyError as exc:
        return f"Assignment lookup failed: {exc}. Tell the student it isn't in the catalogue."
    return format_assignment(course, assignment)
```

Conventions: `snake_case` functions/modules, `PascalCase` classes; no naked `except Exception` in tools
(except the catch-all that converts to a model-actionable sentence, which logs server-side); no student
data in static strings; every agent gets `model_settings` with `max_tokens`; commit messages name the FR.

## Testing Strategy

- **Unit (network-free):** courses loader (delete-a-course behaviour), tool failure sentences, tool
  schemas (no wrapper parameter), prompt builder (3 profiles → 3 prompts; terser at open_tickets ≥ 3),
  ticket model, guardrail tripwire logic, gating function, timeline ordering, custom-runner stamping.
- **Agent wiring via `FakeModel`:** handoff reaches specialist (`result.last_agent`), `StopAtTools`
  ends the run with the tool's output, `output_type=Ticket` yields `type(final_output) is Ticket`,
  `MaxTurnsExceeded` raises, guardrail tripwire raises before any model call.
- **Live checkpoints (scripted, not in CI):** one real conversation per phase against Gemini, captured
  in `demo.md`.
- Coverage expectation: every FR has at least one test that fails before the implementing commit (TDD).

## Boundaries

- **Always:** spec before code; `uv run` for everything; failing test first; one FR-named commit per
  task; tools return sentences (never raise); guardrail/ticket tests green before any commit; graceful
  UI cards for every failure mode; tracebacks logged server-side only.
- **Ask first:** cutting anything from the cut list (FR-11 → FR-6 → AgentHooks half of FR-10); changing
  the model name; adding a dependency; changing the `Ticket` schema; touching `.chainlit/config.toml`
  defaults beyond branding/theme.
- **Never:** commit or print a key; call `set_default_openai_client`; put student name/roll/tier in
  prompt text or tool schemas; let a tool exception reach the runner; answer course questions without a
  tool; hardcode course facts in source; use pip or bare `python` for project code.

## Success Criteria

Every FR-1…FR-13 demonstrates against its PDF "Done when" criterion; every NFR honored; deleting a
course from `courses.json` changes answers with zero code change; regular vs scholarship runs offer
different tool sets; two browser windows have isolated history; `uv run pytest` fully green; `git log`
shows Phase 0 artifacts before all code; README.md / VIVA_NOTES.md / demo.md complete; clean working
tree; `git grep` proves no secret tracked.

## Open Questions

1. **Model name deviation (flagged to the user):** brief says `gemini-2.5-flash`; the provided key gets
   a provider 404 for it. Decision while awaiting user input: `GEMINI_MODEL` env override, code default
   `gemini-2.5-flash`, `.env` pinned to `gemini-3.6-flash`.
2. If the user supplies a real OpenAI platform key, should built-in trace export run *in addition to*
   the local JSONL processor? (Default: local only — FR-13 is satisfied without it.)

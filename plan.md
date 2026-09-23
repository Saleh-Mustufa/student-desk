# plan.md — Saylani Student Ops Desk architecture

> Behaviour: `spec.md` · Master spec: `docs/SPEC.md` · Tasks: `tasks.md` / `tasks/` · Rules: `constitution.md`

## 1. System shape

One conversation, four agents, one shared context object. The **Desk** owns the conversation: it takes
every message, classifies it, answers administrative questions itself, and transfers assignment/career
questions by **handoff** to a cloned specialist. A **Summariser** is reachable **only as a tool**. The
conversation ends when an agent produces a **`Ticket`** — the Desk and both specialists share that
output type — or instantly, when the Desk calls `close_ticket`.

```
                    input guardrail (FR-8, zero model calls)
                              │ passes
                     ┌────────▼────────┐  handoff            ┌─────────────────────┐
 student message ──► │  Student Ops    │ ──────────────────► │ Assignments         │
 (history +          │  Desk           │ ──────────────────► │ specialist (clone)  │
 StudentProfile      │                 │                     └─────────────────────┘
 as context)         │  admin answers, │                     ┌─────────────────────┐
                     │  summarise tool │ ──────────────────► │ Careers             │
                     │  close_ticket   │                     │ specialist (clone)  │
                     └───────┬─────────┘                     └─────────────────────┘
                             │ tool call (as_tool)                    ▲
                     ┌───────▼─────────┐    course tools    │
                     │  Summariser     │    (all agents) ───┘  → data/courses.json
                     │  (agent-as-tool)│                       (list_courses, get_course_details,
                     └─────────────────┘                        get_assignment)

 every agent: output_type=Ticket · model on the agent (FR-1) · own ModelSettings ceiling (NFR-2)
```

## 2. Agents

| Agent | Role / conversation ownership | Instructions | Model settings (deliberate) | Tools | Handoffs |
|---|---|---|---|---|---|
| **Student Ops Desk** | Owns the conversation from the first message; classifies assignment/career/admin; answers admin (schedule/policy) questions itself; files the ticket | Dynamic — rebuilt per turn from `StudentProfile` (FR-4): greets by name, names enrolled course, terser when `open_tickets >= 3`; routing rules name the handoff tools | `temperature=0.2, max_tokens=1000` — classification + structured output need precision; ceiling bounds cost | `summarise_answer`, `close_ticket`, `list_courses`, `get_course_details`, (`scholarship_benefits` only when tier == scholarship) | `assignments_specialist`, `careers_specialist` |
| **Base specialist** (never run directly) | Template the two specialists clone | Static base instructions | `temperature=0.3, max_tokens=800`, `tool_choice="auto"` | reference list, passed fresh to each clone | — |
| **Assignments Specialist** (clone) | Assignment deadlines, requirements, late policy — **cold and factual**: low temperature, terse sentences, cites the policy text verbatim from the tool result | Own instructions only | `temperature=0.1, max_tokens=800` — determinism beats charm for facts (deliberate, defensible) | fresh `[list_courses, get_course_details, get_assignment]` | — |
| **Careers Specialist** (clone) | Career guidance tied to the bootcamp's career paths — **warmer**: encouraging tone, still grounded in `courses.json` career data | Own instructions only | `temperature=0.7, max_tokens=800` — warmth needs some variability (deliberate, defensible) | fresh `[list_courses, get_course_details]` | — |
| **Summariser** | Condenses a long policy answer to ≤ 3 lines. A **tool, not a handoff**: summarisation is a sub-task the Desk borrows and then speaks in its own voice; a handoff would transfer the conversation away from the Desk (FR-6) | Static — "compress, keep every fact, ≤ 3 lines, no preamble" | `temperature=0.1, max_tokens=200` — tiny ceiling; summarisation is cheap or it is pointless | — | — |

Both specialists **share the base agent's model object without restating it** (`clone()` carries `model=`
over); only `name`, `instructions`, `model_settings` differ — exactly the fields the brief allows.
Clones pass **fresh tool lists** (the shallow-copy trap in fundamentals ch. 9) so specialists never grow
each other's tools. The Desk attaches **`AgentHooks` to the Assignments specialist only** (FR-10).

The handoff tools' names are derived from agent names (`transfer_to_assignments_specialist`,
`transfer_to_careers_specialist`); the Desk's routing instructions reference exactly those names.
Renaming a specialist silently breaks routing (fundamentals ch. 12 note) — the wiring test pins the
names.

## 3. Tools (name · signature · return shape)

All tools are `@function_tool`, `async`, and take `RunContextWrapper[StudentProfile]` as their first
parameter — that parameter is **stripped from the generated schema** (FR-3's "no wrapper parameter").
All returns are single-line-or-two strings the model reads; **no tool ever raises** (NFR-4).

| Tool | Signature (beyond wrapper) | Returns | Failure sentence (never raises) |
|---|---|---|---|
| `list_courses` | `() -> str` | One line per course: `id — title (schedule)` | `The course catalogue is currently empty. Apologise and tell the student to check back later.` |
| `get_course_details` | `(course_id: str) -> str` | Title, schedule, each policy as `policy: value` | `Course lookup failed: unknown id '<id>'. Tell the student it isn't in the catalogue.` |
| `get_assignment` | `(course_id: str, assignment_id: str) -> str` | `title · due <date> · <status/policy notes>` | `Assignment lookup failed: unknown id '<aid>' in course '<cid>'. Tell the student it isn't in the catalogue — do not invent an id.` |
| `scholarship_benefits` | `() -> str` | The enrolled course's scholarship benefits (read from `courses.json`; reads `wrapper.context.tier` — **gated**: `is_enabled` returns False for regular tier, so the tool is *absent*, not refused, FR-9a) | `Scholarship details are not published for this course. Say you'll escalate to the office.` |
| `close_ticket` | `(category: Literal["assignment","career","admin"], summary: str, next_step: str, resolved: bool, escalate: bool) -> Ticket` | Constructs and returns a **`Ticket` instance**; the Desk carries `tool_use_behavior=StopAtTools(["close_ticket"])` so the run **ends the moment it is called** and the tool's output becomes `result.final_output` (FR-9b, FR-7) | n/a — args are validated by Pydantic; a bad `category` surfaces as the SDK's tool-arg validation error, caught at the call site |
| `summarise_answer` | `(input: str) -> str` — generated by `Summariser.as_tool(tool_name="summarise_answer", tool_description=…)` | ≤ 3-line condensation the Desk weaves into its own voice | Internal `Runner.run(summariser, …, max_turns=2)` is wrapped: on failure returns `Summarisation failed. Give the student the key facts from the original answer yourself.` |

`courses.json` schema follows the brief's example, extended with two data fields the specialists need
(`career_paths`, `scholarship_benefits` per course) so career advice and scholarship answers are also
file-backed (FR-2). `courses.py` re-reads the file on demand (mtime-checked) — **deleting a course
changes answers with zero code change**.

## 4. Data structures crossing a boundary

| Structure | Shape | Crosses |
|---|---|---|
| `StudentProfile` (dataclass, FR-3) | `name: str · roll_no: str · course_id: str · tier: str = "regular" · open_tickets: int = 0` | built once per session (CLI flags / Chainlit `on_chat_start`) → passed as `context=` on every run → read by tools, dynamic instructions, tool gating |
| `Ticket` (Pydantic, FR-7) | `category: Literal["assignment","career","admin"] · summary: str · next_step: str · resolved: bool · escalate: bool` | the final output of Desk and both specialists; `close_ticket` returns it; UI renders it as a card; program branches on `resolved`/`escalate` in Python |
| `TimelineEntry` (FR-10) | `{"seq": int, "ts": ISO-8601, "event": "agent_start|agent_end|handoff|tool_start|tool_end|llm_start|llm_end", "agent": str, "detail": str}` | `RunHooks` appends in-process → flushed as one JSON object per line to `audit/timeline.jsonl` (durable, NFR-3) |
| `RunWrapperRecord` (FR-11) | `{"request_id": uuid4-hex, "started_at": ISO, "elapsed_ms": int, "agent": str, "outcome": "ok|error", "error_type": str?}` | custom `AgentRunner` stamps around every run → `audit/runs.jsonl` |
| Trace span export (FR-13) | SDK `Span.export()` dict (`trace_id`, `span_id`, `parent_id`, `name`, timings) | local `TracingProcessor` → `audit/traces.jsonl`, one trace id per conversation |
| Guardrail output | `GuardrailFunctionOutput(output_info={"matched": str?}, tripwire_triggered: bool)` | guardrail → call site's `except InputGuardrailTripwireTriggered` → courteous refusal card |
| Conversation history | `result.to_input_list()` | each turn feeds the next run — multi-turn memory in CLI and Chainlit (FR-12) |

## 5. FR-13 landmine — deliberate resolution

The SDK's built-in trace exporter uploads to OpenAI's platform and needs an OpenAI platform key. The
`.env`'s `OPENAI_API_KEY` is a Gemini-endpoint key; exporting with it would 401 on every run. Options
considered: (a) `set_tracing_disabled(True)` — kills the audit story, rejected; (b) export anyway and
swallow 401s — noisy, dishonest; **(c) chosen: keep tracing ON, replace the default processor list with
`set_trace_processors([JsonlTraceProcessor(...)])`** so every trace/span is created and written durably
to `audit/traces.jsonl` under our own control. One conversation = one trace: the CLI/Chainlit layers
create a named `trace("student-ops-desk:<session-id>")` per conversation and wrap every run in it, so
all messages of one conversation share one trace id and every span is nameable from the file. Documented
here per the brief; revisiting requires only a real platform key plus one line in `tracing.py`.

## 6. Cost ceilings (NFR-2)

Every agent declares `ModelSettings` with `max_tokens`: Desk 1000 (structured ticket + routing),
specialists 800, Summariser 200 (a 3-line summary). Guardrail: **zero** model calls by design.
Turn ceiling: `max_turns=10` on every top-level run (classification → handoff → tool round-trip →
ticket, with headroom; caught as `MaxTurnsExceeded` and reported — never a loop, FR-9c).

## 7. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `gemini-2.5-flash` 404s on the provided key ("no longer available to new users") | Brief's model name unusable | `GEMINI_MODEL` env override; code default keeps the brief's name; `.env` pins `gemini-3.6-flash`; flagged in Open Questions |
| `StopAtTools` × `output_type=Ticket` interaction: final output must be a `Ticket` instance, not the tool's string | FR-7/FR-9b conflict | `close_ticket` **returns a `Ticket` object**; FakeModel test pins `type(final_output) is Ticket` before wiring live; fallback documented in tasks (T10) |
| Gemini strict JSON-schema quirks on `output_type` | Ticket parse failures | Prefer `AgentOutputSchema(Ticket, strict_json_schema=False)` if the provider rejects strict mode; parse-failure path is caught and rendered as a friendly card, never a hang |
| Agent rename breaks handoff tool names silently | Routing degrades | Wiring test asserts the generated handoff tool names; instructions built from constants, not duplicated strings |
| Shallow-copy trap: clones sharing tool lists | Cross-specialist tool leakage | Clones pass fresh lists (`tools=[*base.tools, …]`); test asserts per-specialist tool sets |
| Chainlit session state rebuilt per message | Violates FR-12, loses memory | Agent + profile built only in `on_chat_start`, stored in `cl.user_session`; handler only awaits; test reads the handler source structure + two-window manual check in demo.md |
| Windows console mojibake in CLI | Demo unreadable | `sys.stdout.reconfigure(encoding="utf-8")` in `cli.py` |
| Tool schema leaks wrapper/profile | FR-3 violation | Schema test asserts `params_json_schema` has no wrapper key and no profile fields; grep test for student names |
| Trace export silently skipping | Un-auditable runs | Custom processor writes locally; test asserts the JSONL grows and every span has a name |

## 8. Open Questions (user input requested, build unblocked meanwhile)

1. **Model name (flagged):** brief says `gemini-2.5-flash`; the provided key's account gets a provider
   404 for it (exact error captured in `docs/SPEC.md` → assumption 2). Provisional decision:
   `GEMINI_MODEL=gemini-3.6-flash` in `.env`, code default remains `gemini-2.5-flash`. One-line revert.
2. **Trace export:** no OpenAI platform key → local durable JSONL traces (section 5). If you provide a
   platform key, built-in export can run *in addition* with one line.
3. **Stretch items** (only if everything else is green): typed handoff input, SQLite ticket store,
   output guardrail quoting policies not in `courses.json`.

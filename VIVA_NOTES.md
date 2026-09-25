# VIVA_NOTES.md — the eight viva questions, answered in my own words

Every answer names the file and line I would open on screen. Line numbers are
from the final tree; each claim is also pinned by a test I can run live
(`uv run pytest`, network-free).

---

### 1. Show the schema for a tool that reads the profile. Why is the wrapper parameter missing from it?

Open `desk/tools.py:113` (`get_course_details`) — every tool takes
`RunContextWrapper[StudentProfile]` as its first parameter
(`desk/tools.py:52` for `list_courses`). The Agents SDK strips the
`RunContextWrapper` parameter from the generated JSON schema *by design*:
the context is a **local Python object injected at `Runner.run(..., context=)`
time** (`desk/app_state.py:131` passes `context=self.profile`), not model
input. So the schema the model sees has only `course_id` — there is no
parameter it could fill with a student's name, roll number, or tier, and
nothing it could invent. The profile reaches the model **only** through the
dynamic instructions I wrote deliberately (`desk/prompt_builder.py:98`), and
the roll number/tier never reach the prompt at all — tier acts through tool
gating (FR-9a), `open_tickets` through prompt terseness. Pinned by the schema
tests (`tests/test_tools.py` — every `params_json_schema` has no wrapper key
and no profile fields) and the prompt-boundary test
(`tests/test_prompt_builder.py` — name present, roll number and tier words
absent).

### 2. A blocked question cost you nothing. Prove it, from the trace.

The guardrail is a **pure local regex scan** — no model object, no `Runner`
call anywhere in `desk/guardrails.py` (the pattern table is
`desk/guardrails.py:28`). It is wired with `run_in_parallel=False`
(`desk/guardrails.py:80`) because the SDK's default `run_in_parallel=True`
runs the guardrail *concurrently with the first model turn*, which would
still bill tokens; with `False` the tripwire fires **before** the Desk's
model is ever called. Proof in three layers:

1. `tests/test_guardrails.py:180` — off-topic input raises
   `InputGuardrailTripwireTriggered` while the scripted model's recorded
   calls are **empty** (`model.calls == []`): zero billed tokens.
2. `tests/test_guardrails.py:107` — monkeypatching `Runner.run` and
   `Model.get_response` to raise proves the guardrail function itself makes
   zero model calls.
3. From the trace: run the demo (`demo.md`) with a joke question, then open
   `audit/traces.jsonl` — the refused turn produced **no LLM span at all**
   (only the guardrail's run); compare with an on-topic turn, which shows the
   agent and response spans. The UI shows the polite refusal card
   (`app.py` — `OFF_TOPIC_REFUSAL` branch) and the REPL stays alive
   (`desk/cli.py`, `run_turn` catches the tripwire).

### 3. Which attributes do your two specialists share with the base agent, and which are their own?

`desk/agents.py:157` builds the base; `desk/agents.py:193/200` produce both
specialists via `base.clone(...)` — a dataclass shallow copy, so inheritance
is structural, not re-declared:

- **Shared (inherited, never restated):** the `model=` object (FR-1: one
  model instance, tests assert `assignments.model is model`),
  `output_type=Ticket` (declared once at `desk/agents.py:174`), and the
  `handoff_description=None` default. Nothing a clone didn't receive as an
  explicit argument is re-created.
- **Their own:** `name` ("Assignments Specialist" / "Careers Specialist"),
  `instructions` (cold+factual vs warmer — two deliberately different
  static strings), and `model_settings` — Assignments `temperature=0.1,
  max_tokens=800` (`desk/agents.py:69`, determinism beats charm for
  deadlines and verbatim policy text) vs Careers `temperature=0.7,
  max_tokens=800` (`desk/agents.py:72`, warmth needs some variability); the
  base template sits at `0.3/800` with `tool_choice="auto"`
  (`desk/agents.py:64`). Each clone also passes a **fresh tool list**
  (`clone()` copies the reference, not the list — the shallow-copy trap):
  Assignments gets `get_assignment`, Careers doesn't
  (`tests/test_agents.py::test_clones_receive_fresh_tool_lists...` pins the
  lists *and* that the list objects are distinct).

### 4. Rename one specialist. What silently degrades, and where does that name come from?

The handoff tool's name is **derived from the agent's name** — the SDK wraps
each `Agent` in `handoffs=[...]` into a `Handoff` whose tool name is
`transfer_to_` + the name snake-cased (`Handoff.default_tool_name`, in the
installed `agents/handoffs/__init__.py:207`). Rename "Assignments Specialist"
and the tool becomes `transfer_to_<new_name>` — but the Desk's **routing
instructions** still tell the model to call `transfer_to_assignments_specialist`,
so the model would be instructed to call a tool that no longer exists:
assignment questions silently stop routing (the model either flails or
answers out of scope). That's why the name lives in exactly one place — the
shared constants in `desk/prompt_builder.py:36`
(`ASSIGNMENTS_HANDOFF_TOOL = "transfer_to_assignments_specialist"`, same for
Careers) — and the routing scope text is *composed from those constants*
(`desk/prompt_builder.py:86`), never duplicated. The wiring test
(`tests/test_agents.py::test_generated_handoff_tool_names_match_routing_constants_in_the_prompt`)
runs a real scripted turn and pins that the **generated** handoff tool names
equal the constants **and** that both names appear in the resolved system
prompt — renaming a specialist breaks that test loudly instead of degrading
silently.

### 5. Why does the Chainlit handler await the run? What is the exact error if it does not?

`app.py:102` — `answer = await session.send(message.content)`. The run is a
coroutine: `Runner.run` is `async` (`desk/app_state.py:120`'s `send` awaits
it). The handler must await because Chainlit dispatches `on_message` on its
asyncio event loop and consumes the returned value; everything downstream
(model I/O, tool calls) is cooperative async on that one loop. If the
handler **did not await**, it would simply `return` a coroutine object —
Chainlit would never schedule it and the user gets **no reply at all**; the
server logs `RuntimeWarning: coroutine 'on_message' was never awaited`
(that is the exact observable error — no exception page, just a silently
dropped turn). Using the synchronous variant (`Runner.run_sync` or blocking
calls) would freeze the event loop: the whole app — both browser windows,
heartbeats, everything — stalls until the model responds. The project pins
this shape: `tests/test_agents.py` asserts the CLI entry is
`asyncio.run(main())` with no `run_sync` anywhere, and
`tests/test_app.py::test_app_handlers_are_thin_and_session_backed` pins
`await session.send(` in `app.py`.

### 6. Your ticket came back missing a field. Which exception, raised by which layer?

`ModelBehaviorError` (from `agents.exceptions`), raised by the **Agents SDK
runner's structured-output layer** — after the model's final message comes
back, the runner validates/parses it against the declared
`output_type=Ticket` (`desk/ticket.py:17`: a Pydantic model with a
`Literal["assignment","career","admin"]` category and described fields). A
reply that is not valid Ticket JSON — a missing field, a bad category, or
plain prose — fails that parse and the runner raises `ModelBehaviorError`
instead of handing me a half-filled object. Pinned in
`tests/test_ticket.py:120` (a scripted "I cannot file a ticket." reply
raises exactly that). My code **catches** it at the session boundary
(`desk/app_state.py:141`) and converts it to the friendly
`TICKET_PARSE_FAILURE_MESSAGE` card (`desk/errors.py`) with the traceback
logged server-side only — so a deliberately impossible request surfaces the
SDK's parse error as designed, but the student never sees a stack trace.

### 7. Which hook fires once per agent and which fires once per model call? Give the counts for one ticket.

In `DeskRunHooks` (`desk/hooks.py`): `on_agent_start`/`on_agent_end`
(`desk/hooks.py:70/73`) fire **once per agent** — every time the current
agent changes (start) and when an agent produces the final output (end).
`on_llm_start`/`on_llm_end` (`desk/hooks.py:87`) fire **once per model
call** — a multi-turn agent with tool calls makes several model calls and
the pair fires for each. `on_tool_start/end` pair with tool invocations and
`on_handoff` with the transfer.

Counts for one assignment ticket in the demo (Desk classifies → transfers →
Assignments specialist answers; the specialist's answer is the ticket):

| event | count |
|---|---|
| `agent_start` | 2 — Student Ops Desk, then Assignments Specialist |
| `handoff` | 1 |
| `llm_start` | 2 — one Desk classification call, one specialist call |
| `agent_end` | 1 — the specialist (it produced the final output) |

All of these land in one ordered timeline (`audit/timeline.jsonl`) naming
both agents in order — `tests/test_hooks.py` pins the exact sequence across
a scripted handoff. The close-watch `SpecialistAgentHooks` on the assignments
specialist records only its own agent's events and goes quiet for the Desk's
part (FR-10's second half).

### 8. What does your custom runner see that your hooks cannot?

`StampingRunner` (`desk/runner.py:49`) wraps `AgentRunner.run` **around the
whole call** (`super().run(...)`), so it sees the run as a *single unit
with a lifecycle the hooks don't have*:

1. **The run's total wall-clock time and its exit status as one fact** —
   `elapsed_ms` and `outcome: ok|error` stamped around the entire run
   (`audit/runs.jsonl`). Hooks are *events inside* the run: if the run dies
   (rate limit, `MaxTurnsExceeded`, `ModelBehaviorError`), `on_agent_end`
   never fires and no hook says "this run failed" — the runner records the
   error outcome and re-raises (pinned by
   `tests/test_runner.py::test_a_failing_run_stamps_an_error_record_and_reraises`).
2. **Every run in the process, hook-less ones included** — it is registered
   once at startup via `set_default_agent_runner` (`desk/app_state.py` /
   `desk/cli.py`), so it also stamps runs that carry no hooks at all (e.g.
   the Summariser's nested agent-as-tool run, specialists run directly).
   Hooks only see the runs they were passed to.
3. **The run as a request** — a fresh uuid `request_id` per run that ties
   the audit story together (which run produced which timeline entries and
   trace spans), something hooks, which receive only per-event context,
   never synthesize.

In short: hooks see the choreography inside a run; the runner sees the run
itself — its entry, its duration, its success or failure — for every run in
the process.

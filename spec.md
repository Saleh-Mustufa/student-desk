# spec.md — what the Desk does (behaviour, not implementation)

> Master specification: `docs/SPEC.md` · Architecture: `plan.md` · Tasks: `tasks.md` / `tasks/` ·
> Rules: `constitution.md`. The graded brief (`student-ops-desk-project-guide.pdf`) wins on any conflict.

The Student Ops Desk is the front door for Saylani bootcamp student questions. A student asks something
in plain language; the Desk works out whether it is about an assignment, a career, or course
administration; answers from real course data; and closes every resolved conversation with a structured
ticket. It refuses what isn't about the course, knows who is asking without being told in the prompt,
and every run can be audited after the fact.

## Behaviour requirements, restated

**FR-1 — Gemini at the agent.** A question typed in the terminal is answered by Gemini through its
OpenAI-compatible endpoint. The model (client + model name) is declared on each `Agent` — never
process-global, never per-run, and the forbidden global call (`set_default_openai_client`) appears
nowhere. The entry point is an `async def` driven by `asyncio.run`. (User-approved amendment,
2026-09-23: which Gemini model name is active is decided by `desk/model_config.py`'s priority
catalog with automatic failover — the agent-level configuration rule itself is unchanged.)

**FR-2 — Course knowledge lives in a file, reached only through tools.** All course facts — catalogue,
schedules, policies, assignments — live in `courses.json`. The only way any agent can see a fact is by
calling a tool: list the courses, fetch one course's schedule and policies, look up an assignment by
id. Deleting a course from the file removes it from every answer with zero code change. The Desk
declines to invent an assignment id that isn't in the file.

**FR-3 — The student is in context, never in the prompt.** Every run receives a `StudentProfile`
(name, roll number, enrolled course, tier, open-ticket count) as local context. Tools read the profile
from the context wrapper. The message text sent to the model never contains the student's name, roll
number, or tier; the generated schema of any profile-reading tool has no wrapper parameter (the model
can't see — or invent — identity).

**FR-4 — Instructions that change per turn.** The Desk's system prompt is built at request time from
the profile: it greets the student by name, names the course they are enrolled in, and becomes terser
once open_tickets reaches 3. Three different profiles produce three visibly different prompts, and the
resolved prompt can be printed before any model call happens.

**FR-5 — Two specialists, cloned from one base, reached by handoff.** An Assignments specialist and a
Careers specialist are produced by cloning a single base agent; only their instructions and model
settings differ (Assignments: cold and factual, low temperature. Careers: warmer, higher temperature —
both deliberate and defensible). Neither clone restates the model. The Desk transfers the conversation
to whichever fits; the specialist, not the Desk, answers. After the run the answering agent is
identifiable in code, and the handoff appears in the run's items.

**FR-6 — One specialist exposed as a tool, not a handoff.** A Summariser condenses a long policy answer
to three lines. It is wired as a tool the Desk calls, so the Desk keeps the conversation and speaks in
its own voice. Why a tool here and a handoff for the other two: summarisation is a sub-task the Desk
borrows mid-answer; assignment and career questions are jobs that pass to an owner. The final message
after a summarisation still comes from the Desk.

**FR-7 — Every resolved conversation produces a structured ticket.** The Desk's final output for a
resolved query is a typed object, not prose: `Ticket(category: "assignment"|"career"|"admin", summary,
next_step, resolved, escalate)`. The program branches on `resolved` in Python. A deliberately
impossible request surfaces the SDK's parsing error instead of a half-filled object.

**FR-8 — A guardrail that refuses non-course questions, cheaply.** An input guardrail rejects anything
unrelated to the bootcamp before the Desk's model runs. The program catches the tripwire and replies
politely; it never crashes. The refusal costs nothing at the model that would have answered it — the
guardrail is deliberately a zero-model-call check so the trace proves the saving.

**FR-9 — Tool gating, a stopping rule, and a ceiling.** Three separate controls:
(a) a scholarship-only tool is **absent** — not refused — for regular-tier students: the same question
run as regular and as scholarship offers the model a different set of tools;
(b) a `close_ticket` tool ends the run the moment it is called, its output becoming the final result;
(c) a turn ceiling that raises rather than loops — the number is chosen deliberately (10: a resolved
ticket needs a classification turn, a handoff, a tool round-trip, and the ticket turn, with headroom;
10 caps the cost if the model ever circles) and is caught and reported.

**FR-10 — An audit trail across the whole run, and one agent watched closely.** Run-level hooks record
one ordered timeline covering every agent in a conversation, including the handoff, written durably to
disk. Separately, agent-level hooks are attached to exactly one specialist. One student question yields
one timeline naming both agents in order; the agent-level hooks go quiet at the handoff because they
belong to the one agent, and once responsibility transfers, the events belong to the next agent (the
run-level hooks keep covering everything).

**FR-11 — A custom runner wrapping every run.** A custom runner stamps a request id and elapsed time
around every run in the process, registered once at startup. No agent definition changes to accommodate
it — no agent file mentions it — yet the wrapper's output appears for the Desk's run and for the
specialist's run.

**FR-12 — A Chainlit interface with per-session memory.** The Desk is usable in a browser. The agent
and the student's profile are built once when the session opens, never per message. The conversation
remembers earlier turns (a second message referring to the first is understood), two browser windows do
not share history, and the message handler awaits the async run.

**FR-13 — Traceable conversations.** Tracing is on and one student conversation appears as one trace,
not several. Every span in it can be named. Because the SDK's built-in exporter expects an OpenAI
platform key that this project does not have, export goes to a durable local JSONL sink under our own
control instead — one file, one trace id per conversation, every span named (see `plan.md` → FR-13
resolution).

## Non-functional behaviour

- **NFR-1 Secrets:** keys only in `.env`; missing key → clear startup error, not a stack trace.
- **NFR-2 Cost:** every agent declares its own model settings; nothing generates without a ceiling.
- **NFR-3 Observability:** every conversation traceable; the FR-10 audit timeline is written durably,
  not only printed.
- **NFR-4 Failure:** a tool that hits bad data returns a sentence the model can act on; a tool that
  raises into the runner is a defect.
- **NFR-5 Provenance:** `git log` shows the Phase 0 artifacts committed before the first code commit.

## The three things the Desk explicitly will not do

1. **It will not answer anything that is not about this bootcamp.** Weather, general knowledge, code
   help for other contexts, politics, chit-chat — off-topic input is refused courteously before the
   Desk's model is called, and the Desk will not pretend to "sort of" answer it.
2. **It will not do the graded work for the student.** The Desk explains deadlines, policies, and how
   to approach an assignment; it will not produce assignment deliverables or write a student's
   submission for them.
3. **It will not invent course facts or promise policy exceptions.** No assignment ids, deadlines,
   schedules, or policies that aren't in `courses.json`; no waiving a late penalty or overriding a
   published rule — situations outside the published policy are escalated, never improvised.

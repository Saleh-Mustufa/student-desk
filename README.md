# Saylani Student Ops Desk

A multi-agent front desk for Saylani bootcamp students: one Desk agent on
**Google Gemini** (via its OpenAI-compatible endpoint, built with the
[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)), two
cloned specialists reached by **handoff**, a Summariser reachable **only as a
tool**, a typed **Ticket** as every resolved conversation's final output, a
zero-cost **off-topic guardrail**, tool gating, durable audit trails, local
JSONL tracing, and a branded **Chainlit** browser UI.

> **On arrival at the institute — do these 5 things, in order.** (Full details:
> `Agentguide.md` · Continuation for a new ZCode session: `CONTINUE_GOAL.md`)

## 1. Get the code

```bash
git clone https://github.com/Saleh-Mustufa/student-desk.git
cd student-desk
```
(or `git pull` if already cloned)

## 2. Install dependencies

Install [uv](https://docs.astral.sh/uv/) if the PC doesn't have it, then:

```bash
uv sync
```

## 3. Add my key

```bash
cp example.env .env
```
Open `.env` and paste **my** Gemini API key as `OPENAI_API_KEY` (I carry the key
with me — it is never in git). Save. Nothing else in the file needs changing.
Env-var **names** used by the app: `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
`MODEL_PRIORITY` (optional model-catalog reorder) — see `example.env`.

## 4. Check it's alive

```bash
uv run pytest
```
All tests green = good. (A missing key fails fast with a friendly message — that's
by design; redo step 3.)

## 5. Run the demo

```bash
# terminal — one-shot question:
uv run python -m desk.cli --question "When is my A3 due?"

# terminal — interactive session:
uv run python -m desk.cli

# browser — branded Chainlit UI:
uv run chainlit run app.py
```

Quick demo lines:
- **Off-topic refusal (FR-8):** `What's the weather in Karachi?` — refused instantly.
- **Course facts (FR-2):** `When is my A3 due?` — answered from `data/courses.json`.
- **Tier gating (FR-9a):** same question with `--tier regular` vs `--tier scholarship`.

A full scripted walkthrough (one clean conversation, one trace, one ticket —
live Gemini **only** here, quota is scarce): `demo.md`.

## Architecture (one conversation, four agents, one context)

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

 every agent: output_type=Ticket · model on the agent (FR-1) · own max_tokens ceiling (NFR-2)
```

Around the conversation, three process-wide layers write durable audit lines:
**RunHooks** timeline (`audit/timeline.jsonl`), the custom **StampingRunner**
(`audit/runs.jsonl`), and the **JSONL trace processor**
(`audit/traces.jsonl`) — one named trace per conversation.

## Requirement → file map

| Req | Where it lives |
|---|---|
| FR-1 | `desk/config.py`, `desk/model_config.py` (failover catalog), `model=` at the agent in `desk/agents.py`, async entry `desk/cli.py` |
| FR-2 | `data/courses.json`, `desk/courses.py`, tools in `desk/tools.py` |
| FR-3 | `desk/profile.py` (context object), wrapper stripped from tool schemas (`desk/tools.py`) |
| FR-4 | `desk/prompt_builder.py` (dynamic per-turn prompt, printable preview) |
| FR-5 | `desk/agents.py` (`build_base_specialist` + `clone()`, handoffs), routing constants in `desk/prompt_builder.py` |
| FR-6 | `desk/agents.py` (`build_summariser`, `build_summarise_answer_tool` — tool, not handoff) |
| FR-7 | `desk/ticket.py`, `output_type=Ticket` on Desk + specialists |
| FR-8 | `desk/guardrails.py` (zero-model-call tripwire, `run_in_parallel=False`) |
| FR-9 | `desk/tools.py` (`scholarship_benefits` gating, `close_ticket`), `StopAtTools` + `MAX_TURNS=10` (`desk/agents.py`, `desk/cli.py`) |
| FR-10 | `desk/hooks.py` (`DeskRunHooks`, `SpecialistAgentHooks`), wired in `desk/cli.py` |
| FR-11 | `desk/runner.py` (`StampingRunner`), registered once in `desk/cli.py` / `desk/app_state.py` |
| FR-12 | `app.py`, `desk/app_state.py`, `.chainlit/` (config + custom CSS) |
| FR-13 | `desk/tracing.py` (`JsonlTraceProcessor`), one named `trace(...)` per conversation |
| NFR-1 | `desk/errors.py`, config validation (`desk/config.py`) |
| NFR-2 | `ModelSettings` ceilings in `desk/agents.py`; guardrail costs zero |
| NFR-3 | durable JSONL sinks under `audit/` |
| NFR-4 | tools never raise — model-actionable sentences in `desk/tools.py` |
| NFR-5 | `git log` — Phase 0 artifacts committed before any code |

Everything else (full setup troubleshooting, key handling): `Agentguide.md`.
Viva preparation: `VIVA_NOTES.md`. Scripted demo: `demo.md`.

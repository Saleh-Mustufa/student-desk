# Implementation Plan — Saylani Student Ops Desk

> Full task breakdown (acceptance criteria, verification, sizes): `../tasks.md` · Architecture: `../plan.md`
> This file is the execution view: architecture decisions, build order, checkpoints, risks.

## Overview

A four-agent student front desk on the OpenAI Agents SDK (Gemini via OpenAI-compatible endpoint,
model configured at the agent level) with a customized Chainlit UI. Spec-driven: Phase 0 artifacts
committed before any source file; TDD per task; one FR-named commit per task.

## Architecture Decisions

1. **Flat package `desk/` + root `app.py`** — Chainlit expects a root-level script; no build backend
   needed for an app (pyproject has none).
2. **Model object per agent** — `config.build_model()` constructs `OpenAIChatCompletionsModel` from
   env vars; passed as `model=` to each agent. No global client calls anywhere.
3. **All conversation agents share `output_type=Ticket`** (Desk declares; specialists inherit via
   clone) — guarantees FR-7 even after a handoff.
4. **`close_ticket` returns a `Ticket` instance + `StopAtTools`** — satisfies FR-9b (instant stop,
   tool output is final result) and FR-7 (typed) with one mechanism; pinned by a FakeModel test before
   live wiring (fallback path in `plan.md` §7).
5. **Keyword input guardrail (zero model calls)** — cheapest possible; the trace proves a blocked
   question cost nothing; deterministic for tests (fundamentals ch. 15: "the cheapest useful guardrail
   isn't an LLM at all").
6. **Durable local trace processor** replaces the default OpenAI exporter (no platform key available);
   tracing stays ON; one `trace(...)` per conversation (FR-13 resolution, `plan.md` §5).
7. **Custom `AgentRunner` registered once at boot** stamps request id + elapsed on every run (FR-11).
8. **`GEMINI_MODEL` env override** — brief's `gemini-2.5-flash` as code default; provider-recommended
   `gemini-3.6-flash` pinned in `.env` (provider 404 on this key; flagged, `plan.md` §8).

## Build order (dependency-ordered)

config → courses → profile/tools → prompt builder → Desk agent + CLI
→ Ticket → guardrail → specialists/handoffs → summariser tool → gating/close/ceiling
→ timeline hooks → custom runner → local tracing → Chainlit core → Chainlit UX → delivery docs.

## Task List

Index only — full criteria live in `../tasks.md`:

- Phase 1: [ ] T1 config/errors · [ ] T2 courses · [ ] T3 profile+tools · [ ] T4 prompt builder · [ ] T5 Desk+CLI
- **Checkpoint 1:** suite green · real terminal answer from `courses.json` · one FR-named commit per task
- Phase 2: [ ] T6 Ticket · [ ] T7 guardrail · [ ] T8 specialists+handoffs · [ ] T9 summariser tool · [ ] T10 gating/close/ceiling
- **Checkpoint 2:** off-topic refused free · handoff → specialist → typed Ticket · tool sets differ by tier
- Phase 3: [ ] T11 timeline hooks · [ ] T12 custom runner · [ ] T13 local tracing
- **Checkpoint 3:** one timeline + one run record + one trace on disk for one question
- Phase 4: [ ] T14 Chainlit core · [ ] T15 Chainlit UX · [ ] T16 delivery docs + final audit
- **Final:** all FR "Done when" criteria demonstrated · docs complete · clean tree

Parallel pairs (max 2 concurrent): (T2,T3) · (T4,T7) · (T11,T12). Never parallelize shared-file work.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| `StopAtTools` × `output_type` interaction | FakeModel test pins `type(final_output) is Ticket` before live wiring; fallback: parse tool JSON post-run and branch in Python |
| Gemini strict-schema rejects `output_type` | `AgentOutputSchema(Ticket, strict_json_schema=False)`; parse failures caught → friendly card |
| Agent rename breaks handoff tool names | Wiring test pins generated names; instructions reference constants |
| Shallow-copy trap on clone | Fresh tool lists per clone; test asserts per-specialist tool sets |
| Windows console encoding | UTF-8 reconfigure in CLI |
| Chainlit rebuild-per-message | Build once in `on_chat_start`; test asserts handler structure; two-window manual check |

## Open Questions

See `../plan.md` §8 (model name deviation — flagged; local trace export; stretch items).

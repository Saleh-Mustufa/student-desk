# demo.md — the reproducible live demo (one clean conversation, one trace, one ticket)

**This is the only place live Gemini is used** — free-tier quota is scarce,
so the scripted test suite stays network-free and every rehearsal happens
here, once, deliberately.

Before starting: `.env` in place (`OPENAI_API_KEY` — my key, never in git),
`uv sync` done, `uv run pytest` fully green. Delete nothing in `audit/`
before the run — you want the artifacts this conversation writes.

Total time: ~6 minutes. Do the steps in order; every step names the
requirement it demonstrates.

---

## 0. One-time sanity (no quota spent)

```bash
uv run pytest          # 170 passed, network-free
```

## 1. Terminal — the clean conversation (FR-1…FR-5, FR-7, FR-8)

```bash
uv run python -m desk.cli --name Ayesha --roll-no S-2026-042 --course-id agentic-ai-w4
```

- The banner prints the **resolved system prompt** before any model call
  (FR-4) — greets Ayesha by name, names "Agentic AI — Weekday Batch 4".
- Type: `When is class?`
  → Desk answers from `courses.json` itself (admin, FR-2) and files a typed
  **Ticket** (FR-7).
- Type: `When is my A3 due?`
  → the Desk **hands off** to the Assignments specialist (FR-5) — the
  answer comes from `transfer_to_assignments_specialist`, and the printed
  ticket is again a structured one.
- Type: `What's the weather in Karachi tomorrow?`
  → **instant refusal** (FR-8) — before the Desk's model is billed anything.
- Ctrl+C to exit.

## 2. Terminal — tier gating, the same question twice (FR-9a)

```bash
uv run python -m desk.cli --tier regular    --question "What benefits do I have as a student?"
uv run python -m desk.cli --tier scholarship --question "What benefits do I have as a student?"
```

Same question, **two different tool sets**: for the regular tier the model
is never offered `scholarship_benefits` (absent, not refused); for the
scholarship tier it is, and the answer comes from `courses.json`.

## 3. Terminal — the ceiling story (FR-9c), told not run

The viva line: *"max_turns=10, because a resolved ticket needs a
classification turn, a handoff, a tool round-trip and the ticket turn — 10
caps the cost with headroom if the model ever circles."* The catch-and-
report path is proven by `tests/test_gating.py` (network-free); don't burn
quota looping live.

## 4. Browser — the branded Chainlit UI (FR-12)

```bash
uv run chainlit run app.py
```

- The welcome card greets the **Student Ops Desk** brand and the student by
  name; three starter chips (`When is my A3 due?`, `What if I submit late?`,
  `Career roadmap after this bootcamp?`).
- Click `When is my A3 due?` → expand the **Steps** under the answer: the
  tool calls and the handoff are visible (FR-10 close-watch + FR-12 steps),
  and the final **ticket card** shows category, summary, next step and the
  resolved indicator (FR-7).
- Second message: `And what if I submit that one late?` → the desk
  understands "that one" — **memory across turns** (`result.to_input_list()`).
- **Two-window isolation:** open a second browser window (private mode) —
  its conversation is empty and its answers never see window one's history
  (two sessions, two `DeskSession` objects).

## 5. The audit story on disk (FR-10, FR-11, FR-13, NFR-3)

After steps 1–2, open the three sinks — one conversation wrote all three:

```bash
tail -n 5 audit/timeline.jsonl   # ordered events: agent_start → handoff → llm_start …
cat audit/runs.jsonl             # one line per run: request_id, elapsed_ms, outcome
tail -n 8 audit/traces.jsonl     # one trace id per conversation; every span named
```

Point at one trace line set: **all spans share one `trace_id`** (the CLI
wraps the whole conversation in a single named `trace(...)`), and every span
has a non-empty `name`. Then show the cheap-refusal proof (viva Q2): the
weather turn from step 1 produced **no LLM span** in `traces.jsonl` at all.

---

### Failure modes to show if asked (all friendly, never a traceback)

- Rename `.env` and run the CLI → `ConfigError` card naming the exact fix
  (NFR-1). Rename it back.
- Ask the browser something off-topic → the polite refusal card.
- Unknown assignment id: `When is k3 due?` → the desk says it isn't in the
  catalogue rather than inventing one (FR-2, tools return the
  model-actionable sentence — NFR-4).

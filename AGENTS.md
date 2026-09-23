# AGENTS.md — Saylani Student Ops Desk

**Start here:** read `GOAL_PROMPT.md` and follow it in order. It is the authoritative kickoff prompt for this project.

Hard rules that always apply:

1. **Spec before code** — no source file until the Phase 0 artifacts (constitution.md, SPEC.md, spec.md, plan.md, tasks.md) are committed. `git log` order is graded (NFR-5).
2. **`uv` only** — `uv init/add/run/lock`; never pip, never bare `python` for project code.
3. **Secrets** — the Gemini key lives only in `.env` (gitignored, already present). Never print, log, commit, or hardcode it. Missing key → clean startup error (NFR-1).
4. **Use the seven installed skills** in `.agents/skills/` (spec-driven-development, planning-and-task-breakdown, test-driven-development, subagent-driven-development, dispatching-parallel-agents, frontend-ui-engineering, openai-docs) — invoke via the Skill tool if available, otherwise Read the SKILL.md and follow it. None may be skipped.
5. **Requirements** — the graded brief is `student-ops-desk-project-guide.pdf` (FR-1…FR-13, NFR-1…5); the how-to reference is `openai-agents-sdk-fundamentals-guide-6.pdf`. The PDFs win over any other doc on conflict. Never cut FR-7 or FR-8; cut order otherwise: FR-11 → FR-6 → AgentHooks half of FR-10.
6. **Chainlit UI** must be polished and every failure mode handled professionally (friendly cards, no stack traces, server-side-only logging) — see GOAL_PROMPT.md, the Chainlit section.

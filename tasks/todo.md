# Task checklist — Saylani Student Ops Desk

> Live checklist; tick as tasks complete. Acceptance criteria and verification steps: `../tasks.md`.

## Phase 1 — core desk (FR-1…FR-4)
- [x] Task 1: Config, secrets validation, central errors (FR-1 partial, NFR-1)
- [x] Task 2: `courses.json` + loader (FR-2)
- [x] Task 3: `StudentProfile` + course tools that never raise (FR-2, FR-3, NFR-4)
- [x] Task 4: Dynamic prompt builder (FR-4)
- [x] Task 5: Desk agent + async CLI entry (FR-1)

### Checkpoint 1
- [x] `uv run pytest` green · terminal answers from `courses.json` · FR-named commits

## Phase 2 — specialists (FR-5…FR-9)
- [x] Task 6: Typed `Ticket` output (FR-7)
- [x] Task 7: Input guardrail (FR-8)
- [x] Task 8: Specialists via `clone()` + handoffs (FR-5)
- [ ] Task 9: Summariser as a tool (FR-6)
- [ ] Task 10: Tool gating, `close_ticket`, turn ceiling (FR-9)

### Checkpoint 2
- [ ] off-topic refused free · handoff → specialist → typed Ticket · tool sets differ by tier

## Phase 3 — operations (FR-10, FR-11, FR-13)
- [ ] Task 11: Timeline hooks, durable (FR-10, NFR-3)
- [ ] Task 12: Custom runner (FR-11)
- [ ] Task 13: Durable local tracing (FR-13)

### Checkpoint 3
- [ ] one question → one timeline + one run record + one trace on disk

## Phase 4 — interface and delivery (FR-12)
- [ ] Task 14: Chainlit app core (FR-12)
- [ ] Task 15: Chainlit UX — branding, chips, steps, ticket card (FR-12)
- [ ] Task 16: Delivery docs + final audit

### Final definition of done
- [ ] `git log` proves Phase 0 artifacts before all code (NFR-5)
- [ ] every FR-1…FR-13 "Done when" demonstrated · every NFR honored
- [ ] `uv run pytest` fully green · README/VIVA_NOTES/demo complete · clean tree · no secret tracked

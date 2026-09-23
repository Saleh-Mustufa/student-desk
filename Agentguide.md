# Agentguide — Student Ops Desk: quick setup & showcase guide

This guide is for running the **Saylani Student Ops Desk** on a fresh PC (e.g. during a
showcase). Follow it top-to-bottom — it is written so a new ZCode session (or a human)
can go from `git clone` to a live demo in a few minutes.

## 1. What this project is

A Gemini-powered front-desk agent for Saylani bootcamp students. A student asks a
question in plain language; the Desk classifies it (assignment / career / admin),
answers from `data/courses.json` through tools only, hands off to cloned specialist
agents, refuses off-topic questions **before** spending a model token, and ends every
resolved conversation with a structured, typed `Ticket`.

- Behaviour spec: `spec.md` · Architecture: `plan.md` · Rules: `constitution.md`
- Tasks & progress: `tasks.md`, `tasks/todo.md`, `.superpowers/sdd/tasks/progress.md`

## 2. One-time setup (fresh PC)

Prerequisites: **git** and **[uv](https://docs.astral.sh/uv/)** (`pip install uv` or the
standalone installer on the uv site). Python itself is managed by uv.

```bash
git clone https://github.com/Saleh-Mustufa/student-desk.git
cd student-desk
uv sync                      # creates .venv and installs exact locked deps (uv.lock)
```

### Secrets — the only manual step

```bash
cp example.env .env          # Windows Git Bash; in cmd use: copy example.env .env
```

Open `.env` in an editor and paste a real Gemini API key as `OPENAI_API_KEY`.
The key lives **only** in `.env` (gitignored). Never commit, print, or share it.

### Sanity check

```bash
uv run pytest                # full suite must be green and network-free
```

If the key is missing/blank, the CLI fails fast with a friendly setup message (NFR-1) —
that is by design, not a bug.

## 3. Running it

### Terminal (CLI)

```bash
# One-shot question:
uv run python -m desk.cli --question "When is my A3 due?"

# Interactive session (type questions, Ctrl+C to exit):
uv run python -m desk.cli

# Session flags: --name --roll-no --course-id --tier regular|scholarship --open-tickets N
uv run python -m desk.cli --tier scholarship --question "What are my scholarship benefits?"
```

### Browser (Chainlit UI)

> NOTE: the Chainlit app is the last remaining phase of the build (FR-12). Until it
> lands, use the CLI above. Once present (Task 14–15), it will be:
> ```bash
> uv run chainlit run app.py
> ```
> Open the printed localhost URL. Two browser windows = two isolated sessions.

## 4. FR demo map (what to type to show what)

| FR | What to do in the CLI |
|---|---|
| FR-1 | Any question — answer comes from Gemini, model declared on the agent |
| FR-2 | Ask "When is my A3 due?" — facts come from `data/courses.json` via tools only |
| FR-3/4 | Start with `--name Ayesha` — greeting uses the name; roll/tier never appear in the prompt |
| FR-5 | Ask an assignment question — handoff to the Assignments specialist |
| FR-6 | Ask for a long policy answer condensed — summariser runs as a tool, Desk still answers |
| FR-7 | Every resolved conversation ends with a structured Ticket (see run output) |
| FR-8 | Ask "What's the weather in Karachi?" — refused instantly, zero model tokens |
| FR-9 | Run the same scholarship question as `--tier regular` vs `--tier scholarship` — tool set differs |
| FR-10/11/13 | One question → `audit/timeline.jsonl` + `audit/runs.jsonl` + `audit/traces.jsonl` |

## 5. Troubleshooting

- **`uv: command not found`** — install uv first (see §2).
- **Missing key startup error** — you skipped the `.env` step; copy `example.env` → `.env`.
- **429 / 503 in logs** — free-tier rate limits; `desk/model_config.py` fails over to the
  next healthy model automatically. Just retry.
- **`gemini-2.5-flash` unavailable** — retired by the provider for this key; do not
  reinstate it. Keep `GEMINI_MODEL=gemini-3.6-flash`.
- **Mojibake on Windows console** — the CLI already forces UTF-8; if a terminal still
  garbles, use Windows Terminal or Git Bash.

## 6. Repo map (fast orientation)

```
desk/            application package (agents, tools, config, guardrails, ticket, ...)
data/courses.json  the ONLY source of course facts (FR-2) — edit it, answers change
tests/           pytest suite (network-free; scripted model double in tests/helpers/)
audit/           runtime JSONL: timeline, runs, traces (gitignored output)
example.env      template for .env — names only, never real keys
```

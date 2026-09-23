# Saylani Student Ops Desk

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

## 4. Check it's alive

```bash
uv run pytest
```
All tests green = good. (A missing key fails fast with a friendly message — that's
by design; redo step 3.)

## 5. Run the demo

```bash
# one-shot question in the terminal:
uv run python -m desk.cli --question "When is my A3 due?"

# or interactive:
uv run python -m desk.cli
```

Quick demo lines:
- **Off-topic refusal (FR-8):** `What's the weather in Karachi?` — refused instantly.
- **Course facts (FR-2):** `When is my A3 due?` — answered from `data/courses.json`.
- **Tier gating (FR-9a):** same question with `--tier regular` vs `--tier scholarship`.

Everything else (full FR map, troubleshooting, browser UI when it lands): `Agentguide.md`.

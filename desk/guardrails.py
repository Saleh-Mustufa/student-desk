"""FR-8 input guardrail — a ZERO-model-call off-topic tripwire.

The guardrail is a pure, local keyword check: no model object, no
``Runner`` call, no network anywhere in this module. It costs zero billed
tokens per turn. It is wired onto the Desk agent with
``run_in_parallel=False`` so the tripwire fires BEFORE the Desk's model is
ever called (openai-agents 0.22.3 runs ``run_in_parallel=True`` guardrails
concurrently with the first model turn, which would still bill tokens).
"""

from __future__ import annotations

import re
from typing import Any

from agents import Agent, GuardrailFunctionOutput, RunContextWrapper, input_guardrail

# Courteous refusal returned to the student when the guardrail trips: plain
# English, no student data, no tier words, one sentence.
OFF_TOPIC_REFUSAL = (
    "That question is a little outside my desk here — I can only help with "
    "your Saylani bootcamp, such as courses, assignments, class schedules "
    "and support tickets, so please ask me about those."
)

# Curated blocklist of clearly off-topic topics: (reported keyword, regex).
# Word-boundary matching, case-insensitive; plurals folded into one pattern.
OFF_TOPIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("weather", r"\bweather\b"),
        ("joke", r"\bjokes?\b"),
        ("election", r"\belections?\b"),
        ("politics", r"\bpolitics\b|\bpolitical\b|\bpoliticians?\b"),
        ("president", r"\bpresidents?\b"),
        ("prime minister", r"\bprime\s+minister\b"),
        ("recipe", r"\brecipes?\b"),
        ("cricket", r"\bcricket\b"),
        ("football", r"\bfootballs?\b"),
        ("movie", r"\bmovies?\b"),
        ("bollywood", r"\bbollywood\b"),
        ("song", r"\bsongs?\b"),
        ("stock market", r"\bstock\s+market\b"),
        ("horoscope", r"\bhoroscopes?\b"),
        ("astrology", r"\bastrology\b"),
        ("bitcoin", r"\bbitcoins?\b"),
        ("cryptocurrency", r"\bcryptocurrenc(?:y|ies)\b"),
    )
)


def _extract_last_user_text(run_input: Any) -> str | None:
    """Extract the text of the LAST user message from either SDK input shape.

    ``run_input`` is either a plain ``str`` or a list of input items (item
    dicts like ``{"role": "user", "content": ...}`` where ``content`` may be a
    string or a list of parts carrying ``"text"`` keys). Defensive: returns
    ``None`` when no text can be extracted.
    """
    if isinstance(run_input, str):
        return run_input
    if isinstance(run_input, list):
        for item in reversed(run_input):
            if not isinstance(item, dict) or item.get("role") != "user":
                continue
            content = item.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [
                    part["text"]
                    for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                ]
                if texts:
                    return " ".join(texts)
    return None


@input_guardrail(run_in_parallel=False)
async def off_topic_guardrail(
    ctx: RunContextWrapper[Any],
    agent: Agent[Any],
    input: str | list[Any],
) -> GuardrailFunctionOutput:
    """Trip on clearly off-topic questions BEFORE any model call (FR-8).

    Zero model calls by construction: a local regex scan of the last user
    message against ``OFF_TOPIC_PATTERNS`` — nothing else.
    """
    text = _extract_last_user_text(input)
    if text:
        for keyword, pattern in OFF_TOPIC_PATTERNS:
            if pattern.search(text):
                return GuardrailFunctionOutput(
                    output_info={"matched": keyword},
                    tripwire_triggered=True,
                )
    return GuardrailFunctionOutput(output_info=None, tripwire_triggered=False)

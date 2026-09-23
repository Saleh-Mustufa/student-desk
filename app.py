"""Student Ops Desk — the Chainlit front end (FR-12).

A deliberately thin shell over :mod:`desk.app_state`:

- ``@cl.on_chat_start`` validates the configuration and builds the agent +
  student profile **once** per browser session, storing them in
  ``cl.user_session`` — never per message (two windows are two sessions, so
  histories never mix).
- ``@cl.on_message`` only awaits the session run (``await session.send`` —
  fully async) and renders the answer: a structured ticket card
  for resolved conversations (FR-7), the polite refusal card for off-topic
  input (FR-8), friendly failure cards otherwise (NFR-1).
- ``ChainlitRunHooks`` extends the FR-10 run-level timeline with visible
  ``cl.Step`` traces of tool calls and handoffs.
- ``@cl.set_starters`` shows the three guided starter chips.

Run with: ``uv run chainlit run app.py``.
"""

from __future__ import annotations

import chainlit as cl

from desk.app_state import (
    STARTER_CHIPS,
    DeskSession,
    ticket_card,
    welcome_message,
)
from desk.errors import SETUP_FAILURE_INTRO, ConfigError, log_exception
from desk.guardrails import OFF_TOPIC_REFUSAL
from desk.hooks import DeskRunHooks, SpecialistAgentHooks
from desk.ticket import Ticket

APP_AUTHOR = "Student Ops Desk"


def _setup_failure_card() -> str:
    """The friendly startup-failure card (no traceback, no internals)."""
    return f"### ⚠️ Setup needed\n\n{SETUP_FAILURE_INTRO}"


class ChainlitRunHooks(DeskRunHooks):
    """FR-10 timeline plus visible cl.Step traces of tools and handoffs."""

    async def on_tool_start(self, context, agent, tool) -> None:
        await super().on_tool_start(context, agent, tool)
        async with cl.Step(name=f"🔧 {tool.name}", type="tool") as step:
            step.output = "Reading the course catalogue…"

    async def on_tool_end(self, context, agent, tool, result) -> None:
        await super().on_tool_end(context, agent, tool, result)
        async with cl.Step(name=f"🔧 {tool.name} — done", type="tool") as step:
            step.output = str(result)[:500] or "(no output)"

    async def on_handoff(self, context, from_agent, to_agent) -> None:
        await super().on_handoff(context, from_agent, to_agent)
        async with cl.Step(
            name=f"🤝 transferred to {to_agent.name}", type="run"
        ) as step:
            step.output = (
                f"{from_agent.name} handed the conversation to "
                f"{to_agent.name}, who answers from here."
            )


@cl.on_chat_start
async def on_chat_start() -> None:
    """Build the agent + profile ONCE, store them in the session (FR-12)."""
    try:
        session = DeskSession.build(assignments_hooks=SpecialistAgentHooks())
    except ConfigError as exc:
        log_exception(exc)
        await cl.Message(content=_setup_failure_card(), author=APP_AUTHOR).send()
        return

    # FR-10 + FR-12: the run-level timeline also emits visible steps.
    session.run_hooks = ChainlitRunHooks()
    cl.user_session.set("desk_session", session)
    await cl.Message(
        content=welcome_message(session.profile), author=APP_AUTHOR
    ).send()


@cl.set_starters
async def set_starters():
    """The three guided starter chips (T15)."""
    return [
        cl.Starter(label=label, message=message) for label, message in STARTER_CHIPS
    ]


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """One turn: await the run, render the answer or the right card."""
    session: DeskSession | None = cl.user_session.get("desk_session")
    if session is None:
        # The session never started cleanly — the setup card, again.
        await cl.Message(content=_setup_failure_card(), author=APP_AUTHOR).send()
        return

    answer = await session.send(message.content)

    if isinstance(answer, Ticket):
        content = ticket_card(answer)
    elif answer == OFF_TOPIC_REFUSAL:
        content = f"### 🙂 Just so you know\n\n{OFF_TOPIC_REFUSAL}"
    else:
        content = str(answer)

    await cl.Message(content=content, author=APP_AUTHOR).send()

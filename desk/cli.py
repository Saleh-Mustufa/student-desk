"""Async CLI entry point for the Student Ops Desk (FR-1).

One process = one student session: the flags build a ``StudentProfile``, the
resolved system prompt is printed before any model call (FR-4 — the preview is
the real prompt, not a paraphrase), then either a one-shot ``--question`` is
answered or an interactive REPL runs until Ctrl+C/EOF.

Failure modes (NFR-1): startup problems surface as the friendly
``user_message`` sentence with exit code 1 — never a traceback on the console;
the full traceback goes only to the server-side logger (a ``NullHandler``
keeps Python's logging lastResort handler from spraying stderr when no real
handler is configured yet).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from collections.abc import Callable

from agents import (
    Agent,
    InputGuardrailTripwireTriggered,
    MaxTurnsExceeded,
    Runner,
    trace,
)

from desk.agents import build_desk_agent
from desk.app_state import ticket_card
from desk.config import load_config
from desk.errors import LOGGER_NAME, TURN_CEILING_MESSAGE, ConfigError, log_exception, user_message
from desk.guardrails import OFF_TOPIC_REFUSAL
from desk.hooks import DeskRunHooks, SpecialistAgentHooks
from desk.profile import StudentProfile
from desk.prompt_builder import preview_prompt
from desk.runner import StampingRunner
from desk.ticket import Ticket
from desk.tracing import install_jsonl_tracing

BANNER = "Saylani Student Ops Desk — ask about your Saylani bootcamp, or press Ctrl+C to exit."
PROMPT_LABEL = "--- Resolved system prompt (rebuilt per turn from the profile; printed before any model call) ---"

# FR-9c headroom: a resolved ticket needs classification + handoff + tool
# round-trip + ticket turns; 10 turns is the explicit ceiling until the full
# handoff graph lands.
MAX_TURNS = 10


def _render(answer: Ticket | str) -> str:
    """Typed Tickets render as the structured card; sentences print as-is."""
    return ticket_card(answer) if isinstance(answer, Ticket) else answer


def _default_agent_factory() -> Agent[StudentProfile]:
    """Build the Desk with the FR-10 close-watch on exactly one specialist."""
    return build_desk_agent(assignments_hooks=SpecialistAgentHooks())


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252; answers contain en dashes and more."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass  # e.g. captured or redirected streams without reconfigure()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the session flags; a missing ``--question`` means interactive REPL."""
    parser = argparse.ArgumentParser(
        prog="desk.cli",
        description="Saylani Student Ops Desk — terminal front desk for one student session.",
    )
    parser.add_argument("--name", default="Student", help="student's name (default: Student)")
    parser.add_argument("--roll-no", default="S-2026-001", help="roll number (default: S-2026-001)")
    parser.add_argument(
        "--course-id", default="agentic-ai-w4", help="enrolled course id (default: agentic-ai-w4)"
    )
    parser.add_argument(
        "--tier",
        choices=["regular", "scholarship"],
        default="regular",
        help="fee tier (default: regular)",
    )
    parser.add_argument(
        "--open-tickets", type=int, default=0, help="open support tickets (default: 0)"
    )
    parser.add_argument(
        "--question",
        default=None,
        help="one-shot question to answer, then exit; omit it for the interactive REPL",
    )
    return parser.parse_args(argv)


async def run_turn(
    agent: Agent[StudentProfile],
    profile: StudentProfile,
    history: list,
    question: str,
    run_hooks: DeskRunHooks | None = None,
) -> Ticket | str:
    """Run one Desk turn: append the question, run, keep the grown conversation.

    ``history`` is replaced with ``result.to_input_list()`` after the run, so it
    always holds the full user/assistant conversation exactly once — the
    next turn's memory. With ``output_type=Ticket`` on the Desk (FR-7) the
    answer is a typed ``Ticket``; the off-topic refusal (FR-8) stays a
    courteous sentence. ``run_hooks`` (FR-10) records the run-level audit
    timeline across every agent.
    """
    history.append({"role": "user", "content": question})
    try:
        result = await Runner.run(
            agent, history, context=profile, max_turns=MAX_TURNS, hooks=run_hooks
        )
    except InputGuardrailTripwireTriggered:
        # FR-8: the zero-model-call off-topic guardrail tripped before the
        # Desk's model ran. Answer courteously and keep the REPL alive — this
        # is a normal turn outcome, not an error for main()'s handler.
        return OFF_TOPIC_REFUSAL
    except MaxTurnsExceeded:
        # FR-9c: the deliberate ceiling fired instead of the run circling.
        # Report it in plain language and keep the REPL alive.
        return TURN_CEILING_MESSAGE
    history[:] = result.to_input_list()
    return result.final_output


async def main(
    argv: list[str] | None = None, agent_factory=_default_agent_factory
) -> int:
    """One student session. Returns the process exit code.

    The default agent factory attaches the FR-10 agent-level close-watch to
    exactly one specialist; this session also owns one FR-10 run-level
    timeline that every turn appends to.
    """
    _force_utf8_stdout()

    # Tracebacks must never reach the console: with no handler configured,
    # Python's logging lastResort would print them to stderr — stop that.
    logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())

    args = parse_args(argv)
    profile = StudentProfile(
        name=args.name,
        roll_no=args.roll_no,
        course_id=args.course_id,
        tier=args.tier,
        open_tickets=args.open_tickets,
    )

    try:
        # Fail fast on a missing key — before any agent or model is built.
        load_config()
    except ConfigError as exc:
        log_exception(exc)
        print(user_message(exc))
        return 1

    try:
        agent = agent_factory()
    except Exception as exc:
        log_exception(exc)
        print(user_message(exc))
        return 1

    print(BANNER)
    print(PROMPT_LABEL)
    print(preview_prompt(profile))
    print()

    # FR-13: tracing ON, exported to our durable local JSONL sink — the
    # built-in platform exporter (which would 401 on this key) receives
    # nothing. One conversation = one trace: the whole session below shares
    # one named trace id.
    install_jsonl_tracing()

    # FR-11: the custom runner is registered ONCE at startup — every run in
    # this process is wrapped from here on, with no agent file touched.
    from agents.run import set_default_agent_runner

    set_default_agent_runner(StampingRunner())

    # FR-10: one ordered timeline for the whole session, across every agent.
    run_hooks = DeskRunHooks()

    try:
        with trace(workflow_name=f"student-ops-desk:{uuid.uuid4().hex}"):
            if args.question is not None:
                print(
                    _render(
                        await run_turn(
                            agent, profile, [], args.question, run_hooks=run_hooks
                        )
                    )
                )
                return 0

            print("Interactive session — type a question, or press Ctrl+C to exit.")
            history: list = []  # one conversation: memory carried across REPL turns
            while True:
                try:
                    question = input("You: ")
                except EOFError:
                    print("\nGoodbye — come back any time.")
                    return 0
                except KeyboardInterrupt:
                    print("\nGoodbye — come back any time.")
                    return 0
                answer = await run_turn(
                    agent, profile, history, question, run_hooks=run_hooks
                )
                print(f"student> {_render(answer)}")
    except Exception as exc:
        log_exception(exc)
        print(user_message(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

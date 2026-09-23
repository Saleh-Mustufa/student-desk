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
from collections.abc import Callable

from agents import Agent, Runner

from desk.agents import build_desk_agent
from desk.config import load_config
from desk.errors import LOGGER_NAME, ConfigError, log_exception, user_message
from desk.profile import StudentProfile
from desk.prompt_builder import preview_prompt

BANNER = "Saylani Student Ops Desk — ask about your Saylani bootcamp, or press Ctrl+C to exit."
PROMPT_LABEL = "--- Resolved system prompt (rebuilt per turn from the profile; printed before any model call) ---"

# FR-9c headroom: a resolved ticket needs classification + handoff + tool
# round-trip + ticket turns; 10 turns is the explicit ceiling until the full
# handoff graph lands.
MAX_TURNS = 10


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
    agent: Agent[StudentProfile], profile: StudentProfile, history: list, question: str
) -> str:
    """Run one Desk turn: append the question, run, keep the grown conversation.

    ``history`` is replaced with ``result.to_input_list()`` after the run, so it
    always holds the full user/assistant conversation exactly once — the
    next turn's memory.
    """
    history.append({"role": "user", "content": question})
    result = await Runner.run(agent, history, context=profile, max_turns=MAX_TURNS)
    history[:] = result.to_input_list()
    return result.final_output


async def main(argv: list[str] | None = None, agent_factory=build_desk_agent) -> int:
    """One student session. Returns the process exit code."""
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

    try:
        if args.question is not None:
            print(await run_turn(agent, profile, [], args.question))
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
            print(f"student> {await run_turn(agent, profile, history, question)}")
    except Exception as exc:
        log_exception(exc)
        print(user_message(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

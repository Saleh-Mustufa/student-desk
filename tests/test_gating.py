"""Task 10 — tool gating, close_ticket stopping rule, turn ceiling (FR-9).

Three separate controls, all proven network-free through the ScriptedModel:
(a) ``scholarship_benefits`` is ABSENT from the tool set offered to the model
    for regular-tier students and present for scholarship students — the tier
    is read from context only, never from any prompt or schema;
(b) ``close_ticket`` ends the run the moment it is called and its raw output —
    a ``Ticket`` instance — becomes ``result.final_output`` (FR-7 + FR-9b);
(c) ``max_turns=10`` is the deliberate ceiling and ``MaxTurnsExceeded`` is
    caught in the CLI and reported in plain language, REPL still alive.
"""

import inspect
import json
import sys
from pathlib import Path

from agents import Agent, Runner, RunContextWrapper, set_tracing_disabled

from desk.agents import build_desk_agent
from desk.cli import MAX_TURNS, run_turn
from desk.errors import TURN_CEILING_MESSAGE
from desk.profile import StudentProfile
from desk.tools import (
    SCHOLARSHIP_UNPUBLISHED,
    close_ticket,
    scholarship_benefits,
)
from desk.ticket import Ticket

# Imported as ``helpers.*`` (not ``tests.helpers.*``): the ``literalai``
# dependency ships a ``tests`` package into site-packages that shadows the
# project's namespace ``tests`` package on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers.scripted_model import FunctionCallReply, ScriptedModel  # noqa: E402

set_tracing_disabled(True)

ADMIN_TICKET = {
    "category": "admin",
    "summary": "Class runs Mon-Thu, 7-9pm.",
    "next_step": "Attend the next session on Monday evening.",
    "resolved": True,
    "escalate": False,
}


def make_profile(**overrides) -> StudentProfile:
    values = {
        "name": "Ayesha",
        "roll_no": "S-2026-042",
        "course_id": "agentic-ai-w4",
    }
    values.update(overrides)
    return StudentProfile(**values)


def offered_tool_names(model: ScriptedModel) -> list[str]:
    """The tool names the model actually SAW on the run's first model call."""
    return [tool.name for tool in model.calls[0].tools]


# --- FR-9a: the scholarship tool is gated by tier, ABSENT not refused ---------


async def test_scholarship_tool_absent_for_regular_tier_and_present_for_scholarship():
    regular_model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])
    await Runner.run(
        build_desk_agent(regular_model),
        "When is class?",
        context=make_profile(),
        max_turns=MAX_TURNS,
    )
    scholarship_model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])
    await Runner.run(
        build_desk_agent(scholarship_model),
        "When is class?",
        context=make_profile(tier="scholarship"),
        max_turns=MAX_TURNS,
    )

    # The same question, two tiers: the model is OFFERED a different tool set.
    assert "scholarship_benefits" not in offered_tool_names(regular_model)
    assert "scholarship_benefits" in offered_tool_names(scholarship_model)


async def test_gating_reads_the_tier_from_context_only():
    is_enabled = scholarship_benefits.is_enabled
    assert callable(is_enabled)

    probe = Agent(name="probe")
    regular = is_enabled(RunContextWrapper(context=make_profile()), probe)
    scholarship = is_enabled(RunContextWrapper(context=make_profile(tier="scholarship")), probe)
    if inspect.isawaitable(regular):
        regular = await regular
    if inspect.isawaitable(scholarship):
        scholarship = await scholarship

    assert regular is False
    assert scholarship is True


async def test_scholarship_tool_returns_benefit_lines_for_a_known_course():
    model = ScriptedModel(
        replies=[
            FunctionCallReply(name="scholarship_benefits"),
            json.dumps(ADMIN_TICKET),
        ]
    )
    result = await Runner.run(
        build_desk_agent(model),
        "What are my scholarship benefits?",
        context=make_profile(tier="scholarship"),
        max_turns=MAX_TURNS,
    )

    outputs = [
        item.output
        for item in result.new_items
        if type(item).__name__ == "ToolCallOutputItem"
    ]
    # File-backed benefits (FR-2): the lines come from courses.json.
    assert len(outputs) == 1
    assert "Full tuition waiver" in outputs[0]
    assert "Certification exam fee" in outputs[0]


async def test_scholarship_tool_unknown_course_returns_sentence_never_raises():
    model = ScriptedModel(
        replies=[
            FunctionCallReply(name="scholarship_benefits"),
            json.dumps(ADMIN_TICKET),
        ]
    )
    result = await Runner.run(
        build_desk_agent(model),
        "What are my scholarship benefits?",
        context=make_profile(tier="scholarship", course_id="ghost-course"),
        max_turns=MAX_TURNS,
    )

    # NFR-4: bad data becomes the exact model-actionable sentence.
    outputs = [
        item.output
        for item in result.new_items
        if type(item).__name__ == "ToolCallOutputItem"
    ]
    assert outputs == [SCHOLARSHIP_UNPUBLISHED]


# --- FR-9b: close_ticket is a stopping rule whose output IS the ticket --------


def test_desk_declares_the_stopping_rule():
    agent = build_desk_agent(ScriptedModel(replies=[]))

    assert agent.tool_use_behavior == {"stop_at_tool_names": ["close_ticket"]}
    assert "close_ticket" in [tool.name for tool in agent.tools]


async def test_close_ticket_ends_the_run_instantly_ticket_is_final_output():
    ticket_args = dict(ADMIN_TICKET)
    model = ScriptedModel(
        replies=[
            FunctionCallReply(
                name="close_ticket", arguments=json.dumps(ticket_args)
            ),
        ]
    )
    profile = make_profile()

    result = await Runner.run(
        build_desk_agent(model),
        "When is class?",
        context=profile,
        max_turns=MAX_TURNS,
    )

    # FR-7 + FR-9b together: the tool's raw output — a real Ticket instance —
    # is the run's final output, exactly the declared type.
    assert type(result.final_output) is Ticket
    assert result.final_output.summary == ADMIN_TICKET["summary"]
    assert result.final_output.resolved is True
    assert result.final_output.escalate is False
    # Instant stop: exactly ONE model call — the run did not loop back to the
    # LLM after the tool fired.
    assert len(model.calls) == 1
    assert result.last_agent.name == "Student Ops Desk"


# --- FR-9c: the turn ceiling is caught and reported in plain language --------


def test_turn_ceiling_is_the_defended_number_ten():
    assert MAX_TURNS == 10


async def test_max_turns_exceeded_is_caught_and_reported_in_plain_language():
    model = ScriptedModel(
        replies=[FunctionCallReply(name="list_courses")] * 12
    )
    profile = make_profile()
    history: list = []

    answer = await run_turn(
        build_desk_agent(model), profile, history, "list everything, forever"
    )

    # No exception escaped run_turn; the REPL stays alive with a plain,
    # courteous message that names what happened and what to do next.
    assert answer == TURN_CEILING_MESSAGE
    assert "turn" in answer.lower()
    assert "Traceback" not in answer

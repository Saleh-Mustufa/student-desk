"""Tasks 5 + 8 — Desk assembly, specialists via clone(), handoffs (FR-1, FR-5).

Every run goes through the ScriptedModel (agent-level ``model=`` injection) —
no test ever touches the network or the project's real ``.env``. Tracing is
disabled for the suite: the default exporter would only attempt an OpenAI
platform upload and 401; the app keeps tracing ON for FR-13.

The Desk carries ``output_type=Ticket`` (FR-7), so scripted final replies are
valid Ticket JSON and every ``run_turn`` answer is asserted as a typed Ticket.
"""

import inspect
import json
import logging
import sys
from pathlib import Path

import pytest
from agents import Runner, set_tracing_disabled

from desk.agents import build_base_specialist, build_desk_agent, build_specialists
from desk.cli import PROMPT_LABEL, main, parse_args, run_turn
from desk.errors import LOGGER_NAME
from desk.model_config import FailoverModel, resolve_catalog
from desk.profile import StudentProfile
from desk.prompt_builder import (
    ASSIGNMENTS_HANDOFF_TOOL,
    ASSIGNMENTS_SPECIALIST_NAME,
    CAREERS_HANDOFF_TOOL,
    CAREERS_SPECIALIST_NAME,
    preview_prompt,
)
from desk.ticket import Ticket
from desk.tools import get_assignment, get_course_details, list_courses

# Imported as ``helpers.*`` (not ``tests.helpers.*``): the ``literalai``
# dependency ships a ``tests`` package into site-packages that shadows the
# project's namespace ``tests`` package on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers.scripted_model import FunctionCallReply, ScriptedModel  # noqa: E402

set_tracing_disabled(True)

ADMIN_TICKET = {
    "category": "admin",
    "summary": "Class runs Mon-Thu, 7-9pm - see you at class!",
    "next_step": "Attend the next session on Monday evening.",
    "resolved": True,
    "escalate": False,
}
ASSIGNMENT_TICKET = {
    "category": "assignment",
    "summary": "A3 is due on 2026-10-02.",
    "next_step": "Submit A3 on the portal before 2026-10-02.",
    "resolved": True,
    "escalate": False,
}
CAREER_TICKET = {
    "category": "career",
    "summary": "AI agent developer is a fit next step.",
    "next_step": "Book a mentor session to plan the roadmap.",
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


# --- FR-1: agent wiring — the Gemini model is declared ON the agent ----------


def test_build_desk_agent_carries_injected_model_and_exact_wiring():
    model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])

    agent = build_desk_agent(model)

    assert agent.model is model
    assert agent.name == "Student Ops Desk"
    # Dynamic instructions: the two-parameter callable, never a static string.
    assert callable(agent.instructions)
    assert agent.tools == [list_courses, get_course_details]
    assert agent.model_settings.temperature == 0.2
    assert agent.model_settings.max_tokens == 1000
    # FR-5: handoffs wired to the two cloned specialists…
    assert [handoff_agent.name for handoff_agent in agent.handoffs] == [
        ASSIGNMENTS_SPECIALIST_NAME,
        CAREERS_SPECIALIST_NAME,
    ]
    # …and the FR-7 typed output deferred from Task 6 is wired now.
    assert agent.output_type is Ticket


def test_build_desk_agent_without_model_builds_gemini_model_from_config(
    tmp_path, monkeypatch
):
    # Hermetic: a throwaway .env in a tmp dir, real env vars cleared.
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=fake-key-for-wiring-test\n", encoding="utf-8"
    )
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "GEMINI_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)

    agent = build_desk_agent()

    # Model selection is the user-approved failover catalog (desk/model_config.py):
    # the agent receives the wrapper at agent level; its head is the catalog head.
    assert isinstance(agent.model, FailoverModel)
    assert agent.model.active_model_name == resolve_catalog({})[0]
    # The specialists share the Desk's model object — never a second build.
    assert agent.handoffs[0].model is agent.model
    assert agent.handoffs[1].model is agent.model


# --- FR-5: one base, two clones — only name/instructions/settings differ ------


def test_base_specialist_is_the_template_with_deliberate_settings():
    model = ScriptedModel(replies=[])

    base = build_base_specialist(model)

    assert base.model is model
    assert base.model_settings.temperature == 0.3
    assert base.model_settings.max_tokens == 800
    assert base.model_settings.tool_choice == "auto"
    # The typed output type is declared once on the base; clones inherit it.
    assert base.output_type is Ticket
    # Reference tool list — the widest of the two specialists.
    assert base.tools == [list_courses, get_course_details, get_assignment]


def test_both_specialists_are_clones_differing_only_in_allowed_fields():
    model = ScriptedModel(replies=[])

    assignments, careers = build_specialists(model)

    # Neither clone restates ``model=`` — both inherit the base's model object.
    assert assignments.model is model
    assert careers.model is model
    # Exactly the fields the brief allows to differ: name, instructions, settings.
    assert assignments.name == ASSIGNMENTS_SPECIALIST_NAME == "Assignments Specialist"
    assert careers.name == CAREERS_SPECIALIST_NAME == "Careers Specialist"
    assert isinstance(assignments.instructions, str)
    assert isinstance(careers.instructions, str)
    assert assignments.instructions != careers.instructions
    # Deliberate temperature split: cold and factual vs warmer (FR-5).
    assert assignments.model_settings.temperature == 0.1
    assert assignments.model_settings.max_tokens == 800
    assert careers.model_settings.temperature == 0.7
    assert careers.model_settings.max_tokens == 800
    # The typed output type is inherited, never restated.
    assert assignments.output_type is Ticket
    assert careers.output_type is Ticket


def test_clones_receive_fresh_tool_lists_not_the_base_list():
    model = ScriptedModel(replies=[])
    base = build_base_specialist(model)

    assignments, careers = build_specialists(model)

    # Exact per-specialist sets from plan.md §2…
    assert assignments.tools == [list_courses, get_course_details, get_assignment]
    assert careers.tools == [list_courses, get_course_details]
    # …each held in a FRESH list object (clone()'s shallow-copy trap: passing
    # the base's list would let specialists grow each other's tools).
    assert assignments.tools is not base.tools
    assert careers.tools is not base.tools
    assert assignments.tools is not careers.tools


# --- FR-5: handoff routing — generated tool names match the shared constants --


async def test_generated_handoff_tool_names_match_routing_constants_in_the_prompt():
    model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])
    agent = build_desk_agent(model)
    profile = make_profile()

    await Runner.run(agent, "When is class?", context=profile, max_turns=10)

    call = model.calls[0]
    # The generated handoff tool names are exactly the constants the dynamic
    # prompt's routing text references (renaming a specialist breaks this pin).
    assert [handoff.tool_name for handoff in call.handoffs] == [
        ASSIGNMENTS_HANDOFF_TOOL,
        CAREERS_HANDOFF_TOOL,
    ]
    assert ASSIGNMENTS_HANDOFF_TOOL == "transfer_to_assignments_specialist"
    assert CAREERS_HANDOFF_TOOL == "transfer_to_careers_specialist"
    # The routing text names both transfer tools, so the model can route.
    assert ASSIGNMENTS_HANDOFF_TOOL in call.system_instructions
    assert CAREERS_HANDOFF_TOOL in call.system_instructions


# --- FR-5: scripted end-to-end handoffs — the specialist answers --------------


async def test_assignment_question_is_answered_by_the_assignments_specialist():


    model = ScriptedModel(
        replies=[
            FunctionCallReply(name=ASSIGNMENTS_HANDOFF_TOOL),
            json.dumps(ASSIGNMENT_TICKET),
        ]
    )
    agent = build_desk_agent(model)
    profile = make_profile()

    result = await Runner.run(agent, "When is my A3 due?", context=profile, max_turns=10)

    # The specialist, not the Desk, answers.
    assert result.last_agent.name == ASSIGNMENTS_SPECIALIST_NAME
    assert type(result.final_output) is Ticket
    assert result.final_output.category == "assignment"
    # The handoff appears in the run's items, in both directions.
    item_types = [type(item).__name__ for item in result.new_items]
    assert "HandoffCallItem" in item_types
    assert "HandoffOutputItem" in item_types
    # Two model calls: the Desk classified, then the specialist answered.
    assert len(model.calls) == 2
    # The specialist's static instructions (not the Desk's dynamic builder).
    assert model.calls[1].system_instructions.startswith(
        "You are the assignments specialist"
    )


async def test_career_question_is_answered_by_the_careers_specialist():


    model = ScriptedModel(
        replies=[
            FunctionCallReply(name=CAREERS_HANDOFF_TOOL),
            json.dumps(CAREER_TICKET),
        ]
    )
    agent = build_desk_agent(model)
    profile = make_profile()

    result = await Runner.run(agent, "What career paths open after this bootcamp?", context=profile, max_turns=10)

    assert result.last_agent.name == CAREERS_SPECIALIST_NAME
    assert type(result.final_output) is Ticket
    assert result.final_output.category == "career"
    assert len(model.calls) == 2


async def test_admin_question_is_answered_by_the_desk_itself_without_handoff():


    model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])
    agent = build_desk_agent(model)
    profile = make_profile()

    result = await Runner.run(agent, "When is class?", context=profile, max_turns=10)

    # No transfer: the Desk keeps admin questions and answers in its own voice.
    assert result.last_agent.name == "Student Ops Desk"
    assert type(result.final_output) is Ticket
    assert result.final_output.category == "admin"
    assert len(model.calls) == 1


# --- FR-1/FR-7: run_turn — scripted end-to-end turn through the SDK runner ----


async def test_run_turn_returns_typed_ticket_and_grows_history():
    model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])
    agent = build_desk_agent(model)
    profile = make_profile()
    history: list = []

    answer = await run_turn(agent, profile, history, "When is class?")

    assert type(answer) is Ticket
    assert answer.category == "admin"
    assert answer.resolved is True
    # to_input_list: the user message plus the assistant reply — no duplicates.
    assert [item["role"] for item in history] == ["user", "assistant"]


async def test_run_turn_second_turn_keeps_memory_without_duplicating_history():
    model = ScriptedModel(
        replies=[json.dumps(ADMIN_TICKET), json.dumps(ASSIGNMENT_TICKET)]
    )
    agent = build_desk_agent(model)
    profile = make_profile()
    history: list = []

    await run_turn(agent, profile, history, "first question")
    await run_turn(agent, profile, history, "second question")

    assert [item["role"] for item in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    # The second model call saw the whole prior conversation plus the new turn.
    assert len(model.calls[1].input) == 3


async def test_run_passes_dynamic_system_prompt_tools_and_handoffs_to_model():
    model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])
    agent = build_desk_agent(model)
    profile = make_profile()
    history: list = []

    await run_turn(agent, profile, history, "hello")

    call = model.calls[0]
    # The dynamic instructions were resolved against this run's profile…
    assert call.system_instructions == preview_prompt(profile)
    assert call.system_instructions.startswith(
        "You are the Student Ops Desk assistant, currently helping Ayesha."
    )
    # …exactly the two catalogue tools are offered as function tools…
    assert [tool.name for tool in call.tools] == [
        "list_courses",
        "get_course_details",
    ]
    # …and the two handoff transfer tools are offered separately.
    assert [handoff.tool_name for handoff in call.handoffs] == [
        ASSIGNMENTS_HANDOFF_TOOL,
        CAREERS_HANDOFF_TOOL,
    ]
    # Agent-level settings reached the model call (cost ceiling, NFR-2).
    assert call.model_settings.temperature == 0.2
    assert call.model_settings.max_tokens == 1000


# --- FR-1: CLI argument parsing ----------------------------------------------


def test_parse_args_applies_the_documented_defaults():
    args = parse_args([])

    assert args.name == "Student"
    assert args.roll_no == "S-2026-001"
    assert args.course_id == "agentic-ai-w4"
    assert args.tier == "regular"
    assert args.open_tickets == 0
    assert args.question is None


def test_parse_args_accepts_all_flags_and_both_tiers():
    args = parse_args(
        [
            "--name", "Bilal",
            "--roll-no", "S-2026-009",
            "--course-id", "data-analytics-w2",
            "--tier", "scholarship",
            "--open-tickets", "2",
            "--question", "When is class?",
        ]
    )

    assert args.name == "Bilal"
    assert args.course_id == "data-analytics-w2"
    assert args.tier == "scholarship"
    assert args.open_tickets == 2
    assert args.question == "When is class?"


def test_parse_args_rejects_an_unknown_tier(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--tier", "gold"])

    assert "invalid choice" in capsys.readouterr().err


# --- NFR-1: async entry point shape ------------------------------------------


def test_main_is_async_and_module_entry_is_asyncio_run_of_main():
    import desk.cli

    assert inspect.iscoroutinefunction(desk.cli.main)
    source = Path(desk.cli.__file__).read_text(encoding="utf-8")
    assert "asyncio.run(main())" in source
    assert "run_sync" not in source


# --- NFR-1: main() with a missing key fails cleanly, before building anything


async def test_main_missing_key_prints_friendly_message_returns_1_and_builds_nothing(
    tmp_path, monkeypatch, capfd
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env reachable from here

    def factory_must_not_run():
        raise AssertionError("agent must not be built before config is validated")

    code = await main(["--question", "When is class?"], agent_factory=factory_must_not_run)

    captured = capfd.readouterr()
    assert code == 1
    assert "OPENAI_API_KEY" in captured.out
    assert ".env" in captured.out
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


async def test_main_routes_the_config_traceback_to_the_server_side_logger_only(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    # main() attaches the server-side handler before anything can fail, so the
    # logging lastResort handler can never spray the traceback onto stderr.
    logging.getLogger(LOGGER_NAME).handlers.clear()
    await main(["--question", "When is class?"])
    handlers = logging.getLogger(LOGGER_NAME).handlers
    assert any(isinstance(h, logging.NullHandler) for h in handlers)


# --- FR-1: main() one-shot — friendly banner, prompt preview, answer, exit 0 --


async def test_main_one_shot_prints_preview_then_answer_and_returns_0(
    tmp_path, monkeypatch, capfd
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
    monkeypatch.chdir(tmp_path)  # no real .env is read

    model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])
    agent = build_desk_agent(model)
    builds: list[int] = []

    def factory():
        builds.append(1)
        return agent

    code = await main(
        ["--question", "When is class?", "--name", "Ayesha"], agent_factory=factory
    )

    captured = capfd.readouterr()
    assert code == 0
    # The typed ticket's content reaches the student, not a raw object dump.
    assert ADMIN_TICKET["summary"] in captured.out
    assert ADMIN_TICKET["next_step"] in captured.out
    # The resolved system prompt was printed before any model call (FR-4)…
    assert "currently helping Ayesha" in captured.out
    assert captured.out.index(PROMPT_LABEL) < captured.out.index(ADMIN_TICKET["summary"])
    # …with exactly one agent build and one model call — no network.
    assert builds == [1]
    assert len(model.calls) == 1


# --- FR-1: interactive REPL — one conversation history across turns ----------


class _PipedInput:
    """Replays piped lines, then raises EOFError like a closed stdin."""

    def __init__(self, lines):
        self._lines = list(lines)

    def __call__(self, prompt=""):
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


async def test_main_repl_answers_each_question_and_keeps_one_conversation(
    tmp_path, monkeypatch, capfd
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", _PipedInput(["first question", "second question"]))

    model = ScriptedModel(
        replies=[json.dumps(ADMIN_TICKET), json.dumps(ASSIGNMENT_TICKET)]
    )
    agent = build_desk_agent(model)

    code = await main([], agent_factory=lambda: agent)

    captured = capfd.readouterr()
    assert code == 0
    assert ADMIN_TICKET["summary"] in captured.out
    assert ASSIGNMENT_TICKET["summary"] in captured.out
    assert "Goodbye" in captured.out
    # Second turn saw the full prior conversation plus the new question.
    assert len(model.calls) == 2
    assert len(model.calls[1].input) == 3


# --- Windows console safety ----------------------------------------------------


def test_utf8_stdout_reconfigure_is_safe_on_a_captured_console():
    import desk.cli

    # Under pytest, sys.stdout is a capture object without reconfigure() on
    # some platforms — the guarded helper must not raise, whatever the stream.
    desk.cli._force_utf8_stdout()

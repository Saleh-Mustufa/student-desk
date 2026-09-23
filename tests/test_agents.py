"""Task 5 — Desk agent assembly + async CLI entry (FR-1).

Every run goes through the ScriptedModel (agent-level ``model=`` injection) —
no test ever touches the network or the project's real ``.env``. Tracing is
disabled for the suite: the default exporter would only attempt an OpenAI
platform upload and 401; the app keeps tracing ON for FR-13.
"""

import inspect
import logging
import sys
from pathlib import Path

import pytest
from agents import OpenAIChatCompletionsModel, set_tracing_disabled

from desk.agents import build_desk_agent
from desk.cli import PROMPT_LABEL, main, parse_args, run_turn
from desk.errors import LOGGER_NAME
from desk.profile import StudentProfile
from desk.prompt_builder import preview_prompt
from desk.tools import get_course_details, list_courses

# Imported as ``helpers.*`` (not ``tests.helpers.*``): the ``literalai``
# dependency ships a ``tests`` package into site-packages that shadows the
# project's namespace ``tests`` package on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers.scripted_model import ScriptedModel  # noqa: E402

set_tracing_disabled(True)

ANSWER = "Your first assignment is Python and prompt foundations, due 2026-09-18."


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
    model = ScriptedModel(replies=[ANSWER])

    agent = build_desk_agent(model)

    assert agent.model is model
    assert agent.name == "Student Ops Desk"
    # Dynamic instructions: the two-parameter callable, never a static string.
    assert callable(agent.instructions)
    assert agent.tools == [list_courses, get_course_details]
    assert agent.model_settings.temperature == 0.2
    assert agent.model_settings.max_tokens == 1000
    # Nothing pre-built for later tasks: no handoffs, no structured output.
    assert agent.handoffs == []
    assert agent.output_type is None


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

    assert isinstance(agent.model, OpenAIChatCompletionsModel)
    assert agent.model.model == "gemini-2.5-flash"


# --- FR-1: run_turn — scripted end-to-end turn through the SDK runner --------


async def test_run_turn_returns_scripted_answer_and_grows_history():
    model = ScriptedModel(replies=[ANSWER])
    agent = build_desk_agent(model)
    profile = make_profile()
    history: list = []

    answer = await run_turn(agent, profile, history, "What is my first assignment?")

    assert answer == ANSWER
    # to_input_list: the user message plus the assistant reply — no duplicates.
    assert [item["role"] for item in history] == ["user", "assistant"]


async def test_run_turn_second_turn_keeps_memory_without_duplicating_history():
    model = ScriptedModel(replies=["first answer", "second answer"])
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


async def test_run_passes_dynamic_system_prompt_and_exactly_two_tools_to_model():
    model = ScriptedModel(replies=[ANSWER])
    agent = build_desk_agent(model)
    profile = make_profile()
    history: list = []

    await run_turn(agent, profile, history, "hello")

    call = model.calls[0]
    # The dynamic instructions were resolved against this run's profile.
    assert call.system_instructions == preview_prompt(profile)
    assert call.system_instructions.startswith(
        "You are the Student Ops Desk assistant, currently helping Ayesha."
    )
    # Exactly the two catalogue tools offered — nothing from later tasks.
    assert [tool.name for tool in call.tools] == [
        "list_courses",
        "get_course_details",
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

    model = ScriptedModel(replies=["Mon-Thu, 7-9pm - see you at class!"])
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
    assert "Mon-Thu, 7-9pm - see you at class!" in captured.out
    # The resolved system prompt was printed before any model call (FR-4)…
    assert "currently helping Ayesha" in captured.out
    assert captured.out.index(PROMPT_LABEL) < captured.out.index("Mon-Thu")
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

    model = ScriptedModel(replies=["first answer", "second answer"])
    agent = build_desk_agent(model)

    code = await main([], agent_factory=lambda: agent)

    captured = capfd.readouterr()
    assert code == 0
    assert "first answer" in captured.out
    assert "second answer" in captured.out
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

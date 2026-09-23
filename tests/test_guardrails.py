"""Task 7 — FR-8 zero-model-call off-topic input guardrail.

Unit tests call the guardrail function directly (no runner, no model);
integration tests run the ScriptedModel through the SDK runner and prove the
tripwire fires BEFORE the Desk's model is ever called. No test touches the
network or the project's real ``.env``.
"""

import sys
from pathlib import Path

import pytest
from agents import (
    Agent,
    GuardrailFunctionOutput,
    InputGuardrailTripwireTriggered,
    RunContextWrapper,
    Runner,
    set_tracing_disabled,
)

from desk.agents import build_desk_agent
from desk.cli import run_turn
from desk.guardrails import OFF_TOPIC_REFUSAL, off_topic_guardrail
from desk.profile import StudentProfile

# Imported as ``helpers.*`` (not ``tests.helpers.*``): the ``literalai``
# dependency ships a ``tests`` package into site-packages that shadows the
# project's namespace ``tests`` package on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers.scripted_model import ScriptedModel  # noqa: E402

set_tracing_disabled(True)

# openai-agents 0.22.3: ``@input_guardrail`` wraps the function into an
# ``InputGuardrail`` object; the raw callable lives on ``guardrail_function``.
guardrail_fn = off_topic_guardrail.guardrail_function


def make_profile(**overrides) -> StudentProfile:
    values = {
        "name": "Ayesha",
        "roll_no": "S-2026-042",
        "course_id": "agentic-ai-w4",
    }
    values.update(overrides)
    return StudentProfile(**values)


def make_ctx_and_agent():
    return (
        RunContextWrapper(context=make_profile()),
        Agent(name="probe-agent"),
    )


# --- Unit: on-topic questions pass -------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "When is my A3 due?",
        "What if I submit late?",
        "Career roadmap after this bootcamp?",
        "How do I raise a support ticket for my course?",
    ],
)
async def test_on_topic_questions_do_not_trip(question):
    ctx, agent = make_ctx_and_agent()

    result = await guardrail_fn(ctx, agent, question)

    assert isinstance(result, GuardrailFunctionOutput)
    assert result.tripwire_triggered is False
    assert result.output_info is None


# --- Unit: off-topic questions trip -------------------------------------------


@pytest.mark.parametrize(
    ("question", "keyword"),
    [
        ("What's the weather in Karachi tomorrow?", "weather"),
        ("Tell me a joke about cats", "joke"),
        ("Who is going to win the election?", "election"),
        ("Give me a biryani recipe", "recipe"),
        ("Who won the cricket match last night?", "cricket"),
        ("What's the best movie of 2026?", "movie"),
        ("How is the stock market doing today?", "stock market"),
    ],
)
async def test_off_topic_questions_trip_and_name_the_keyword(question, keyword):
    ctx, agent = make_ctx_and_agent()

    result = await guardrail_fn(ctx, agent, question)

    assert result.tripwire_triggered is True
    assert result.output_info == {"matched": keyword}


# --- Unit: zero model calls, PROVEN -------------------------------------------


async def test_guardrail_makes_zero_model_calls(monkeypatch):
    import agents as agents_sdk

    async def _no_runner_run(*args, **kwargs):
        raise AssertionError("the guardrail must never invoke Runner.run")

    async def _no_model_get_response(*args, **kwargs):
        raise AssertionError("the guardrail must never invoke a model")

    monkeypatch.setattr(agents_sdk.Runner, "run", _no_runner_run)
    monkeypatch.setattr(agents_sdk.Model, "get_response", _no_model_get_response)

    ctx, agent = make_ctx_and_agent()

    passed = await guardrail_fn(ctx, agent, "When is my A3 due?")
    assert passed.tripwire_triggered is False

    tripped = await guardrail_fn(ctx, agent, "What's the weather in Karachi tomorrow?")
    assert tripped.tripwire_triggered is True


# --- Unit: SDK input shapes (str vs list of items) -----------------------------


async def test_guardrail_uses_the_last_user_message_of_an_item_list():
    ctx, agent = make_ctx_and_agent()
    items = [
        {"role": "user", "content": "What's the weather in Karachi tomorrow?"},
        {"role": "assistant", "content": "Please ask about your bootcamp."},
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "When is my A3 due?"}],
        },
    ]

    result = await guardrail_fn(ctx, agent, items)

    # Only the LAST user message counts — earlier turns stay in history.
    assert result.tripwire_triggered is False


async def test_guardrail_trips_on_off_topic_last_user_message_in_an_item_list():
    ctx, agent = make_ctx_and_agent()
    items = [
        {"role": "user", "content": "When is my A3 due?"},
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "Tell me a joke"}],
        },
    ]

    result = await guardrail_fn(ctx, agent, items)

    assert result.tripwire_triggered is True
    assert result.output_info == {"matched": "joke"}


async def test_guardrail_does_not_trip_when_no_text_can_be_extracted():
    ctx, agent = make_ctx_and_agent()
    items = [
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": None},
    ]

    result = await guardrail_fn(ctx, agent, items)

    # Defensive: no extractable text -> never trip.
    assert result.tripwire_triggered is False


# --- Integration: tripwire fires BEFORE the Desk's model runs ------------------


async def test_tripwire_fires_before_the_desk_model_runs():
    model = ScriptedModel(replies=[])  # ANY model call would raise AssertionError
    agent = build_desk_agent(model)
    profile = make_profile()

    with pytest.raises(InputGuardrailTripwireTriggered):
        await Runner.run(agent, "Tell me a joke about cats", context=profile, max_turns=10)

    # Zero billed Desk-model tokens: the guardrail tripped first.
    assert model.calls == []


async def test_on_topic_question_still_reaches_the_model_exactly_once():
    model = ScriptedModel(replies=["Assignment A3 is due on 2026-09-18."])
    agent = build_desk_agent(model)
    profile = make_profile()

    result = await Runner.run(agent, "When is my A3 due?", context=profile, max_turns=10)

    assert result.final_output == "Assignment A3 is due on 2026-09-18."
    assert len(model.calls) == 1


# --- Integration: CLI courteous refusal, no crash ------------------------------


async def test_run_turn_returns_courteous_refusal_and_keeps_the_repl_alive():
    model = ScriptedModel(replies=[])  # the Desk model must never be reached
    agent = build_desk_agent(model)
    profile = make_profile()
    history: list = []

    answer = await run_turn(agent, profile, history, "What's the weather in Karachi tomorrow?")

    # The refusal is the turn's reply; no exception escapes run_turn.
    assert answer == OFF_TOPIC_REFUSAL


async def test_off_topic_refusal_text_is_courteous_and_data_free():
    # One courteous sentence: invites bootcamp questions, no student data,
    # no tier words, no leaked internals.
    assert "bootcamp" in OFF_TOPIC_REFUSAL.lower()
    assert "regular" not in OFF_TOPIC_REFUSAL.lower()
    assert "scholarship" not in OFF_TOPIC_REFUSAL.lower()
    assert OFF_TOPIC_REFUSAL.strip().endswith(".")

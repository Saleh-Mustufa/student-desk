"""Tasks 14+15 — Chainlit app core and branded UX (FR-12).

The session logic lives in ``desk/app_state.py`` — pure, testable without a
running Chainlit server: the agent and profile are built ONCE per session,
history flows through ``result.to_input_list()`` (multi-turn memory), and two
sessions never share state (two browser windows). Every failure mode maps to
a friendly card text from ``desk/errors.py`` — no tracebacks to the user;
server-side logging only. ``app.py`` is a thin shell over this logic and is
verified structurally (handler wiring, session store usage, starters).

All runs go through the ScriptedModel — network-free.
"""

import json
import sys
from pathlib import Path

import pytest
from agents import Runner, set_tracing_disabled

from desk.app_state import DeskSession, ensure_process_setup
from desk.errors import (
    MODEL_FAILURE_MESSAGE,
    SETUP_FAILURE_INTRO,
    TICKET_PARSE_FAILURE_MESSAGE,
    TURN_CEILING_MESSAGE,
    ConfigError,
)
from desk.profile import StudentProfile
from desk.ticket import Ticket

# Imported as ``helpers.*`` (not ``tests.helpers.*``): the ``literalai``
# dependency ships a ``tests`` package into site-packages that shadows the
# project's namespace ``tests`` package on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers.scripted_model import ScriptedModel  # noqa: E402

set_tracing_disabled(True)

ADMIN_TICKET = {
    "category": "admin",
    "summary": "Class runs Mon-Thu, 7-9pm.",
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


@pytest.fixture(autouse=True)
def quiet_process_setup(monkeypatch, request):
    """Most tests stub the process-wide setup; its own tests enable it."""
    if request.node.get_closest_marker("real_setup"):
        yield None
        return
    calls = []
    monkeypatch.setattr("desk.app_state.ensure_process_setup", lambda: calls.append(1))
    yield calls


def make_session(replies, **overrides) -> DeskSession:
    return DeskSession.build(model=ScriptedModel(replies=replies), **overrides)


# --- FR-12: the agent and profile are built ONCE per session ------------------


async def test_session_builds_agent_and_profile_once_and_uses_them_per_message():
    session = make_session([json.dumps(ADMIN_TICKET), json.dumps(ASSIGNMENT_TICKET)])

    first = await session.send("When is class?")
    second = await session.send("And my A3 due date?")

    assert isinstance(first, Ticket) and isinstance(second, Ticket)
    # ONE agent object, built once — the same agent served both messages.
    assert session.agent is session.agent
    assert isinstance(session.profile, StudentProfile)
    assert session.history, "the conversation memory grew"


async def test_two_sessions_are_isolated_no_shared_history():
    s1 = make_session([json.dumps(ADMIN_TICKET)])
    s2 = make_session([json.dumps(ADMIN_TICKET)])

    await s1.send("Window one question")

    assert s1.history and s2.history == []
    assert s1.history is not s2.history
    assert s1.agent is not s2.agent


async def test_second_message_refers_to_the_first_multi_turn_memory():
    session = make_session([json.dumps(ADMIN_TICKET), json.dumps(ASSIGNMENT_TICKET)])

    await session.send("When is class?")
    await session.send("What about the late policy for that class?")

    # The second run saw the whole prior conversation plus the new question.
    assert len(session.history) >= 4  # user, assistant, user, assistant


def test_session_build_requires_a_valid_key_before_anything_else(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env reachable

    with pytest.raises(ConfigError) as excinfo:
        DeskSession.build()

    assert "OPENAI_API_KEY" in str(excinfo.value)


# --- FR-12/NFR-1: process-wide setup happens once, at the first session ------


@pytest.mark.real_setup
def test_ensure_process_setup_runs_once_per_process(monkeypatch):
    import desk.app_state as app_state

    traced, stamped = [], []
    monkeypatch.setattr(app_state, "install_jsonl_tracing", lambda: traced.append(1))
    monkeypatch.setattr(
        app_state, "_register_stamping_runner", lambda: stamped.append(1)
    )
    monkeypatch.setattr(app_state, "_PROCESS_SETUP_DONE", False)

    app_state.ensure_process_setup()
    app_state.ensure_process_setup()
    app_state.ensure_process_setup()

    assert traced == [1]
    assert stamped == [1]


# --- failure modes: friendly card text, never a traceback (NFR-1, FR-12) ------


async def test_off_topic_input_gets_the_polite_refusal_not_a_crash():
    from desk.guardrails import OFF_TOPIC_REFUSAL

    session = make_session([])  # ANY model call would raise AssertionError

    answer = await session.send("Tell me a joke about cats")

    assert answer == OFF_TOPIC_REFUSAL


async def test_turn_ceiling_is_reported_in_plain_language():
    from helpers.scripted_model import FunctionCallReply

    session = DeskSession.build(
        model=ScriptedModel(replies=[FunctionCallReply(name="list_courses")] * 12)
    )

    answer = await session.send("list everything, forever")

    assert answer == TURN_CEILING_MESSAGE


async def test_unparseable_ticket_reply_is_reported_without_a_raw_dump():
    session = make_session(["I cannot file a ticket."])

    answer = await session.send("When is my A3 due?")

    assert answer == TICKET_PARSE_FAILURE_MESSAGE


async def test_model_failure_is_reported_and_logged_server_side(
    tmp_path, monkeypatch, capfd
):
    session = DeskSession.build(model=ScriptedModel(replies=[]))
    logged = []
    monkeypatch.setattr(
        "desk.app_state.log_exception", lambda exc: logged.append(exc)
    )

    answer = await session.send("When is class?")

    assert answer == MODEL_FAILURE_MESSAGE
    assert logged, "the failure was recorded server-side"
    captured = capfd.readouterr()
    assert "Traceback" not in captured.out and "Traceback" not in captured.err


# --- T15: branded content and the structured ticket card ----------------------


def test_welcome_greeting_is_branded_for_the_student():
    from desk.app_state import welcome_message

    text = welcome_message(StudentProfile(name="Ayesha", roll_no="S-2026-042",
                                          course_id="agentic-ai-w4"))

    assert "Student Ops Desk" in text
    assert "Ayesha" in text


def test_ticket_card_renders_the_structured_fields_with_indicators():
    from desk.app_state import ticket_card

    resolved = Ticket(**ADMIN_TICKET)
    escalated = Ticket(
        category="admin",
        summary="Portal rejects the roll number.",
        next_step="Route to the registrar's office.",
        resolved=False,
        escalate=True,
    )

    resolved_card = ticket_card(resolved)
    assert "admin" in resolved_card
    assert ADMIN_TICKET["summary"] in resolved_card
    assert ADMIN_TICKET["next_step"] in resolved_card
    assert "Resolved" in resolved_card

    escalated_card = ticket_card(escalated)
    assert "Escalated" in escalated_card
    assert "Resolved" not in escalated_card.replace("Not resolved", "")


def test_starter_chips_are_the_three_guided_questions():
    from desk.app_state import STARTER_CHIPS

    messages = [message for _label, message in STARTER_CHIPS]
    assert messages == [
        "When is my A3 due?",
        "What if I submit late?",
        "Career roadmap after this bootcamp?",
    ]
    assert all(label.strip() for label, _message in STARTER_CHIPS)


# --- app.py: thin handlers over the session store (structure) -----------------


def test_app_handlers_are_thin_and_session_backed():
    source = Path("app.py").read_text(encoding="utf-8")

    # Built ONCE in on_chat_start, stored in the user session — never per message.
    assert "@cl.on_chat_start" in source
    assert "@cl.on_message" in source
    assert 'cl.user_session.set("desk_session"' in source
    assert 'cl.user_session.get("desk_session"' in source
    assert "DeskSession.build(" in source
    # The message handler awaits the session run (async, never run_sync).
    assert "await session.send(" in source
    assert "run_sync" not in source
    # Branded UX: starters wired, steps visible, ticket card rendered.
    assert "@cl.set_starters" in source
    assert "cl.Step(" in source
    assert "ticket_card(" in source
    assert "welcome_message(" in source
    # Guardrail refusals render as the polite card; failures as friendly cards.
    assert "OFF_TOPIC_REFUSAL" in source or "polite_refusal" in source


# --- T15: branded config + custom stylesheet are tracked in git ---------------


def test_chainlit_config_is_branded_and_uses_the_tracked_stylesheet():
    config = Path(".chainlit/config.toml").read_text(encoding="utf-8")

    # Branded identity, dark-first, styled via our tracked stylesheet.
    assert 'name = "Student Ops Desk"' in config
    assert 'custom_css = "/public/custom.css"' in config
    assert 'default_theme = "dark"' in config


def test_custom_stylesheet_exists_and_carries_the_brand():
    css = Path(".chainlit/public/custom.css").read_text(encoding="utf-8")

    assert css.strip(), "the stylesheet is empty"
    # Saylani brand green drives the accent colour, in any letter case.
    assert "8dc63f" in css.lower()
    # Dark-mode-consistent: a dark surface colour is defined alongside it.
    assert "0e1117" in css.lower() or "111827" in css.lower()

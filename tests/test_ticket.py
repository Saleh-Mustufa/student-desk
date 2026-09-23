"""Task 6 — Ticket: the typed final output of every resolved conversation (FR-7).

Every run goes through the ScriptedModel (agent-level ``model=`` injection) —
no test ever touches the network or the project's real ``.env``. Tracing is
disabled for the suite: the default exporter would only attempt an OpenAI
platform upload and 401; the app keeps tracing ON for FR-13.

The ``output_type=Ticket`` mechanics are proven against a throwaway probe
agent built here — wiring the real Desk agent is deliberately deferred to
Task 8.
"""

import json
import sys
from pathlib import Path

import pytest
from agents import set_tracing_disabled
from pydantic import ValidationError

from desk.ticket import Ticket

# Imported as ``helpers.*`` (not ``tests.helpers.*``): the ``literalai``
# dependency ships a ``tests`` package into site-packages that shadows the
# project's namespace ``tests`` package on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers.scripted_model import ScriptedModel  # noqa: E402

set_tracing_disabled(True)

TICKET_JSON = {
    "category": "assignment",
    "summary": "Student asked when assignment 3 is due.",
    "next_step": "Submit A3 on the portal by 2026-09-30.",
    "resolved": True,
    "escalate": False,
}

ESCALATION_JSON = {
    "category": "admin",
    "summary": "Student reports the portal rejects their roll number.",
    "next_step": "Route to the registrar's office for a manual record fix.",
    "resolved": False,
    "escalate": True,
}


def make_ticket_agent(replies: list[str]):
    from agents import Agent

    return Agent(
        name="Ticket Probe",
        instructions="Return the ticket JSON.",
        model=ScriptedModel(replies=replies),
        output_type=Ticket,
    )


# --- FR-7: the Ticket model itself -------------------------------------------


def test_ticket_accepts_valid_fields():
    ticket = Ticket(**TICKET_JSON)

    assert ticket.category == "assignment"
    assert ticket.summary.startswith("Student asked")
    assert ticket.next_step.startswith("Submit")
    assert ticket.resolved is True
    assert ticket.escalate is False


def test_ticket_rejects_a_category_outside_the_literal():
    bad = {**TICKET_JSON, "category": "complaint"}

    with pytest.raises(ValidationError):
        Ticket(**bad)


def test_ticket_field_descriptions_reach_the_json_schema_the_model_sees():
    schema = Ticket.model_json_schema()

    props = schema["properties"]
    for field_name in ("category", "summary", "next_step", "resolved", "escalate"):
        assert props[field_name].get("description"), f"{field_name} lacks a description"
    assert schema["properties"]["category"]["enum"] == [
        "assignment",
        "career",
        "admin",
    ]


# --- FR-7: output_type mechanics — the runner shapes the final output --------


async def test_runner_parses_a_valid_json_reply_into_exactly_a_ticket():
    from agents import Runner

    agent = make_ticket_agent(replies=[json.dumps(TICKET_JSON)])

    result = await Runner.run(agent, "When is A3 due?")

    # Exactly the declared type — not a dict, not a subclass.
    assert type(result.final_output) is Ticket
    assert result.final_output.category == "assignment"
    assert result.final_output.resolved is True  # code branches on this flag


async def test_runner_flips_the_branch_when_the_ticket_says_escalate():
    from agents import Runner

    agent = make_ticket_agent(replies=[json.dumps(ESCALATION_JSON)])

    result = await Runner.run(agent, "The portal rejects my roll number!")

    assert type(result.final_output) is Ticket
    assert result.final_output.resolved is False
    assert result.final_output.escalate is True  # the escalation branch fires


async def test_unshapeable_reply_raises_model_behavior_error():
    from agents import Runner
    from agents.exceptions import ModelBehaviorError

    agent = make_ticket_agent(replies=["I cannot file a ticket."])

    with pytest.raises(ModelBehaviorError):
        await Runner.run(agent, "When is A3 due?")

"""Task 12 — custom runner wrapping every run (FR-11).

``StampingRunner(AgentRunner)`` stamps a uuid request id and elapsed
milliseconds around ``super().run()`` and appends a ``RunWrapperRecord`` to
``audit/runs.jsonl``. It is registered ONCE at startup via
``set_default_agent_runner`` — no agent definition changes to accommodate it
(no file under ``desk/`` that defines agents or tools mentions it). All runs
go through the ScriptedModel — network-free.
"""

import json
import re
import sys
import uuid
from pathlib import Path

import pytest
from agents import Runner, set_tracing_disabled
from agents.run import set_default_agent_runner

from desk.agents import build_desk_agent, build_specialists
from desk.profile import StudentProfile
from desk.runner import StampingRunner

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

RECORD_KEYS = {"request_id", "started_at", "elapsed_ms", "agent", "outcome"}


def make_profile(**overrides) -> StudentProfile:
    values = {
        "name": "Ayesha",
        "roll_no": "S-2026-042",
        "course_id": "agentic-ai-w4",
    }
    values.update(overrides)
    return StudentProfile(**values)


def read_records(sink: Path) -> list[dict]:
    return [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines()]


# --- FR-11: the wrapper stamps Desk runs AND specialist runs ------------------


async def test_wrapper_record_appears_for_desk_and_specialist_runs(tmp_path):
    sink = tmp_path / "audit" / "runs.jsonl"
    runner = StampingRunner(sink=sink)
    set_default_agent_runner(runner)
    try:
        model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET), json.dumps(ASSIGNMENT_TICKET)])
        profile = make_profile()

        await Runner.run(
            build_desk_agent(model), "When is class?",
            context=profile, max_turns=10,
        )
        assignments, _careers = build_specialists(model)
        await Runner.run(
            assignments, "When is my A3 due?",
            context=profile, max_turns=10,
        )
    finally:
        set_default_agent_runner(None)  # restore the SDK default for the suite

    records = read_records(sink)
    assert [r["agent"] for r in records] == ["Student Ops Desk", "Assignments Specialist"]
    for record in records:
        assert record["outcome"] == "ok"
        assert record["elapsed_ms"] >= 0
    # Every run gets its own stamped request id.
    assert records[0]["request_id"] != records[1]["request_id"]


async def test_run_wrapper_record_shape_is_durable_jsonl(tmp_path):
    sink = tmp_path / "runs.jsonl"
    runner = StampingRunner(sink=sink)
    set_default_agent_runner(runner)
    try:
        await Runner.run(
            build_desk_agent(ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])),
            "When is class?", context=make_profile(), max_turns=10,
        )
    finally:
        set_default_agent_runner(None)

    assert sink.exists()
    records = read_records(sink)
    assert len(records) == 1
    record = records[0]
    assert set(record) == RECORD_KEYS
    assert re.fullmatch(r"[0-9a-f]{32}", record["request_id"])  # uuid4 hex
    uuid.UUID(hex=record["request_id"])
    assert record["started_at"].endswith("+00:00") or "T" in record["started_at"]
    assert isinstance(record["elapsed_ms"], int)


async def test_a_failing_run_stamps_an_error_record_and_reraises(tmp_path):
    sink = tmp_path / "runs.jsonl"
    runner = StampingRunner(sink=sink)
    set_default_agent_runner(runner)
    try:
        with pytest.raises(AssertionError):
            # ScriptedModel with NO replies raises on the first model call.
            await Runner.run(
                build_desk_agent(ScriptedModel(replies=[])),
                "When is class?", context=make_profile(), max_turns=10,
            )
    finally:
        set_default_agent_runner(None)

    records = read_records(sink)
    assert len(records) == 1
    assert records[0]["outcome"] == "error"
    assert records[0]["error_type"] == "AssertionError"


# --- FR-11: registration at startup — no agent file mentions the wrapper ------


def test_no_agent_definition_file_mentions_the_custom_runner():
    agent_files = [
        "desk/agents.py",
        "desk/tools.py",
        "desk/prompt_builder.py",
        "desk/profile.py",
        "desk/ticket.py",
        "desk/guardrails.py",
    ]
    for name in agent_files:
        source = Path(name).read_text(encoding="utf-8")
        assert "StampingRunner" not in source, name
        assert "set_default_agent_runner" not in source, name

    # It lives in exactly two places: its module and the startup wiring.
    assert "StampingRunner" in Path("desk/runner.py").read_text(encoding="utf-8")
    assert "StampingRunner()" in Path("desk/cli.py").read_text(encoding="utf-8")

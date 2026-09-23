"""Task 11 — audit hooks: one run-level timeline, one watched specialist (FR-10).

``DeskRunHooks(RunHooks)`` records ONE ordered timeline across every agent in
the conversation — including the handoff — and appends it durably as JSON
lines (NFR-3). ``SpecialistAgentHooks(AgentHooks)`` is attached to EXACTLY ONE
specialist. All runs go through the ScriptedModel — network-free.
"""

import json
import sys
from pathlib import Path

from agents import Runner, set_tracing_disabled

from desk.agents import build_desk_agent, build_specialists
from desk.cli import run_turn
from desk.hooks import DeskRunHooks, SpecialistAgentHooks
from desk.profile import StudentProfile
from desk.prompt_builder import (
    ASSIGNMENTS_HANDOFF_TOOL,
    ASSIGNMENTS_SPECIALIST_NAME,
)

# Imported as ``helpers.*`` (not ``tests.helpers.*``): the ``literalai``
# dependency ships a ``tests`` package into site-packages that shadows the
# project's namespace ``tests`` package on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers.scripted_model import FunctionCallReply, ScriptedModel  # noqa: E402

set_tracing_disabled(True)

ASSIGNMENT_TICKET = {
    "category": "assignment",
    "summary": "A3 is due on 2026-10-02.",
    "next_step": "Submit A3 on the portal before 2026-10-02.",
    "resolved": True,
    "escalate": False,
}
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


# --- FR-10: one ordered run-level timeline across the handoff -----------------


async def test_run_hooks_timeline_names_both_agents_in_order_across_a_handoff(
    tmp_path,
):
    timeline = DeskRunHooks(sink=tmp_path / "timeline.jsonl")
    model = ScriptedModel(
        replies=[
            FunctionCallReply(name=ASSIGNMENTS_HANDOFF_TOOL),
            json.dumps(ASSIGNMENT_TICKET),
        ]
    )
    agent = build_desk_agent(model)

    await Runner.run(
        agent, "When is my A3 due?", context=make_profile(), max_turns=10,
        hooks=timeline,
    )

    events = [(entry["event"], entry["agent"]) for entry in timeline.entries]
    agent_starts = [name for event, name in events if event == "agent_start"]
    # One timeline, both agents, in conversation order: the Desk classified,
    # then the specialist answered.
    assert agent_starts == ["Student Ops Desk", ASSIGNMENTS_SPECIALIST_NAME]

    # The handoff sits between the two agent_start entries and names both.
    handoff = [e for e in timeline.entries if e["event"] == "handoff"]
    assert len(handoff) == 1
    handoff_entry = handoff[0]
    start_indices = [i for i, (ev, _) in enumerate(events) if ev == "agent_start"]
    handoff_index = next(
        i for i, (ev, _) in enumerate(events) if ev == "handoff"
    )
    assert start_indices[0] < handoff_index < start_indices[1]
    assert handoff_entry["agent"] == "Student Ops Desk"
    assert ASSIGNMENTS_SPECIALIST_NAME in handoff_entry["detail"]

    # The answering specialist's agent_end closes the timeline.
    agent_ends = [name for event, name in events if event == "agent_end"]
    assert agent_ends[-1] == ASSIGNMENTS_SPECIALIST_NAME


async def test_timeline_entries_are_ordered_durable_json_lines(tmp_path):
    sink = tmp_path / "audit" / "timeline.jsonl"
    timeline = DeskRunHooks(sink=sink)
    model = ScriptedModel(
        replies=[
            FunctionCallReply(name=ASSIGNMENTS_HANDOFF_TOOL),
            json.dumps(ASSIGNMENT_TICKET),
        ]
    )

    await Runner.run(
        build_desk_agent(model), "When is A3 due?",
        context=make_profile(), max_turns=10, hooks=timeline,
    )

    assert sink.exists()
    lines = sink.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(timeline.entries)
    parsed = [json.loads(line) for line in lines]
    # Every line carries the full TimelineEntry shape, strictly ordered.
    assert [e["seq"] for e in parsed] == list(range(1, len(parsed) + 1))
    for entry in parsed:
        assert set(entry) == {"seq", "ts", "event", "agent", "detail"}
        assert entry["ts"]  # non-empty ISO timestamp
        assert entry["agent"]


# --- FR-10: agent-level hooks attached to EXACTLY ONE specialist --------------


def test_specialist_hooks_attach_to_one_specialist_only():
    hooks = SpecialistAgentHooks(sink=Path("unused.jsonl"))
    assignments, careers = build_specialists(
        ScriptedModel(replies=[]), assignments_hooks=hooks
    )

    assert assignments.hooks is hooks
    assert careers.hooks is None


async def test_specialist_hooks_belong_to_their_one_agent(tmp_path):
    specialist_hooks = SpecialistAgentHooks(sink=tmp_path / "specialist.jsonl")
    model = ScriptedModel(
        replies=[
            FunctionCallReply(name=ASSIGNMENTS_HANDOFF_TOOL),
            json.dumps(ASSIGNMENT_TICKET),
        ]
    )

    await Runner.run(
        build_desk_agent(model, assignments_hooks=specialist_hooks),
        "When is A3 due?",
        context=make_profile(),
        max_turns=10,
    )

    # The close-watch recorded activity for its ONE agent only — nothing
    # while the Desk owned the conversation.
    assert specialist_hooks.entries, "the watched specialist recorded nothing"
    assert all(
        entry["agent"] == ASSIGNMENTS_SPECIALIST_NAME
        for entry in specialist_hooks.entries
    )
    # Its first event is the specialist's own start, after the transfer.
    assert specialist_hooks.entries[0]["event"] == "agent_start"


# --- FR-10: the CLI wires both hook layers ------------------------------------


async def test_run_turn_passes_the_run_hooks_to_the_runner(tmp_path):
    timeline = DeskRunHooks(sink=tmp_path / "timeline.jsonl")
    model = ScriptedModel(replies=[json.dumps(ADMIN_TICKET)])
    history: list = []

    await run_turn(
        build_desk_agent(model), make_profile(), history, "When is class?",
        run_hooks=timeline,
    )

    assert any(e["event"] == "agent_start" for e in timeline.entries)
    assert any(e["event"] == "agent_end" for e in timeline.entries)


def test_cli_source_wires_the_default_factory_and_run_hooks():
    source = Path("desk/cli.py").read_text(encoding="utf-8")

    # The default agent factory attaches the close-watch to one specialist…
    assert "SpecialistAgentHooks()" in source
    # …and the session creates the run-level timeline handed to every turn.
    assert "DeskRunHooks(" in source

"""Task 13 — durable local tracing (FR-13).

``JsonlTraceProcessor`` replaces the SDK's default exporter (which needs an
OpenAI platform key this project does not have — exporting would 401 on every
run; plan.md §5 documents this deliberate resolution). Tracing stays ON: one
conversation appears as ONE trace, every span is nameable, and every event is
written durably to ``audit/traces.jsonl``.

Reconciliation with the rest of the suite: test modules run with
``set_tracing_disabled(True)``; the fixture here owns the global tracing
state and restores it afterwards, and the CLI tests restore in ``finally``.
All runs go through the ScriptedModel — network-free.
"""

import json
import sys
from pathlib import Path

import pytest
from agents import Runner, set_trace_processors, set_tracing_disabled, trace

from desk.agents import build_desk_agent
from desk.cli import main
from desk.profile import StudentProfile
from desk.tracing import install_jsonl_tracing

# Imported as ``helpers.*`` (not ``tests.helpers.*``): the ``literalai``
# dependency ships a ``tests`` package into site-packages that shadows the
# project's namespace ``tests`` package on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers.scripted_model import FunctionCallReply, ScriptedModel  # noqa: E402

ASSIGNMENTS_HANDOFF_TOOL = "transfer_to_assignments_specialist"
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


def read_payloads(sink: Path) -> list[dict]:
    return [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def local_tracing(tmp_path):
    """Own the process-global tracing state for one test, then restore it."""
    processor = install_jsonl_tracing(sink=tmp_path / "traces.jsonl")
    yield processor
    set_tracing_disabled(True)
    set_trace_processors([])


# --- FR-13: one conversation = one trace, every span named --------------------


async def test_one_conversation_is_one_trace_with_named_spans(
    tmp_path, local_tracing
):
    model = ScriptedModel(
        replies=[
            FunctionCallReply(name=ASSIGNMENTS_HANDOFF_TOOL),
            json.dumps(ASSIGNMENT_TICKET),  # turn 1: Desk -> specialist
            json.dumps(ADMIN_TICKET),  # turn 2 of the SAME conversation
        ]
    )
    agent = build_desk_agent(model)
    profile = make_profile()

    with trace(workflow_name="student-ops-desk:test"):
        await Runner.run(agent, "When is my A3 due?", context=profile, max_turns=10)
        await Runner.run(agent, "When is class?", context=profile, max_turns=10)
    local_tracing.force_flush()

    payloads = read_payloads(tmp_path / "traces.jsonl")
    spans = [p for p in payloads if p["object"] == "trace.span"]
    traces = [p for p in payloads if p["object"] == "trace"]
    assert spans, "no spans were exported"
    assert traces, "no trace was exported"
    # BOTH turns — including the handoff — share ONE trace id (FR-13).
    assert len({span["trace_id"] for span in spans}) == 1
    assert spans[0]["trace_id"] == traces[0]["id"]
    assert traces[0]["workflow_name"].startswith("student-ops-desk")
    # Every span has a non-empty name — every span can be named.
    assert all(span.get("name") for span in spans)
    # The handoff is visible in the trace: spans from two agents.
    agent_span_names = " ".join(span["name"] for span in spans)
    assert "Assignments Specialist" in agent_span_names


def test_install_jsonl_tracing_replaces_the_default_exporter(tmp_path):
    try:
        processor = install_jsonl_tracing(sink=tmp_path / "traces.jsonl")

        from agents.tracing import get_trace_provider

        provider = get_trace_provider()
        # Exactly ONE processor is registered — ours. Nothing else (and in
        # particular no OpenAI platform exporter) receives events.
        assert tuple(provider._multi_processor._processors) == (processor,)
        # Tracing is ON — spans are created, not no-ops.
        assert provider._disabled is False
    finally:
        set_tracing_disabled(True)
        set_trace_processors([])


# --- FR-13: the CLI wraps the whole conversation in ONE named trace -----------


class _PipedInput:
    """Replays piped lines, then raises EOFError like a closed stdin."""

    def __init__(self, lines):
        self._lines = list(lines)

    def __call__(self, prompt=""):
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


async def test_cli_wraps_the_whole_conversation_in_one_named_trace(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-123")
    monkeypatch.chdir(tmp_path)  # the durable sink lands in this tmp audit/
    monkeypatch.setattr(
        "builtins.input", _PipedInput(["first question", "second question"])
    )
    model = ScriptedModel(
        replies=[json.dumps(ADMIN_TICKET), json.dumps(ASSIGNMENT_TICKET)]
    )

    try:
        code = await main([], agent_factory=lambda: build_desk_agent(model))
    finally:
        set_tracing_disabled(True)
        set_trace_processors([])

    assert code == 0
    payloads = read_payloads(tmp_path / "audit" / "traces.jsonl")
    spans = [p for p in payloads if p["object"] == "trace.span"]
    traces = [p for p in payloads if p["object"] == "trace"]
    assert spans and traces
    # One REPL session, two turns — ONE trace id across both (FR-13).
    assert len({span["trace_id"] for span in spans}) == 1
    assert traces[0]["workflow_name"].startswith("student-ops-desk:")
    assert all(span.get("name") for span in spans)

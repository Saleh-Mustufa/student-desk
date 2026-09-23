"""FR-10 audit hooks — one timeline for the whole run, one close-watched agent.

Two complementary hook layers, both durable JSON lines (NFR-3):

- ``DeskRunHooks(RunHooks)`` is passed per run (``Runner.run(..., hooks=)``)
  and records ONE ordered timeline across EVERY agent in the conversation,
  including the handoff: agent starts/ends, the transfer, tool calls and LLM
  calls, all in one sequence.
- ``SpecialistAgentHooks(AgentHooks)`` lives ON an agent (attached to exactly
  one specialist by the caller) and records only that agent's own events.
  Once responsibility transfers, the close-watch's events belong to the next
  agent by construction — the run-level timeline keeps covering everything.

Every entry follows the TimelineEntry shape from plan.md §4:
``{"seq", "ts", "event", "agent", "detail"}`` — one JSON object per line,
appended and flushed on every event.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agents import AgentHooks, RunHooks

DEFAULT_TIMELINE_SINK = Path("audit/timeline.jsonl")
DEFAULT_SPECIALIST_SINK = Path("audit/specialist_timeline.jsonl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class _TimelineWriter:
    """Appends ordered entries as JSON lines; flushes every event (NFR-3)."""

    def __init__(self, sink: str | Path) -> None:
        self.sink = Path(sink)
        self.entries: list[dict] = []
        self._seq = 0

    def record(self, event: str, agent: str, detail: str = "") -> dict:
        self._seq += 1
        entry = {
            "seq": self._seq,
            "ts": _now_iso(),
            "event": event,
            "agent": agent,
            "detail": detail,
        }
        self.entries.append(entry)
        self.sink.parent.mkdir(parents=True, exist_ok=True)
        with self.sink.open("a", encoding="utf-8") as timeline_file:
            timeline_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry


class DeskRunHooks(RunHooks):
    """Run-level hooks: one ordered timeline across every agent (FR-10)."""

    def __init__(self, sink: str | Path = DEFAULT_TIMELINE_SINK) -> None:
        self._timeline = _TimelineWriter(sink)

    @property
    def entries(self) -> list[dict]:
        """The in-memory mirror of what was written durably to the sink."""
        return self._timeline.entries

    async def on_agent_start(self, context, agent) -> None:
        self._timeline.record("agent_start", agent.name)

    async def on_agent_end(self, context, agent, output) -> None:
        self._timeline.record("agent_end", agent.name)

    async def on_handoff(self, context, from_agent, to_agent) -> None:
        self._timeline.record(
            "handoff", from_agent.name, f"transferred to {to_agent.name}"
        )

    async def on_tool_start(self, context, agent, tool) -> None:
        self._timeline.record("tool_start", agent.name, tool.name)

    async def on_tool_end(self, context, agent, tool, result) -> None:
        self._timeline.record("tool_end", agent.name, tool.name)

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self._timeline.record("llm_start", agent.name)

    async def on_llm_end(self, context, agent, response) -> None:
        self._timeline.record("llm_end", agent.name)


class SpecialistAgentHooks(AgentHooks):
    """Agent-level hooks: a close-watch on exactly ONE specialist (FR-10)."""

    def __init__(self, sink: str | Path = DEFAULT_SPECIALIST_SINK) -> None:
        self._timeline = _TimelineWriter(sink)

    @property
    def entries(self) -> list[dict]:
        return self._timeline.entries

    async def on_start(self, context, agent) -> None:
        self._timeline.record("agent_start", agent.name)

    async def on_end(self, context, agent, output) -> None:
        self._timeline.record("agent_end", agent.name)

    async def on_handoff(self, context, agent, source) -> None:
        self._timeline.record(
            "handoff", agent.name, f"transferred from {source.name}"
        )

    async def on_tool_start(self, context, agent, tool) -> None:
        self._timeline.record("tool_start", agent.name, tool.name)

    async def on_tool_end(self, context, agent, tool, result) -> None:
        self._timeline.record("tool_end", agent.name, tool.name)

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self._timeline.record("llm_start", agent.name)

    async def on_llm_end(self, context, agent, response) -> None:
        self._timeline.record("llm_end", agent.name)

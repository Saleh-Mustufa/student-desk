"""FR-11 — a custom runner stamped around every run in the process.

``StampingRunner`` subclasses the SDK's ``AgentRunner``, overrides ``run()``
and stamps a uuid request id plus elapsed milliseconds around the real run.
It is registered ONCE at startup (``desk.cli``) via
``agents.run.set_default_agent_runner`` — so EVERY ``Runner.run`` in the
process is wrapped, Desk runs, specialist runs and nested tool-agent runs
alike — while NO agent definition changes to accommodate it: no file that
defines agents or tools mentions this module.

Every wrapped run appends one ``RunWrapperRecord`` (plan.md §4) to
``audit/runs.jsonl``:
``{"request_id", "started_at", "elapsed_ms", "agent", "outcome", "error_type"?}``
— one JSON object per line, durable (NFR-3), with ``outcome="error"`` and the
exception type recorded when a run fails before the record is flushed.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agents.run import AgentRunner

DEFAULT_RUNS_SINK = Path("audit/runs.jsonl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class StampingRunner(AgentRunner):
    """Wrap every run: stamp request id + elapsed ms, record it durably."""

    def __init__(self, sink: str | Path = DEFAULT_RUNS_SINK) -> None:
        super().__init__()
        self.sink = Path(sink)
        self.records: list[dict] = []

    def _append(self, record: dict) -> None:
        self.records.append(record)
        self.sink.parent.mkdir(parents=True, exist_ok=True)
        with self.sink.open("a", encoding="utf-8") as runs_file:
            runs_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def run(self, starting_agent, input, **kwargs):
        request_id = uuid4().hex
        started_at = _now_iso()
        started = time.perf_counter()
        try:
            result = await super().run(starting_agent, input, **kwargs)
        except Exception as exc:
            self._append(
                {
                    "request_id": request_id,
                    "started_at": started_at,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000),
                    "agent": starting_agent.name,
                    "outcome": "error",
                    "error_type": type(exc).__name__,
                }
            )
            raise
        self._append(
            {
                "request_id": request_id,
                "started_at": started_at,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "agent": starting_agent.name,
                "outcome": "ok",
            }
        )
        return result

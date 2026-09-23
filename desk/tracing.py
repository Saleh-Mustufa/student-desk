"""FR-13 — durable local tracing under our own control.

The SDK's built-in trace exporter uploads to the OpenAI platform and needs an
OpenAI platform key; this project's ``OPENAI_API_KEY`` is a Gemini-endpoint
key, so exporting would 401 on every run (noise, dishonest silence). The
deliberate resolution documented in plan.md §5: tracing stays ON, and
:func:`install_jsonl_tracing` REPLACES the default processor list with a
single local :class:`JsonlTraceProcessor` — every trace and span is created
normally and written as one JSON object per line to ``audit/traces.jsonl``.

The CLI wraps each conversation in ONE named ``trace(...)`` so every turn of
a conversation — every agent, tool call and handoff — shares one trace id
(the runner reuses the active trace instead of making one per run).

Methods are deliberately SYNC: the SDK's ``SynchronousMultiTracingProcessor``
calls processor methods directly, so each event is written the moment it
fires — durable, unbuffered (NFR-3).
"""

from __future__ import annotations

import json
from pathlib import Path

from agents import TracingProcessor, set_trace_processors, set_tracing_disabled

DEFAULT_TRACES_SINK = Path("audit/traces.jsonl")


def _span_name(span) -> str:
    """A nameable label for any span: span_data's name, else its kind.

    Span exports carry no top-level ``name`` — it lives on the span data
    (agent spans name the agent, function spans the tool, ...). Response
    spans have no name field, so their kind stands in; a name is never empty.
    """
    data = span.span_data.export() if span.span_data is not None else {}
    name = data.get("name")
    if name:
        return str(name)
    return str(data.get("type") or type(span.span_data).__name__)


class JsonlTraceProcessor(TracingProcessor):
    """Write every trace and span event as a JSON line to a local sink."""

    def __init__(self, sink: str | Path = DEFAULT_TRACES_SINK) -> None:
        self.sink = Path(sink)

    def _append(self, payload: dict) -> None:
        self.sink.parent.mkdir(parents=True, exist_ok=True)
        with self.sink.open("a", encoding="utf-8") as traces_file:
            traces_file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def on_trace_start(self, trace) -> None:
        self._append({"type": "trace_start", **trace.export()})

    def on_trace_end(self, trace) -> None:
        self._append({"type": "trace_end", **trace.export()})

    def on_span_start(self, span) -> None:
        # The ended span's export is the durable record; starts are ephemeral.
        return None

    def on_span_end(self, span) -> None:
        payload = span.export() or {}
        self._append({"type": "span", "name": _span_name(span), **payload})

    def shutdown(self) -> None:
        # Writes are synchronous; there is nothing buffered to flush.
        return None

    def force_flush(self, timeout_ms: int = 30000) -> bool:
        return True


def install_jsonl_tracing(sink: str | Path = DEFAULT_TRACES_SINK) -> JsonlTraceProcessor:
    """Route ALL tracing to the local JSONL sink and keep tracing ON (FR-13).

    Replaces the process's processor list with exactly one
    :class:`JsonlTraceProcessor` — the built-in platform exporter receives
    nothing, so no export (and no 401) is ever attempted. Call once at
    startup; the caller owns the returned processor if it wants to read or
    flush it.
    """
    processor = JsonlTraceProcessor(sink)
    set_trace_processors([processor])
    set_tracing_disabled(False)
    return processor

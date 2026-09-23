"""ScriptedModel — a network-free model double for the test suite (tests only).

Subclasses the SDK's abstract ``agents.Model`` with the exact abstract
signature of openai-agents 0.22.3 (``agents/models/interface.py``). Each queued
reply becomes a plain-text ``ResponseOutputMessage`` inside a ``ModelResponse``;
every ``get_response`` call is recorded (system instructions, input items, tool
list, settings) so tests can assert exactly what the runner sent to the model.

It is injected as the agent-level ``model=`` argument — never via
``RunConfig.model`` (constitution: model configuration lives on the agent,
tests included).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from agents import Model, ModelResponse, Usage
from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.items import TResponseInputItem, TResponseStreamEvent
from agents.model_settings import ModelSettings
from agents.tool import Tool
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
from openai.types.responses.response_prompt_param import ResponsePromptParam


def text_message(text: str, message_id: str = "msg-scripted-1") -> ResponseOutputMessage:
    """Build a completed assistant message whose single part is plain text."""
    return ResponseOutputMessage(
        id=message_id,
        status="completed",
        role="assistant",
        content=[ResponseOutputText(text=text, type="output_text", annotations=[])],
        type="message",
    )


@dataclass
class ScriptedCall:
    """One recorded ``get_response`` invocation."""

    system_instructions: str | None
    input: str | list[TResponseInputItem]
    model_settings: ModelSettings
    tools: list[Tool]


@dataclass
class ScriptedModel(Model):
    """Replays queued text replies and records every call made through it."""

    replies: list[str] = field(default_factory=list)
    calls: list[ScriptedCall] = field(default_factory=list)

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: object,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> ModelResponse:
        self.calls.append(
            ScriptedCall(
                system_instructions=system_instructions,
                input=input,
                model_settings=model_settings,
                tools=list(tools),
            )
        )
        if not self.replies:
            raise AssertionError("ScriptedModel received more calls than scripted replies")
        text = self.replies.pop(0)
        return ModelResponse(
            output=[text_message(text)],
            usage=Usage(),
            response_id=f"resp-scripted-{len(self.calls)}",
        )

    async def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: object,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> AsyncIterator[TResponseStreamEvent]:
        raise NotImplementedError("ScriptedModel supports only non-streaming runs")
        yield  # unreachable: makes this an async generator per the abstract signature

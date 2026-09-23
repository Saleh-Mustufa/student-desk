"""ScriptedModel — a network-free model double for the test suite (tests only).

Subclasses the SDK's abstract ``agents.Model`` with the exact abstract
signature of openai-agents 0.22.3 (``agents/models/interface.py``). Each queued
reply becomes either a plain-text ``ResponseOutputMessage`` or — for tool
calls and handoff transfers — a ``ResponseFunctionToolCall`` (the exact output
item type the runner parses in ``agents/run_internal/``); every ``get_response``
call is recorded (system instructions, input items, tool list, handoff list,
settings) so tests can assert exactly what the runner sent to the model.

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
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
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
class FunctionCallReply:
    """A queued function-call reply — a tool call or a handoff transfer.

    ``arguments`` is the raw JSON string exactly as the model would emit it;
    ``{}`` suits the no-input handoff tools and argument-less tools.
    """

    name: str
    arguments: str = "{}"


@dataclass
class ScriptedCall:
    """One recorded ``get_response`` invocation."""

    system_instructions: str | None
    input: str | list[TResponseInputItem]
    model_settings: ModelSettings
    tools: list[Tool]
    handoffs: list[Handoff] = field(default_factory=list)


class ScriptedModel(Model):
    """Replays queued replies (text or function calls) and records every call.

    Deliberately a plain class, NOT a dataclass: the SDK serialises agent
    graphs with ``dataclasses.asdict`` (run-state identity signatures), and
    an agent-as-tool's ``FunctionTool._agent_instance`` points back at the
    agent that holds this model — a dataclass model that also recorded those
    tools would close a reference cycle and blow the recursion limit.
    """

    def __init__(self, replies: list[str | FunctionCallReply] | None = None) -> None:
        self.replies: list[str | FunctionCallReply] = list(replies or [])
        self.calls: list[ScriptedCall] = []

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
                handoffs=list(handoffs),
            )
        )
        if not self.replies:
            raise AssertionError("ScriptedModel received more calls than scripted replies")
        reply = self.replies.pop(0)
        if isinstance(reply, FunctionCallReply):
            output: list = [
                ResponseFunctionToolCall(
                    name=reply.name,
                    arguments=reply.arguments,
                    call_id=f"call-scripted-{len(self.calls)}",
                    type="function_call",
                )
            ]
        else:
            output = [text_message(reply)]
        return ModelResponse(
            output=output,
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

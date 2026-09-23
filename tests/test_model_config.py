"""Model failover catalog — desk/model_config.py (user-approved spec amendment, 2026-09-23).

Network-free: the inner per-catalog models are stubs injected through the factory seam,
cooldowns are driven by an injected clock, and the OpenAI exceptions are constructed with
synthetic httpx responses. No test touches the real .env or the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from agents import Model, OpenAIChatCompletionsModel
from openai import InternalServerError, NotFoundError, RateLimitError

sys.path.insert(0, str(Path(__file__).parent))

from desk.config import DeskConfig  # noqa: E402
from desk.model_config import (  # noqa: E402
    MODEL_CATALOG,
    FailoverModel,
    build_model,
    resolve_catalog,
)


# ---------------------------------------------------------------- test doubles


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StubInner:
    """Duck-typed stand-in for an inner OpenAIChatCompletionsModel."""

    def __init__(self, name: str, script: list) -> None:
        self.name = name
        self.script = list(script)
        self.calls: list[dict] = []

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        *,
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
        **kwargs,
    ):
        self.calls.append(
            {
                "system_instructions": system_instructions,
                "input": input,
                "model_settings": model_settings,
                "tools": tools,
                "output_schema": output_schema,
                "handoffs": handoffs,
                "tracing": tracing,
            }
        )
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def stream_response(self, *args, **kwargs):  # pragma: no cover - not under test here
        raise NotImplementedError


class FakeResponse:
    """A ModelResponse stand-in so tests can tell which inner model answered."""

    def __init__(self, marker: str) -> None:
        self.marker = marker


def _resp(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://unit.test"))


def rate_limited(message: str = "Quota exceeded for metric: generate_content_free_tier_requests"):
    return RateLimitError(message, response=_resp(429), body=None)


def per_day_rate_limited():
    return RateLimitError(
        "Quota exceeded for metric: GenerateRequestsPerDayPerProjectPerModel",
        response=_resp(429),
        body=None,
    )


def not_found():
    return NotFoundError("model not found", response=_resp(404), body=None)


def server_busy():
    return InternalServerError("high demand", response=_resp(503), body=None)


def make_failover(scripts: dict[str, list], clock: FakeClock | None = None) -> tuple[FailoverModel, FakeClock]:
    clock = clock or FakeClock()
    model = FailoverModel(
        catalog=list(scripts.keys()),
        factory=lambda name: StubInner(name, scripts[name]),
        clock=clock.monotonic,
    )
    return model, clock


# ------------------------------------------------------------------- catalog


def test_default_catalog_head_is_the_user_priority_model():
    assert resolve_catalog({})[0] == "gemini-3.6-flash"


def test_default_catalog_order_lite_before_five_rpm_flash():
    catalog = resolve_catalog({})
    assert catalog.index("gemini-3.5-flash-lite") < catalog.index("gemini-3.8-flash")


def test_gemma_models_are_excluded_from_the_catalog():
    assert all("gemma" not in name for name in resolve_catalog({}))


def test_model_priority_env_reorders_the_catalog():
    catalog = resolve_catalog({"MODEL_PRIORITY": "gemini-3-flash, gemini-3.6-flash"})
    assert catalog[:2] == ["gemini-3-flash", "gemini-3.6-flash"]
    assert len(catalog) == len(MODEL_CATALOG)  # nothing lost, only reordered


def test_unknown_priority_entries_are_ignored():
    catalog = resolve_catalog({"MODEL_PRIORITY": "not-a-real-model,gemini-3-flash"})
    assert catalog[0] == "gemini-3-flash"
    assert "not-a-real-model" not in catalog


def test_gemini_model_env_pins_the_head():
    catalog = resolve_catalog({"GEMINI_MODEL": "gemini-3.5-flash"})
    assert catalog[0] == "gemini-3.5-flash"
    assert len(catalog) == len(MODEL_CATALOG)


# -------------------------------------------------------------- failover core


async def test_failover_model_implements_the_sdk_model_interface():
    model, _ = make_failover({"m-a": [FakeResponse("ok")]})
    assert isinstance(model, Model)


async def test_call_fails_over_to_next_model_on_429():
    model, _ = make_failover(
        {
            "m-a": [rate_limited()],
            "m-b": [FakeResponse("from-b")],
        }
    )
    response = await model.get_response(None, "hi", None, [], None, [], None)
    assert response.marker == "from-b"


async def test_cooldown_skips_model_until_window_expires():
    model, clock = make_failover(
        {
            "m-a": [rate_limited(), FakeResponse("from-a-recovered")],
            "m-b": [FakeResponse("from-b"), FakeResponse("from-b-again")],
        }
    )
    first = await model.get_response(None, "hi", None, [], None, [], None)
    assert first.marker == "from-b"

    clock.advance(10)  # still inside the 60s window
    second = await model.get_response(None, "hi", None, [], None, [], None)
    assert second.marker == "from-b-again"  # m-a still cooling down, m-b answers again

    clock.advance(61)  # window expired, m-a is healthy again
    third = await model.get_response(None, "hi", None, [], None, [], None)
    assert third.marker == "from-a-recovered"


async def test_404_skips_the_model_for_the_rest_of_the_session():
    model, clock = make_failover(
        {
            "m-a": [not_found(), FakeResponse("from-a-should-never-happen")],
            "m-b": [FakeResponse("from-b"), FakeResponse("from-b-again")],
        }
    )
    first = await model.get_response(None, "hi", None, [], None, [], None)
    clock.advance(100000)  # far beyond any cooldown window
    second = await model.get_response(None, "hi", None, [], None, [], None)
    assert first.marker == "from-b"
    assert second.marker == "from-b-again"


async def test_503_uses_a_short_cooldown():
    model, clock = make_failover(
        {
            "m-a": [server_busy(), FakeResponse("from-a-recovered")],
            "m-b": [FakeResponse("from-b"), FakeResponse("from-b-again")],
        }
    )
    first = await model.get_response(None, "hi", None, [], None, [], None)
    clock.advance(10)
    second = await model.get_response(None, "hi", None, [], None, [], None)
    clock.advance(30)  # short window (30s) has passed
    third = await model.get_response(None, "hi", None, [], None, [], None)
    assert first.marker == "from-b"
    assert second.marker == "from-b-again"
    assert third.marker == "from-a-recovered"


async def test_per_day_quota_cools_down_for_a_full_day():
    model, clock = make_failover(
        {
            "m-a": [per_day_rate_limited(), FakeResponse("from-a-recovered")],
            "m-b": [FakeResponse("from-b"), FakeResponse("from-b-again")],
        }
    )
    first = await model.get_response(None, "hi", None, [], None, [], None)
    clock.advance(3600)  # an hour later — still cooling down
    second = await model.get_response(None, "hi", None, [], None, [], None)
    assert first.marker == "from-b"
    assert second.marker == "from-b-again"
    assert clock.now - 1000.0 < 23 * 3600  # the day window has not expired inside this test


async def test_when_every_model_fails_the_last_error_surfaces():
    model, _ = make_failover(
        {
            "m-a": [rate_limited()],
            "m-b": [server_busy()],
        }
    )
    with pytest.raises(InternalServerError):
        await model.get_response(None, "hi", None, [], None, [], None)


async def test_arguments_are_forwarded_to_the_inner_model_unchanged():
    model, _ = make_failover({"m-a": [FakeResponse("ok")]})
    await model.get_response(
        "system prompt", [{"role": "user", "content": "hi"}], "settings", ["tool"], "schema", ["handoff"], "tracing"
    )
    inner = model._models["m-a"]
    call = inner.calls[0]
    assert call["system_instructions"] == "system prompt"
    assert call["input"] == [{"role": "user", "content": "hi"}]
    assert call["model_settings"] == "settings"
    assert call["tools"] == ["tool"]
    assert call["output_schema"] == "schema"
    assert call["handoffs"] == ["handoff"]
    assert call["tracing"] == "tracing"


async def test_active_model_name_reports_first_healthy_entry():
    model, _ = make_failover(
        {
            "m-a": [rate_limited()],
            "m-b": [FakeResponse("ok")],
        }
    )
    assert model.active_model_name == "m-a"
    await model.get_response(None, "hi", None, [], None, [], None)
    assert model.active_model_name == "m-b"


# ----------------------------------------------------------- build_model wire


def test_build_model_returns_failover_wrapping_chat_completions_models():
    config = DeskConfig(
        model_name="gemini-3.6-flash",
        base_url="https://unit.test/v1beta/openai/",
        api_key="test-key-123",
    )
    model = build_model(config, env={})
    assert isinstance(model, FailoverModel)
    head = model._models[resolve_catalog({})[0]]
    assert isinstance(head, OpenAIChatCompletionsModel)
    assert head.model == resolve_catalog({})[0]

"""Model selection and failover — the single model-config module (FR-1, user-approved 2026-09-23).

The provider retired ``gemini-2.5-flash`` for this project's key and free-tier quotas make any
single model a single point of failure. This module owns WHICH model answers:

* ``MODEL_CATALOG`` — the priority-ordered list of Gemini OpenAI-compatible models.
* ``FailoverModel`` — an SDK ``Model`` wrapper that tries catalog entries in order and cools an
  entry down on 429 (60 s, or ~24 h when the provider reports a per-day quota), 503 (30 s) and
  404 (rest of the session), retrying the call on the next healthy entry.
* ``build_model`` — builds the wrapper around one shared ``AsyncOpenAI`` client; the wrapper is
  the object every agent receives as ``model=`` (agent-level configuration; never per-run,
  never global — the forbidden process-global client call appears nowhere in this repo).

Gemma-family models are deliberately excluded from the catalog: they cannot call tools, and the
Desk is tool-required (FR-2).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping

from openai import AsyncOpenAI, InternalServerError, NotFoundError, RateLimitError

from agents import Model, OpenAIChatCompletionsModel

# Priority order: the user's preferred head first, then the 15-RPM lite tier (best availability
# with tool support), then the 5-RPM full-flash tier.
MODEL_CATALOG: list[str] = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3-flash",
]

# Cooldown windows (seconds) chosen from the provider's own error semantics.
_MINUTE = 60.0
_DAY = 24 * 3600.0
PERMANENT_SKIP = float("inf")


def resolve_catalog(env: Mapping[str, str]) -> list[str]:
    """Order the catalog: MODEL_PRIORITY reorders the head, GEMINI_MODEL pins it.

    Unknown ids in either variable are ignored (typo-safe); every catalog model keeps its place
    in the default order unless promoted.
    """
    catalog = list(MODEL_CATALOG)
    priority = [part.strip() for part in (env.get("MODEL_PRIORITY") or "").split(",") if part.strip()]
    promoted = [name for name in priority if name in catalog]
    pinned = env.get("GEMINI_MODEL", "").strip()
    if pinned in catalog and pinned not in promoted:
        promoted.append(pinned)
    return promoted + [name for name in catalog if name not in promoted]


def cooldown_for(exc: BaseException) -> float:
    """Map a provider failure to a cooldown window in seconds."""
    if isinstance(exc, NotFoundError):
        return PERMANENT_SKIP
    if isinstance(exc, RateLimitError):
        text = str(exc).lower().replace("_", "").replace("-", "")
        if "perday" in text:
            return _DAY
        return _MINUTE
    if isinstance(exc, InternalServerError):
        return 30.0
    return _MINUTE


class FailoverModel(Model):
    """Tries catalog models in priority order, cooling down entries that fail.

    The wrapper never inspects or changes the conversation: every argument is forwarded
    unchanged to whichever inner model answers.
    """

    def __init__(
        self,
        catalog: list[str],
        factory: Callable[[str], Model],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.catalog = list(catalog)
        self._models: dict[str, Model] = {name: factory(name) for name in self.catalog}
        self._clock = clock
        self._cooldown_until: dict[str, float] = {name: 0.0 for name in self.catalog}
        self._permanently_skipped: set[str] = set()

    def _healthy_names(self) -> list[str]:
        now = self._clock()
        healthy = [
            name
            for name in self.catalog
            if name not in self._permanently_skipped and self._cooldown_until[name] <= now
        ]
        if healthy:
            return healthy
        # Everything is cooling down: still try the highest-priority entry that is not
        # permanently skipped rather than giving up without a model.
        fallback = [name for name in self.catalog if name not in self._permanently_skipped]
        return fallback[:1]

    @property
    def active_model_name(self) -> str:
        healthy = self._healthy_names()
        return healthy[0] if healthy else self.catalog[0]

    def _mark_failure(self, name: str, exc: BaseException) -> None:
        window = cooldown_for(exc)
        if window is PERMANENT_SKIP:
            self._permanently_skipped.add(name)
        else:
            self._cooldown_until[name] = self._clock() + window

    async def get_response(
        self,
        system_instructions: str | None,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt=None,
        **kwargs,
    ):
        last_error: BaseException | None = None
        for name in self._healthy_names():
            try:
                return await self._models[name].get_response(
                    system_instructions,
                    input,
                    model_settings,
                    tools,
                    output_schema,
                    handoffs,
                    tracing,
                    previous_response_id=previous_response_id,
                    conversation_id=conversation_id,
                    prompt=prompt,
                    **kwargs,
                )
            except (NotFoundError, RateLimitError, InternalServerError) as exc:
                self._mark_failure(name, exc)
                last_error = exc
        assert last_error is not None, "catalog is empty"
        raise last_error

    async def stream_response(
        self,
        system_instructions: str | None,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt=None,
        **kwargs,
    ):
        # Failover applies until the first chunk arrives; once a model starts streaming, a
        # mid-stream failure propagates (restarting silently would duplicate partial output).
        for name in self._healthy_names():
            inner = self._models[name]
            stream = inner.stream_response(
                system_instructions,
                input,
                model_settings,
                tools,
                output_schema,
                handoffs,
                tracing,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                prompt=prompt,
                **kwargs,
            )
            try:
                first = await stream.__anext__()
            except StopAsyncIteration:
                return
            except (NotFoundError, RateLimitError, InternalServerError) as exc:
                self._mark_failure(name, exc)
                continue
            yield first
            async for chunk in stream:
                yield chunk
            return


def build_model(config, env: Mapping[str, str] | None = None) -> FailoverModel:
    """Wire the failover wrapper every agent receives as its agent-level ``model=``.

    ``config`` is the DeskConfig from ``desk.config`` (duck-typed here to keep the import
    graph acyclic): only ``config.api_key`` and ``config.base_url`` are read.
    """
    catalog = resolve_catalog(os.environ if env is None else env)
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
    return FailoverModel(
        catalog,
        lambda name: OpenAIChatCompletionsModel(model=name, openai_client=client),
    )

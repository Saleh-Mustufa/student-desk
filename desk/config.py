"""Desk configuration (FR-1 partial, NFR-1).

Loads settings from environment variables (plus a project-root .env when no
mapping is passed), validates the Gemini API key, and builds the agent-level
model object. The model is declared per agent — there is deliberately no
process-global OpenAI client here. WHICH Gemini model is active is decided by
the failover catalog in ``desk/model_config.py`` (user-approved amendment,
2026-09-23); ``GEMINI_MODEL`` pins the head of that catalog.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

from desk.errors import ConfigError
from desk.model_config import FailoverModel, build_model as _build_failover_model

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL_NAME = "gemini-2.5-flash"


@dataclass
class DeskConfig:
    model_name: str
    base_url: str
    api_key: str


def load_config(env: Mapping[str, str] | None = None) -> DeskConfig:
    """Build a DeskConfig from a mapping, defaulting to the process environment.

    When ``env`` is None the project-root ``.env`` is loaded into the
    environment first. A missing or blank ``OPENAI_API_KEY`` raises
    ``ConfigError`` with the exact fix, never a stack trace.
    """
    if env is None:
        load_dotenv(".env")
        env = os.environ

    api_key = (env.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ConfigError(
            "OPENAI_API_KEY is missing or blank. Add the line "
            "OPENAI_API_KEY=<your Gemini API key> to the .env file in the "
            "project root and restart the Desk."
        )

    return DeskConfig(
        model_name=env.get("GEMINI_MODEL", DEFAULT_MODEL_NAME),
        base_url=env.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
        api_key=api_key,
    )


def build_model(config: DeskConfig) -> FailoverModel:
    """Wire the agent-level model object declared on each Agent.

    Delegates to ``desk.model_config`` — the failover catalog decides which Gemini
    model answers; ``config.model_name`` (from ``GEMINI_MODEL``) pins its head.
    """
    return _build_failover_model(config)

"""Task 1 — config, secrets validation, central errors (FR-1 partial, NFR-1).

Every test injects its own fake env mapping (or a throwaway .env in a tmp dir);
the project's real .env is never read by the test suite.
"""

import logging
from pathlib import Path

import pytest
from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from desk.config import DeskConfig, build_model, load_config
from desk.errors import ConfigError

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-2.5-flash"


# --- happy path: DeskConfig from an injected env mapping -------------------


def test_load_config_defaults_from_env_mapping():
    config = load_config({"OPENAI_API_KEY": "test-key-123"})

    assert isinstance(config, DeskConfig)
    assert config.api_key == "test-key-123"
    assert config.base_url == DEFAULT_BASE_URL
    assert config.model_name == DEFAULT_MODEL


def test_load_config_reads_gemini_model_and_base_url_overrides():
    config = load_config(
        {
            "OPENAI_API_KEY": "test-key-123",
            "OPENAI_BASE_URL": "https://example.invalid/v1/",
            "GEMINI_MODEL": "gemini-2.0-flash",
        }
    )

    assert config.model_name == "gemini-2.0-flash"
    assert config.base_url == "https://example.invalid/v1/"
    assert config.api_key == "test-key-123"


def test_load_config_reads_dotenv_file_when_env_is_none(tmp_path, monkeypatch):
    # Throwaway .env in a tmp dir — the project's real .env is never touched.
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=fake-key-from-tmp-dotenv\n", encoding="utf-8"
    )
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "GEMINI_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)

    config = load_config()

    assert config.api_key == "fake-key-from-tmp-dotenv"


# --- NFR-1: missing/blank key fails cleanly, stating the exact fix ---------


def test_missing_api_key_raises_config_error_stating_the_fix():
    with pytest.raises(ConfigError) as excinfo:
        load_config({"GEMINI_MODEL": DEFAULT_MODEL})

    message = str(excinfo.value)
    assert "OPENAI_API_KEY" in message
    assert ".env" in message
    # No traceback chain: raised directly, not wrapped around another error.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_blank_api_key_raises_config_error():
    with pytest.raises(ConfigError):
        load_config({"OPENAI_API_KEY": "   "})


# --- FR-1: build_model wires the agent-level model, never a global ---------


def test_build_model_returns_chat_completions_model_on_async_openai():
    config = DeskConfig(
        model_name="gemini-2.5-flash",
        base_url=DEFAULT_BASE_URL,
        api_key="test-key-123",
    )

    model = build_model(config)

    assert isinstance(model, OpenAIChatCompletionsModel)
    assert model.model == "gemini-2.5-flash"
    client = model._client
    assert isinstance(client, AsyncOpenAI)
    assert str(client.base_url) == DEFAULT_BASE_URL
    assert client.api_key == "test-key-123"


def test_no_set_default_openai_client_in_desk_package():
    desk_dir = Path(__file__).resolve().parent.parent / "desk"
    offenders = [
        path.name
        for path in sorted(desk_dir.rglob("*.py"))
        if "set_default_openai_client" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


# --- NFR-1: central error utility — logs server-side, speaks friendly ------


def test_log_exception_writes_full_traceback_to_server_logger_only(
    caplog, capfd
):
    from desk.errors import LOGGER_NAME, log_exception

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        try:
            raise ValueError("boom")
        except ValueError as exc:
            log_exception(exc)

    assert caplog.records[0].name == LOGGER_NAME
    assert "Traceback (most recent call last)" in caplog.text
    assert "ValueError: boom" in caplog.text
    # Nothing leaked to stdout or stderr.
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_user_message_returns_config_error_message_verbatim():
    from desk.errors import ConfigError, user_message

    exc = ConfigError("OPENAI_API_KEY is missing. Add it to .env and restart.")

    assert user_message(exc) == "OPENAI_API_KEY is missing. Add it to .env and restart."


def test_user_message_returns_generic_line_for_unknown_errors():
    from desk.errors import user_message

    assert user_message(RuntimeError("secret detail: abc123")) == (
        "Something went wrong. Please try again."
    )

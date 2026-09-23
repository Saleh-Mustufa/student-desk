"""Central error types and utilities (NFR-1).

One place the Desk raises its known errors from and one place the UI turns
exceptions into friendly sentences. Full tracebacks go only to the server-side
logger — never to the chat, never to stdout.
"""

from __future__ import annotations

import logging

LOGGER_NAME = "student_ops_desk"


class ConfigError(Exception):
    """Raised when startup configuration is missing or invalid (NFR-1)."""


_GENERIC_USER_MESSAGE = "Something went wrong. Please try again."


def log_exception(exc: BaseException) -> None:
    """Record the full traceback on the server-side logger.

    The traceback never reaches stdout/stderr or the chat: the UI shows only
    what ``user_message`` returns.
    """
    logging.getLogger(LOGGER_NAME).error("Unhandled exception", exc_info=exc)


def user_message(exc: BaseException) -> str:
    """Return a short, friendly sentence for the user; details stay in logs."""
    if isinstance(exc, ConfigError):
        return str(exc)
    return _GENERIC_USER_MESSAGE

"""StudentProfile — the local context object every agent and tool shares (FR-3).

Built once per session (CLI flags / Chainlit ``on_chat_start``) and passed as
``context=`` on every run. Tools, dynamic instructions and tool gating read it
from ``RunContextWrapper.context``; it is never hardcoded into prompts and
never leaks into any tool's JSON schema.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StudentProfile:
    """Who the Desk is talking to in this session."""

    name: str
    roll_no: str
    course_id: str
    tier: str = "regular"  # "regular" or "scholarship"
    open_tickets: int = 0

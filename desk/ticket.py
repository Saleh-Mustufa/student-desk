"""Ticket — the typed final output of every resolved conversation (FR-7).

The Desk agent is wired with ``output_type=Ticket`` so the SDK runner parses
the model's final message into this structured object (see Task 8). Code —
never prose — reads ``resolved`` / ``escalate`` to decide the next action,
which is why every field carries a description the model sees in the JSON
schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    """Structured final output of every resolved conversation (FR-7)."""

    category: Literal["assignment", "career", "admin"] = Field(
        description="Which queue the question belongs to: assignment, career or admin."
    )
    summary: str = Field(
        description="One-sentence summary of what the student asked and the answer given."
    )
    next_step: str = Field(
        description="The single concrete action the student should take next."
    )
    resolved: bool = Field(
        description="True when the question was fully answered in this conversation."
    )
    escalate: bool = Field(
        description="True when the issue needs a human (faculty or admin staff) to act."
    )

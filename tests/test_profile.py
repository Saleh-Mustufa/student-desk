"""Task 3 — ``StudentProfile`` as the local context object (FR-3).

The profile is a plain dataclass built once per session and passed as
``context=`` on every run. Nothing about a student may be hardcoded into the
source: identity lives only where the profile object is constructed, so the
grep test pins that the demo student's name appears nowhere under ``desk/``.
"""

import dataclasses
from pathlib import Path

from desk.profile import StudentProfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# A distinctive demo student name — must exist in tests/app wiring only,
# never in the ``desk`` package itself (FR-3 "grep the source" check).
DEMO_NAME = "Fatima Khan"


def test_profile_is_a_dataclass_with_exactly_the_specified_fields():
    names = [field.name for field in dataclasses.fields(StudentProfile)]

    assert names == ["name", "roll_no", "course_id", "tier", "open_tickets"]


def test_profile_holds_the_identity_fields():
    profile = StudentProfile(
        name=DEMO_NAME, roll_no="SW-2026-014", course_id="agentic-ai-w4"
    )

    assert profile.name == DEMO_NAME
    assert profile.roll_no == "SW-2026-014"
    assert profile.course_id == "agentic-ai-w4"


def test_profile_defaults_to_regular_tier_and_no_open_tickets():
    profile = StudentProfile(name=DEMO_NAME, roll_no="R-1", course_id="any-course")

    assert profile.tier == "regular"
    assert profile.open_tickets == 0


def test_profile_accepts_scholarship_tier_and_open_tickets():
    profile = StudentProfile(
        name=DEMO_NAME,
        roll_no="R-1",
        course_id="any-course",
        tier="scholarship",
        open_tickets=2,
    )

    assert profile.tier == "scholarship"
    assert profile.open_tickets == 2


def test_demo_student_name_appears_nowhere_under_desk_package():
    """FR-3: student identity comes from the profile object, never the source.

    Grep every file under the ``desk`` package (binary-safe, includes any
    bytecode) for the demo student's distinctive name.
    """
    hits = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "desk").rglob("*")
        if path.is_file() and DEMO_NAME.encode("utf-8") in path.read_bytes()
    ]

    assert hits == []

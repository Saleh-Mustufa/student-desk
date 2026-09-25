"""Course tools for the Desk and the specialists (FR-3, NFR-4, FR-9).

Every tool is ``@function_tool``-decorated and takes
``RunContextWrapper[StudentProfile]`` as its first parameter — the SDK strips
that parameter from the generated JSON schema, so no profile field ever leaks
into tool arguments (FR-3). All tools return strings the model reads and
**never raise** (NFR-4): unknown-id ``KeyError``s from the repo become exact
model-actionable failure sentences (plan.md §3) and ``CourseDataError``
becomes a data-unavailable sentence. The one deliberate exception to the
string rule is ``close_ticket`` (FR-9b): it returns a **Ticket instance**
whose raw output becomes the run's final output under the Desk's
``StopAtTools`` stopping rule — the student never sees it as tool text.

``scholarship_benefits`` reads ``wrapper.context.tier`` through its
``is_enabled`` callable: for regular-tier students the tool is **absent** from
the offered tool set — not refused — so the model is never even told it
exists (FR-9a).
"""

from __future__ import annotations

from typing import Literal

from agents import RunContextWrapper, function_tool

from desk.courses import CourseDataError, repo
from desk.profile import StudentProfile
from desk.ticket import Ticket

# Shared failure sentences (plan.md §3) — returned to the model, never raised.
_CATALOGUE_EMPTY = (
    "The course catalogue is currently empty. Apologise and tell the student "
    "to check back later."
)
_DATA_UNAVAILABLE = (
    "Course data is unavailable right now. Tell the student the desk cannot "
    "reach the catalogue and suggest trying again."
)
SCHOLARSHIP_UNPUBLISHED = (
    "Scholarship details are not published for this course. Say you'll "
    "escalate to the office."
)


def _lookup_id(raw: str) -> str:
    """Normalise a catalogue id for lookup: trimmed and case-insensitive.

    Students (and therefore models) ask about "A3" while the catalogue stores
    "a3" — an exact, case-sensitive match would fail and send the model into
    retry loops. The failure sentences still echo the id as the caller wrote
    it, so an unknown id is reported transparently.
    """
    return raw.strip().casefold()


def _scholarship_tier_enabled(
    wrapper: RunContextWrapper[StudentProfile], agent
) -> bool:
    """FR-9a gating: the tool exists only for scholarship-tier students."""
    return getattr(wrapper.context, "tier", "regular") == "scholarship"


@function_tool(is_enabled=_scholarship_tier_enabled)
async def scholarship_benefits(wrapper: RunContextWrapper[StudentProfile]) -> str:
    """Return the enrolled course's scholarship benefits, one per line."""
    try:
        course = repo.get_course(_lookup_id(wrapper.context.course_id))
    except KeyError:
        return SCHOLARSHIP_UNPUBLISHED
    except CourseDataError:
        return _DATA_UNAVAILABLE

    benefits = course.get("scholarship_benefits", [])
    if not benefits:
        return SCHOLARSHIP_UNPUBLISHED
    return "\n".join(f"- {benefit}" for benefit in benefits)


@function_tool
async def close_ticket(
    wrapper: RunContextWrapper[StudentProfile],
    category: Literal["assignment", "career", "admin"],
    summary: str,
    next_step: str,
    resolved: bool,
    escalate: bool,
) -> Ticket:
    """File the structured ticket that closes the student's resolved question.

    Call this once the question is fully answered: category is which queue
    the question belongs to, summary is one sentence covering what was asked
    and the answer given, next_step is the single concrete action the student
    should take, resolved is true when fully answered, escalate is true when
    a human must act.
    """
    # FR-9b: the Ticket INSTANCE (not text) is the tool's return; the Desk's
    # StopAtTools rule ends the run right here and this object becomes
    # result.final_output — a typed ticket through the stop path (FR-7).
    return Ticket(
        category=category,
        summary=summary,
        next_step=next_step,
        resolved=resolved,
        escalate=escalate,
    )


@function_tool
async def list_courses(wrapper: RunContextWrapper[StudentProfile]) -> str:
    """List every course the desk offers, with its weekly schedule."""
    try:
        courses = repo.list_courses()
    except CourseDataError:
        return _DATA_UNAVAILABLE
    if not courses:
        return _CATALOGUE_EMPTY
    return "\n".join(
        f"{course['id']} — {course['title']} ({course['schedule']})"
        for course in courses
    )


@function_tool
async def get_course_details(
    wrapper: RunContextWrapper[StudentProfile], course_id: str
) -> str:
    """Return one course's title, weekly schedule, and every policy."""
    try:
        course = repo.get_course(_lookup_id(course_id))
    except KeyError:
        return (
            f"Course lookup failed: unknown id '{course_id}'. Tell the student "
            "it isn't in the catalogue."
        )
    except CourseDataError:
        return _DATA_UNAVAILABLE

    # id/title/schedule are validated by the repo; policies are optional so a
    # missing key renders nothing instead of masquerading as an unknown id.
    lines = [course["title"], f"schedule: {course['schedule']}"]
    lines.extend(
        f"{policy}: {value}"
        for policy, value in course.get("policies", {}).items()
    )
    return "\n".join(lines)


@function_tool
async def get_assignment(
    wrapper: RunContextWrapper[StudentProfile], course_id: str, assignment_id: str
) -> str:
    """Return one assignment's title, due date, and any status or policy notes."""
    try:
        assignment = repo.get_assignment(
            _lookup_id(course_id), _lookup_id(assignment_id)
        )
    except KeyError:
        return (
            f"Assignment lookup failed: unknown id '{assignment_id}' in course "
            f"'{course_id}'. Tell the student it isn't in the catalogue — do "
            "not invent an id."
        )
    except CourseDataError:
        return _DATA_UNAVAILABLE

    # Render only the identity fields here; any further fields the data adds
    # flow through untouched. Fields other than the id are optional so a
    # missing one never turns into a misleading "unknown id" sentence.
    parts = [
        assignment.get("title", "(untitled)"),
        f"due {assignment.get('due', 'unknown')}",
    ]
    parts.extend(
        f"{key}: {value}"
        for key, value in assignment.items()
        if key not in {"id", "title", "due"}
    )
    return " · ".join(parts)

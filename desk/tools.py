"""Course tools for the Desk and the specialists (FR-3, NFR-4).

Every tool is ``@function_tool``-decorated and takes
``RunContextWrapper[StudentProfile]`` as its first parameter — the SDK strips
that parameter from the generated JSON schema, so no profile field ever leaks
into tool arguments (FR-3). All tools return strings the model reads and
**never raise** (NFR-4): unknown-id ``KeyError``s from the repo become exact
model-actionable failure sentences (plan.md §3) and ``CourseDataError``
becomes a data-unavailable sentence.

These three tools are deliberately not profile-specific, so they never read
``wrapper.context`` — the parameter exists for context-type uniformity with
the profile-aware tools that follow (e.g. ``scholarship_benefits`` reads
``wrapper.context.tier``).
"""

from __future__ import annotations

from agents import RunContextWrapper, function_tool

from desk.courses import CourseDataError, repo
from desk.profile import StudentProfile

# Shared failure sentences (plan.md §3) — returned to the model, never raised.
_CATALOGUE_EMPTY = (
    "The course catalogue is currently empty. Apologise and tell the student "
    "to check back later."
)
_DATA_UNAVAILABLE = (
    "Course data is unavailable right now. Tell the student the desk cannot "
    "reach the catalogue and suggest trying again."
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
        course = repo.get_course(course_id)
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
        assignment = repo.get_assignment(course_id, assignment_id)
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

"""Dynamic system prompt builder (FR-4) — rebuilt at request time.

The Agents SDK calls ``build_system_prompt`` before every run and requires the
callable to accept exactly two parameters, ``(wrapper, agent)``; the returned
string is the Desk's system prompt for *that* turn, composed from
``wrapper.context`` (the ``StudentProfile``). The same composition is
reachable without a run via ``preview_prompt`` — printable before any model
call — and both paths share ``_compose``, so the preview is the real prompt,
not a paraphrase.

FR-3 boundary: the prompt deliberately contains the student's NAME (dynamic
personalisation per the graded brief) but never the roll number and never the
tier — those stay in context only. Course facts are not hardcoded either: the
enrolled course's title is resolved through ``desk.courses.repo``, and any
lookup failure (unknown id ``KeyError``, unreachable data
``CourseDataError``) degrades to a generic line — the builder never raises
into the runner (NFR-4).
"""

from __future__ import annotations

from agents import RunContextWrapper

from desk.courses import CourseDataError, repo
from desk.profile import StudentProfile

AGENT_NAME = "Student Ops Desk"

# FR-5 routing constants — the single source of truth for the specialist
# identities and the handoff tool names. ``desk.agents`` names its clones
# exactly these names, so the SDK derives the handoff tools
# ``transfer_to_<name>``; the wiring test pins generated names == constants.
# The scope routing below references the constants — never duplicated strings.
ASSIGNMENTS_SPECIALIST_NAME = "Assignments Specialist"
CAREERS_SPECIALIST_NAME = "Careers Specialist"
ASSIGNMENTS_HANDOFF_TOOL = "transfer_to_assignments_specialist"
CAREERS_HANDOFF_TOOL = "transfer_to_careers_specialist"

# Tone directives — deliberately different wording per branch (tests assert on
# the distinctive phrases): warm and helpful by default, terse once the
# student has three or more open tickets.
_WARM_TONE = (
    "Tone: be warm, encouraging, and helpful — explain clearly, take an "
    "extra sentence when it aids understanding, and offer related help "
    "before moving on."
)
_TERSE_TONE = (
    "Tone: be brisk and terse — short sentences, get to the resolution "
    "fast, skip the pleasantries and offers."
)
_GENERIC_COURSE_LINE = (
    "The student's enrolled course could not be confirmed from the catalogue "
    "right now — rely on the course catalogue tools for all course specifics."
)


def _resolve_course_title(course_id: str) -> str | None:
    """Return the course title, or ``None`` when it cannot be confirmed."""
    try:
        return str(repo.get_course(course_id)["title"])
    except (KeyError, CourseDataError):
        return None


def _compose(profile: StudentProfile, course_title: str | None, agent_name: str) -> str:
    """Render the system prompt from a profile, resolved course, and agent name.

    The single composition point for both the in-run path and the preview, so
    the printable prompt is exactly the prompt a run would send.
    """
    greeting = f"You are the {agent_name} assistant, currently helping {profile.name}."
    course_line = (
        f'The student is enrolled in "{course_title}".'
        if course_title is not None
        else _GENERIC_COURSE_LINE
    )
    tone = _TERSE_TONE if profile.open_tickets >= 3 else _WARM_TONE
    scope = (
        "Scope:\n"
        "- Answer only questions about the Saylani bootcamp; politely "
        "decline anything else.\n"
        "- Ground every course fact in the course catalogue tools; never "
        "invent schedules, deadlines, or policies.\n"
        "- Assignment questions (deadlines, requirements, late policy): "
        f"transfer the conversation to the assignments specialist by "
        f"calling {ASSIGNMENTS_HANDOFF_TOOL}.\n"
        "- Career questions (career paths, roadmap after the bootcamp, "
        f"placement): transfer the conversation to the careers specialist "
        f"by calling {CAREERS_HANDOFF_TOOL}.\n"
        "- Administrative questions (schedules, enrolment, general "
        "policies): answer yourself from the catalogue tools.\n"
        "- Once the student's question is resolved, end the conversation by "
        "calling close_ticket with the structured ticket. If you answer "
        "directly without calling close_ticket, your final message must "
        "instead be a single raw JSON object with the fields category "
        "(assignment, career or admin), summary, next_step, resolved and "
        "escalate — no markdown fences, no commentary around it."
    )
    return "\n\n".join([greeting, course_line, tone, scope])


def build_system_prompt(wrapper: RunContextWrapper[StudentProfile], agent) -> str:
    """Build the Desk's system prompt at request time from the run context.

    Signature is exactly the two parameters the Agents SDK demands for
    dynamic instructions — a different arity raises ``TypeError`` before any
    run starts, by design.
    """
    profile = wrapper.context
    return _compose(profile, _resolve_course_title(profile.course_id), agent.name)


def preview_prompt(profile: StudentProfile, agent_name: str = AGENT_NAME) -> str:
    """The same prompt, printable from a bare profile before any model call."""
    return _compose(profile, _resolve_course_title(profile.course_id), agent_name)

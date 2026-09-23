"""Task 4 — dynamic system prompt rebuilt per turn from the profile (FR-4).

``build_system_prompt`` is a 2-parameter callable exactly as the Agents SDK
requires (``TypeError`` otherwise). Both paths — in-run and ``preview_prompt``
— compose through one shared internal function, so the prompt is printable
before any model call and is *the same* prompt a run would send. Failure paths
swap in a *real* ``CourseRepo`` over a tmp data file — no mocks anywhere — and
the builder must never raise (NFR-4 applied to instructions).

Style phrases and identity boundaries are pinned here as literals, not
imported, so a bug in the wording under test cannot make its own test pass.
"""

from pathlib import Path

import pytest
from agents import Agent, RunContextWrapper

import desk.prompt_builder as prompt_builder_module
from desk.courses import CourseRepo
from desk.profile import StudentProfile
from desk.prompt_builder import build_system_prompt, preview_prompt

AGENT_NAME = "Student Ops Desk"
AGENTIC_TITLE = "Agentic AI — Weekday Batch 4"
ANALYTICS_TITLE = "Data Analytics — Weekend Batch 2"

# Distinctive tone phrases: the warm and terse branches must be visibly
# different wording, not a paraphrase of one another.
WARM_PHRASE = "warm, encouraging"
TERSE_PHRASE = "short sentences"
GENERIC_COURSE_MARKER = "could not be confirmed from the catalogue"

# Scope markers the brief requires in every prompt.
SCOPE_BOOTCAMP = "only questions about the Saylani bootcamp"
SCOPE_TOOLS = "course catalogue tools"
SCOPE_CLOSE = "close_ticket"


def in_run_prompt(profile: StudentProfile, agent_name: str = AGENT_NAME) -> str:
    """Build the prompt exactly as the SDK would during a run."""
    return build_system_prompt(RunContextWrapper(context=profile), Agent(name=agent_name))


def _install_repo(tmp_path, courses_json_text: str) -> Path:
    """Point the builder's repo at a real CourseRepo over a tmp data file."""
    target = tmp_path / "courses.json"
    target.write_text(courses_json_text, encoding="utf-8")
    repo = CourseRepo(target)
    return repo.path


# --- greeting, course naming, and per-profile difference -----------------------


def test_prompt_greets_the_student_by_name():
    profile = StudentProfile(
        name="Ayesha Malik", roll_no="SW-2026-001", course_id="agentic-ai-w4"
    )

    result = in_run_prompt(profile)

    assert "helping Ayesha Malik" in result


def test_prompt_names_the_enrolled_course_title():
    enrolled = StudentProfile(
        name="Bilal Ahmed", roll_no="SW-2026-002", course_id="data-analytics-w2"
    )

    result = in_run_prompt(enrolled)

    assert ANALYTICS_TITLE in result
    assert AGENTIC_TITLE not in result


def test_three_profiles_produce_three_visibly_different_prompts():
    p1 = StudentProfile(
        name="Ayesha Malik", roll_no="SW-2026-001", course_id="agentic-ai-w4",
        tier="regular", open_tickets=0,
    )
    p2 = StudentProfile(
        name="Bilal Ahmed", roll_no="SW-2026-002", course_id="data-analytics-w2",
        tier="scholarship", open_tickets=1,
    )
    p3 = StudentProfile(
        name="Sana Iqbal", roll_no="SW-2026-003", course_id="agentic-ai-w4",
        tier="regular", open_tickets=5,
    )

    prompts = [in_run_prompt(profile) for profile in (p1, p2, p3)]

    assert prompts[0] != prompts[1]
    assert prompts[1] != prompts[2]
    assert prompts[0] != prompts[2]
    # Each prompt is about its own student, course, and tone.
    assert "helping Ayesha Malik" in prompts[0] and AGENTIC_TITLE in prompts[0]
    assert WARM_PHRASE in prompts[0] and TERSE_PHRASE not in prompts[0]
    assert "helping Bilal Ahmed" in prompts[1] and ANALYTICS_TITLE in prompts[1]
    assert "helping Sana Iqbal" in prompts[2]
    assert TERSE_PHRASE in prompts[2] and WARM_PHRASE not in prompts[2]


def test_tone_turns_terse_exactly_at_three_open_tickets():
    regular = StudentProfile(
        name="Ayesha Malik", roll_no="SW-2026-001", course_id="agentic-ai-w4",
        open_tickets=2,
    )
    overloaded = StudentProfile(
        name="Ayesha Malik", roll_no="SW-2026-001", course_id="agentic-ai-w4",
        open_tickets=3,
    )

    at_two = in_run_prompt(regular)
    at_three = in_run_prompt(overloaded)

    assert WARM_PHRASE in at_two and TERSE_PHRASE not in at_two
    assert TERSE_PHRASE in at_three and WARM_PHRASE not in at_three


# --- FR-3 identity boundary: name yes, roll number and tier never --------------


@pytest.mark.parametrize(
    "profile",
    [
        StudentProfile(
            name="Ayesha Malik", roll_no="SW-2026-001", course_id="agentic-ai-w4",
            tier="regular", open_tickets=0,
        ),
        StudentProfile(
            name="Bilal Ahmed", roll_no="SW-2026-002", course_id="data-analytics-w2",
            tier="scholarship", open_tickets=5,
        ),
    ],
    ids=["regular-tier", "scholarship-tier"],
)
def test_prompt_contains_name_but_never_roll_number_or_tier_word(profile):
    result = in_run_prompt(profile)

    assert profile.name in result
    assert profile.roll_no not in result
    lowered = result.lower()
    assert "regular" not in lowered
    assert "scholarship" not in lowered


# --- graceful degradation: the prompt builder must never raise -----------------


def test_unknown_course_id_degrades_gracefully():
    profile = StudentProfile(
        name="Ayesha Malik", roll_no="SW-2026-001", course_id="ghost-course"
    )

    result = in_run_prompt(profile)  # must not raise

    assert "helping Ayesha Malik" in result  # still greets by name
    assert GENERIC_COURSE_MARKER in result  # generic wording...
    assert AGENTIC_TITLE not in result and ANALYTICS_TITLE not in result  # ...no course


def test_unreachable_course_data_degrades_gracefully(tmp_path, monkeypatch):
    """A vanished data file (CourseDataError) degrades like an unknown id."""
    data_file = _install_repo(tmp_path, '{"courses": []}')
    monkeypatch.setattr(prompt_builder_module, "repo", CourseRepo(data_file))
    data_file.unlink()
    profile = StudentProfile(
        name="Bilal Ahmed", roll_no="SW-2026-002", course_id="agentic-ai-w4"
    )

    result = in_run_prompt(profile)  # must not raise

    assert "helping Bilal Ahmed" in result
    assert GENERIC_COURSE_MARKER in result
    assert AGENTIC_TITLE not in result


# --- the Desk's scope rules are part of every prompt ---------------------------


@pytest.mark.parametrize(
    "profile",
    [
        StudentProfile(
            name="Ayesha Malik", roll_no="SW-2026-001", course_id="agentic-ai-w4",
            open_tickets=0,
        ),
        StudentProfile(
            name="Sana Iqbal", roll_no="SW-2026-003", course_id="data-analytics-w2",
            open_tickets=4,
        ),
    ],
    ids=["warm-branch", "terse-branch"],
)
def test_prompt_states_the_desk_scope_rules(profile):
    result = in_run_prompt(profile)

    assert SCOPE_BOOTCAMP in result
    assert SCOPE_TOOLS in result
    assert SCOPE_CLOSE in result


# --- printable before any model call: preview == in-run, deterministically -----


def test_preview_prompt_matches_the_in_run_prompt():
    profile = StudentProfile(
        name="Ayesha Malik", roll_no="SW-2026-001", course_id="agentic-ai-w4",
        open_tickets=2,
    )

    assert preview_prompt(profile) == in_run_prompt(profile)
    assert preview_prompt(profile, "Assignments Specialist") == in_run_prompt(
        profile, "Assignments Specialist"
    )


def test_preview_prompt_works_from_a_bare_profile_without_a_run():
    profile = StudentProfile(
        name="Bilal Ahmed", roll_no="SW-2026-002", course_id="data-analytics-w2"
    )

    result = preview_prompt(profile)

    assert "helping Bilal Ahmed" in result
    assert ANALYTICS_TITLE in result
    assert AGENT_NAME in result  # the default agent name is part of the prompt


# --- the SDK contract: exactly two parameters ----------------------------------


def test_build_system_prompt_requires_exactly_two_arguments():
    profile = StudentProfile(
        name="Ayesha Malik", roll_no="SW-2026-001", course_id="agentic-ai-w4"
    )
    wrapper = RunContextWrapper(context=profile)
    agent = Agent(name=AGENT_NAME)

    with pytest.raises(TypeError):
        build_system_prompt(wrapper)  # too few
    with pytest.raises(TypeError):
        build_system_prompt(wrapper, agent, "extra")  # too many

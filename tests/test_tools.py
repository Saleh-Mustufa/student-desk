"""Task 3 — course tools that never raise (FR-3, NFR-4).

Happy-path tests run against the real ``desk.courses.repo`` (real data, real
files). Failure paths swap in a *real* ``CourseRepo`` pointed at a tmp data
file (empty catalogue, deleted file) — no mocks anywhere. Tools are invoked
through the SDK's own ``invoke_function_tool`` exactly as a model run would
invoke them, so the tests exercise the real schema parsing and context forking.
"""

import json
from pathlib import Path

import pytest
from agents.tool import ToolContext, invoke_function_tool

import desk.tools as tools_module
from desk.courses import CourseRepo, repo
from desk.profile import StudentProfile
from desk.tools import get_assignment, get_course_details, list_courses

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTIC = "agentic-ai-w4"
ANALYTICS = "data-analytics-w2"

DEMO_PROFILE = StudentProfile(
    name="Fatima Khan", roll_no="SW-2026-014", course_id=AGENTIC
)

# Exact contract sentences (plan.md §3) — pinned here, not imported, so a bug
# in the constants under test cannot make its own test pass.
CATALOGUE_EMPTY_SENTENCE = (
    "The course catalogue is currently empty. Apologise and tell the student "
    "to check back later."
)
DATA_UNAVAILABLE_SENTENCE = (
    "Course data is unavailable right now. Tell the student the desk cannot "
    "reach the catalogue and suggest trying again."
)

# Keyed by tool name: FunctionTool instances are unhashable (eq dataclass).
EXPECTED_TOOL_ARGS = {
    "list_courses": set(),
    "get_course_details": {"course_id"},
    "get_assignment": {"course_id", "assignment_id"},
}
PROFILE_FIELDS = {"name", "roll_no", "course_id", "tier", "open_tickets"}


async def invoke(tool, args=None, profile=DEMO_PROFILE):
    """Invoke a function tool through the SDK exactly as a run would."""
    ctx = ToolContext(
        context=profile,
        tool_name=tool.name,
        tool_call_id=f"call-{tool.name}",
        tool_arguments=json.dumps(args or {}),
    )
    return await invoke_function_tool(
        function_tool=tool, context=ctx, arguments=ctx.tool_arguments
    )


def _install_repo(tmp_path, monkeypatch, courses_json_text: str) -> Path:
    """Point the tools' repo at a real CourseRepo over a tmp data file."""
    target = tmp_path / "courses.json"
    target.write_text(courses_json_text, encoding="utf-8")
    monkeypatch.setattr(tools_module, "repo", CourseRepo(target))
    return target


@pytest.fixture
def unreachable_repo(tmp_path, monkeypatch):
    """A real CourseRepo whose data file vanishes after construction, so every
    read raises ``CourseDataError`` — the desk cannot reach the catalogue."""
    target = _install_repo(tmp_path, monkeypatch, '{"courses": []}')
    target.unlink()
    return target


# --- happy path: rendered against the real data file --------------------------


async def test_list_courses_renders_one_line_per_course_from_real_data():
    result = await invoke(list_courses)

    assert result.splitlines() == [
        f"{AGENTIC} — Agentic AI — Weekday Batch 4 (Mon–Thu, 7–9pm)",
        f"{ANALYTICS} — Data Analytics — Weekend Batch 2 (Sat–Sun, 10am–1pm)",
    ]


async def test_get_course_details_renders_title_schedule_and_every_policy():
    course = repo.get_course(AGENTIC)

    result = await invoke(get_course_details, {"course_id": AGENTIC})

    lines = result.splitlines()
    assert lines[0] == course["title"]
    assert f"schedule: {course['schedule']}" in lines
    for policy, value in course["policies"].items():
        assert f"{policy}: {value}" in lines
    assert len(lines) == 2 + len(course["policies"])  # title + schedule + policies


async def test_get_assignment_renders_title_then_due_date():
    assignment = repo.get_assignment(AGENTIC, "a3")

    result = await invoke(
        get_assignment, {"course_id": AGENTIC, "assignment_id": "a3"}
    )

    assert result == f"{assignment['title']} · due {assignment['due']}"
    assert result == "First coded agent · due 2026-10-02"


async def test_course_tools_do_not_read_the_profile_in_context():
    """The three course tools are not profile-specific: they must answer with
    no profile at all in the context (uniform wrapper, deliberately unread)."""
    catalogue = await invoke(list_courses, profile=None)
    details = await invoke(get_course_details, {"course_id": ANALYTICS}, profile=None)

    assert ANALYTICS in catalogue
    assert "Data Analytics — Weekend Batch 2" in details


# --- unknown ids: exact model-actionable failure sentences (NFR-4) ------------


async def test_get_course_details_unknown_id_returns_exact_failure_sentence():
    result = await invoke(get_course_details, {"course_id": "robotics-w1"})

    assert result == (
        "Course lookup failed: unknown id 'robotics-w1'. Tell the student it "
        "isn't in the catalogue."
    )


@pytest.mark.parametrize(
    ("course_id", "assignment_id"),
    [
        (AGENTIC, "a99"),  # known course, unknown assignment id
        ("ghost-course", "a1"),  # unknown course id
    ],
    ids=["unknown-assignment", "unknown-course"],
)
async def test_get_assignment_unknown_ids_return_exact_failure_sentence(
    course_id, assignment_id
):
    result = await invoke(
        get_assignment, {"course_id": course_id, "assignment_id": assignment_id}
    )

    assert result == (
        f"Assignment lookup failed: unknown id '{assignment_id}' in course "
        f"'{course_id}'. Tell the student it isn't in the catalogue — do not "
        "invent an id."
    )


async def test_list_courses_on_empty_catalogue_returns_exact_sentence(
    tmp_path, monkeypatch
):
    _install_repo(tmp_path, monkeypatch, '{"courses": []}')

    result = await invoke(list_courses)

    assert result == CATALOGUE_EMPTY_SENTENCE


# --- data unreachable: no tool ever raises (NFR-4) -----------------------------


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (list_courses, None),
        (get_course_details, {"course_id": AGENTIC}),
        (get_assignment, {"course_id": AGENTIC, "assignment_id": "a1"}),
    ],
    ids=["list_courses", "get_course_details", "get_assignment"],
)
async def test_tool_never_raises_when_course_data_is_unreachable(
    tool, args, unreachable_repo
):
    result = await invoke(tool, args, profile=None)

    assert result == DATA_UNAVAILABLE_SENTENCE


# --- FR-3: generated schemas leak no wrapper and no profile fields ------------


def _properties(tool) -> dict:
    return tool.params_json_schema.get("properties", {})


def test_list_courses_schema_exposes_no_arguments():
    assert _properties(list_courses) == {}


def test_get_course_details_schema_exposes_only_the_course_id_argument():
    assert set(_properties(get_course_details)) == {"course_id"}
    assert get_course_details.params_json_schema["required"] == ["course_id"]


def test_get_assignment_schema_exposes_only_the_two_id_arguments():
    assert set(_properties(get_assignment)) == {"course_id", "assignment_id"}
    assert get_assignment.params_json_schema["required"] == [
        "course_id",
        "assignment_id",
    ]


@pytest.mark.parametrize(
    "tool", [list_courses, get_course_details, get_assignment], ids=lambda t: t.name
)
def test_no_tool_schema_leaks_the_wrapper_or_profile_fields(tool):
    leaked_profile_fields = set(_properties(tool)) - EXPECTED_TOOL_ARGS[tool.name]

    assert leaked_profile_fields & PROFILE_FIELDS == set()
    assert "wrapper" not in _properties(tool)
    assert "wrapper" not in json.dumps(tool.params_json_schema)

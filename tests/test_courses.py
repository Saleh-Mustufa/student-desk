"""Task 2 — course facts in data/courses.json, file-backed repo (FR-2).

Every test either reads the committed data file (happy path) or writes its own
copy into a tmp dir; no test ever mutates the real ``data/courses.json``.
"""

import json
from pathlib import Path

import pytest

from desk.courses import CourseDataError, CourseRepo, repo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_DATA_FILE = PROJECT_ROOT / "data" / "courses.json"

AGENTIC = "agentic-ai-w4"
ANALYTICS = "data-analytics-w2"


def _write_courses(tmp_path: Path, courses: list[dict]) -> Path:
    target = tmp_path / "courses.json"
    target.write_text(
        json.dumps({"courses": courses}, indent=2), encoding="utf-8"
    )
    return target


def _copy_minus_course(tmp_path: Path, course_id: str) -> Path:
    """Copy the real courses.json to tmp_path minus one course."""
    data = json.loads(REAL_DATA_FILE.read_text(encoding="utf-8"))
    data["courses"] = [c for c in data["courses"] if c["id"] != course_id]
    return _write_courses(tmp_path, data["courses"])


# --- happy path: both courses load from the file -----------------------------


def test_repo_lists_both_courses_with_id_title_schedule():
    courses = repo.list_courses()

    assert [c["id"] for c in courses] == [AGENTIC, ANALYTICS]
    for entry in courses:
        assert set(entry) == {"id", "title", "schedule"}
    agentic = courses[0]
    assert agentic["title"] == "Agentic AI — Weekday Batch 4"
    assert agentic["schedule"] == "Mon–Thu, 7–9pm"


def test_get_course_returns_full_facts_from_file():
    course = repo.get_course(AGENTIC)

    assert course["title"] == "Agentic AI — Weekday Batch 4"
    policies = course["policies"]
    assert policies["late_submission"] == "48 hours, 20% penalty"
    assert "plagiarism" in policies
    assert "resubmission" in policies
    assert course["scholarship_benefits"]
    assert course["career_paths"]
    # The brief's example assignment, verbatim.
    assert {
        "id": "a3",
        "title": "First coded agent",
        "due": "2026-10-02",
    } in course["assignments"]


def test_get_assignment_returns_assignment_for_known_ids():
    assignment = repo.get_assignment(AGENTIC, "a3")

    assert assignment == {"id": "a3", "title": "First coded agent", "due": "2026-10-02"}


# --- unknown ids raise KeyError inside the loader ----------------------------


def test_get_course_raises_keyerror_with_known_ids_for_unknown_id():
    with pytest.raises(KeyError) as excinfo:
        repo.get_course("robotics-w1")

    message = str(excinfo.value)
    assert "robotics-w1" in message
    assert AGENTIC in message  # known ids listed -> helpful
    assert ANALYTICS in message


def test_get_assignment_raises_keyerror_for_unknown_assignment_id():
    with pytest.raises(KeyError) as excinfo:
        repo.get_assignment(AGENTIC, "a99")

    message = str(excinfo.value)
    assert "a99" in message
    assert AGENTIC in message


def test_get_assignment_raises_keyerror_for_unknown_course_id():
    with pytest.raises(KeyError):
        repo.get_assignment("ghost-course", "a1")


def test_scholarship_and_career_lookups_raise_keyerror_for_unknown_course():
    with pytest.raises(KeyError):
        repo.get_scholarship_benefits("ghost-course")
    with pytest.raises(KeyError):
        repo.get_career_paths("ghost-course")


# --- formatted string lookups -------------------------------------------------


def test_get_scholarship_benefits_returns_formatted_string():
    benefits = repo.get_scholarship_benefits(AGENTIC)

    assert isinstance(benefits, str)
    assert benefits.startswith("- ")
    assert "\n- " in benefits  # one perk per line
    assert "tuition" in benefits.lower()


def test_get_career_paths_returns_formatted_string():
    career_paths = repo.get_career_paths(ANALYTICS)

    assert isinstance(career_paths, str)
    assert career_paths.startswith("- ")
    assert "\n- " in career_paths


def test_scholarship_benefits_supports_dict_shaped_perks(tmp_path):
    course = json.loads(REAL_DATA_FILE.read_text(encoding="utf-8"))["courses"][0]
    course["scholarship_benefits"] = {
        "tuition_waiver": "100%",
        "stipend": "monthly",
    }
    target = _write_courses(tmp_path, [course])

    benefits = CourseRepo(target).get_scholarship_benefits(AGENTIC)

    assert "- tuition_waiver: 100%" in benefits
    assert "- stipend: monthly" in benefits


# --- FR-2: deleting a course changes answers with zero code change -----------


@pytest.mark.parametrize("deleted", [AGENTIC, ANALYTICS])
def test_deleting_course_from_file_changes_list_and_get(tmp_path, deleted):
    survivor = ANALYTICS if deleted == AGENTIC else AGENTIC
    target = _copy_minus_course(tmp_path, deleted)
    scoped_repo = CourseRepo(target)

    assert [c["id"] for c in scoped_repo.list_courses()] == [survivor]
    with pytest.raises(KeyError):
        scoped_repo.get_course(deleted)
    with pytest.raises(KeyError):
        scoped_repo.get_scholarship_benefits(deleted)
    # The survivor still answers fully.
    assert scoped_repo.get_course(survivor)["title"]
    assert scoped_repo.get_assignment(survivor, "a1")["id"] == "a1"


def test_repo_rereads_file_on_every_access_no_stale_cache(tmp_path):
    data = json.loads(REAL_DATA_FILE.read_text(encoding="utf-8"))
    target = _write_courses(tmp_path, data["courses"])
    scoped_repo = CourseRepo(target)

    assert len(scoped_repo.list_courses()) == 2

    # Edit the same file underneath the same repo instance.
    target.write_text(
        json.dumps(
            {"courses": [c for c in data["courses"] if c["id"] != ANALYTICS]},
            indent=2,
        ),
        encoding="utf-8",
    )

    assert [c["id"] for c in scoped_repo.list_courses()] == [AGENTIC]


# --- missing / corrupt data raises CourseDataError (NFR-1 pattern) -----------


def test_missing_file_raises_course_data_error_at_construction(tmp_path):
    absent = tmp_path / "courses.json"

    with pytest.raises(CourseDataError) as excinfo:
        CourseRepo(absent)

    message = str(excinfo.value)
    assert "not found" in message.lower()
    assert str(absent) in message  # says where
    assert "courses.json" in message  # says what is needed


def test_file_deleted_after_construction_raises_course_data_error_on_read(
    tmp_path,
):
    target = _copy_minus_course(tmp_path, ANALYTICS)
    scoped_repo = CourseRepo(target)
    target.unlink()

    with pytest.raises(CourseDataError) as excinfo:
        scoped_repo.list_courses()

    assert str(target) in str(excinfo.value)


def test_corrupt_json_raises_course_data_error_with_reason(tmp_path):
    target = tmp_path / "courses.json"
    target.write_text('{"courses": [ oops', encoding="utf-8")

    with pytest.raises(CourseDataError) as excinfo:
        CourseRepo(target)

    message = str(excinfo.value)
    assert "valid JSON" in message
    assert str(target) in message


def test_wrong_shape_json_raises_course_data_error(tmp_path):
    target = tmp_path / "courses.json"
    target.write_text('{"catalogue": []}', encoding="utf-8")

    with pytest.raises(CourseDataError) as excinfo:
        CourseRepo(target)

    assert "'courses'" in str(excinfo.value)


def test_course_entry_missing_required_fields_raises_course_data_error(tmp_path):
    target = tmp_path / "courses.json"
    target.write_text(
        json.dumps({"courses": [{"id": "half-defined"}]}), encoding="utf-8"
    )

    with pytest.raises(CourseDataError) as excinfo:
        CourseRepo(target)

    message = str(excinfo.value)
    assert "title" in message and "schedule" in message
    assert str(target) in message


# --- module-level singleton ----------------------------------------------------


def test_repo_singleton_points_at_project_data_file():
    expected = PROJECT_ROOT / "data" / "courses.json"

    assert repo.path == expected
    assert isinstance(repo, CourseRepo)
    assert len(repo.list_courses()) == 2

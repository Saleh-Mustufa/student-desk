"""File-backed course repository (FR-2).

All course facts live in ``data/courses.json`` — the single source of truth.
``CourseRepo`` re-reads the file on every access, so editing or deleting a
course changes what the Desk can answer with zero code change. Lookups for
unknown ids raise ``KeyError`` inside the loader; the agent tools (later task)
translate those into sentences the model can act on. A missing or corrupt
data file raises ``CourseDataError`` with the fix — the friendly-startup-error
pattern from NFR-1.
"""

from __future__ import annotations

import json
from pathlib import Path


class CourseDataError(Exception):
    """Raised when ``courses.json`` is missing, unreadable, or malformed."""


def _format_perks(value: object) -> str:
    """Render a list (or dict) of perks as one readable line per entry."""
    if isinstance(value, dict):
        return "\n".join(f"- {key}: {item}" for key, item in value.items())
    return "\n".join(f"- {item}" for item in value)


class CourseRepo:
    """Reads course facts from a ``courses.json`` file, fresh on every access.

    Deliberately no cache: the file is re-parsed for each call so a course
    deleted from the file disappears from every answer with zero code change.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        # Fail fast at construction on missing/corrupt data (NFR-1 pattern);
        # every later access re-validates via ``_load``.
        self._load()

    def _load(self) -> list[dict]:
        """Parse and validate the data file, raising ``CourseDataError`` with the fix."""
        if not self.path.is_file():
            raise CourseDataError(
                f"Course data file not found: {self.path}. Create or restore a "
                "courses.json file at that path and restart the Desk."
            )
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CourseDataError(
                f"Course data file is not valid JSON: {self.path}. Fix the JSON "
                f"syntax ({exc.msg} on line {exc.lineno}) and restart the Desk."
            ) from exc

        if not isinstance(data, dict) or not isinstance(data.get("courses"), list):
            raise CourseDataError(
                "Course data file must be a JSON object with a 'courses' list: "
                f"{self.path}."
            )

        for index, course in enumerate(data["courses"]):
            if not isinstance(course, dict):
                raise CourseDataError(
                    f"Course entry {index} must be a JSON object: {self.path}."
                )
            missing = [
                key for key in ("id", "title", "schedule") if not course.get(key)
            ]
            if missing:
                raise CourseDataError(
                    f"Course entry {index} in {self.path} is missing required "
                    f"field(s): {', '.join(missing)}."
                )
        return data["courses"]

    def _require_course(self, courses: list[dict], course_id: str) -> dict:
        for course in courses:
            if course.get("id") == course_id:
                return course
        known = ", ".join(str(course.get("id", "?")) for course in courses)
        raise KeyError(
            f"No course with id {course_id!r} (data file: {self.path}). "
            f"Known course ids: {known}."
        )

    def list_courses(self) -> list[dict]:
        """Return every course as ``{"id", "title", "schedule"}``."""
        return [
            {"id": course["id"], "title": course["title"], "schedule": course["schedule"]}
            for course in self._load()
        ]

    def get_course(self, course_id: str) -> dict:
        """Return the full course record (policies, assignments, perks, paths)."""
        return dict(self._require_course(self._load(), course_id))

    def get_assignment(self, course_id: str, assignment_id: str) -> dict:
        """Return one assignment of one course; ``KeyError`` on unknown ids."""
        course = self._require_course(self._load(), course_id)
        assignments = course.get("assignments", [])
        for assignment in assignments:
            if assignment.get("id") == assignment_id:
                return dict(assignment)
        known = ", ".join(
            str(assignment.get("id", "?")) for assignment in assignments
        )
        raise KeyError(
            f"No assignment with id {assignment_id!r} in course {course_id!r}. "
            f"Known assignment ids: {known}."
        )

    def get_scholarship_benefits(self, course_id: str) -> str:
        """Return the course's scholarship perks as a formatted string."""
        course = self._require_course(self._load(), course_id)
        return _format_perks(course.get("scholarship_benefits", []))

    def get_career_paths(self, course_id: str) -> str:
        """Return the roles the course prepares for as a formatted string."""
        course = self._require_course(self._load(), course_id)
        return _format_perks(course.get("career_paths", []))


PROJECT_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "courses.json"

repo = CourseRepo(PROJECT_DATA_FILE)

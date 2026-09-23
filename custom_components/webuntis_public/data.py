from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .const import (
    TITLE_SUBJECT_ROOM,
    TITLE_SUBJECT_ROOM_TEACHER,
    TITLE_SUBJECT_TEACHER,
)

_POSITION_FALLBACK_TYPES = {
    "position1": "SUBJECT",
    "position2": "ROOM",
    "position3": "TEACHER",
    "position4": "CLASS",
}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _element_name(element: dict[str, Any], element_type: str) -> str:
    if element_type == "SUBJECT":
        candidates = ("longName", "displayName", "shortName", "name")
    elif element_type == "TEACHER":
        candidates = ("displayName", "longName", "shortName", "name")
    else:
        candidates = ("shortName", "displayName", "longName", "name")

    for key in candidates:
        value = element.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _append_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)


def _extract_elements(entry: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {
        "SUBJECT": {"current": [], "removed": []},
        "TEACHER": {"current": [], "removed": []},
        "ROOM": {"current": [], "removed": []},
        "CLASS": {"current": [], "removed": []},
        "STUDENT": {"current": [], "removed": []},
    }

    for position, fallback_type in _POSITION_FALLBACK_TYPES.items():
        for item in as_list(entry.get(position)):
            if not isinstance(item, dict):
                continue
            for state in ("current", "removed"):
                for raw_element in as_list(item.get(state)):
                    if not isinstance(raw_element, dict):
                        continue
                    element_type = str(raw_element.get("type") or fallback_type).upper()
                    if element_type not in result:
                        continue
                    _append_unique(
                        result[element_type][state],
                        _element_name(raw_element, element_type),
                    )
    return result


def _text_values(entry: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(label: str, value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text or text in seen:
            return
        seen.add(text)
        result.append((label, text))

    add("lesson_info", entry.get("lessonInfo"))
    add("substitution", entry.get("substitutionText"))
    add("info", entry.get("periodText"))

    text_type_labels = {
        "LESSON_INFO": "lesson_info",
        "PERIOD_INFO": "info",
        "SUBSTITUTION_TEXT": "substitution",
    }
    for text_item in as_list(entry.get("texts")):
        if not isinstance(text_item, dict):
            continue
        label = text_type_labels.get(str(text_item.get("type") or "").upper(), "info")
        add(label, text_item.get("text"))

    return result


def _parse_datetime(value: Any, tz) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _join(values: tuple[str, ...] | list[str]) -> str:
    return ", ".join(value for value in values if value)


@dataclass(frozen=True, slots=True)
class WebUntisLesson:
    start: datetime
    end: datetime
    subject: str
    status: str
    subjects: tuple[str, ...]
    old_subjects: tuple[str, ...]
    teachers: tuple[str, ...]
    old_teachers: tuple[str, ...]
    rooms: tuple[str, ...]
    old_rooms: tuple[str, ...]
    texts: tuple[tuple[str, str], ...]
    raw_count: int

    @property
    def cancelled(self) -> bool:
        return self.status == "CANCEL"

    @property
    def changed(self) -> bool:
        if self.status and self.status not in {"REGULAR", "STANDARD"}:
            return True
        if self.old_subjects and self.subjects and set(self.old_subjects) != set(self.subjects):
            return True
        if self.old_teachers and self.teachers and set(self.old_teachers) != set(self.teachers):
            return True
        if self.old_rooms and self.rooms and set(self.old_rooms) != set(self.rooms):
            return True
        return any(label == "substitution" for label, _value in self.texts)

    @property
    def summary(self) -> str:
        return self.subject

    def formatted_summary(self, title_format: str, *, subject: str | None = None) -> str:
        parts: list[str] = [subject or self.subject]
        if title_format in {TITLE_SUBJECT_ROOM, TITLE_SUBJECT_ROOM_TEACHER} and self.room:
            parts.append(self.room)
        if title_format in {TITLE_SUBJECT_TEACHER, TITLE_SUBJECT_ROOM_TEACHER} and self.teacher:
            parts.append(self.teacher)
        return " · ".join(parts)

    @property
    def room(self) -> str | None:
        value = _join(self.rooms) or _join(self.old_rooms)
        return value or None

    @property
    def teacher(self) -> str | None:
        value = _join(self.teachers) or _join(self.old_teachers)
        return value or None

    @property
    def status_label(self) -> str | None:
        """Return a stable, language-neutral status key for UI translation."""
        if not self.status or self.status in {"REGULAR", "STANDARD"}:
            return None
        return {
            "CANCEL": "cancelled",
            "ADDITIONAL": "additional",
            "CHANGED": "changed",
        }.get(self.status, self.status.lower())



def parse_lessons(
    raw_entries: list[dict[str, Any]],
    start_local: datetime,
    end_local: datetime,
    tz,
) -> list[WebUntisLesson]:
    """Parse raw WebUntis entries and merge technical duplicates."""
    grouped: dict[tuple[datetime, datetime, str, str], dict[str, Any]] = {}

    for entry in raw_entries:
        duration = entry.get("duration") or {}
        start = _parse_datetime(duration.get("start"), tz)
        end = _parse_datetime(duration.get("end"), tz)
        if start is None or end is None:
            continue
        if end <= start_local or start >= end_local:
            continue

        elements = _extract_elements(entry)
        subjects = elements["SUBJECT"]["current"]
        old_subjects = elements["SUBJECT"]["removed"]
        status = str(entry.get("status") or "").upper()
        subject = _join(subjects) or _join(old_subjects) or "lesson"

        key = (start, end, subject, status)
        item = grouped.get(key)
        if item is None:
            item = {
                "start": start,
                "end": end,
                "status": status,
                "subjects": [],
                "old_subjects": [],
                "teachers": [],
                "old_teachers": [],
                "rooms": [],
                "old_rooms": [],
                "texts": [],
                "raw_count": 0,
            }
            grouped[key] = item

        item["raw_count"] += 1
        for value in subjects:
            _append_unique(item["subjects"], value)
        for value in old_subjects:
            _append_unique(item["old_subjects"], value)
        for value in elements["TEACHER"]["current"]:
            _append_unique(item["teachers"], value)
        for value in elements["TEACHER"]["removed"]:
            _append_unique(item["old_teachers"], value)
        for value in elements["ROOM"]["current"]:
            _append_unique(item["rooms"], value)
        for value in elements["ROOM"]["removed"]:
            _append_unique(item["old_rooms"], value)
        for text_item in _text_values(entry):
            if text_item not in item["texts"]:
                item["texts"].append(text_item)

    lessons = [
        WebUntisLesson(
            start=item["start"],
            end=item["end"],
            subject=_join(item["subjects"]) or _join(item["old_subjects"]) or "lesson",
            status=item["status"],
            subjects=tuple(item["subjects"]),
            old_subjects=tuple(item["old_subjects"]),
            teachers=tuple(item["teachers"]),
            old_teachers=tuple(item["old_teachers"]),
            rooms=tuple(item["rooms"]),
            old_rooms=tuple(item["old_rooms"]),
            texts=tuple(item["texts"]),
            raw_count=item["raw_count"],
        )
        for item in grouped.values()
    ]
    lessons.sort(key=lambda lesson: (lesson.start, lesson.end, lesson.subject))
    return lessons

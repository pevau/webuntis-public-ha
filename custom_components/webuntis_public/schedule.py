from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .data import WebUntisLesson


def local_now(hass: HomeAssistant) -> datetime:
    """Return current time in the Home Assistant timezone."""
    tz = dt_util.get_time_zone(hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
    return dt_util.now().astimezone(tz)


def day_bounds(hass: HomeAssistant, offset_days: int = 0) -> tuple[datetime, datetime]:
    """Return local start/end timestamps for a calendar day."""
    now = local_now(hass)
    start = (now + timedelta(days=offset_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=1)


def active_lessons(lessons: Iterable[WebUntisLesson]) -> list[WebUntisLesson]:
    """Return lessons that are not cancelled."""
    return [lesson for lesson in lessons if not lesson.cancelled]


def scheduled_slots(
    lessons: Iterable[WebUntisLesson],
) -> list[tuple[datetime, datetime, list[WebUntisLesson]]]:
    """Group all timetable entries by their exact time slot, including cancellations."""
    grouped: dict[tuple[datetime, datetime], list[WebUntisLesson]] = {}
    for lesson in lessons:
        grouped.setdefault((lesson.start, lesson.end), []).append(lesson)
    return [
        (start, end, grouped[(start, end)])
        for start, end in sorted(grouped, key=lambda value: (value[0], value[1]))
    ]


def unique_slots(
    lessons: Iterable[WebUntisLesson],
) -> list[tuple[datetime, datetime, list[WebUntisLesson]]]:
    """Group active parallel lessons that share exactly the same time slot."""
    return scheduled_slots(active_lessons(lessons))


def slot_cancelled(
    slot: tuple[datetime, datetime, list[WebUntisLesson]],
) -> bool:
    """Return whether all timetable entries in a slot are cancelled."""
    return bool(slot[2]) and all(lesson.cancelled for lesson in slot[2])


def current_slot(
    lessons: Iterable[WebUntisLesson], now: datetime
) -> tuple[datetime, datetime, list[WebUntisLesson]] | None:
    """Return the current active lesson slot."""
    candidates = [
        slot for slot in unique_slots(lessons) if slot[0] <= now < slot[1]
    ]
    return min(candidates, key=lambda slot: (slot[0], slot[1]), default=None)


def next_slot(
    lessons: Iterable[WebUntisLesson], now: datetime
) -> tuple[datetime, datetime, list[WebUntisLesson]] | None:
    """Return current slot, if active, otherwise the next future slot."""
    candidates = [slot for slot in unique_slots(lessons) if slot[1] > now]
    return min(candidates, key=lambda slot: (slot[0], slot[1]), default=None)


def school_status(lessons: Iterable[WebUntisLesson], now: datetime) -> str:
    """Return the current school-day status for active lessons."""
    slots = unique_slots(lessons)
    if not slots:
        return "school_free"

    start = min(slot[0] for slot in slots)
    end = max(slot[1] for slot in slots)

    if now < start:
        return "before_school"
    if now >= end:
        return "after_school"
    if current_slot(lessons, now) is not None:
        return "lesson"
    return "break"


def slot_subjects(slot: tuple[datetime, datetime, list[WebUntisLesson]]) -> str:
    """Return all subjects in a slot, preserving source order."""
    values: list[str] = []
    for lesson in slot[2]:
        if lesson.subject and lesson.subject not in values:
            values.append(lesson.subject)
    return " / ".join(values)


def slot_rooms(slot: tuple[datetime, datetime, list[WebUntisLesson]]) -> str | None:
    values: list[str] = []
    for lesson in slot[2]:
        if lesson.room:
            for value in (part.strip() for part in lesson.room.split(",")):
                if value and value not in values:
                    values.append(value)
    return ", ".join(values) or None


def slot_teachers(slot: tuple[datetime, datetime, list[WebUntisLesson]]) -> str | None:
    values: list[str] = []
    for lesson in slot[2]:
        if lesson.teacher:
            for value in (part.strip() for part in lesson.teacher.split(",")):
                if value and value not in values:
                    values.append(value)
    return ", ".join(values) or None


def slot_changed(slot: tuple[datetime, datetime, list[WebUntisLesson]]) -> bool:
    return any(lesson.changed for lesson in slot[2])


def _merged_instruction_intervals(
    lessons: Iterable[WebUntisLesson],
) -> list[tuple[datetime, datetime]]:
    """Return active lesson intervals merged to remove parallel overlaps."""
    intervals = [(start, end) for start, end, _items in unique_slots(lessons)]
    if not intervals:
        return []

    intervals.sort(key=lambda value: (value[0], value[1]))
    merged: list[list[datetime]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def instruction_total_seconds(lessons: Iterable[WebUntisLesson]) -> int:
    """Return total scheduled instruction seconds, excluding breaks/overlaps."""
    return max(
        0,
        int(
            sum(
                (end - start).total_seconds()
                for start, end in _merged_instruction_intervals(lessons)
            )
        ),
    )


def instruction_elapsed_seconds(
    lessons: Iterable[WebUntisLesson], now: datetime
) -> int:
    """Return elapsed instruction seconds up to now, excluding breaks/overlaps."""
    seconds = 0.0
    for start, end in _merged_instruction_intervals(lessons):
        if now <= start:
            continue
        seconds += (min(now, end) - start).total_seconds()
    return max(0, int(seconds))


def remaining_instruction_minutes(
    lessons: Iterable[WebUntisLesson], now: datetime
) -> int:
    """Return remaining scheduled lesson minutes, excluding breaks and overlaps."""
    total = instruction_total_seconds(lessons)
    elapsed = instruction_elapsed_seconds(lessons, now)
    remaining = max(0, total - elapsed)
    return int((remaining + 59) // 60)

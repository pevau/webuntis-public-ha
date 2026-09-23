from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.webuntis_public.data import WebUntisLesson
from custom_components.webuntis_public import schedule


UTC = timezone.utc
BASE = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)


def _lesson(
    start_minutes: int,
    end_minutes: int,
    *,
    subject: str = "Mathematik",
    status: str = "REGULAR",
    teachers: tuple[str, ...] = (),
    rooms: tuple[str, ...] = (),
    old_teachers: tuple[str, ...] = (),
    texts: tuple[tuple[str, str], ...] = (),
) -> WebUntisLesson:
    return WebUntisLesson(
        start=BASE + timedelta(minutes=start_minutes),
        end=BASE + timedelta(minutes=end_minutes),
        subject=subject,
        status=status,
        subjects=(subject,),
        old_subjects=(),
        teachers=teachers,
        old_teachers=old_teachers,
        rooms=rooms,
        old_rooms=(),
        texts=texts,
        raw_count=1,
    )


def test_active_lessons_filters_cancelled_entries() -> None:
    active = _lesson(0, 45)
    cancelled = _lesson(45, 90, subject="Deutsch", status="CANCEL")

    assert schedule.active_lessons([active, cancelled]) == [active]


def test_scheduled_slots_groups_parallel_entries() -> None:
    math = _lesson(0, 45, subject="Mathematik")
    physics = _lesson(0, 45, subject="Physik")
    german = _lesson(60, 105, subject="Deutsch")

    slots = schedule.scheduled_slots([german, math, physics])

    assert len(slots) == 2
    assert slots[0][2] == [math, physics]
    assert slots[1][2] == [german]


def test_unique_slots_excludes_cancelled_entries() -> None:
    active = _lesson(0, 45)
    cancelled = _lesson(45, 90, subject="Deutsch", status="CANCEL")

    slots = schedule.unique_slots([active, cancelled])

    assert len(slots) == 1
    assert slots[0][2] == [active]


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["CANCEL"], True),
        (["CANCEL", "CANCEL"], True),
        (["CANCEL", "REGULAR"], False),
    ],
)
def test_slot_cancelled(statuses: list[str], expected: bool) -> None:
    items = [
        _lesson(0, 45, subject=f"Fach {index}", status=status)
        for index, status in enumerate(statuses)
    ]
    slot = (items[0].start, items[0].end, items)

    assert schedule.slot_cancelled(slot) is expected


def test_current_slot_includes_start_and_excludes_end() -> None:
    lesson = _lesson(0, 45)

    assert schedule.current_slot([lesson], lesson.start) is not None
    assert schedule.current_slot([lesson], lesson.end) is None


def test_next_slot_returns_current_slot_while_lesson_is_running() -> None:
    first = _lesson(0, 45, subject="Mathematik")
    second = _lesson(60, 105, subject="Deutsch")
    now = BASE + timedelta(minutes=20)

    slot = schedule.next_slot([first, second], now)

    assert slot is not None
    assert slot[2] == [first]


def test_next_slot_skips_finished_slot() -> None:
    first = _lesson(0, 45, subject="Mathematik")
    second = _lesson(60, 105, subject="Deutsch")
    now = BASE + timedelta(minutes=50)

    slot = schedule.next_slot([first, second], now)

    assert slot is not None
    assert slot[2] == [second]


def test_slot_subjects_preserves_order_and_removes_duplicates() -> None:
    slot = (
        BASE,
        BASE + timedelta(minutes=45),
        [
            _lesson(0, 45, subject="Mathematik"),
            _lesson(0, 45, subject="Physik"),
            _lesson(0, 45, subject="Mathematik"),
        ],
    )

    assert schedule.slot_subjects(slot) == "Mathematik / Physik"


def test_slot_rooms_merges_and_deduplicates_rooms() -> None:
    slot = (
        BASE,
        BASE + timedelta(minutes=45),
        [
            _lesson(0, 45, rooms=("A101", "A102")),
            _lesson(0, 45, subject="Physik", rooms=("A102", "B201")),
        ],
    )

    assert schedule.slot_rooms(slot) == "A101, A102, B201"


def test_slot_teachers_merges_and_deduplicates_teachers() -> None:
    slot = (
        BASE,
        BASE + timedelta(minutes=45),
        [
            _lesson(0, 45, teachers=("Anna Beispiel", "Max Mustermann")),
            _lesson(
                0,
                45,
                subject="Physik",
                teachers=("Max Mustermann", "Eva Beispiel"),
            ),
        ],
    )

    assert schedule.slot_teachers(slot) == (
        "Anna Beispiel, Max Mustermann, Eva Beispiel"
    )


def test_slot_changed_is_true_when_one_parallel_lesson_changed() -> None:
    regular = _lesson(0, 45)
    changed = _lesson(0, 45, subject="Physik", status="CHANGED")
    slot = (BASE, BASE + timedelta(minutes=45), [regular, changed])

    assert schedule.slot_changed(slot) is True


def test_instruction_total_seconds_excludes_breaks_overlaps_and_cancellations() -> None:
    lessons = [
        _lesson(0, 60),
        _lesson(30, 90, subject="Parallelfach"),
        _lesson(120, 180, subject="Deutsch"),
        _lesson(180, 225, subject="Ausfall", status="CANCEL"),
    ]

    assert schedule.instruction_total_seconds(lessons) == 9000


@pytest.mark.parametrize(
    ("now_minutes", "expected"),
    [
        (-10, 0),
        (30, 1800),
        (90, 5400),
        (105, 5400),
        (150, 7200),
        (200, 9000),
    ],
)
def test_instruction_elapsed_seconds(now_minutes: int, expected: int) -> None:
    lessons = [
        _lesson(0, 60),
        _lesson(30, 90, subject="Parallelfach"),
        _lesson(120, 180, subject="Deutsch"),
    ]

    assert (
        schedule.instruction_elapsed_seconds(
            lessons,
            BASE + timedelta(minutes=now_minutes),
        )
        == expected
    )


@pytest.mark.parametrize(
    ("now_minutes", "expected_minutes"),
    [
        (-1, 150),
        (30, 120),
        (90, 60),
        (150, 30),
        (181, 0),
    ],
)
def test_remaining_instruction_minutes(
    now_minutes: int,
    expected_minutes: int,
) -> None:
    lessons = [
        _lesson(0, 60),
        _lesson(30, 90, subject="Parallelfach"),
        _lesson(120, 180, subject="Deutsch"),
    ]

    assert schedule.remaining_instruction_minutes(
        lessons,
        BASE + timedelta(minutes=now_minutes),
    ) == expected_minutes


def test_remaining_instruction_minutes_rounds_up_partial_minute() -> None:
    lesson = _lesson(0, 45)
    now = BASE + timedelta(minutes=44, seconds=1)

    assert schedule.remaining_instruction_minutes([lesson], now) == 1


def test_day_bounds_uses_home_assistant_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        schedule.dt_util,
        "now",
        lambda: datetime(2026, 9, 23, 13, 15, tzinfo=UTC),
    )
    hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))

    start, end = schedule.day_bounds(hass, offset_days=1)

    assert start.isoformat() == "2026-09-24T00:00:00+02:00"
    assert end.isoformat() == "2026-09-25T00:00:00+02:00"

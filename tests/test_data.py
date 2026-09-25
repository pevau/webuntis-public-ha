from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.webuntis_public.const import (
    TITLE_SUBJECT,
    TITLE_SUBJECT_ROOM,
    TITLE_SUBJECT_ROOM_TEACHER,
    TITLE_SUBJECT_TEACHER,
)
from custom_components.webuntis_public.data import WebUntisLesson, as_list, parse_lessons


UTC = timezone.utc
DAY_START = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
DAY_END = DAY_START + timedelta(days=1)


def test_parse_lessons_converts_utc_across_dst_start() -> None:
    tz = ZoneInfo("Europe/Vienna")
    entry = _entry(
        start="2026-03-29T00:30:00+00:00",
        end="2026-03-29T01:30:00+00:00",
        subject=_element("SUBJECT", long_name="DST"),
    )

    lessons = parse_lessons(
        [entry],
        datetime(2026, 3, 29, 0, 0, tzinfo=tz),
        datetime(2026, 3, 29, 5, 0, tzinfo=tz),
        tz,
    )

    assert len(lessons) == 1
    assert lessons[0].start.isoformat() == "2026-03-29T01:30:00+01:00"
    assert lessons[0].end.isoformat() == "2026-03-29T03:30:00+02:00"


def test_parse_lessons_converts_utc_across_dst_end() -> None:
    tz = ZoneInfo("Europe/Vienna")
    entries = [
        _entry(
            start="2026-10-25T00:30:00+00:00",
            end="2026-10-25T00:45:00+00:00",
            subject=_element("SUBJECT", long_name="DST first"),
        ),
        _entry(
            start="2026-10-25T01:30:00+00:00",
            end="2026-10-25T01:45:00+00:00",
            subject=_element("SUBJECT", long_name="DST second"),
        ),
    ]

    lessons = parse_lessons(
        entries,
        datetime(2026, 10, 25, 0, 0, tzinfo=tz),
        datetime(2026, 10, 25, 5, 0, tzinfo=tz),
        tz,
    )

    assert [lesson.start.isoformat() for lesson in lessons] == [
        "2026-10-25T02:30:00+02:00",
        "2026-10-25T02:30:00+01:00",
    ]
    assert lessons[0].start.fold == 0
    assert lessons[1].start.fold == 1


def _element(
    element_type: str,
    *,
    long_name: str | None = None,
    display_name: str | None = None,
    short_name: str | None = None,
    name: str | None = None,
) -> dict[str, str]:
    result = {"type": element_type}
    if long_name is not None:
        result["longName"] = long_name
    if display_name is not None:
        result["displayName"] = display_name
    if short_name is not None:
        result["shortName"] = short_name
    if name is not None:
        result["name"] = name
    return result


def _entry(
    *,
    start: datetime | str = datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
    end: datetime | str = datetime(2026, 9, 23, 8, 45, tzinfo=UTC),
    subject: dict[str, str] | None = None,
    old_subject: dict[str, str] | None = None,
    teacher: dict[str, str] | None = None,
    old_teacher: dict[str, str] | None = None,
    room: dict[str, str] | None = None,
    old_room: dict[str, str] | None = None,
    status: str = "REGULAR",
    substitution_text: str | None = None,
    lesson_info: str | None = None,
) -> dict:
    def iso(value: datetime | str) -> str:
        return value.isoformat() if isinstance(value, datetime) else value

    entry: dict = {
        "duration": {"start": iso(start), "end": iso(end)},
        "status": status,
        "position1": [
            {
                "current": [subject] if subject else [],
                "removed": [old_subject] if old_subject else [],
            }
        ],
        "position2": [
            {
                "current": [room] if room else [],
                "removed": [old_room] if old_room else [],
            }
        ],
        "position3": [
            {
                "current": [teacher] if teacher else [],
                "removed": [old_teacher] if old_teacher else [],
            }
        ],
    }
    if substitution_text is not None:
        entry["substitutionText"] = substitution_text
    if lesson_info is not None:
        entry["lessonInfo"] = lesson_info
    return entry


def _parse(*entries: dict) -> list[WebUntisLesson]:
    return parse_lessons(list(entries), DAY_START, DAY_END, UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        ([1, 2], [1, 2]),
        ((1, 2), [1, 2]),
        ("one", ["one"]),
    ],
)
def test_as_list_normalizes_supported_values(value, expected) -> None:
    assert as_list(value) == expected


def test_parse_regular_lesson() -> None:
    lessons = _parse(
        _entry(
            subject=_element("SUBJECT", long_name="Mathematik", short_name="M"),
            teacher=_element("TEACHER", long_name="Max Mustermann", short_name="MM"),
            room=_element("ROOM", short_name="A101", long_name="Raum A101"),
        )
    )

    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson.subject == "Mathematik"
    assert lesson.teacher == "Max Mustermann"
    assert lesson.room == "A101"
    assert lesson.status == "REGULAR"
    assert lesson.raw_count == 1
    assert lesson.changed is False
    assert lesson.cancelled is False


def test_teacher_prefers_long_name_over_display_name_and_short_name() -> None:
    lesson = _parse(
        _entry(
            subject=_element("SUBJECT", long_name="Deutsch"),
            teacher=_element(
                "TEACHER",
                long_name="Anna Beispiel",
                display_name="AB",
                short_name="A.B.",
            ),
        )
    )[0]

    assert lesson.teacher == "Anna Beispiel"


def test_teacher_falls_back_to_display_name() -> None:
    lesson = _parse(
        _entry(
            subject=_element("SUBJECT", long_name="Deutsch"),
            teacher=_element("TEACHER", display_name="AB", short_name="A.B."),
        )
    )[0]

    assert lesson.teacher == "AB"


def test_subject_prefers_long_name() -> None:
    lesson = _parse(
        _entry(
            subject=_element(
                "SUBJECT",
                long_name="Betriebswirtschaft",
                display_name="BWL",
                short_name="BW",
            )
        )
    )[0]

    assert lesson.subject == "Betriebswirtschaft"


def test_room_prefers_short_name() -> None:
    lesson = _parse(
        _entry(
            subject=_element("SUBJECT", long_name="Englisch"),
            room=_element(
                "ROOM",
                short_name="B204",
                display_name="Raum B204",
                long_name="Gebäude B Raum 204",
            ),
        )
    )[0]

    assert lesson.room == "B204"


def test_entry_outside_requested_range_is_ignored() -> None:
    lessons = _parse(
        _entry(
            start=datetime(2026, 9, 22, 8, 0, tzinfo=UTC),
            end=datetime(2026, 9, 22, 8, 45, tzinfo=UTC),
            subject=_element("SUBJECT", long_name="Mathematik"),
        )
    )

    assert lessons == []


def test_entry_with_invalid_datetime_is_ignored() -> None:
    lessons = _parse(
        _entry(
            start="not-a-date",
            subject=_element("SUBJECT", long_name="Mathematik"),
        )
    )

    assert lessons == []


def test_technical_duplicates_are_merged() -> None:
    first = _entry(
        subject=_element("SUBJECT", long_name="Mathematik"),
        teacher=_element("TEACHER", long_name="Lehrer Eins"),
        room=_element("ROOM", short_name="A101"),
        lesson_info="Bitte Taschenrechner mitbringen",
    )
    second = _entry(
        subject=_element("SUBJECT", long_name="Mathematik"),
        teacher=_element("TEACHER", long_name="Lehrer Zwei"),
        room=_element("ROOM", short_name="A102"),
        lesson_info="Bitte Taschenrechner mitbringen",
    )

    lessons = _parse(first, second)

    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson.raw_count == 2
    assert lesson.teachers == ("Lehrer Eins", "Lehrer Zwei")
    assert lesson.rooms == ("A101", "A102")
    assert lesson.texts == (("lesson_info", "Bitte Taschenrechner mitbringen"),)


def test_cancelled_lesson_uses_removed_subject_as_fallback() -> None:
    lesson = _parse(
        _entry(
            subject=None,
            old_subject=_element("SUBJECT", long_name="Physik"),
            status="CANCEL",
        )
    )[0]

    assert lesson.subject == "Physik"
    assert lesson.cancelled is True
    assert lesson.changed is True
    assert lesson.status_label == "cancelled"


def test_regular_lesson_with_changed_teacher_is_marked_changed() -> None:
    lesson = _parse(
        _entry(
            subject=_element("SUBJECT", long_name="Deutsch"),
            teacher=_element("TEACHER", long_name="Neue Lehrkraft"),
            old_teacher=_element("TEACHER", long_name="Alte Lehrkraft"),
        )
    )[0]

    assert lesson.changed is True


def test_substitution_text_marks_lesson_changed() -> None:
    lesson = _parse(
        _entry(
            subject=_element("SUBJECT", long_name="Deutsch"),
            substitution_text="Vertretung",
        )
    )[0]

    assert ("substitution", "Vertretung") in lesson.texts
    assert lesson.changed is True


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("", None),
        ("REGULAR", None),
        ("STANDARD", None),
        ("CANCEL", "cancelled"),
        ("ADDITIONAL", "additional"),
        ("CHANGED", "changed"),
        ("SPECIAL", "special"),
    ],
)
def test_status_label(status: str, expected: str | None) -> None:
    lesson = WebUntisLesson(
        start=datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
        end=datetime(2026, 9, 23, 8, 45, tzinfo=UTC),
        subject="Mathematik",
        status=status,
        subjects=("Mathematik",),
        old_subjects=(),
        teachers=("Max Mustermann",),
        old_teachers=(),
        rooms=("A101",),
        old_rooms=(),
        texts=(),
        raw_count=1,
    )

    assert lesson.status_label == expected


@pytest.mark.parametrize(
    ("title_format", "expected"),
    [
        (TITLE_SUBJECT, "Mathematik"),
        (TITLE_SUBJECT_ROOM, "Mathematik · A101"),
        (TITLE_SUBJECT_TEACHER, "Mathematik · Max Mustermann"),
        (
            TITLE_SUBJECT_ROOM_TEACHER,
            "Mathematik · A101 · Max Mustermann",
        ),
    ],
)
def test_formatted_summary(title_format: str, expected: str) -> None:
    lesson = WebUntisLesson(
        start=datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
        end=datetime(2026, 9, 23, 8, 45, tzinfo=UTC),
        subject="Mathematik",
        status="REGULAR",
        subjects=("Mathematik",),
        old_subjects=(),
        teachers=("Max Mustermann",),
        old_teachers=(),
        rooms=("A101",),
        old_rooms=(),
        texts=(),
        raw_count=1,
    )

    assert lesson.formatted_summary(title_format) == expected


def test_unnamed_subject_falls_back_to_generic_lesson() -> None:
    lesson = _parse(
        _entry(subject=_element("SUBJECT"))
    )[0]

    assert lesson.subject == "lesson"


def test_parser_ignores_malformed_position_items_and_unknown_elements() -> None:
    entry = _entry(subject=_element("SUBJECT", long_name="Deutsch"))
    entry["position1"] = [
        "invalid",
        {
            "current": [
                "invalid",
                {"type": "UNKNOWN", "longName": "Ignored"},
                {"longName": "Deutsch"},
            ],
            "removed": [],
        },
    ]

    lesson = _parse(entry)[0]

    assert lesson.subject == "Deutsch"


def test_text_values_ignore_invalid_empty_and_duplicate_items() -> None:
    entry = _entry(
        subject=_element("SUBJECT", long_name="Deutsch"),
        lesson_info="Hinweis",
    )
    entry["texts"] = [
        "invalid",
        {"type": "PERIOD_INFO", "text": None},
        {"type": "PERIOD_INFO", "text": "   "},
        {"type": "LESSON_INFO", "text": "Hinweis"},
        {"type": "UNKNOWN", "text": "Zusatz"},
    ]

    lesson = _parse(entry)[0]

    assert lesson.texts == (("lesson_info", "Hinweis"), ("info", "Zusatz"))


def test_parse_datetime_accepts_naive_datetime_text() -> None:
    tz = ZoneInfo("Europe/Vienna")
    lessons = parse_lessons(
        [
            _entry(
                start="2026-09-23T08:00:00",
                end="2026-09-23T08:45:00",
                subject=_element("SUBJECT", long_name="Deutsch"),
            )
        ],
        datetime(2026, 9, 23, 0, 0, tzinfo=tz),
        datetime(2026, 9, 24, 0, 0, tzinfo=tz),
        tz,
    )

    assert lessons[0].start.isoformat() == "2026-09-23T08:00:00+02:00"


def test_changed_detects_subject_and_room_changes() -> None:
    base = dict(
        start=datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
        end=datetime(2026, 9, 23, 8, 45, tzinfo=UTC),
        subject="Mathematik",
        status="REGULAR",
        teachers=(),
        old_teachers=(),
        texts=(),
        raw_count=1,
    )
    subject_change = WebUntisLesson(
        **base,
        subjects=("Mathematik",),
        old_subjects=("Physik",),
        rooms=(),
        old_rooms=(),
    )
    room_change = WebUntisLesson(
        **base,
        subjects=("Mathematik",),
        old_subjects=(),
        rooms=("A102",),
        old_rooms=("A101",),
    )

    assert subject_change.changed is True
    assert room_change.changed is True


def test_summary_and_removed_room_teacher_fallbacks() -> None:
    lesson = WebUntisLesson(
        start=datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
        end=datetime(2026, 9, 23, 8, 45, tzinfo=UTC),
        subject="Mathematik",
        status="REGULAR",
        subjects=("Mathematik",),
        old_subjects=(),
        teachers=(),
        old_teachers=("Alte Lehrkraft",),
        rooms=(),
        old_rooms=("A101",),
        texts=(),
        raw_count=1,
    )

    assert lesson.summary == "Mathematik"
    assert lesson.room == "A101"
    assert lesson.teacher == "Alte Lehrkraft"

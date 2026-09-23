from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.webuntis_public import button as button_module
from custom_components.webuntis_public import calendar as calendar_module
from custom_components.webuntis_public import event as event_module
from custom_components.webuntis_public import sensor as sensor_module
from custom_components.webuntis_public.const import (
    OPT_SHOW_CANCELLED,
    OPT_SHOW_CLASS,
    OPT_SHOW_ROOM,
    OPT_SHOW_TEACHER,
    OPT_TITLE_FORMAT,
    TITLE_SUBJECT_ROOM_TEACHER,
)
from custom_components.webuntis_public.data import WebUntisLesson


UTC = timezone.utc
BASE = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)


class FakeCoordinator:
    def __init__(self, lessons=None) -> None:
        self.device_identifier = "example.webuntis.com-123"
        self.device_name = "Example School – 5A"
        self.configuration_url = (
            "https://example.webuntis.com/WebUntis/?school=example"
            "#/basic/timetablePublic/class?entityId=123"
        )
        self.class_id = 123
        self.class_name = "5A"
        self.last_update_success = True
        self.data_source = "live"
        self.hass = SimpleNamespace(config=SimpleNamespace(language="de"))
        self.lessons = list(lessons or [])
        self.force_refresh_calls = 0
        self._sequence = 0
        self._changes: list[dict] = []
        self.last_successful_fetch = datetime(2026, 9, 23, 7, 55, tzinfo=UTC)

    def cached_lessons_between(self, start, end):
        return [
            lesson
            for lesson in self.lessons
            if lesson.end > start and lesson.start < end
        ]

    async def async_get_lessons(self, start, end):
        return self.cached_lessons_between(start, end)

    async def async_force_refresh(self):
        self.force_refresh_calls += 1

    @property
    def timetable_change_sequence(self):
        return self._sequence

    def timetable_changes_since(self, sequence):
        return [
            item
            for item in self._changes
            if int(item.get("sequence", 0)) > sequence
        ]

    @property
    def diagnostic_state(self):
        return {
            "data_source": self.data_source,
            "last_successful_fetch": self.last_successful_fetch.isoformat(),
            "last_refresh_attempt": "2026-09-23T07:56:00+00:00",
            "cache_age_minutes": 5,
            "weeks_cached": 2,
            "last_error": None,
            "last_error_at": None,
            "consecutive_failures": 0,
        }

    def diagnostic_weeks(self):
        return [
            {"week": "2026-09-21", "entries": 10},
            {"week": "2026-09-28", "entries": 8},
        ]


def _entry(options=None, runtime_data=None):
    return SimpleNamespace(
        options=dict(options or {}),
        runtime_data=runtime_data or [],
    )


def _lesson(
    start_minutes: int,
    end_minutes: int,
    *,
    subject: str = "Mathematik",
    status: str = "REGULAR",
    teachers: tuple[str, ...] = ("Anna Beispiel",),
    old_teachers: tuple[str, ...] = (),
    rooms: tuple[str, ...] = ("A101",),
    old_rooms: tuple[str, ...] = (),
    old_subjects: tuple[str, ...] = (),
    texts: tuple[tuple[str, str], ...] = (),
) -> WebUntisLesson:
    return WebUntisLesson(
        start=BASE + timedelta(minutes=start_minutes),
        end=BASE + timedelta(minutes=end_minutes),
        subject=subject,
        status=status,
        subjects=(subject,),
        old_subjects=old_subjects,
        teachers=teachers,
        old_teachers=old_teachers,
        rooms=rooms,
        old_rooms=old_rooms,
        texts=texts,
        raw_count=1,
    )


def _set_today(entity, lessons):
    entity._lessons_today = lambda: list(lessons)


def _set_day_lookup(entity, mapping):
    entity._lessons_for_day = lambda offset=0: list(mapping.get(offset, []))


def test_sensor_setup_registers_ten_entities() -> None:
    coordinator = FakeCoordinator()
    entry = _entry(runtime_data=[coordinator])
    added = []

    asyncio.run(sensor_module.async_setup_entry(None, entry, added.extend))

    assert len(added) == 10
    assert len({entity.unique_id for entity in added}) == 10


def test_button_and_event_setup_register_one_entity_per_class() -> None:
    coordinators = [FakeCoordinator(), FakeCoordinator()]
    coordinators[1].device_identifier = "example.webuntis.com-124"
    entry = _entry(runtime_data=coordinators)

    buttons = []
    events = []
    asyncio.run(button_module.async_setup_entry(None, entry, buttons.extend))
    asyncio.run(event_module.async_setup_entry(None, entry, events.extend))

    assert len(buttons) == 2
    assert len(events) == 2


def test_current_lesson_sensor_reports_parallel_subjects_and_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lessons = [
        _lesson(0, 45, subject="Mathematik"),
        _lesson(0, 45, subject="Physik", teachers=("Max Mustermann",), rooms=("B201",)),
    ]
    sensor = sensor_module.WebUntisCurrentLessonSensor(_entry(), FakeCoordinator())
    _set_today(sensor, lessons)
    monkeypatch.setattr(sensor_module, "local_now", lambda _hass: BASE + timedelta(minutes=20))

    assert sensor.native_value == "Mathematik / Physik"
    attrs = sensor.extra_state_attributes
    assert attrs["laeuft_gerade"] is True
    assert attrs["raum"] == "A101, B201"
    assert attrs["lehrer"] == "Anna Beispiel, Max Mustermann"


def test_current_lesson_sensor_reports_no_lesson(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensor = sensor_module.WebUntisCurrentLessonSensor(_entry(), FakeCoordinator())
    _set_today(sensor, [])
    monkeypatch.setattr(sensor_module, "local_now", lambda _hass: BASE)

    assert sensor.native_value == "no_lesson"
    assert sensor.extra_state_attributes == {"laeuft_gerade": False}


def test_next_lesson_sensor_reports_future_lesson(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = FakeCoordinator([_lesson(60, 105, subject="Deutsch")])
    sensor = sensor_module.WebUntisNextLessonSensor(_entry(), coordinator)
    monkeypatch.setattr(sensor_module, "local_now", lambda _hass: BASE + timedelta(minutes=30))

    assert sensor.native_value == "Deutsch"
    attrs = sensor.extra_state_attributes
    assert attrs["laeuft_gerade"] is False
    assert attrs["beginn"] == (BASE + timedelta(minutes=60)).isoformat()


def test_school_status_sensor_reports_break_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lessons = [
        _lesson(0, 45, subject="Mathematik"),
        _lesson(60, 105, subject="Deutsch"),
    ]
    sensor = sensor_module.WebUntisSchoolStatusSensor(_entry(), FakeCoordinator())
    _set_today(sensor, lessons)
    monkeypatch.setattr(
        sensor_module,
        "local_now",
        lambda _hass: BASE + timedelta(minutes=50),
    )

    assert sensor.native_value == "break"
    attrs = sensor.extra_state_attributes
    assert attrs["schulbeginn"] == BASE.isoformat()
    assert attrs["schulschluss"] == (BASE + timedelta(minutes=105)).isoformat()
    assert attrs["aktuelles_fach"] is None
    assert attrs["naechstes_fach"] == "Deutsch"
    assert attrs["naechste_stunde_ab"] == (BASE + timedelta(minutes=60)).isoformat()
    assert attrs["verbleibende_stunden"] == 1


def test_next_school_day_skips_empty_and_cancelled_only_days() -> None:
    sensor = sensor_module.WebUntisNextSchoolDaySensor(_entry(), FakeCoordinator())
    _set_day_lookup(
        sensor,
        {
            1: [],
            2: [_lesson(24 * 60, 24 * 60 + 45, status="CANCEL")],
            3: [
                _lesson(
                    2 * 24 * 60,
                    2 * 24 * 60 + 45,
                    subject="Deutsch",
                )
            ],
        },
    )

    assert sensor.native_value == datetime(2026, 9, 25, tzinfo=UTC).date()
    assert sensor.extra_state_attributes["stunden"] == 1
    assert sensor.extra_state_attributes["faecher"] == ["Deutsch"]


def test_next_school_day_summary_combines_future_day_information() -> None:
    sensor = sensor_module.WebUntisNextSchoolDaySummarySensor(
        _entry(),
        FakeCoordinator(),
    )
    target_day = [
        _lesson(
            2 * 24 * 60,
            2 * 24 * 60 + 45,
            subject="Mathematik",
        ),
        _lesson(
            2 * 24 * 60 + 60,
            2 * 24 * 60 + 105,
            subject="Deutsch",
            status="CHANGED",
            teachers=("Max Mustermann",),
            rooms=("B201",),
        ),
        _lesson(
            2 * 24 * 60 + 120,
            2 * 24 * 60 + 165,
            subject="Sport",
            status="CANCEL",
        ),
    ]
    _set_day_lookup(
        sensor,
        {
            1: [_lesson(24 * 60, 24 * 60 + 45, status="CANCEL")],
            2: target_day,
        },
    )

    assert sensor.native_value == 2
    attrs = sensor.extra_state_attributes
    assert attrs["datum"] == "2026-09-25"
    assert attrs["tage_bis_dahin"] == 2
    assert attrs["morgen_schulfrei"] is True
    assert attrs["faecher"] == ["Mathematik", "Deutsch"]
    assert attrs["lehrer"] == ["Anna Beispiel", "Max Mustermann"]
    assert attrs["raeume"] == ["A101", "B201"]
    assert attrs["aenderungen"] == 2
    assert attrs["ausfaelle"] == 1
    assert attrs["ausgefallene_faecher"] == ["Sport"]
    assert len(attrs["stundenplan"]) == 2
    assert attrs["stundenplan"][1]["geaendert"] is True


def test_school_day_progress_includes_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lessons = [
        _lesson(0, 45, subject="Mathematik"),
        _lesson(60, 120, subject="Deutsch"),
    ]
    sensor = sensor_module.WebUntisSchoolDayProgressSensor(_entry(), FakeCoordinator())
    _set_today(sensor, lessons)
    monkeypatch.setattr(sensor_module, "local_now", lambda _hass: BASE + timedelta(minutes=60))

    assert sensor.native_value == 50.0
    assert sensor.extra_state_attributes["inklusive_pausen"] is True


def test_school_day_progress_reports_school_free() -> None:
    sensor = sensor_module.WebUntisSchoolDayProgressSensor(_entry(), FakeCoordinator())
    _set_today(sensor, [])

    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {
        "schulfrei": True,
        "inklusive_pausen": True,
    }


def test_daily_summary_combines_day_information(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lessons = [
        _lesson(0, 45, subject="Mathematik"),
        _lesson(60, 105, subject="Deutsch", status="CHANGED"),
        _lesson(120, 165, subject="Sport", status="CANCEL"),
    ]
    sensor = sensor_module.WebUntisDailySummarySensor(_entry(), FakeCoordinator())
    _set_today(sensor, lessons)
    monkeypatch.setattr(sensor_module, "local_now", lambda _hass: BASE + timedelta(minutes=20))

    assert sensor.native_value == 2
    attrs = sensor.extra_state_attributes
    assert attrs["schulfrei"] is False
    assert attrs["aenderungen"] == 2
    assert attrs["ausfaelle"] == 1
    assert attrs["aktuelle_stunde"] == "Mathematik"
    assert attrs["naechste_stunde"] == "Deutsch"
    assert attrs["verbleibende_stunden"] == 2
    assert attrs["planmaessiger_schulbeginn"] == BASE.isoformat()
    assert attrs["planmaessiger_schulschluss"] == (BASE + timedelta(minutes=165)).isoformat()
    assert attrs["spaeterer_schulbeginn_minuten"] == 0
    assert attrs["frueherer_schulschluss_minuten"] == 60
    assert attrs["erste_stunde_entfaellt"] is False
    assert attrs["letzte_stunde_entfaellt"] is True
    assert attrs["unterrichtsfortschritt"] == 22.2
    assert attrs["unterricht_minuten_absolviert"] == 20
    assert attrs["unterricht_minuten_gesamt"] == 90


@pytest.mark.parametrize(
    ("source", "icon"),
    [
        ("live", "mdi:cloud-check"),
        ("cache", "mdi:cached"),
        ("stale_cache", "mdi:cloud-alert"),
        ("unavailable", "mdi:cloud-off-outline"),
        ("unknown", "mdi:database-clock"),
    ],
)
def test_data_status_sensor_maps_source_to_icon(source: str, icon: str) -> None:
    coordinator = FakeCoordinator()
    coordinator.data_source = source
    sensor = sensor_module.WebUntisDataStatusSensor(_entry(), coordinator)

    assert sensor.native_value == source
    assert sensor.icon == icon
    assert sensor.extra_state_attributes["cache_wochen"] == 2


def test_diagnostic_sensors_expose_last_fetch_and_cached_weeks() -> None:
    coordinator = FakeCoordinator()
    last_fetch = sensor_module.WebUntisLastSuccessfulFetchSensor(_entry(), coordinator)
    cached = sensor_module.WebUntisCachedWeeksSensor(_entry(), coordinator)

    assert last_fetch.native_value == datetime(2026, 9, 23, 7, 55, tzinfo=UTC)
    assert cached.native_value == 2
    assert cached.extra_state_attributes["wochen"][0]["week"] == "2026-09-21"


def _translations() -> dict[str, str]:
    prefix = "component.webuntis_public.common."
    return {
        prefix + "calendar.lesson": "Unterricht",
        prefix + "calendar.class_line": "Klasse: {value}",
        prefix + "calendar.teacher_line": "Lehrer: {value}",
        prefix + "calendar.room_line": "Raum: {value}",
        prefix + "calendar.subject_change": "Fach: {old} → {new}",
        prefix + "calendar.teacher_change": "Lehrer: {old} → {new}",
        prefix + "calendar.room_change": "Raum: {old} → {new}",
        prefix + "calendar.status.cancelled": "Entfällt",
        prefix + "calendar.status.changed": "Geändert",
        prefix + "calendar.status_line": "Status: {value}",
        prefix + "calendar.text.substitution": "Vertretung",
        prefix + "calendar.text_line": "{label}: {value}",
        prefix + "calendar.cancelled_summary": "Entfällt: {summary}",
    }


def test_calendar_hides_cancelled_lessons_when_option_disabled() -> None:
    calendar = calendar_module.WebUntisPublicCalendar(
        _entry({OPT_SHOW_CANCELLED: False}),
        FakeCoordinator(),
        _translations(),
    )

    assert calendar._visible(_lesson(0, 45, status="CANCEL")) is False
    assert calendar._visible(_lesson(60, 105)) is True


def test_calendar_event_respects_display_options_and_translations() -> None:
    lesson = _lesson(
        0,
        45,
        subject="Deutsch",
        status="CHANGED",
        teachers=("Neue Lehrkraft",),
        old_teachers=("Alte Lehrkraft",),
        rooms=("B201",),
        old_rooms=("A101",),
        old_subjects=("Mathematik",),
        texts=(("substitution", "Vertretungsstunde"),),
    )
    options = {
        OPT_TITLE_FORMAT: TITLE_SUBJECT_ROOM_TEACHER,
        OPT_SHOW_CLASS: True,
        OPT_SHOW_TEACHER: True,
        OPT_SHOW_ROOM: True,
    }
    calendar = calendar_module.WebUntisPublicCalendar(
        _entry(options),
        FakeCoordinator(),
        _translations(),
    )

    event = calendar._to_event(lesson)

    assert event.summary == "Deutsch · B201 · Neue Lehrkraft"
    assert event.location == "B201"
    assert "Klasse: 5A" in event.description
    assert "Lehrer: Neue Lehrkraft" in event.description
    assert "Raum: B201" in event.description
    assert "Fach: Mathematik → Deutsch" in event.description
    assert "Status: Geändert" in event.description
    assert "Vertretung: Vertretungsstunde" in event.description
    assert event.uid.startswith("webuntis-123-")


def test_calendar_cancelled_event_gets_cancelled_summary() -> None:
    calendar = calendar_module.WebUntisPublicCalendar(
        _entry(),
        FakeCoordinator(),
        _translations(),
    )

    event = calendar._to_event(_lesson(0, 45, subject="Sport", status="CANCEL"))

    assert event.summary.startswith("Entfällt: Sport")


def test_calendar_uid_is_stable_for_same_semantic_lesson() -> None:
    calendar = calendar_module.WebUntisPublicCalendar(
        _entry(),
        FakeCoordinator(),
        _translations(),
    )
    lesson = _lesson(0, 45, subject="Mathematik")

    assert calendar._to_event(lesson).uid == calendar._to_event(lesson).uid


def test_calendar_async_get_events_filters_cancelled_lessons() -> None:
    lessons = [
        _lesson(0, 45, subject="Mathematik"),
        _lesson(60, 105, subject="Sport", status="CANCEL"),
    ]
    coordinator = FakeCoordinator(lessons)
    calendar = calendar_module.WebUntisPublicCalendar(
        _entry({OPT_SHOW_CANCELLED: False}),
        coordinator,
        _translations(),
    )

    events = asyncio.run(
        calendar.async_get_events(
            None,
            BASE - timedelta(minutes=1),
            BASE + timedelta(hours=3),
        )
    )

    assert [event.summary for event in events] == ["Mathematik"]


def test_refresh_button_calls_force_refresh() -> None:
    coordinator = FakeCoordinator()
    button = button_module.WebUntisRefreshButton(_entry(), coordinator)

    asyncio.run(button.async_press())

    assert coordinator.force_refresh_calls == 1


def test_event_entity_emits_every_unseen_change(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = FakeCoordinator()
    entity = event_module.WebUntisTimetableChangeEvent(_entry(), coordinator)
    emitted: list[tuple[str, dict]] = []

    monkeypatch.setattr(entity, "_trigger_event", lambda event_type, data: emitted.append((event_type, data)))
    monkeypatch.setattr(entity, "async_write_ha_state", lambda: None)

    coordinator._sequence = 2
    coordinator._changes = [
        {"sequence": 1, "week": "2026-09-21"},
        {"sequence": 2, "week": "2026-09-28"},
    ]

    entity._handle_coordinator_update()

    assert emitted == [
        ("timetable_changed", {"sequence": 1, "week": "2026-09-21"}),
        ("timetable_changed", {"sequence": 2, "week": "2026-09-28"}),
    ]
    assert entity._last_sequence == 2


def test_entity_availability_follows_coordinator() -> None:
    coordinator = FakeCoordinator()
    sensor = sensor_module.WebUntisSchoolStatusSensor(_entry(), coordinator)

    assert sensor.available is True
    coordinator.last_update_success = False
    assert sensor.available is False

from __future__ import annotations

import asyncio
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError, ClientResponseError

from custom_components.webuntis_public import coordinator as coordinator_module
from custom_components.webuntis_public.const import OPT_EXCLUDE_SUBJECTS
from custom_components.webuntis_public.data import parse_lessons
from custom_components.webuntis_public.coordinator import (
    RETRY_DELAYS,
    WebUntisPublicCoordinator,
    WebUntisTemporaryUnavailable,
)


UTC = timezone.utc


class FakeClientResponseError(ClientResponseError):
    """Small HTTP error double with a stable string representation."""

    def __init__(self, status: int) -> None:
        self.status = status
        self.message = f"HTTP {status}"

    def __str__(self) -> str:
        return self.message


class FakeResponse:
    def __init__(
        self,
        payload,
        *,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.raise_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        self.raise_calls += 1
        if self.error is not None:
            raise self.error

    async def json(self, *, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _bare_coordinator() -> WebUntisPublicCoordinator:
    item = object.__new__(WebUntisPublicCoordinator)
    item._weeks = {}
    item._force_refresh = False
    item._timetable_change_sequence = 0
    item._last_timetable_change = None
    item._timetable_change_history = []
    item.class_name = "5A"
    return item


def _entry(
    start: datetime,
    end: datetime,
    *,
    subject: str = "Mathematik",
    teacher: str = "Anna Beispiel",
    room: str = "A101",
    status: str = "REGULAR",
    ids: list[int] | None = None,
) -> dict:
    return {
        "duration": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "status": status,
        "ids": ids or [1],
        "position1": [
            {
                "current": [
                    {
                        "type": "SUBJECT",
                        "longName": subject,
                        "shortName": subject[:3],
                    }
                ]
            }
        ],
        "position2": [
            {
                "current": [
                    {
                        "type": "ROOM",
                        "shortName": room,
                    }
                ]
            }
        ],
        "position3": [
            {
                "current": [
                    {
                        "type": "TEACHER",
                        "longName": teacher,
                        "shortName": teacher[:2],
                    }
                ]
            }
        ],
    }


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (
            datetime(2026, 9, 21, 8, 0, tzinfo=UTC),
            datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
            [Date(2026, 9, 21)],
        ),
        (
            datetime(2026, 9, 25, 8, 0, tzinfo=UTC),
            datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
            [Date(2026, 9, 21), Date(2026, 9, 28)],
        ),
        (
            datetime(2026, 9, 28, 8, 0, tzinfo=UTC),
            datetime(2026, 10, 12, 8, 0, tzinfo=UTC),
            [Date(2026, 9, 28), Date(2026, 10, 5), Date(2026, 10, 12)],
        ),
    ],
)
def test_weeks_for_range(start: datetime, end: datetime, expected: list[Date]) -> None:
    assert WebUntisPublicCoordinator._weeks_for_range(start, end) == expected


def test_cached_lessons_keeps_distinct_entries_without_ids() -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    start = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 21, 8, 45, tzinfo=UTC)

    mathematics = _entry(
        start,
        end,
        subject="Mathematik",
        teacher="Anna Beispiel",
        room="A101",
    )
    english = _entry(
        start,
        end,
        subject="Englisch",
        teacher="Max Mustermann",
        room="B202",
    )
    mathematics["ids"] = []
    english["ids"] = []

    item._weeks[monday.isoformat()] = {
        "fetched_at": datetime.now(UTC),
        "entries": [mathematics, english],
    }

    lessons = item.cached_lessons_between(
        datetime(2026, 9, 21, 7, 0, tzinfo=UTC),
        datetime(2026, 9, 21, 10, 0, tzinfo=UTC),
    )

    assert len(lessons) == 2
    assert {lesson.subject for lesson in lessons} == {"Mathematik", "Englisch"}


def test_cached_lessons_excludes_configured_subjects_case_insensitively() -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    item.entry = SimpleNamespace(
        options={OPT_EXCLUDE_SUBJECTS: " mathematik,\nRELIGION "}
    )
    monday = Date(2026, 9, 21)
    start = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 21, 8, 45, tzinfo=UTC)
    item._weeks[monday.isoformat()] = {
        "fetched_at": datetime.now(UTC),
        "entries": [
            _entry(start, end, subject="Mathematik"),
            _entry(start + timedelta(hours=1), end + timedelta(hours=1), subject="Englisch"),
            _entry(start + timedelta(hours=2), end + timedelta(hours=2), subject="Religion"),
        ],
    }

    lessons = item.cached_lessons_between(
        datetime(2026, 9, 21, 7, 0, tzinfo=UTC),
        datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
    )

    assert [lesson.subject for lesson in lessons] == ["Englisch"]


def test_parse_utc_normalizes_naive_and_offset_datetimes() -> None:
    naive = WebUntisPublicCoordinator._parse_utc("2026-09-23T10:00:00")
    offset = WebUntisPublicCoordinator._parse_utc("2026-09-23T12:00:00+02:00")

    assert naive == datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    assert offset == datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    assert WebUntisPublicCoordinator._parse_utc("invalid") is None
    assert WebUntisPublicCoordinator._parse_utc(None) is None


def test_to_local_attaches_timezone_to_naive_datetime() -> None:
    tz = coordinator_module.dt_util.get_time_zone("Europe/Vienna")
    value = datetime(2026, 9, 23, 10, 0)

    converted = WebUntisPublicCoordinator._to_local(value, tz)

    assert converted.isoformat() == "2026-09-23T10:00:00+02:00"


def test_is_stale_uses_different_ttls(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now)
    current_monday = now.date() - timedelta(days=now.weekday())
    item = _bare_coordinator()

    assert item._is_stale(current_monday, now - timedelta(minutes=9)) is False
    assert item._is_stale(current_monday, now - timedelta(minutes=11)) is True

    next_monday = current_monday + timedelta(days=7)
    assert item._is_stale(next_monday, now - timedelta(minutes=29)) is False
    assert item._is_stale(next_monday, now - timedelta(minutes=31)) is True

    future_monday = current_monday + timedelta(days=14)
    assert item._is_stale(future_monday, now - timedelta(hours=5)) is False
    assert item._is_stale(future_monday, now - timedelta(hours=7)) is True

    previous_monday = current_monday - timedelta(days=7)
    assert item._is_stale(previous_monday, now - timedelta(hours=23)) is False
    assert item._is_stale(previous_monday, now - timedelta(hours=25)) is True


def test_fresh_week_uses_cache_without_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _bare_coordinator()
    monday = Date(2026, 9, 21)
    item._weeks[monday.isoformat()] = {
        "fetched_at": datetime.now(UTC),
        "entries": [{"cached": True}],
    }
    monkeypatch.setattr(item, "_is_stale", lambda *_args: False)
    fetch = AsyncMock()
    monkeypatch.setattr(item, "_async_fetch_week", fetch)

    result = asyncio.run(item._async_refresh_week_if_needed(monday))

    assert result == (False, "cache", None)
    fetch.assert_not_awaited()


def test_force_refresh_bypasses_fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _bare_coordinator()
    monday = Date(2026, 9, 21)
    item._force_refresh = True
    item._weeks[monday.isoformat()] = {
        "fetched_at": datetime.now(UTC),
        "entries": [{"cached": True}],
    }
    monkeypatch.setattr(item, "_is_stale", lambda *_args: False)
    fetch = AsyncMock(return_value=[{"live": True}])
    monkeypatch.setattr(item, "_async_fetch_week", fetch)
    monkeypatch.setattr(item, "_detect_timetable_change", lambda *_args: None)

    result = asyncio.run(item._async_refresh_week_if_needed(monday))

    assert result == (True, "live", None)
    fetch.assert_awaited_once_with(monday)
    assert item._weeks[monday.isoformat()]["entries"] == [{"live": True}]


def test_retryable_http_error_is_retried_until_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    monday = Date(2026, 9, 21)
    fetch = AsyncMock(
        side_effect=[
            FakeClientResponseError(500),
            FakeClientResponseError(503),
            [{"live": True}],
        ]
    )
    sleep = AsyncMock()
    monkeypatch.setattr(item, "_async_fetch_week", fetch)
    monkeypatch.setattr(item, "_detect_timetable_change", lambda *_args: None)
    monkeypatch.setattr(coordinator_module.asyncio, "sleep", sleep)

    result = asyncio.run(item._async_refresh_week_if_needed(monday))

    assert result == (True, "live", None)
    assert fetch.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == list(RETRY_DELAYS)


def test_network_error_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _bare_coordinator()
    monday = Date(2026, 9, 21)
    fetch = AsyncMock(side_effect=[ClientError("network"), [{"live": True}]])
    sleep = AsyncMock()
    monkeypatch.setattr(item, "_async_fetch_week", fetch)
    monkeypatch.setattr(item, "_detect_timetable_change", lambda *_args: None)
    monkeypatch.setattr(coordinator_module.asyncio, "sleep", sleep)

    result = asyncio.run(item._async_refresh_week_if_needed(monday))

    assert result == (True, "live", None)
    assert fetch.await_count == 2
    sleep.assert_awaited_once_with(RETRY_DELAYS[0])


def test_http_404_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _bare_coordinator()
    monday = Date(2026, 9, 21)
    fetch = AsyncMock(side_effect=FakeClientResponseError(404))
    sleep = AsyncMock()
    monkeypatch.setattr(item, "_async_fetch_week", fetch)
    monkeypatch.setattr(coordinator_module.asyncio, "sleep", sleep)

    with pytest.raises(WebUntisTemporaryUnavailable, match="HTTP 404"):
        asyncio.run(item._async_refresh_week_if_needed(monday))

    fetch.assert_awaited_once_with(monday)
    sleep.assert_not_awaited()


def test_retry_failure_uses_stale_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _bare_coordinator()
    monday = Date(2026, 9, 21)
    cached_entries = [{"cached": True}]
    item._weeks[monday.isoformat()] = {
        "fetched_at": datetime.now(UTC) - timedelta(hours=1),
        "entries": cached_entries,
    }
    monkeypatch.setattr(item, "_is_stale", lambda *_args: True)
    fetch = AsyncMock(side_effect=FakeClientResponseError(503))
    sleep = AsyncMock()
    monkeypatch.setattr(item, "_async_fetch_week", fetch)
    monkeypatch.setattr(coordinator_module.asyncio, "sleep", sleep)

    changed, source, error = asyncio.run(
        item._async_refresh_week_if_needed(monday)
    )

    assert changed is False
    assert source == "stale_cache"
    assert error == "HTTP 503"
    assert fetch.await_count == 3
    assert item._weeks[monday.isoformat()]["entries"] is cached_entries


def test_retry_failure_rejects_cache_older_than_24_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    monday = Date(2026, 9, 21)
    item._weeks[monday.isoformat()] = {
        "fetched_at": datetime.now(UTC) - timedelta(hours=24, seconds=1),
        "entries": [{"cached": True}],
    }
    monkeypatch.setattr(item, "_is_stale", lambda *_args: True)
    monkeypatch.setattr(
        item,
        "_async_fetch_week",
        AsyncMock(side_effect=FakeClientResponseError(503)),
    )
    monkeypatch.setattr(coordinator_module.asyncio, "sleep", AsyncMock())

    with pytest.raises(WebUntisTemporaryUnavailable, match="HTTP 503"):
        asyncio.run(item._async_refresh_week_if_needed(monday))


def test_cache_exactly_24_hours_old_is_usable_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    fixed_now = datetime.now(UTC)
    cached = {
        "fetched_at": fixed_now - timedelta(hours=24),
        "entries": [{"cached": True}],
    }
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: fixed_now)

    assert item._cache_is_usable_fallback(cached) is True

def test_successful_refresh_records_detected_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    monday = Date(2026, 9, 21)
    item._weeks[monday.isoformat()] = {
        "fetched_at": datetime.now(UTC) - timedelta(hours=1),
        "entries": [{"old": True}],
    }
    monkeypatch.setattr(item, "_is_stale", lambda *_args: True)
    monkeypatch.setattr(
        item,
        "_async_fetch_week",
        AsyncMock(return_value=[{"new": True}]),
    )
    monkeypatch.setattr(
        item,
        "_detect_timetable_change",
        lambda *_args: {
            "week": monday.isoformat(),
            "added_count": 1,
            "removed_count": 1,
        },
    )

    result = asyncio.run(item._async_refresh_week_if_needed(monday))

    assert result == (True, "live", None)
    assert item.timetable_change_sequence == 1
    assert item.last_timetable_change["sequence"] == 1
    assert item.timetable_changes_since(0) == [item.last_timetable_change]
    assert item.timetable_changes_since(1) == []


def test_timetable_change_ignores_technical_duplicate_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now)

    start = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 24, 8, 45, tzinfo=UTC)
    lesson = _entry(start, end)

    change = item._detect_timetable_change(monday, [lesson], [lesson, lesson])

    assert change is None


def test_timetable_change_reports_semantic_teacher_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now)

    start = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 24, 8, 45, tzinfo=UTC)
    old = _entry(start, end, teacher="Anna Beispiel")
    new = _entry(start, end, teacher="Max Mustermann")

    change = item._detect_timetable_change(monday, [old], [new])

    assert change is not None
    assert change["added_count"] == 1
    assert change["removed_count"] == 1
    assert change["change_count"] == 2
    assert change["added"][0]["teacher"] == "Max Mustermann"
    assert change["removed"][0]["teacher"] == "Anna Beispiel"


def test_timetable_change_ignores_already_finished_lessons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now)

    start = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 22, 8, 45, tzinfo=UTC)

    change = item._detect_timetable_change(
        monday,
        [_entry(start, end, teacher="Alt")],
        [_entry(start, end, teacher="Neu")],
    )

    assert change is None


def test_async_fetch_week_uses_correct_endpoint_and_flattens_days() -> None:
    item = _bare_coordinator()
    item.server = "example.webuntis.com"
    item.school = "ExampleSchool"
    item.class_id = 123
    response = FakeResponse(
        {
            "days": [
                {"gridEntries": [{"id": 1}, {"id": 2}]},
                {"gridEntries": {"id": 3}},
                {"gridEntries": None},
            ]
        }
    )
    item._session = FakeSession(response)

    entries = asyncio.run(item._async_fetch_week(Date(2026, 9, 21)))

    assert entries == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert len(item._session.calls) == 1
    url, kwargs = item._session.calls[0]
    assert url == (
        "https://example.webuntis.com"
        "/WebUntis/api/rest/view/v1/timetable/entries"
    )
    assert kwargs["params"] == {
        "start": "2026-09-21",
        "end": "2026-09-26",
        "format": "2",
        "resourceType": "CLASS",
        "resources": "123",
        "timetableType": "STANDARD",
        "layout": "START_TIME",
    }
    assert kwargs["headers"]["anonymous-school"] == "ExampleSchool"
    assert kwargs["headers"]["Accept"] == "application/json"
    assert response.raise_calls == 1


def test_async_fetch_week_rejects_unexpected_response_format() -> None:
    item = _bare_coordinator()
    item.server = "example.webuntis.com"
    item.school = None
    item.class_id = 123
    item._session = FakeSession(FakeResponse(["unexpected"]))

    with pytest.raises(ValueError, match="Unexpected WebUntis response format"):
        asyncio.run(item._async_fetch_week(Date(2026, 9, 21)))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "Unexpected WebUntis response format"),
        ({"error": "not authorized"}, "Unexpected WebUntis response format"),
        ({"days": {}}, "Unexpected WebUntis days format"),
        ({"days": ["invalid"]}, "Unexpected WebUntis day format"),
        (
            {"days": [{"gridEntries": "invalid"}]},
            "Unexpected WebUntis gridEntries format",
        ),
        (
            {"days": [{"gridEntries": ["invalid"]}]},
            "Unexpected WebUntis timetable entry format",
        ),
    ],
)
def test_async_fetch_week_rejects_malformed_timetable_structure(
    payload,
    message: str,
) -> None:
    item = _bare_coordinator()
    item.server = "example.webuntis.com"
    item.school = None
    item.class_id = 123
    item._session = FakeSession(FakeResponse(payload))

    with pytest.raises(ValueError, match=message):
        asyncio.run(item._async_fetch_week(Date(2026, 9, 21)))


def test_async_fetch_week_accepts_legitimate_empty_days() -> None:
    item = _bare_coordinator()
    item.server = "example.webuntis.com"
    item.school = None
    item.class_id = 123
    item._session = FakeSession(FakeResponse({"days": []}))

    assert asyncio.run(item._async_fetch_week(Date(2026, 9, 21))) == []


def test_setup_loads_recent_valid_cache_and_ignores_old_entries() -> None:
    item = _bare_coordinator()
    now = datetime.now(UTC)
    item._store = SimpleNamespace(
        async_load=AsyncMock(
            return_value={
                "weeks": {
                    "2026-09-21": {
                        "fetched_at": now.isoformat(),
                        "entries": [{"fresh": True}],
                    },
                    "2026-01-05": {
                        "fetched_at": (now - timedelta(days=121)).isoformat(),
                        "entries": [{"old": True}],
                    },
                    "invalid": {
                        "fetched_at": now.isoformat(),
                        "entries": "not-a-list",
                    },
                }
            }
        )
    )
    item._data_source = "unavailable"

    asyncio.run(item._async_setup())

    assert list(item._weeks) == ["2026-09-21"]
    assert item._data_source == "cache"


def test_save_cache_excludes_entries_older_than_120_days() -> None:
    item = _bare_coordinator()
    now = datetime.now(UTC)
    item._weeks = {
        "2026-09-21": {
            "fetched_at": now,
            "entries": [{"fresh": True}],
        },
        "2026-01-05": {
            "fetched_at": now - timedelta(days=121),
            "entries": [{"old": True}],
        },
    }
    save = AsyncMock()
    item._store = SimpleNamespace(async_save=save)

    asyncio.run(item._async_save_cache())

    saved = save.await_args.args[0]
    assert list(saved["weeks"]) == ["2026-09-21"]
    assert saved["weeks"]["2026-09-21"]["entries"] == [{"fresh": True}]



def test_timetable_change_emits_lesson_cancelled_semantic_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now)

    start = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 24, 8, 45, tzinfo=UTC)
    old = _entry(start, end, status="REGULAR")
    new = _entry(start, end, status="CANCEL")

    change = item._detect_timetable_change(monday, [old], [new])

    assert change is not None
    assert len(change["semantic_events"]) == 1
    event = change["semantic_events"][0]
    assert event["event_type"] == "lesson_cancelled"
    assert event["subject"] == "Mathematik"
    assert event["previous"]["status"] == "regular"
    assert event["current"]["status"] == "cancelled"


def test_timetable_change_emits_lesson_substituted_semantic_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now)

    start = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 24, 8, 45, tzinfo=UTC)
    old = _entry(start, end, teacher="Anna Beispiel")
    new = _entry(start, end, teacher="Max Mustermann", status="CHANGED")

    change = item._detect_timetable_change(monday, [old], [new])

    assert change is not None
    assert len(change["semantic_events"]) == 1
    event = change["semantic_events"][0]
    assert event["event_type"] == "lesson_substituted"
    assert event["previous"]["teacher"] == "Anna Beispiel"
    assert event["current"]["teacher"] == "Max Mustermann"



def test_timetable_change_emits_room_changed_semantic_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    monkeypatch.setattr(
        coordinator_module.dt_util,
        "now",
        lambda: datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )
    start = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 24, 8, 45, tzinfo=UTC)

    change = item._detect_timetable_change(
        monday,
        [_entry(start, end, room="A101")],
        [_entry(start, end, room="B202")],
    )

    assert change is not None
    events = [
        event for event in change["semantic_events"]
        if event["event_type"] == "lesson_room_changed"
    ]
    assert len(events) == 1
    assert events[0]["previous"]["room"] == "A101"
    assert events[0]["current"]["room"] == "B202"


def test_timetable_change_emits_time_changed_semantic_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    monkeypatch.setattr(
        coordinator_module.dt_util,
        "now",
        lambda: datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )
    old_start = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    old_end = datetime(2026, 9, 24, 8, 45, tzinfo=UTC)
    new_start = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
    new_end = datetime(2026, 9, 24, 9, 45, tzinfo=UTC)

    change = item._detect_timetable_change(
        monday,
        [_entry(old_start, old_end)],
        [_entry(new_start, new_end)],
    )

    assert change is not None
    events = [
        event for event in change["semantic_events"]
        if event["event_type"] == "lesson_time_changed"
    ]
    assert len(events) == 1
    assert events[0]["previous"]["start"].endswith("10:00:00+02:00")
    assert events[0]["current"]["start"].endswith("11:00:00+02:00")



def test_timetable_change_emits_school_start_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    monkeypatch.setattr(
        coordinator_module.dt_util,
        "now",
        lambda: datetime(2026, 9, 23, 6, 0, tzinfo=UTC),
    )
    first_old = _entry(
        datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
        datetime(2026, 9, 24, 8, 45, tzinfo=UTC),
        subject="Mathematik",
    )
    first_new = _entry(
        datetime(2026, 9, 24, 9, 0, tzinfo=UTC),
        datetime(2026, 9, 24, 9, 45, tzinfo=UTC),
        subject="Mathematik",
    )
    last = _entry(
        datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 24, 12, 45, tzinfo=UTC),
        subject="Englisch",
    )

    change = item._detect_timetable_change(monday, [first_old, last], [first_new, last])

    assert change is not None
    events = [
        event for event in change["semantic_events"]
        if event["event_type"] == "school_start_changed"
    ]
    assert len(events) == 1
    assert events[0]["previous_start"].endswith("10:00:00+02:00")
    assert events[0]["current_start"].endswith("11:00:00+02:00")


def test_timetable_change_emits_school_end_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    monkeypatch.setattr(
        coordinator_module.dt_util,
        "now",
        lambda: datetime(2026, 9, 23, 6, 0, tzinfo=UTC),
    )
    first = _entry(
        datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
        datetime(2026, 9, 24, 8, 45, tzinfo=UTC),
        subject="Mathematik",
    )
    last_old = _entry(
        datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 24, 12, 45, tzinfo=UTC),
        subject="Englisch",
    )
    last_new = _entry(
        datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 24, 13, 45, tzinfo=UTC),
        subject="Englisch",
    )

    change = item._detect_timetable_change(monday, [first, last_old], [first, last_new])

    assert change is not None
    events = [
        event for event in change["semantic_events"]
        if event["event_type"] == "school_end_changed"
    ]
    assert len(events) == 1
    assert events[0]["previous_end"].endswith("14:45:00+02:00")
    assert events[0]["current_end"].endswith("15:45:00+02:00")



def test_semantic_events_do_not_repeat_persistent_old_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _bare_coordinator()
    item.hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Vienna"))
    monday = Date(2026, 9, 21)
    monkeypatch.setattr(
        coordinator_module.dt_util,
        "now",
        lambda: datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )
    start = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 24, 8, 45, tzinfo=UTC)

    previous = _entry(start, end, teacher="Max", room="B202")
    current = _entry(start, end, teacher="Max", room="B202")
    previous["position3"][0]["removed"] = previous["position3"][0]["current"].copy()
    previous["position2"][0]["removed"] = previous["position2"][0]["current"].copy()
    current["position3"][0]["removed"] = current["position3"][0]["current"].copy()
    current["position2"][0]["removed"] = current["position2"][0]["current"].copy()
    old_lessons = parse_lessons([previous], ZoneInfo("Europe/Vienna"))
    new_lessons = parse_lessons([current], ZoneInfo("Europe/Vienna"))

    event_types = {
        event["event_type"]
        for event in item._semantic_events(old_lessons, new_lessons)
    }
    assert "lesson_substituted" not in event_types
    assert "lesson_room_changed" not in event_types

from __future__ import annotations

import asyncio
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.webuntis_public import coordinator as coordinator_module
from custom_components.webuntis_public.coordinator import (
    WebUntisPublicCoordinator,
    WebUntisTemporaryUnavailable,
)


UTC = timezone.utc


def _coordinator() -> WebUntisPublicCoordinator:
    item = object.__new__(WebUntisPublicCoordinator)
    item._weeks = {}
    item._force_refresh = False
    item._data_source = "unavailable"
    item._last_refresh_attempt = None
    item._last_error = None
    item._last_error_at = None
    item._consecutive_failures = 0
    item._timetable_change_sequence = 0
    item._last_timetable_change = None
    item._timetable_change_history = []
    item._lock = asyncio.Lock()
    item.class_id = 123
    item.class_name = "5A"
    item.server = "example.webuntis.com"
    item.school = "example-school"
    item.school_name = "Example School"
    item.hass = SimpleNamespace(
        config=SimpleNamespace(time_zone="Europe/Vienna")
    )
    item.entry = SimpleNamespace(options={})
    return item


def _entry(
    start: datetime,
    end: datetime,
    *,
    ids: list[int] | None = None,
    subject: str = "Mathematik",
) -> dict:
    return {
        "ids": ids or [1],
        "duration": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "status": "REGULAR",
        "position1": [
            {
                "current": [
                    {
                        "type": "SUBJECT",
                        "longName": subject,
                    }
                ]
            }
        ],
        "position2": [{"current": []}],
        "position3": [{"current": []}],
    }


def test_device_metadata_properties() -> None:
    item = _coordinator()

    assert item.device_identifier == "example.webuntis.com-123"
    assert item.device_name == "Example School – 5A"
    assert item.configuration_url == (
        "https://example.webuntis.com/WebUntis/?school=example-school"
        "#/basic/timetablePublic/class?entityId=123"
    )


def test_configuration_url_without_school() -> None:
    item = _coordinator()
    item.school = None

    assert item.configuration_url == (
        "https://example.webuntis.com/WebUntis/"
        "#/basic/timetablePublic/class?entityId=123"
    )


def test_last_successful_fetch_and_cache_age() -> None:
    item = _coordinator()
    now = datetime.now(UTC)
    item._weeks = {
        "2026-09-21": {
            "fetched_at": now - timedelta(minutes=20),
            "entries": [],
        },
        "2026-09-28": {
            "fetched_at": now - timedelta(minutes=5),
            "entries": [],
        },
    }

    assert item.last_successful_fetch == item._weeks["2026-09-28"]["fetched_at"]
    age = item.cache_age_minutes
    assert age is not None
    assert 4 <= age <= 6


def test_cache_age_is_none_without_cache() -> None:
    item = _coordinator()

    assert item.last_successful_fetch is None
    assert item.cache_age_minutes is None


def test_diagnostic_state_and_error_lifecycle() -> None:
    item = _coordinator()
    item._data_source = "stale_cache"
    item._last_refresh_attempt = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)

    item._record_error("offline")
    first_error_at = item._last_error_at
    item._record_error("still offline")

    state = item.diagnostic_state
    assert state["data_source"] == "stale_cache"
    assert state["last_refresh_attempt"] == "2026-09-23T10:00:00+00:00"
    assert state["last_error"] == "still offline"
    assert state["consecutive_failures"] == 2
    assert first_error_at is not None

    item._clear_error()
    assert item._last_error is None
    assert item._last_error_at is None
    assert item._consecutive_failures == 0


def test_diagnostic_weeks_reports_valid_and_invalid_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    now = datetime.now(UTC)
    item._weeks = {
        "2026-09-21": {
            "fetched_at": now - timedelta(minutes=5),
            "entries": [{"id": 1}],
        },
        "invalid": {
            "fetched_at": now - timedelta(minutes=10),
            "entries": [{"id": 2}, {"id": 3}],
        },
    }
    monkeypatch.setattr(item, "_is_stale", lambda *_args: False)

    result = item.diagnostic_weeks()

    assert result[0]["week"] == "2026-09-21"
    assert result[0]["entries"] == 1
    assert result[0]["stale"] is False
    assert result[1]["week"] == "invalid"
    assert result[1]["entries"] == 2
    assert result[1]["stale"] is None


@pytest.mark.parametrize(
    "stored",
    [
        None,
        [],
        {"weeks": []},
    ],
)
def test_setup_ignores_invalid_store_shapes(stored) -> None:
    item = _coordinator()
    item._store = SimpleNamespace(async_load=AsyncMock(return_value=stored))

    asyncio.run(item._async_setup())

    assert item._weeks == {}
    assert item._data_source == "unavailable"


def test_async_update_data_returns_snapshot_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    item.entry.options = {"next_lesson_days": 7}
    ensure = AsyncMock()
    monkeypatch.setattr(item, "_async_ensure_range", ensure)
    monkeypatch.setattr(
        coordinator_module.dt_util,
        "now",
        lambda: datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(item, "_snapshot", lambda: {"ok": True})

    result = asyncio.run(item._async_update_data())

    assert result == {"ok": True}
    assert ensure.await_count == 1
    start, end = ensure.await_args.args
    assert end - start == timedelta(days=7, minutes=1)
    assert ensure.await_args.kwargs == {"notify": False}


def test_async_update_data_raises_update_failed_without_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    monkeypatch.setattr(
        item,
        "_async_ensure_range",
        AsyncMock(side_effect=WebUntisTemporaryUnavailable("offline")),
    )

    with pytest.raises(UpdateFailed, match="offline"):
        asyncio.run(item._async_update_data())


def test_async_update_data_keeps_cache_on_temporary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    item._weeks["2026-09-21"] = {
        "fetched_at": datetime.now(UTC),
        "entries": [],
    }
    monkeypatch.setattr(
        item,
        "_async_ensure_range",
        AsyncMock(side_effect=WebUntisTemporaryUnavailable("offline")),
    )
    monkeypatch.setattr(item, "_snapshot", lambda: {"source": "cache"})

    assert asyncio.run(item._async_update_data()) == {"source": "cache"}


def test_force_refresh_sets_flag_only_for_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    seen = []

    async def request_refresh():
        seen.append(item._force_refresh)

    monkeypatch.setattr(item, "async_request_refresh", request_refresh)

    asyncio.run(item.async_force_refresh())

    assert seen == [True]
    assert item._force_refresh is False


def test_force_refresh_resets_flag_when_request_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()

    async def request_refresh():
        assert item._force_refresh is True
        raise RuntimeError("boom")

    monkeypatch.setattr(item, "async_request_refresh", request_refresh)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(item.async_force_refresh())

    assert item._force_refresh is False


def test_async_get_lessons_ensures_range_then_reads_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    ensure = AsyncMock()
    monkeypatch.setattr(item, "_async_ensure_range", ensure)
    monkeypatch.setattr(
        item,
        "cached_lessons_between",
        lambda *_args: ["lesson"],
    )

    result = asyncio.run(item.async_get_lessons(start, end))

    assert result == ["lesson"]
    ensure.assert_awaited_once_with(start, end, notify=True)


def test_cached_lessons_between_deduplicates_entries_across_weeks() -> None:
    item = _coordinator()
    start = datetime(2026, 9, 27, 23, 0, tzinfo=UTC)
    end = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
    lesson_start = datetime(2026, 9, 28, 8, 0, tzinfo=UTC)
    lesson_end = datetime(2026, 9, 28, 8, 45, tzinfo=UTC)
    duplicate = _entry(lesson_start, lesson_end, ids=[77])
    item._weeks = {
        "2026-09-21": {
            "fetched_at": datetime.now(UTC),
            "entries": [duplicate, "invalid"],
        },
        "2026-09-28": {
            "fetched_at": datetime.now(UTC),
            "entries": [duplicate],
        },
    }

    lessons = item.cached_lessons_between(start, end)

    assert len(lessons) == 1
    assert lessons[0].subject == "Mathematik"


def test_ensure_range_live_refresh_sets_live_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    item._lock = asyncio.Lock()
    start = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    end = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    monday = Date(2026, 9, 21)

    async def refresh_week(requested_monday):
        assert requested_monday == monday
        item._weeks[monday.isoformat()] = {
            "fetched_at": datetime.now(UTC),
            "entries": [],
        }
        return True, "live", None

    save = AsyncMock()
    notifications = []
    monkeypatch.setattr(item, "_async_refresh_week_if_needed", refresh_week)
    monkeypatch.setattr(item, "_async_save_cache", save)
    monkeypatch.setattr(
        item,
        "async_set_updated_data",
        lambda data: notifications.append(data),
    )
    monkeypatch.setattr(item, "_snapshot", lambda: {"source": item._data_source})

    asyncio.run(item._async_ensure_range(start, end, notify=True))

    assert item._data_source == "live"
    save.assert_awaited_once()
    assert notifications == [{"source": "live"}]
    assert item._last_error is None


def test_ensure_range_uses_cache_without_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    item._lock = asyncio.Lock()
    monday = Date(2026, 9, 21)
    item._weeks[monday.isoformat()] = {
        "fetched_at": datetime.now(UTC),
        "entries": [],
    }
    monkeypatch.setattr(
        item,
        "_async_refresh_week_if_needed",
        AsyncMock(return_value=(False, "cache", None)),
    )
    notify = []
    monkeypatch.setattr(item, "async_set_updated_data", lambda data: notify.append(data))

    asyncio.run(
        item._async_ensure_range(
            datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
            datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
            notify=True,
        )
    )

    assert item._data_source == "cache"
    assert notify == []


def test_ensure_range_stale_cache_records_fallback_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    item._lock = asyncio.Lock()
    monday = Date(2026, 9, 21)
    item._weeks[monday.isoformat()] = {
        "fetched_at": datetime.now(UTC),
        "entries": [],
    }
    monkeypatch.setattr(
        item,
        "_async_refresh_week_if_needed",
        AsyncMock(return_value=(False, "stale_cache", "HTTP 503")),
    )

    asyncio.run(
        item._async_ensure_range(
            datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
            datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
            notify=False,
        )
    )

    assert item._data_source == "stale_cache"
    assert item._last_error == "HTTP 503"
    assert item._consecutive_failures == 1


def test_ensure_range_raises_when_no_requested_week_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    item._lock = asyncio.Lock()
    monkeypatch.setattr(
        item,
        "_async_refresh_week_if_needed",
        AsyncMock(side_effect=WebUntisTemporaryUnavailable("offline")),
    )

    with pytest.raises(WebUntisTemporaryUnavailable, match="offline"):
        asyncio.run(
            item._async_ensure_range(
                datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
                datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
                notify=False,
            )
        )

    assert item._data_source == "unavailable"
    assert item._last_error == "offline"
    assert item._consecutive_failures == 1


def test_ensure_range_continues_when_one_week_fails_but_another_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    item._lock = asyncio.Lock()
    first = Date(2026, 9, 21)
    second = Date(2026, 9, 28)
    item._weeks[second.isoformat()] = {
        "fetched_at": datetime.now(UTC),
        "entries": [],
    }

    async def refresh(monday):
        if monday == first:
            raise WebUntisTemporaryUnavailable("first offline")
        return False, "cache", None

    monkeypatch.setattr(item, "_async_refresh_week_if_needed", refresh)

    asyncio.run(
        item._async_ensure_range(
            datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
            datetime(2026, 9, 29, 12, 0, tzinfo=UTC),
            notify=False,
        )
    )

    assert item._data_source == "cache"


def test_refresh_history_is_limited_to_twenty_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _coordinator()
    monkeypatch.setattr(item, "_is_stale", lambda *_args: True)
    monkeypatch.setattr(
        item,
        "_async_fetch_week",
        AsyncMock(return_value=[]),
    )

    counter = {"value": 0}

    def detect(*_args):
        counter["value"] += 1
        return {
            "week": "2026-09-21",
            "added_count": 1,
            "removed_count": 0,
            "marker": counter["value"],
        }

    monkeypatch.setattr(item, "_detect_timetable_change", detect)

    for index in range(21):
        monday = Date(2026, 1, 5) + timedelta(weeks=index)
        item._weeks[monday.isoformat()] = {
            "fetched_at": datetime.now(UTC) - timedelta(days=10),
            "entries": [{"old": index}],
        }
        asyncio.run(item._async_refresh_week_if_needed(monday))

    assert item.timetable_change_sequence == 21
    assert len(item._timetable_change_history) == 20
    assert item._timetable_change_history[0]["sequence"] == 2
    assert item._timetable_change_history[-1]["sequence"] == 21

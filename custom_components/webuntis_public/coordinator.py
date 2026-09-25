from __future__ import annotations

import asyncio
from datetime import date as Date
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientTimeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLASS_ID,
    CONF_CLASS_NAME,
    CONF_SCHOOL,
    CONF_SCHOOL_NAME,
    CONF_SERVER,
    DEFAULT_EXCLUDE_SUBJECTS,
    DEFAULT_NEXT_LESSON_DAYS,
    DOMAIN,
    OPT_EXCLUDE_SUBJECTS,
    OPT_NEXT_LESSON_DAYS,
)
from .data import WebUntisLesson, as_list, parse_lessons

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=10)
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS = (2, 5)
STORAGE_VERSION = 1
MAX_STALE_CACHE_AGE = timedelta(hours=24)


class WebUntisTemporaryUnavailable(Exception):
    """Raised when WebUntis is unavailable and no cached week exists."""


class WebUntisPublicCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Central data source for all WebUntis Public entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        class_id: int | None = None,
        class_name: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}_{class_id or entry.data[CONF_CLASS_ID]}",
            config_entry=entry,
            update_interval=UPDATE_INTERVAL,
            always_update=True,
        )
        self.entry = entry
        self.server = entry.data[CONF_SERVER]
        self.school = entry.data.get(CONF_SCHOOL) or None
        self.class_id = int(class_id if class_id is not None else entry.data[CONF_CLASS_ID])
        self.class_name = class_name or entry.data.get(CONF_CLASS_NAME, str(self.class_id))
        self.school_name = entry.data.get(CONF_SCHOOL_NAME) or self.school or self.server
        self._session = async_get_clientsession(hass)
        self._lock = asyncio.Lock()
        self._weeks: dict[str, dict[str, Any]] = {}
        primary_class_id = int(entry.data.get(CONF_CLASS_ID, self.class_id))
        store_key = (
            f"{DOMAIN}.{entry.entry_id}"
            if self.class_id == primary_class_id
            else f"{DOMAIN}.{entry.entry_id}.{self.class_id}"
        )
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, store_key)

        self._data_source = "unavailable"
        self._last_refresh_attempt: datetime | None = None
        self._last_error: str | None = None
        self._last_error_at: datetime | None = None
        self._consecutive_failures = 0
        self._force_refresh = False
        self._timetable_change_sequence = 0
        self._last_timetable_change: dict[str, Any] | None = None
        self._timetable_change_history: list[dict[str, Any]] = []

    @property
    def device_identifier(self) -> str:
        return f"{self.server}-{self.class_id}"

    @property
    def device_name(self) -> str:
        return f"{self.school_name} – {self.class_name}"

    @property
    def configuration_url(self) -> str:
        school = f"?school={self.school}" if self.school else ""
        return (
            f"https://{self.server}/WebUntis/{school}"
            f"#/basic/timetablePublic/class?entityId={self.class_id}"
        )

    @property
    def data_source(self) -> str:
        return self._data_source

    @property
    def timetable_change_sequence(self) -> int:
        """Return an incrementing sequence for detected timetable changes."""
        return self._timetable_change_sequence

    @property
    def last_timetable_change(self) -> dict[str, Any] | None:
        """Return the last detected semantic timetable change."""
        return self._last_timetable_change

    def timetable_changes_since(self, sequence: int) -> list[dict[str, Any]]:
        """Return recent timetable changes newer than the supplied sequence."""
        return [
            change
            for change in self._timetable_change_history
            if int(change.get("sequence", 0)) > sequence
        ]

    @property
    def last_successful_fetch(self) -> datetime | None:
        return max(
            (value["fetched_at"] for value in self._weeks.values()),
            default=None,
        )

    @property
    def cache_age_minutes(self) -> int | None:
        fetched_at = self.last_successful_fetch
        if fetched_at is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - fetched_at).total_seconds() // 60))

    @property
    def diagnostic_state(self) -> dict[str, Any]:
        return {
            "data_source": self._data_source,
            "last_successful_fetch": (
                self.last_successful_fetch.isoformat()
                if self.last_successful_fetch
                else None
            ),
            "last_refresh_attempt": (
                self._last_refresh_attempt.isoformat()
                if self._last_refresh_attempt
                else None
            ),
            "cache_age_minutes": self.cache_age_minutes,
            "weeks_cached": len(self._weeks),
            "last_error": self._last_error,
            "last_error_at": (
                self._last_error_at.isoformat() if self._last_error_at else None
            ),
            "consecutive_failures": self._consecutive_failures,
        }

    def diagnostic_weeks(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        result: list[dict[str, Any]] = []
        for key in sorted(self._weeks):
            value = self._weeks[key]
            fetched_at = value["fetched_at"]
            try:
                monday = Date.fromisoformat(key)
                stale = self._is_stale(monday, fetched_at)
            except ValueError:
                stale = None
            result.append(
                {
                    "week": key,
                    "fetched_at": fetched_at.isoformat(),
                    "age_minutes": max(
                        0, int((now - fetched_at).total_seconds() // 60)
                    ),
                    "entries": len(value.get("entries", [])),
                    "stale": stale,
                }
            )
        return result

    async def _async_setup(self) -> None:
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        weeks = stored.get("weeks")
        if not isinstance(weeks, dict):
            return

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=120)
        for key, value in weeks.items():
            if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
                continue
            fetched_at = self._parse_utc(value.get("fetched_at"))
            if fetched_at is None or fetched_at < cutoff:
                continue
            self._weeks[str(key)] = {
                "fetched_at": fetched_at,
                "entries": value["entries"],
            }

        if self._weeks:
            self._data_source = "cache"
            _LOGGER.debug("Loaded %d WebUntis week(s) from persistent cache", len(self._weeks))

    async def _async_update_data(self) -> dict[str, Any]:
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
        now = dt_util.now().astimezone(tz)
        lookahead_days = int(
            self.entry.options.get(OPT_NEXT_LESSON_DAYS, DEFAULT_NEXT_LESSON_DAYS)
        )
        try:
            await self._async_ensure_range(
                now - timedelta(minutes=1),
                now + timedelta(days=lookahead_days),
                notify=False,
            )
        except WebUntisTemporaryUnavailable as err:
            if not self._weeks:
                raise UpdateFailed(str(err)) from err
            _LOGGER.warning("WebUntis unavailable; keeping cached timetable: %s", err)

        return self._snapshot()

    async def async_force_refresh(self) -> None:
        """Refresh all coordinator weeks from WebUntis, bypassing cache TTL once."""
        self._force_refresh = True
        try:
            await self.async_request_refresh()
        finally:
            self._force_refresh = False

    async def async_get_lessons(
        self, start_date: datetime, end_date: datetime
    ) -> list[WebUntisLesson]:
        await self._async_ensure_range(start_date, end_date, notify=True)
        return self.cached_lessons_between(start_date, end_date)

    def cached_lessons_between(
        self, start_date: datetime, end_date: datetime
    ) -> list[WebUntisLesson]:
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
        start_local = self._to_local(start_date, tz)
        end_local = self._to_local(end_date, tz)
        entries: list[dict[str, Any]] = []

        for monday in self._weeks_for_range(start_local, end_local):
            cached = self._weeks.get(monday.isoformat())
            if not cached:
                continue
            entries.extend(
                entry
                for entry in cached["entries"]
                if isinstance(entry, dict)
            )

        # parse_lessons performs semantic grouping after parsing start/end and
        # lesson metadata. Avoid deduplicating raw API entries here: WebUntis
        # may omit technical IDs, and distinct simultaneous lessons must not be
        # discarded merely because their duration is identical.
        lessons = parse_lessons(entries, start_local, end_local, tz)
        excluded_subjects = self._excluded_subjects()
        if not excluded_subjects:
            return lessons

        return [
            lesson
            for lesson in lessons
            if not any(
                subject.casefold() in excluded_subjects
                for subject in (
                    lesson.subject,
                    *lesson.subjects,
                    *lesson.old_subjects,
                )
                if subject
            )
        ]

    def _excluded_subjects(self) -> set[str]:
        """Return normalized subject names configured for exclusion."""
        entry = getattr(self, "entry", None)
        options = getattr(entry, "options", {}) if entry is not None else {}
        raw_value = options.get(OPT_EXCLUDE_SUBJECTS, DEFAULT_EXCLUDE_SUBJECTS)
        if not isinstance(raw_value, str):
            return set()

        return {
            value.strip().casefold()
            for value in raw_value.replace("\n", ",").split(",")
            if value.strip()
        }

    async def _async_ensure_range(
        self,
        start_date: datetime,
        end_date: datetime,
        *,
        notify: bool,
    ) -> None:
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
        start_local = self._to_local(start_date, tz)
        end_local = self._to_local(end_date, tz)
        weeks = self._weeks_for_range(start_local, end_local)
        changed = False
        errors: list[WebUntisTemporaryUnavailable] = []
        sources: list[str] = []
        fallback_errors: list[str] = []
        self._last_refresh_attempt = datetime.now(timezone.utc)

        async with self._lock:
            for monday in weeks:
                try:
                    week_changed, source, fallback_error = (
                        await self._async_refresh_week_if_needed(monday)
                    )
                except WebUntisTemporaryUnavailable as err:
                    errors.append(err)
                    _LOGGER.warning("Could not load WebUntis week %s: %s", monday, err)
                    continue
                changed = changed or week_changed
                sources.append(source)
                if fallback_error:
                    fallback_errors.append(fallback_error)
            if changed:
                await self._async_save_cache()

        available_weeks = sum(
            1 for monday in weeks if monday.isoformat() in self._weeks
        )
        if errors and available_weeks == 0:
            self._data_source = "unavailable"
            self._record_error(str(errors[0]))
            raise errors[0]

        if "stale_cache" in sources:
            self._data_source = "stale_cache"
            if fallback_errors:
                self._record_error(fallback_errors[-1])
        elif "live" in sources:
            self._data_source = "live"
            self._clear_error()
        elif sources:
            self._data_source = "cache"

        if changed and notify:
            self.async_set_updated_data(self._snapshot())

    async def _async_refresh_week_if_needed(
        self, monday: Date
    ) -> tuple[bool, str, str | None]:
        key = monday.isoformat()
        cached = self._weeks.get(key)
        if (
            cached
            and not self._force_refresh
            and not self._is_stale(monday, cached["fetched_at"])
        ):
            return False, "cache", None

        stale_entries = cached["entries"] if cached else None
        last_error: Exception | None = None
        attempts = len(RETRY_DELAYS) + 1

        for attempt in range(attempts):
            try:
                entries = await self._async_fetch_week(monday)
            except (ClientError, asyncio.TimeoutError, ValueError) as err:
                last_error = err
                status = err.status if isinstance(err, ClientResponseError) else None
                retryable = status is None or status in RETRYABLE_HTTP_STATUS
                if not retryable or attempt >= attempts - 1:
                    break
                delay = RETRY_DELAYS[attempt]
                _LOGGER.debug(
                    "WebUntis request for week %s failed%s; retrying in %ss",
                    key,
                    f" with HTTP {status}" if status else "",
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                timetable_change = self._detect_timetable_change(
                    monday,
                    stale_entries,
                    entries,
                )
                self._weeks[key] = {
                    "fetched_at": datetime.now(timezone.utc),
                    "entries": entries,
                }
                if timetable_change:
                    self._timetable_change_sequence += 1
                    timetable_change["sequence"] = self._timetable_change_sequence
                    self._last_timetable_change = timetable_change
                    self._timetable_change_history.append(timetable_change)
                    self._timetable_change_history = self._timetable_change_history[-20:]
                    _LOGGER.info(
                        "Detected WebUntis timetable change for class %s in week %s: "
                        "%d added, %d removed",
                        self.class_name,
                        key,
                        timetable_change["added_count"],
                        timetable_change["removed_count"],
                    )
                if attempt:
                    _LOGGER.info(
                        "WebUntis request for week %s succeeded after %d retry/retries",
                        key,
                        attempt,
                    )
                return True, "live", None

        error_text = str(last_error) if last_error else "Unknown fetch error"
        if stale_entries is not None and self._cache_is_usable_fallback(cached):
            _LOGGER.warning(
                "WebUntis unavailable for week %s; using persistent/stale cache (%s)",
                key,
                last_error,
            )
            return False, "stale_cache", error_text

        if stale_entries is not None:
            _LOGGER.warning(
                "WebUntis unavailable for week %s; cached data is older than %s and "
                "will not be used (%s)",
                key,
                MAX_STALE_CACHE_AGE,
                last_error,
            )

        raise WebUntisTemporaryUnavailable(
            f"Fetch for week {key} failed: {last_error}"
        ) from last_error

    @staticmethod
    def _cache_is_usable_fallback(cached: dict[str, Any] | None) -> bool:
        """Return whether cached data is recent enough for outage fallback."""
        if not cached:
            return False
        fetched_at = cached.get("fetched_at")
        if not isinstance(fetched_at, datetime):
            return False
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        else:
            fetched_at = fetched_at.astimezone(timezone.utc)
        return dt_util.utcnow() - fetched_at <= MAX_STALE_CACHE_AGE

    async def _async_fetch_week(self, monday: Date) -> list[dict[str, Any]]:
        saturday = monday + timedelta(days=5)
        url = f"https://{self.server}/WebUntis/api/rest/view/v1/timetable/entries"
        params = {
            "start": monday.isoformat(),
            "end": saturday.isoformat(),
            "format": "2",
            "resourceType": "CLASS",
            "resources": str(self.class_id),
            "timetableType": "STANDARD",
            "layout": "START_TIME",
        }
        headers = {
            "Accept": "application/json",
            "User-Agent": "HomeAssistant-WebUntis-Public",
        }
        if self.school:
            headers["anonymous-school"] = self.school

        async with self._session.get(
            url,
            params=params,
            headers=headers,
            timeout=ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            raw = await response.json(content_type=None)

        entries: list[dict[str, Any]] = []
        if not isinstance(raw, dict) or "days" not in raw:
            raise ValueError("Unexpected WebUntis response format")

        days = raw["days"]
        if not isinstance(days, list):
            raise ValueError("Unexpected WebUntis days format")

        for day in days:
            if not isinstance(day, dict):
                raise ValueError("Unexpected WebUntis day format")

            grid_entries = day.get("gridEntries")
            if grid_entries is None:
                continue
            if isinstance(grid_entries, dict):
                grid_entries = [grid_entries]
            elif not isinstance(grid_entries, list):
                raise ValueError("Unexpected WebUntis gridEntries format")

            for entry in grid_entries:
                if not isinstance(entry, dict):
                    raise ValueError("Unexpected WebUntis timetable entry format")
                entries.append(entry)

        _LOGGER.debug("Fetched %d WebUntis entries for week %s", len(entries), monday)
        return entries

    def _detect_timetable_change(
        self,
        monday: Date,
        old_entries: list[dict[str, Any]] | None,
        new_entries: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Compare semantic lesson data and return future-relevant differences."""
        if old_entries is None:
            return None

        tz = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
        start_local = datetime(
            monday.year,
            monday.month,
            monday.day,
            tzinfo=tz,
        )
        end_local = start_local + timedelta(days=7)
        now_local = dt_util.now().astimezone(tz)

        old_lessons = [
            lesson
            for lesson in parse_lessons(
                old_entries,
                start_local,
                end_local,
                tz,
            )
            if lesson.end > now_local
        ]
        new_lessons = [
            lesson
            for lesson in parse_lessons(
                new_entries,
                start_local,
                end_local,
                tz,
            )
            if lesson.end > now_local
        ]

        old_map = {
            self._lesson_fingerprint(lesson): lesson
            for lesson in old_lessons
        }
        new_map = {
            self._lesson_fingerprint(lesson): lesson
            for lesson in new_lessons
        }

        added_keys = sorted(new_map.keys() - old_map.keys())
        removed_keys = sorted(old_map.keys() - new_map.keys())
        if not added_keys and not removed_keys:
            return None

        return {
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "week": monday.isoformat(),
            "class_name": self.class_name,
            "added_count": len(added_keys),
            "removed_count": len(removed_keys),
            "change_count": len(added_keys) + len(removed_keys),
            "added": [
                self._lesson_event_data(new_map[key])
                for key in added_keys[:20]
            ],
            "removed": [
                self._lesson_event_data(old_map[key])
                for key in removed_keys[:20]
            ],
            "semantic_events": self._semantic_events(old_lessons, new_lessons),
            "truncated": len(added_keys) > 20 or len(removed_keys) > 20,
        }

    def _semantic_events(
        self,
        old_lessons: list[WebUntisLesson],
        new_lessons: list[WebUntisLesson],
    ) -> list[dict[str, Any]]:
        """Return automation-friendly events for important timetable changes."""
        events: list[dict[str, Any]] = []
        old_by_slot: dict[tuple[str, str], list[WebUntisLesson]] = {}
        for lesson in old_lessons:
            key = (lesson.start.isoformat(), lesson.end.isoformat())
            old_by_slot.setdefault(key, []).append(lesson)

        for lesson in new_lessons:
            key = (lesson.start.isoformat(), lesson.end.isoformat())
            candidates = old_by_slot.get(key, [])
            previous = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.subject == lesson.subject
                ),
                candidates[0] if len(candidates) == 1 else None,
            )
            if previous is None:
                continue

            base = {
                "class_name": self.class_name,
                "start": lesson.start.isoformat(),
                "end": lesson.end.isoformat(),
                "subject": lesson.subject,
                "teacher": lesson.teacher,
                "room": lesson.room,
            }

            if lesson.cancelled and not previous.cancelled:
                events.append(
                    {
                        **base,
                        "event_type": "lesson_cancelled",
                        "previous": self._lesson_event_data(previous),
                        "current": self._lesson_event_data(lesson),
                    }
                )
                continue

            subject_changed = previous.subjects != lesson.subjects
            teacher_changed = previous.teachers != lesson.teachers
            if subject_changed or teacher_changed:
                events.append(
                    {
                        **base,
                        "event_type": "lesson_substituted",
                        "previous": self._lesson_event_data(previous),
                        "current": self._lesson_event_data(lesson),
                    }
                )

            room_changed = previous.rooms != lesson.rooms
            if room_changed:
                events.append(
                    {
                        **base,
                        "event_type": "lesson_room_changed",
                        "previous": self._lesson_event_data(previous),
                        "current": self._lesson_event_data(lesson),
                    }
                )

        events.extend(self._lesson_time_change_events(old_lessons, new_lessons))
        events.extend(self._school_day_boundary_events(old_lessons, new_lessons))
        return events

    def _school_day_boundary_events(
        self,
        old_lessons: list[WebUntisLesson],
        new_lessons: list[WebUntisLesson],
    ) -> list[dict[str, Any]]:
        """Detect changed first/last lesson times for each school day."""
        events: list[dict[str, Any]] = []
        dates = sorted(
            {lesson.start.date() for lesson in old_lessons}
            & {lesson.start.date() for lesson in new_lessons}
        )

        for day in dates:
            old_day = sorted(
                (lesson for lesson in old_lessons if lesson.start.date() == day),
                key=lambda lesson: (lesson.start, lesson.end),
            )
            new_day = sorted(
                (lesson for lesson in new_lessons if lesson.start.date() == day),
                key=lambda lesson: (lesson.start, lesson.end),
            )
            old_first, new_first = old_day[0], new_day[0]
            if old_first.start != new_first.start:
                events.append(
                    {
                        "event_type": "school_start_changed",
                        "class_name": self.class_name,
                        "date": day.isoformat(),
                        "previous_start": old_first.start.isoformat(),
                        "current_start": new_first.start.isoformat(),
                    }
                )

            old_last, new_last = old_day[-1], new_day[-1]
            if old_last.end != new_last.end:
                events.append(
                    {
                        "event_type": "school_end_changed",
                        "class_name": self.class_name,
                        "date": day.isoformat(),
                        "previous_end": old_last.end.isoformat(),
                        "current_end": new_last.end.isoformat(),
                    }
                )

        return events

    def _lesson_time_change_events(
        self,
        old_lessons: list[WebUntisLesson],
        new_lessons: list[WebUntisLesson],
    ) -> list[dict[str, Any]]:
        """Detect lessons that moved while retaining their semantic identity."""
        events: list[dict[str, Any]] = []
        matched_new: set[int] = set()

        for previous in old_lessons:
            candidates = [
                (index, lesson)
                for index, lesson in enumerate(new_lessons)
                if index not in matched_new
                and lesson.subject == previous.subject
                and lesson.start.date() == previous.start.date()
                and (lesson.start != previous.start or lesson.end != previous.end)
            ]
            if len(candidates) != 1:
                continue

            index, lesson = candidates[0]
            matched_new.add(index)
            events.append(
                {
                    "event_type": "lesson_time_changed",
                    "class_name": self.class_name,
                    "start": lesson.start.isoformat(),
                    "end": lesson.end.isoformat(),
                    "subject": lesson.subject,
                    "teacher": lesson.teacher,
                    "room": lesson.room,
                    "previous": self._lesson_event_data(previous),
                    "current": self._lesson_event_data(lesson),
                }
            )

        return events

    @staticmethod
    def _lesson_fingerprint(lesson: WebUntisLesson) -> tuple[Any, ...]:
        """Return a stable semantic fingerprint, ignoring technical duplicates."""
        return (
            lesson.start.isoformat(),
            lesson.end.isoformat(),
            lesson.status,
            lesson.subjects,
            lesson.old_subjects,
            lesson.teachers,
            lesson.old_teachers,
            lesson.rooms,
            lesson.old_rooms,
            lesson.texts,
        )

    @staticmethod
    def _lesson_event_data(lesson: WebUntisLesson) -> dict[str, Any]:
        """Return compact JSON-serialisable lesson data for the event entity."""
        return {
            "start": lesson.start.isoformat(),
            "end": lesson.end.isoformat(),
            "subject": lesson.subject,
            "status": lesson.status_label or "regular",
            "teacher": lesson.teacher,
            "room": lesson.room,
        }

    def _is_stale(self, monday: Date, fetched_at: datetime) -> bool:
        now = datetime.now(timezone.utc)
        today = dt_util.now().date()
        current_monday = today - timedelta(days=today.weekday())
        delta_weeks = (monday - current_monday).days // 7

        if delta_weeks == 0:
            ttl = timedelta(minutes=10)
        elif delta_weeks == 1:
            ttl = timedelta(minutes=30)
        elif delta_weeks > 1:
            ttl = timedelta(hours=6)
        else:
            ttl = timedelta(hours=24)
        return now - fetched_at >= ttl

    async def _async_save_cache(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=120)
        serialised: dict[str, Any] = {}
        for key, value in self._weeks.items():
            fetched_at = value["fetched_at"]
            if fetched_at < cutoff:
                continue
            serialised[key] = {
                "fetched_at": fetched_at.isoformat(),
                "entries": value["entries"],
            }
        await self._store.async_save({"weeks": serialised})

    def _record_error(self, error: str) -> None:
        self._last_error = error
        self._last_error_at = datetime.now(timezone.utc)
        self._consecutive_failures += 1

    def _clear_error(self) -> None:
        self._last_error = None
        self._last_error_at = None
        self._consecutive_failures = 0

    def _snapshot(self) -> dict[str, Any]:
        return self.diagnostic_state

    @staticmethod
    def _weeks_for_range(start_local: datetime, end_local: datetime) -> list[Date]:
        first_day = start_local.date()
        last_day = end_local.date()
        monday = first_day - timedelta(days=first_day.weekday())
        weeks: list[Date] = []
        cursor = monday
        while cursor <= last_day:
            weeks.append(cursor)
            cursor += timedelta(days=7)
        return weeks

    @staticmethod
    def _to_local(value: datetime, tz) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=tz)
        return value.astimezone(tz)

    @staticmethod
    def _parse_utc(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

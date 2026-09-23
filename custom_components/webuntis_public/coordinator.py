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
    DEFAULT_NEXT_LESSON_DAYS,
    DOMAIN,
    OPT_NEXT_LESSON_DAYS,
)
from .data import WebUntisLesson, as_list, parse_lessons

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=10)
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS = (2, 5)
STORAGE_VERSION = 1


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
        seen: set[tuple[str, str, str]] = set()

        for monday in self._weeks_for_range(start_local, end_local):
            cached = self._weeks.get(monday.isoformat())
            if not cached:
                continue
            for entry in cached["entries"]:
                if not isinstance(entry, dict):
                    continue
                duration = entry.get("duration") or {}
                ids = entry.get("ids") or []
                key = (
                    str(duration.get("start") or ""),
                    str(duration.get("end") or ""),
                    ",".join(str(value) for value in ids),
                )
                if key in seen:
                    continue
                seen.add(key)
                entries.append(entry)

        return parse_lessons(entries, start_local, end_local, tz)

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
        if cached and not self._is_stale(monday, cached["fetched_at"]):
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
                self._weeks[key] = {
                    "fetched_at": datetime.now(timezone.utc),
                    "entries": entries,
                }
                if attempt:
                    _LOGGER.info(
                        "WebUntis request for week %s succeeded after %d retry/retries",
                        key,
                        attempt,
                    )
                return True, "live", None

        error_text = str(last_error) if last_error else "Unbekannter Abruffehler"
        if stale_entries is not None:
            _LOGGER.warning(
                "WebUntis unavailable for week %s; using persistent/stale cache (%s)",
                key,
                last_error,
            )
            return False, "stale_cache", error_text

        raise WebUntisTemporaryUnavailable(
            f"Abruf für Woche {key} fehlgeschlagen: {last_error}"
        ) from last_error

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
            "User-Agent": "HomeAssistant-WebUntis-Public/0.6.0",
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
        if not isinstance(raw, dict):
            raise ValueError("Unerwartetes WebUntis-Antwortformat")
        for day in as_list(raw.get("days")):
            if not isinstance(day, dict):
                continue
            for entry in as_list(day.get("gridEntries")):
                if isinstance(entry, dict):
                    entries.append(entry)

        _LOGGER.debug("Fetched %d WebUntis entries for week %s", len(entries), monday)
        return entries

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

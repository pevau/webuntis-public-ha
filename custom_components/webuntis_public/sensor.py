from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NEXT_LESSON_DAYS, DOMAIN, OPT_NEXT_LESSON_DAYS
from .coordinator import WebUntisPublicCoordinator
from .data import WebUntisLesson
from .schedule import (
    current_slot,
    day_bounds,
    local_now,
    next_slot,
    instruction_elapsed_seconds,
    instruction_total_seconds,
    school_status,
    slot_changed,
    slot_rooms,
    slot_subjects,
    slot_teachers,
    unique_slots,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: list[WebUntisPublicCoordinator] = entry.runtime_data
    entities: list[SensorEntity] = []
    for coordinator in coordinators:
        entities.extend(
            [
                WebUntisCurrentLessonSensor(entry, coordinator),
                WebUntisNextLessonSensor(entry, coordinator),
                WebUntisSchoolStatusSensor(entry, coordinator),
                WebUntisTodayStartSensor(entry, coordinator),
                WebUntisTodayEndSensor(entry, coordinator),
                WebUntisNextSchoolDaySensor(entry, coordinator),
                WebUntisNextSchoolDaySummarySensor(entry, coordinator),
                WebUntisSchoolDayProgressSensor(entry, coordinator),
                WebUntisInstructionProgressSensor(entry, coordinator),
                WebUntisDailySummarySensor(entry, coordinator),
                WebUntisDataStatusSensor(entry, coordinator),
                WebUntisLastSuccessfulFetchSensor(entry, coordinator),
                WebUntisCachedWeeksSensor(entry, coordinator),
            ]
        )
    async_add_entities(entities)


class _WebUntisSensorBase(
    CoordinatorEntity[WebUntisPublicCoordinator], SensorEntity
):
    _attr_has_entity_name = True
    _time_sensitive = False

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator, key: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{coordinator.device_identifier}-{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_identifier)},
            "name": coordinator.device_name,
            "manufacturer": "Untis",
            "model": "Public timetable",
            "configuration_url": coordinator.configuration_url,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._time_sensitive:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass,
                    lambda _now: self.async_write_ha_state(),
                    timedelta(minutes=1),
                )
            )

    def _lessons_for_day(self, offset_days: int = 0) -> list[WebUntisLesson]:
        start, end = day_bounds(self.hass, offset_days)
        return self.coordinator.cached_lessons_between(start, end)

    def _lessons_today(self) -> list[WebUntisLesson]:
        return self._lessons_for_day(0)

    def _next_school_day_slots(self):
        days = int(
            self._entry.options.get(
                OPT_NEXT_LESSON_DAYS, DEFAULT_NEXT_LESSON_DAYS
            )
        )
        for offset in range(1, days + 1):
            slots = unique_slots(self._lessons_for_day(offset))
            if slots:
                return offset, slots
        return None


class WebUntisCurrentLessonSensor(_WebUntisSensorBase):
    _attr_translation_key = "current_lesson"
    _attr_icon = "mdi:book-open-page-variant-outline"
    _time_sensitive = True

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "current_lesson")

    def _slot(self):
        return current_slot(self._lessons_today(), local_now(self.hass))

    @property
    def native_value(self) -> str:
        slot = self._slot()
        return slot_subjects(slot) if slot else "no_lesson"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slot = self._slot()
        if slot is None:
            return {"laeuft_gerade": False}
        return {
            "beginn": slot[0].isoformat(),
            "ende": slot[1].isoformat(),
            "raum": slot_rooms(slot),
            "lehrer": slot_teachers(slot),
            "geaendert": slot_changed(slot),
            "laeuft_gerade": True,
        }


class WebUntisNextLessonSensor(_WebUntisSensorBase):
    _attr_translation_key = "next_lesson"
    _attr_icon = "mdi:book-clock-outline"
    _time_sensitive = True

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "next_lesson")

    def _slot(self):
        now = local_now(self.hass)
        days = int(self._entry.options.get(OPT_NEXT_LESSON_DAYS, DEFAULT_NEXT_LESSON_DAYS))
        lessons = self.coordinator.cached_lessons_between(
            now - timedelta(minutes=1), now + timedelta(days=days)
        )
        return next_slot(lessons, now)

    @property
    def native_value(self) -> str | None:
        slot = self._slot()
        return slot_subjects(slot) if slot else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slot = self._slot()
        if slot is None:
            return {}
        now = local_now(self.hass)
        return {
            "beginn": slot[0].isoformat(),
            "ende": slot[1].isoformat(),
            "raum": slot_rooms(slot),
            "lehrer": slot_teachers(slot),
            "laeuft_gerade": slot[0] <= now < slot[1],
            "geaendert": slot_changed(slot),
        }


class WebUntisSchoolStatusSensor(_WebUntisSensorBase):
    _attr_translation_key = "school_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "school_free",
        "before_school",
        "lesson",
        "break",
        "after_school",
    ]
    _time_sensitive = True

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "school_status")

    def _values(self) -> dict[str, Any]:
        lessons = self._lessons_today()
        slots = unique_slots(lessons)
        now = local_now(self.hass)
        current = current_slot(lessons, now)
        future = [slot for slot in slots if slot[0] > now]
        next_lesson = min(future, key=lambda slot: (slot[0], slot[1]), default=None)
        return {
            "status": school_status(lessons, now),
            "start": min((slot[0] for slot in slots), default=None),
            "end": max((slot[1] for slot in slots), default=None),
            "current": current,
            "next": next_lesson,
            "remaining": len([slot for slot in slots if slot[1] > now]),
        }

    @property
    def native_value(self) -> str:
        return self._values()["status"]

    @property
    def icon(self) -> str:
        return {
            "school_free": "mdi:calendar-remove-outline",
            "before_school": "mdi:clock-start",
            "lesson": "mdi:school",
            "break": "mdi:coffee-outline",
            "after_school": "mdi:home-clock-outline",
        }.get(self.native_value, "mdi:school-outline")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        values = self._values()
        current = values["current"]
        next_lesson = values["next"]
        return {
            "schulbeginn": values["start"].isoformat() if values["start"] is not None else None,
            "schulschluss": values["end"].isoformat() if values["end"] is not None else None,
            "aktuelles_fach": slot_subjects(current) if current is not None else None,
            "aktuelle_stunde_bis": current[1].isoformat() if current is not None else None,
            "naechstes_fach": slot_subjects(next_lesson) if next_lesson is not None else None,
            "naechste_stunde_ab": next_lesson[0].isoformat() if next_lesson is not None else None,
            "verbleibende_stunden": values["remaining"],
        }


class _DayBoundarySensor(_WebUntisSensorBase):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    day_offset = 0
    use_end = False

    @property
    def native_value(self) -> datetime | None:
        slots = unique_slots(self._lessons_for_day(self.day_offset))
        if not slots:
            return None
        return max(slot[1] for slot in slots) if self.use_end else min(slot[0] for slot in slots)


class WebUntisTodayStartSensor(_DayBoundarySensor):
    _attr_translation_key = "today_start"
    _attr_icon = "mdi:clock-start"

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "today_start")


class WebUntisTodayEndSensor(_DayBoundarySensor):
    _attr_translation_key = "today_end"
    _attr_icon = "mdi:clock-end"
    use_end = True

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "today_end")


class WebUntisNextSchoolDaySensor(_WebUntisSensorBase):
    _attr_translation_key = "next_school_day"
    _attr_icon = "mdi:calendar-arrow-right"
    _attr_device_class = SensorDeviceClass.DATE
    _time_sensitive = True

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "next_school_day")

    @property
    def native_value(self) -> date | None:
        result = self._next_school_day_slots()
        if result is None:
            return None
        _offset, slots = result
        return slots[0][0].date()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._next_school_day_slots()
        if result is None:
            return {}
        _offset, slots = result
        return {
            "schulbeginn": min(slot[0] for slot in slots).isoformat(),
            "schulschluss": max(slot[1] for slot in slots).isoformat(),
            "stunden": len(slots),
            "faecher": [slot_subjects(slot) for slot in slots],
        }


class WebUntisNextSchoolDaySummarySensor(_WebUntisSensorBase):
    _attr_translation_key = "next_school_day_summary"
    _attr_icon = "mdi:calendar-text-outline"
    _time_sensitive = True

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "next_school_day_summary")

    def _values(self) -> dict[str, Any] | None:
        result = self._next_school_day_slots()
        if result is None:
            return None

        offset, slots = result
        lessons = self._lessons_for_day(offset)
        changed = [lesson for lesson in lessons if lesson.changed]
        cancelled = [lesson for lesson in lessons if lesson.cancelled]

        teachers: list[str] = []
        rooms: list[str] = []
        for slot in slots:
            for lesson in slot[2]:
                for teacher in lesson.teachers:
                    if teacher and teacher not in teachers:
                        teachers.append(teacher)
                for room in lesson.rooms:
                    if room and room not in rooms:
                        rooms.append(room)

        return {
            "offset": offset,
            "slots": slots,
            "changed": changed,
            "cancelled": cancelled,
            "teachers": teachers,
            "rooms": rooms,
        }

    @property
    def native_value(self) -> int | None:
        values = self._values()
        return len(values["slots"]) if values is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        values = self._values()
        if values is None:
            return {}

        slots = values["slots"]
        changed = values["changed"]
        cancelled = values["cancelled"]

        return {
            "datum": slots[0][0].date().isoformat(),
            "tage_bis_dahin": values["offset"],
            "schulbeginn": min(slot[0] for slot in slots).isoformat(),
            "schulschluss": max(slot[1] for slot in slots).isoformat(),
            "faecher": [slot_subjects(slot) for slot in slots],
            "lehrer": values["teachers"],
            "raeume": values["rooms"],
            "aenderungen": len(changed),
            "geaenderte_faecher": [lesson.subject for lesson in changed],
            "ausfaelle": len(cancelled),
            "ausgefallene_faecher": [lesson.subject for lesson in cancelled],
            "stundenplan": [
                {
                    "beginn": slot[0].isoformat(),
                    "ende": slot[1].isoformat(),
                    "fach": slot_subjects(slot),
                    "lehrer": slot_teachers(slot),
                    "raum": slot_rooms(slot),
                    "geaendert": slot_changed(slot),
                }
                for slot in slots
            ],
        }


class WebUntisSchoolDayProgressSensor(_WebUntisSensorBase):
    _attr_translation_key = "school_day_progress"
    _attr_icon = "mdi:progress-clock"
    _attr_native_unit_of_measurement = PERCENTAGE
    _time_sensitive = True

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "school_day_progress")

    def _progress_data(self) -> tuple[float | None, datetime | None, datetime | None]:
        slots = unique_slots(self._lessons_today())
        if not slots:
            return None, None, None

        start = min(slot[0] for slot in slots)
        end = max(slot[1] for slot in slots)
        now = local_now(self.hass)

        if now <= start:
            progress = 0.0
        elif now >= end:
            progress = 100.0
        else:
            total = (end - start).total_seconds()
            elapsed = (now - start).total_seconds()
            progress = 100.0 * elapsed / total if total > 0 else 100.0

        return round(max(0.0, min(100.0, progress)), 1), start, end

    @property
    def native_value(self) -> float | None:
        return self._progress_data()[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        progress, start, end = self._progress_data()
        if progress is None or start is None or end is None:
            return {"schulfrei": True, "inklusive_pausen": True}

        now = local_now(self.hass)
        total_minutes = max(0, round((end - start).total_seconds() / 60))
        elapsed_minutes = max(
            0,
            min(total_minutes, round((now - start).total_seconds() / 60)),
        )
        return {
            "schulfrei": False,
            "schulbeginn": start.isoformat(),
            "schulschluss": end.isoformat(),
            "vergangen_minuten": elapsed_minutes,
            "gesamt_minuten": total_minutes,
            "inklusive_pausen": True,
        }


class WebUntisInstructionProgressSensor(_WebUntisSensorBase):
    _attr_translation_key = "instruction_progress"
    _attr_icon = "mdi:book-clock-outline"
    _attr_native_unit_of_measurement = PERCENTAGE
    _time_sensitive = True

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "instruction_progress")

    def _values(self) -> tuple[float | None, int, int]:
        lessons = self._lessons_today()
        total_seconds = instruction_total_seconds(lessons)
        if total_seconds <= 0:
            return None, 0, 0

        elapsed_seconds = instruction_elapsed_seconds(lessons, local_now(self.hass))
        progress = 100.0 * elapsed_seconds / total_seconds
        return (
            round(max(0.0, min(100.0, progress)), 1),
            int((elapsed_seconds + 59) // 60),
            int((total_seconds + 59) // 60),
        )

    @property
    def native_value(self) -> float | None:
        return self._values()[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        progress, elapsed_minutes, total_minutes = self._values()
        return {
            "schulfrei": progress is None,
            "unterricht_minuten_absolviert": elapsed_minutes,
            "unterricht_minuten_gesamt": total_minutes,
            "unterricht_minuten_verbleibend": max(0, total_minutes - elapsed_minutes),
            "pausen_nicht_mitgerechnet": True,
        }


class WebUntisDailySummarySensor(_WebUntisSensorBase):
    _attr_translation_key = "daily_summary"
    _attr_icon = "mdi:calendar-today"
    _time_sensitive = True

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "daily_summary")

    def _values(self):
        lessons = self._lessons_today()
        slots = unique_slots(lessons)
        now = local_now(self.hass)
        changed = [lesson for lesson in lessons if lesson.changed]
        cancelled = [lesson for lesson in lessons if lesson.cancelled]

        start = min((slot[0] for slot in slots), default=None)
        end = max((slot[1] for slot in slots), default=None)

        if start is None or end is None:
            progress = None
        elif now <= start:
            progress = 0.0
        elif now >= end:
            progress = 100.0
        else:
            total = (end - start).total_seconds()
            elapsed = (now - start).total_seconds()
            progress = 100.0 * elapsed / total if total > 0 else 100.0

        remaining = [slot for slot in slots if slot[1] > now]
        current = current_slot(lessons, now)

        upcoming = [
            slot for slot in slots
            if slot[0] > now
        ]
        next_lesson = min(
            upcoming,
            key=lambda slot: (slot[0], slot[1]),
            default=None,
        )

        return {
            "lessons": lessons,
            "slots": slots,
            "changed": changed,
            "cancelled": cancelled,
            "start": start,
            "end": end,
            "progress": (
                round(max(0.0, min(100.0, progress)), 1)
                if progress is not None
                else None
            ),
            "remaining": remaining,
            "current": current,
            "next": next_lesson,
        }

    @property
    def native_value(self) -> int:
        return len(self._values()["slots"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        values = self._values()
        slots = values["slots"]
        changed = values["changed"]
        cancelled = values["cancelled"]
        current = values["current"]
        next_lesson = values["next"]

        return {
            "schulfrei": not slots,
            "schulbeginn": (
                values["start"].isoformat()
                if values["start"] is not None
                else None
            ),
            "schulschluss": (
                values["end"].isoformat()
                if values["end"] is not None
                else None
            ),
            "faecher": [slot_subjects(slot) for slot in slots],
            "aenderungen": len(changed),
            "geaenderte_faecher": [
                lesson.subject for lesson in changed
            ],
            "ausfaelle": len(cancelled),
            "ausgefallene_faecher": [
                lesson.subject for lesson in cancelled
            ],
            "fortschritt": values["progress"],
            "verbleibende_stunden": len(values["remaining"]),
            "aktuelle_stunde": (
                slot_subjects(current) if current is not None else None
            ),
            "naechste_stunde": (
                slot_subjects(next_lesson)
                if next_lesson is not None
                else None
            ),
            "naechste_stunde_beginn": (
                next_lesson[0].isoformat()
                if next_lesson is not None
                else None
            ),
        }


class WebUntisDataStatusSensor(_WebUntisSensorBase):
    _attr_translation_key = "data_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["live", "cache", "stale_cache", "unavailable"]

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "data_status")

    @property
    def native_value(self) -> str:
        return self.coordinator.data_source

    @property
    def icon(self) -> str:
        return {
            "live": "mdi:cloud-check",
            "cache": "mdi:cached",
            "stale_cache": "mdi:cloud-alert",
            "unavailable": "mdi:cloud-off-outline",
        }.get(self.coordinator.data_source, "mdi:database-clock")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.coordinator.diagnostic_state
        return {
            "datenquelle": state["data_source"],
            "cache_alter_minuten": state["cache_age_minutes"],
            "cache_wochen": state["weeks_cached"],
            "letzter_abrufversuch": state["last_refresh_attempt"],
            "letzter_fehler": state["last_error"],
            "letzter_fehler_zeitpunkt": state["last_error_at"],
            "aufeinanderfolgende_fehler": state["consecutive_failures"],
        }


class WebUntisLastSuccessfulFetchSensor(_WebUntisSensorBase):
    _attr_translation_key = "last_successful_fetch"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:update"

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "last_successful_fetch")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_successful_fetch


class WebUntisCachedWeeksSensor(_WebUntisSensorBase):
    _attr_translation_key = "cached_weeks"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:database-clock"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator) -> None:
        super().__init__(entry, coordinator, "cached_weeks")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.diagnostic_weeks())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"wochen": self.coordinator.diagnostic_weeks()}

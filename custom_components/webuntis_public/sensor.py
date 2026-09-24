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
    scheduled_slots,
    slot_cancelled,
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
                WebUntisNextSchoolDaySensor(entry, coordinator),
                WebUntisNextSchoolDaySummarySensor(entry, coordinator),
                WebUntisSchoolDayProgressSensor(entry, coordinator),
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
            return {"in_progress": False}
        return {
            "start_time": slot[0].isoformat(),
            "end_time": slot[1].isoformat(),
            "room": slot_rooms(slot),
            "teachers": slot_teachers(slot),
            "changed": slot_changed(slot),
            "in_progress": True,
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
            "start_time": slot[0].isoformat(),
            "end_time": slot[1].isoformat(),
            "room": slot_rooms(slot),
            "teachers": slot_teachers(slot),
            "in_progress": slot[0] <= now < slot[1],
            "changed": slot_changed(slot),
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
            "school_start_time": values["start"].isoformat() if values["start"] is not None else None,
            "school_end_time": values["end"].isoformat() if values["end"] is not None else None,
            "current_subject": slot_subjects(current) if current is not None else None,
            "current_lesson_end_time": current[1].isoformat() if current is not None else None,
            "next_subject": slot_subjects(next_lesson) if next_lesson is not None else None,
            "next_lesson_start_time": next_lesson[0].isoformat() if next_lesson is not None else None,
            "remaining_lessons": values["remaining"],
        }


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
            "school_start_time": min(slot[0] for slot in slots).isoformat(),
            "school_end_time": max(slot[1] for slot in slots).isoformat(),
            "lessons": len(slots),
            "subjects": [slot_subjects(slot) for slot in slots],
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
            "date": slots[0][0].date().isoformat(),
            "days_until": values["offset"],
            "no_school_tomorrow": values["offset"] > 1,
            "school_start_time": min(slot[0] for slot in slots).isoformat(),
            "school_end_time": max(slot[1] for slot in slots).isoformat(),
            "subjects": [slot_subjects(slot) for slot in slots],
            "teachers": values["teachers"],
            "rooms": values["rooms"],
            "changes": len(changed),
            "changed_subjects": [lesson.subject for lesson in changed],
            "cancellations": len(cancelled),
            "cancelled_subjects": [lesson.subject for lesson in cancelled],
            "schedule": [
                {
                    "start_time": slot[0].isoformat(),
                    "end_time": slot[1].isoformat(),
                    "subject": slot_subjects(slot),
                    "teachers": slot_teachers(slot),
                    "room": slot_rooms(slot),
                    "changed": slot_changed(slot),
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
            return {"school_free": True, "includes_breaks": True}

        now = local_now(self.hass)
        total_minutes = max(0, round((end - start).total_seconds() / 60))
        elapsed_minutes = max(
            0,
            min(total_minutes, round((now - start).total_seconds() / 60)),
        )
        return {
            "school_free": False,
            "school_start_time": start.isoformat(),
            "school_end_time": end.isoformat(),
            "elapsed_minutes": elapsed_minutes,
            "total_minutes": total_minutes,
            "includes_breaks": True,
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
        scheduled = scheduled_slots(lessons)

        planned_start = min((slot[0] for slot in scheduled), default=None)
        planned_end = max((slot[1] for slot in scheduled), default=None)
        first_cancelled = bool(scheduled and slot_cancelled(scheduled[0]))
        last_cancelled = bool(scheduled and slot_cancelled(scheduled[-1]))

        instruction_total = instruction_total_seconds(lessons)
        instruction_elapsed = instruction_elapsed_seconds(lessons, now)
        instruction_progress = (
            round(100.0 * instruction_elapsed / instruction_total, 1)
            if instruction_total > 0
            else None
        )

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
            "planned_start": planned_start,
            "planned_end": planned_end,
            "first_cancelled": first_cancelled,
            "last_cancelled": last_cancelled,
            "instruction_progress": instruction_progress,
            "instruction_elapsed_minutes": int((instruction_elapsed + 59) // 60),
            "instruction_total_minutes": int((instruction_total + 59) // 60),
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
            "school_free": not slots,
            "scheduled_school_start_time": (
                values["planned_start"].isoformat()
                if values["planned_start"] is not None
                else None
            ),
            "scheduled_school_end_time": (
                values["planned_end"].isoformat()
                if values["planned_end"] is not None
                else None
            ),
            "late_start_minutes": (
                int((values["start"] - values["planned_start"]).total_seconds() // 60)
                if (
                    values["start"] is not None
                    and values["planned_start"] is not None
                    and values["start"] > values["planned_start"]
                )
                else 0
            ),
            "early_end_minutes": (
                int((values["planned_end"] - values["end"]).total_seconds() // 60)
                if (
                    values["end"] is not None
                    and values["planned_end"] is not None
                    and values["end"] < values["planned_end"]
                )
                else 0
            ),
            "first_lesson_cancelled": values["first_cancelled"],
            "last_lesson_cancelled": values["last_cancelled"],
            "school_start_time": (
                values["start"].isoformat()
                if values["start"] is not None
                else None
            ),
            "school_end_time": (
                values["end"].isoformat()
                if values["end"] is not None
                else None
            ),
            "subjects": [slot_subjects(slot) for slot in slots],
            "changes": len(changed),
            "changed_subjects": [
                lesson.subject for lesson in changed
            ],
            "cancellations": len(cancelled),
            "cancelled_subjects": [
                lesson.subject for lesson in cancelled
            ],
            "school_day_progress": values["progress"],
            "instruction_progress": values["instruction_progress"],
            "instruction_elapsed_minutes": values["instruction_elapsed_minutes"],
            "instruction_total_minutes": values["instruction_total_minutes"],
            "remaining_lessons": len(values["remaining"]),
            "current_lesson": (
                slot_subjects(current) if current is not None else None
            ),
            "next_lesson": (
                slot_subjects(next_lesson)
                if next_lesson is not None
                else None
            ),
            "next_lesson_start_time": (
                next_lesson[0].isoformat()
                if next_lesson is not None
                else None
            ),
            "schedule": [
                {
                    "start_time": slot[0].isoformat(),
                    "end_time": slot[1].isoformat(),
                    "subject": slot_subjects(slot),
                    "teachers": slot_teachers(slot),
                    "room": slot_rooms(slot),
                    "changed": slot_changed(slot),
                }
                for slot in slots
            ],
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
            "data_source": state["data_source"],
            "cache_age_minutes": state["cache_age_minutes"],
            "cached_weeks": state["weeks_cached"],
            "last_refresh_attempt": state["last_refresh_attempt"],
            "last_error": state["last_error"],
            "last_error_at": state["last_error_at"],
            "consecutive_failures": state["consecutive_failures"],
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
        return {"weeks": self.coordinator.diagnostic_weeks()}

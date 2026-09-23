from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WebUntisPublicCoordinator
from .schedule import (
    current_slot,
    day_bounds,
    local_now,
    scheduled_slots,
    slot_cancelled,
    slot_subjects,
    unique_slots,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: list[WebUntisPublicCoordinator] = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for coordinator in coordinators:
        entities.extend(
            [
                WebUntisTodayChangesBinarySensor(entry, coordinator),
                WebUntisSchoolFreeTodayBinarySensor(entry, coordinator),
                WebUntisSchoolFreeTomorrowBinarySensor(entry, coordinator),
                WebUntisLessonRunningBinarySensor(entry, coordinator),
                WebUntisSchoolStartsLaterTodayBinarySensor(entry, coordinator),
                WebUntisSchoolEndsEarlierTodayBinarySensor(entry, coordinator),
                WebUntisFirstLessonCancelledTodayBinarySensor(entry, coordinator),
                WebUntisLastLessonCancelledTodayBinarySensor(entry, coordinator),
            ]
        )
    async_add_entities(entities)


class _WebUntisBinaryBase(
    CoordinatorEntity[WebUntisPublicCoordinator], BinarySensorEntity
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

    def _lessons_for_day(self, offset_days: int = 0):
        start, end = day_bounds(self.hass, offset_days)
        return self.coordinator.cached_lessons_between(start, end)


class WebUntisTodayChangesBinarySensor(_WebUntisBinaryBase):
    _attr_translation_key = "today_has_changes"
    _attr_icon = "mdi:calendar-alert"

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "today_has_changes")

    def _changed(self):
        return [lesson for lesson in self._lessons_for_day(0) if lesson.changed]

    @property
    def is_on(self) -> bool:
        return bool(self._changed())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        changed = self._changed()
        return {
            "anzahl": len(changed),
            "faecher": [lesson.subject for lesson in changed],
        }


class _SchoolFreeBinarySensor(_WebUntisBinaryBase):
    day_offset = 0

    @property
    def is_on(self) -> bool:
        return not bool(unique_slots(self._lessons_for_day(self.day_offset)))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        raw = self._lessons_for_day(self.day_offset)
        cancelled = [lesson for lesson in raw if lesson.cancelled]
        return {
            "geplante_ausgefallene_stunden": len(
                {(lesson.start, lesson.end) for lesson in cancelled}
            ),
            "grund": "no_active_lessons" if self.is_on else None,
        }


class WebUntisSchoolFreeTodayBinarySensor(_SchoolFreeBinarySensor):
    _attr_translation_key = "school_free_today"
    _attr_icon = "mdi:calendar-remove"

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "school_free_today")


class WebUntisSchoolFreeTomorrowBinarySensor(_SchoolFreeBinarySensor):
    _attr_translation_key = "school_free_tomorrow"
    _attr_icon = "mdi:calendar-remove-outline"
    day_offset = 1

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "school_free_tomorrow")


class WebUntisLessonRunningBinarySensor(_WebUntisBinaryBase):
    _attr_translation_key = "lesson_running"
    _attr_icon = "mdi:school"
    _time_sensitive = True

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "lesson_running")

    def _slot(self):
        return current_slot(self._lessons_for_day(0), local_now(self.hass))

    @property
    def is_on(self) -> bool:
        return self._slot() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slot = self._slot()
        if slot is None:
            return {}
        return {
            "faecher": slot_subjects(slot),
            "beginn": slot[0].isoformat(),
            "ende": slot[1].isoformat(),
        }



def _day_boundary_data(lessons):
    planned = scheduled_slots(lessons)
    active = unique_slots(lessons)
    if not planned:
        return None, None, None, None

    planned_start = planned[0][0]
    planned_end = planned[-1][1]
    actual_start = active[0][0] if active else None
    actual_end = active[-1][1] if active else None
    return planned_start, planned_end, actual_start, actual_end


class WebUntisSchoolStartsLaterTodayBinarySensor(_WebUntisBinaryBase):
    _attr_translation_key = "school_starts_later_today"
    _attr_icon = "mdi:clock-alert-outline"

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "school_starts_later_today")

    def _values(self):
        lessons = self._lessons_for_day(0)
        planned_start, _planned_end, actual_start, _actual_end = _day_boundary_data(lessons)
        return lessons, planned_start, actual_start

    @property
    def is_on(self) -> bool:
        _lessons, planned_start, actual_start = self._values()
        return bool(
            planned_start
            and actual_start
            and actual_start > planned_start
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        lessons, planned_start, actual_start = self._values()
        cancelled_before_start = [
            lesson.subject
            for lesson in lessons
            if lesson.cancelled
            and actual_start is not None
            and lesson.start < actual_start
        ]
        return {
            "planmaessiger_beginn": (
                planned_start.isoformat() if planned_start else None
            ),
            "tatsaechlicher_beginn": (
                actual_start.isoformat() if actual_start else None
            ),
            "spaeter_um_minuten": (
                int((actual_start - planned_start).total_seconds() // 60)
                if planned_start and actual_start and actual_start > planned_start
                else 0
            ),
            "ausgefallene_faecher_davor": cancelled_before_start,
        }


class WebUntisSchoolEndsEarlierTodayBinarySensor(_WebUntisBinaryBase):
    _attr_translation_key = "school_ends_earlier_today"
    _attr_icon = "mdi:clock-alert-outline"

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "school_ends_earlier_today")

    def _values(self):
        lessons = self._lessons_for_day(0)
        _planned_start, planned_end, _actual_start, actual_end = _day_boundary_data(lessons)
        return lessons, planned_end, actual_end

    @property
    def is_on(self) -> bool:
        _lessons, planned_end, actual_end = self._values()
        return bool(
            planned_end
            and actual_end
            and actual_end < planned_end
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        lessons, planned_end, actual_end = self._values()
        cancelled_after_end = [
            lesson.subject
            for lesson in lessons
            if lesson.cancelled
            and actual_end is not None
            and lesson.end > actual_end
        ]
        return {
            "planmaessiger_schluss": (
                planned_end.isoformat() if planned_end else None
            ),
            "tatsaechlicher_schluss": (
                actual_end.isoformat() if actual_end else None
            ),
            "frueher_um_minuten": (
                int((planned_end - actual_end).total_seconds() // 60)
                if planned_end and actual_end and actual_end < planned_end
                else 0
            ),
            "ausgefallene_faecher_danach": cancelled_after_end,
        }


class _EdgeLessonCancelledBinarySensor(_WebUntisBinaryBase):
    use_last = False

    def _slot(self):
        slots = scheduled_slots(self._lessons_for_day(0))
        if not slots:
            return None
        return slots[-1] if self.use_last else slots[0]

    @property
    def is_on(self) -> bool:
        slot = self._slot()
        return bool(slot and slot_cancelled(slot))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slot = self._slot()
        if slot is None:
            return {}
        return {
            "beginn": slot[0].isoformat(),
            "ende": slot[1].isoformat(),
            "faecher": slot_subjects(slot),
        }


class WebUntisFirstLessonCancelledTodayBinarySensor(
    _EdgeLessonCancelledBinarySensor
):
    _attr_translation_key = "first_lesson_cancelled_today"
    _attr_icon = "mdi:calendar-start"

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "first_lesson_cancelled_today")


class WebUntisLastLessonCancelledTodayBinarySensor(
    _EdgeLessonCancelledBinarySensor
):
    _attr_translation_key = "last_lesson_cancelled_today"
    _attr_icon = "mdi:calendar-end"
    use_last = True

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "last_lesson_cancelled_today")

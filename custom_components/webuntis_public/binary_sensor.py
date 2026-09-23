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
from .schedule import current_slot, day_bounds, local_now, slot_subjects, unique_slots


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
    _attr_name = "Stundenplanänderung heute"
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
            "grund": (
                "Keine stattfindenden Unterrichtsstunden im öffentlichen Stundenplan"
                if self.is_on
                else None
            ),
        }


class WebUntisSchoolFreeTodayBinarySensor(_SchoolFreeBinarySensor):
    _attr_name = "Schulfrei heute"
    _attr_icon = "mdi:calendar-remove"

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "school_free_today")


class WebUntisSchoolFreeTomorrowBinarySensor(_SchoolFreeBinarySensor):
    _attr_name = "Schulfrei morgen"
    _attr_icon = "mdi:calendar-remove-outline"
    day_offset = 1

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(entry, coordinator, "school_free_tomorrow")


class WebUntisLessonRunningBinarySensor(_WebUntisBinaryBase):
    _attr_name = "Unterricht läuft"
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

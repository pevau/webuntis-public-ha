from __future__ import annotations

from datetime import timedelta
import hashlib

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_SHOW_CANCELLED,
    DEFAULT_SHOW_CLASS,
    DEFAULT_SHOW_ROOM,
    DEFAULT_SHOW_TEACHER,
    DEFAULT_TITLE_FORMAT,
    DOMAIN,
    OPT_SHOW_CANCELLED,
    OPT_SHOW_CLASS,
    OPT_SHOW_ROOM,
    OPT_SHOW_TEACHER,
    OPT_TITLE_FORMAT,
)
from .coordinator import WebUntisPublicCoordinator
from .data import WebUntisLesson


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: list[WebUntisPublicCoordinator] = entry.runtime_data
    async_add_entities([WebUntisPublicCalendar(entry, coordinator) for coordinator in coordinators])


class WebUntisPublicCalendar(
    CoordinatorEntity[WebUntisPublicCoordinator], CalendarEntity
):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = coordinator.device_identifier
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_identifier)},
            "name": coordinator.device_name,
            "manufacturer": "Untis",
            "model": "Public timetable",
            "configuration_url": coordinator.configuration_url,
        }

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        lessons = self.coordinator.cached_lessons_between(
            now, now + timedelta(days=7)
        )
        visible = [lesson for lesson in lessons if self._visible(lesson)]
        return self._to_event(visible[0]) if visible else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date,
        end_date,
    ) -> list[CalendarEvent]:
        lessons = await self.coordinator.async_get_lessons(start_date, end_date)
        return [self._to_event(lesson) for lesson in lessons if self._visible(lesson)]

    def _visible(self, lesson: WebUntisLesson) -> bool:
        show_cancelled = self._entry.options.get(
            OPT_SHOW_CANCELLED, DEFAULT_SHOW_CANCELLED
        )
        return show_cancelled or not lesson.cancelled

    def _to_event(self, lesson: WebUntisLesson) -> CalendarEvent:
        title_format = self._entry.options.get(OPT_TITLE_FORMAT, DEFAULT_TITLE_FORMAT)
        show_teacher = self._entry.options.get(OPT_SHOW_TEACHER, DEFAULT_SHOW_TEACHER)
        show_room = self._entry.options.get(OPT_SHOW_ROOM, DEFAULT_SHOW_ROOM)
        show_class = self._entry.options.get(OPT_SHOW_CLASS, DEFAULT_SHOW_CLASS)

        uid_source = (
            f"{self.coordinator.class_id}|{lesson.start.isoformat()}|"
            f"{lesson.end.isoformat()}|{lesson.subject}|{lesson.status}"
        )
        uid_hash = hashlib.sha1(uid_source.encode("utf-8")).hexdigest()[:20]
        return CalendarEvent(
            start=lesson.start,
            end=lesson.end,
            summary=lesson.formatted_summary(title_format),
            location=lesson.room if show_room else None,
            description=lesson.description(
                self.coordinator.class_name,
                show_class=show_class,
                show_teacher=show_teacher,
                show_room=show_room,
            ),
            uid=f"webuntis-{self.coordinator.class_id}-{uid_hash}",
        )

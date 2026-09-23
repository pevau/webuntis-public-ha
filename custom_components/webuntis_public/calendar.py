from __future__ import annotations

from datetime import timedelta
import hashlib

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.translation import async_get_translations
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
    translations = await async_get_translations(
        hass, hass.config.language, "common", {DOMAIN}
    )
    async_add_entities(
        [
            WebUntisPublicCalendar(entry, coordinator, translations)
            for coordinator in coordinators
        ]
    )


class WebUntisPublicCalendar(
    CoordinatorEntity[WebUntisPublicCoordinator], CalendarEntity
):
    _attr_has_entity_name = True
    _attr_translation_key = "timetable"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: WebUntisPublicCoordinator,
        translations: dict[str, str],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._translations = translations
        self._language = coordinator.hass.config.language
        self._attr_unique_id = coordinator.device_identifier
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_identifier)},
            "name": coordinator.device_name,
            "manufacturer": "Untis",
            "model": "Public timetable",
            "configuration_url": coordinator.configuration_url,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_CORE_CONFIG_UPDATE, self._async_core_config_updated
            )
        )

    async def _async_core_config_updated(self, event: Event) -> None:
        language = event.data.get("language")
        if not language or language == self._language:
            return
        self._language = language
        self._translations = await async_get_translations(
            self.hass, language, "common", {DOMAIN}
        )
        self.async_write_ha_state()

    def _tr(self, key: str) -> str:
        return self._translations.get(
            f"component.{DOMAIN}.common.{key}",
            key,
        )

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

    def _subject(self, lesson: WebUntisLesson) -> str:
        return self._tr("calendar.lesson") if lesson.subject == "lesson" else lesson.subject

    def _description(
        self,
        lesson: WebUntisLesson,
        *,
        show_class: bool,
        show_teacher: bool,
        show_room: bool,
    ) -> str:
        details: list[str] = []
        if show_class:
            details.append(
                self._tr("calendar.class_line").format(
                    value=self.coordinator.class_name
                )
            )
        if show_teacher and lesson.teacher:
            details.append(
                self._tr("calendar.teacher_line").format(value=lesson.teacher)
            )
        if show_room and lesson.room:
            details.append(self._tr("calendar.room_line").format(value=lesson.room))

        if (
            lesson.old_subjects
            and lesson.subjects
            and set(lesson.old_subjects) != set(lesson.subjects)
        ):
            details.append(
                self._tr("calendar.subject_change").format(
                    old=", ".join(lesson.old_subjects),
                    new=", ".join(lesson.subjects),
                )
            )
        if (
            show_teacher
            and lesson.old_teachers
            and lesson.teachers
            and set(lesson.old_teachers) != set(lesson.teachers)
        ):
            details.append(
                self._tr("calendar.teacher_change").format(
                    old=", ".join(lesson.old_teachers),
                    new=", ".join(lesson.teachers),
                )
            )
        if (
            show_room
            and lesson.old_rooms
            and lesson.rooms
            and set(lesson.old_rooms) != set(lesson.rooms)
        ):
            details.append(
                self._tr("calendar.room_change").format(
                    old=", ".join(lesson.old_rooms),
                    new=", ".join(lesson.rooms),
                )
            )

        if lesson.status_label:
            status = self._tr(f"calendar.status.{lesson.status_label}")
            details.append(self._tr("calendar.status_line").format(value=status))

        for label, value in lesson.texts:
            translated_label = self._tr(f"calendar.text.{label}")
            details.append(
                self._tr("calendar.text_line").format(
                    label=translated_label,
                    value=value,
                )
            )
        return "\n".join(details)

    def _to_event(self, lesson: WebUntisLesson) -> CalendarEvent:
        title_format = self._entry.options.get(OPT_TITLE_FORMAT, DEFAULT_TITLE_FORMAT)
        show_teacher = self._entry.options.get(OPT_SHOW_TEACHER, DEFAULT_SHOW_TEACHER)
        show_room = self._entry.options.get(OPT_SHOW_ROOM, DEFAULT_SHOW_ROOM)
        show_class = self._entry.options.get(OPT_SHOW_CLASS, DEFAULT_SHOW_CLASS)

        summary = lesson.formatted_summary(
            title_format,
            subject=self._subject(lesson),
        )
        if lesson.cancelled:
            summary = self._tr("calendar.cancelled_summary").format(summary=summary)

        uid_source = (
            f"{self.coordinator.class_id}|{lesson.start.isoformat()}|"
            f"{lesson.end.isoformat()}|{lesson.subject}|{lesson.status}"
        )
        uid_hash = hashlib.sha1(uid_source.encode("utf-8")).hexdigest()[:20]
        return CalendarEvent(
            start=lesson.start,
            end=lesson.end,
            summary=summary,
            location=lesson.room if show_room else None,
            description=self._description(
                lesson,
                show_class=show_class,
                show_teacher=show_teacher,
                show_room=show_room,
            ),
            uid=f"webuntis-{self.coordinator.class_id}-{uid_hash}",
        )

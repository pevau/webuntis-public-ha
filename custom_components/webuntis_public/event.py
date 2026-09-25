from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WebUntisPublicCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: list[WebUntisPublicCoordinator] = entry.runtime_data
    async_add_entities(
        WebUntisTimetableChangeEvent(entry, coordinator)
        for coordinator in coordinators
    )


class WebUntisTimetableChangeEvent(
    CoordinatorEntity[WebUntisPublicCoordinator], EventEntity
):
    """Expose semantic timetable changes as a Home Assistant event entity."""

    _attr_has_entity_name = True
    _attr_translation_key = "timetable_change"
    _attr_icon = "mdi:calendar-sync"
    _attr_event_types = [
        "timetable_changed",
        "lesson_cancelled",
        "lesson_substituted",
    ]

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: WebUntisPublicCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = (
            f"{coordinator.device_identifier}-timetable_change"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_identifier)},
            "name": coordinator.device_name,
            "manufacturer": "Untis",
            "model": "Public timetable",
            "configuration_url": coordinator.configuration_url,
        }
        self._last_sequence = coordinator.timetable_change_sequence

    @callback
    def _handle_coordinator_update(self) -> None:
        sequence = self.coordinator.timetable_change_sequence
        if sequence > self._last_sequence:
            changes: list[dict[str, Any]] = (
                self.coordinator.timetable_changes_since(self._last_sequence)
            )
            for change in changes:
                self._trigger_event("timetable_changed", change)
                for semantic_event in change.get("semantic_events", []):
                    event_type = semantic_event.get("event_type")
                    if event_type in self._attr_event_types:
                        self._trigger_event(event_type, semantic_event)
            self._last_sequence = sequence

        super()._handle_coordinator_update()

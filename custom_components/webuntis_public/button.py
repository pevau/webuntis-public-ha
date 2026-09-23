from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
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
        WebUntisRefreshButton(entry, coordinator)
        for coordinator in coordinators
    )


class WebUntisRefreshButton(
    CoordinatorEntity[WebUntisPublicCoordinator], ButtonEntity
):
    _attr_has_entity_name = True
    _attr_translation_key = "refresh_timetable"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.device_identifier}-refresh_timetable"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_identifier)},
            "name": coordinator.device_name,
            "manufacturer": "Untis",
            "model": "Public timetable",
            "configuration_url": coordinator.configuration_url,
        }

    async def async_press(self) -> None:
        """Request an immediate timetable refresh."""
        await self.coordinator.async_request_refresh()

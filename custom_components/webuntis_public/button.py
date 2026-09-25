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
        [
            entity
            for coordinator in coordinators
            for entity in (
                WebUntisRefreshButton(entry, coordinator),
                WebUntisLiveActivityTestButton(entry, coordinator),
            )
        ]
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
        await self.coordinator.async_force_refresh()


class WebUntisLiveActivityTestButton(
    CoordinatorEntity[WebUntisPublicCoordinator], ButtonEntity
):
    _attr_has_entity_name = True
    _attr_translation_key = "test_live_activity"
    _attr_icon = "mdi:cellphone-information"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, entry: ConfigEntry, coordinator: WebUntisPublicCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.device_identifier}-test_live_activity"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_identifier)},
            "name": coordinator.device_name,
            "manufacturer": "Untis",
            "model": "Public timetable",
            "configuration_url": coordinator.configuration_url,
        }

    async def async_press(self) -> None:
        """Fire a test event consumed by the Live Activity blueprint."""
        self.hass.bus.async_fire(
            f"{DOMAIN}_test_live_activity",
            {"device_identifier": self.coordinator.device_identifier},
        )

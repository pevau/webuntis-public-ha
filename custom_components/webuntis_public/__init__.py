from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CLASS_ID,
    CONF_CLASS_IDS,
    CONF_CLASS_NAME,
    CONF_CLASS_NAMES,
    CONF_SCHOOL_NAME,
)
from .coordinator import WebUntisPublicCoordinator

PLATFORMS = ["calendar", "sensor", "binary_sensor"]


def _configured_classes(entry: ConfigEntry) -> list[tuple[int, str]]:
    """Return configured class IDs and names, including legacy entries."""
    raw_ids = entry.data.get(CONF_CLASS_IDS)
    raw_names = entry.data.get(CONF_CLASS_NAMES, {})
    if not isinstance(raw_ids, (list, tuple)) or not raw_ids:
        class_id = int(entry.data[CONF_CLASS_ID])
        return [(class_id, str(entry.data.get(CONF_CLASS_NAME, class_id)))]

    names = raw_names if isinstance(raw_names, dict) else {}
    result: list[tuple[int, str]] = []
    seen: set[int] = set()
    for raw_id in raw_ids:
        try:
            class_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if class_id in seen:
            continue
        seen.add(class_id)
        name = names.get(str(class_id)) or names.get(class_id)
        if not name and class_id == int(entry.data.get(CONF_CLASS_ID, -1)):
            name = entry.data.get(CONF_CLASS_NAME)
        result.append((class_id, str(name or class_id)))
    return result


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate single-class entries to the multi-class schema."""
    if entry.version < 3:
        data: dict[str, Any] = dict(entry.data)
        class_id = int(data[CONF_CLASS_ID])
        class_name = str(data.get(CONF_CLASS_NAME, class_id))
        data.setdefault(CONF_CLASS_IDS, [class_id])
        data.setdefault(CONF_CLASS_NAMES, {str(class_id): class_name})
        school_title = str(data.get(CONF_SCHOOL_NAME) or entry.title).strip()
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            title=school_title or entry.title,
            version=3,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinators = [
        WebUntisPublicCoordinator(hass, entry, class_id, class_name)
        for class_id, class_name in _configured_classes(entry)
    ]
    await asyncio.gather(*(coordinator.async_config_entry_first_refresh() for coordinator in coordinators))
    entry.runtime_data = coordinators
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

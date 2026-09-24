from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryError
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CLASS_ID,
    CONF_CLASS_IDS,
    CONF_CLASS_NAME,
    CONF_CLASS_NAMES,
    CONF_SCHOOL_NAME,
)
from .coordinator import WebUntisPublicCoordinator

PLATFORMS = ["calendar", "sensor", "button", "event"]


OBSOLETE_ENTITY_KEYS = {
    "tomorrow_start",
    "tomorrow_end",
    "next_school_day_start",
    "next_school_day_end",
    "today_lesson_count",
    "remaining_lessons_today",
    "remaining_instruction_time",
    "today_changes",
    "cancelled_lessons_today",
    "today_start",
    "today_end",
    "instruction_progress",
    "today_has_changes",
    "school_free_today",
    "school_free_tomorrow",
    "lesson_running",
    "school_starts_later_today",
    "school_ends_earlier_today",
    "first_lesson_cancelled_today",
    "last_lesson_cancelled_today",
}


def _remove_obsolete_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinators: list[WebUntisPublicCoordinator],
) -> None:
    """Remove entity-registry entries replaced by the compact entity model."""
    registry = er.async_get(hass)
    device_prefixes = tuple(
        f"{coordinator.device_identifier}-" for coordinator in coordinators
    )

    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id:
            continue

        unique_id = str(entity.unique_id)
        suffix = unique_id.rsplit("-", 1)[-1]
        if suffix not in OBSOLETE_ENTITY_KEYS:
            continue

        # The config entry already scopes ownership to this integration instance.
        # Keep the current-device check only as an additional fast-path; obsolete
        # entities from classes removed from the configuration must be cleaned too.
        if device_prefixes and unique_id.startswith(device_prefixes):
            registry.async_remove(entity.entity_id)
            continue
        registry.async_remove(entity.entity_id)


def _valid_class_id(value: Any) -> int | None:
    """Return a positive WebUntis class ID or None for invalid input."""
    try:
        class_id = int(value)
    except (TypeError, ValueError):
        return None
    return class_id if class_id > 0 else None


def _configured_classes(entry: ConfigEntry) -> list[tuple[int, str]]:
    """Return configured class IDs and names, including legacy entries."""
    raw_ids = entry.data.get(CONF_CLASS_IDS)
    raw_names = entry.data.get(CONF_CLASS_NAMES, {})
    primary_id = _valid_class_id(entry.data.get(CONF_CLASS_ID))

    if not isinstance(raw_ids, (list, tuple)) or not raw_ids:
        if primary_id is None:
            return []
        return [(primary_id, str(entry.data.get(CONF_CLASS_NAME, primary_id)))]

    names = raw_names if isinstance(raw_names, dict) else {}
    result: list[tuple[int, str]] = []
    seen: set[int] = set()
    for raw_id in raw_ids:
        class_id = _valid_class_id(raw_id)
        if class_id is None or class_id in seen:
            continue
        seen.add(class_id)
        name = names.get(str(class_id)) or names.get(class_id)
        if not name and class_id == primary_id:
            name = entry.data.get(CONF_CLASS_NAME)
        result.append((class_id, str(name or class_id)))
    return result


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate single-class entries to the multi-class schema."""
    if entry.version < 3:
        data: dict[str, Any] = dict(entry.data)
        class_id = _valid_class_id(data.get(CONF_CLASS_ID))
        if class_id is None:
            return False
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
    configured_classes = _configured_classes(entry)
    if not configured_classes:
        raise ConfigEntryError("No valid WebUntis class IDs configured")

    coordinators = [
        WebUntisPublicCoordinator(hass, entry, class_id, class_name)
        for class_id, class_name in configured_classes
    ]
    # Refresh coordinators sequentially during setup. All configured classes use
    # the same WebUntis school endpoint, so parallel first refreshes only create
    # avoidable request bursts and can increase the chance of rate limiting.
    for coordinator in coordinators:
        await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinators
    _remove_obsolete_entities(hass, entry, coordinators)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

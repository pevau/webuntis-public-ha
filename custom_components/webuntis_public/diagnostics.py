from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import WebUntisPublicCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return privacy-conscious diagnostics for a config entry."""
    coordinators: list[WebUntisPublicCoordinator] = entry.runtime_data

    classes: list[dict[str, Any]] = []
    for coordinator in coordinators:
        classes.append(
            {
                "class_id": coordinator.class_id,
                "class_name": coordinator.class_name,
                "runtime": coordinator.diagnostic_state,
                "cache": coordinator.diagnostic_weeks(),
            }
        )

    return {
        "entry": {
            "title": entry.title,
            "server": entry.data.get("server"),
            "school": entry.data.get("school"),
            "school_name": entry.data.get("school_name"),
            "configured_class_ids": entry.data.get("class_ids"),
            "options": dict(entry.options),
        },
        "classes": classes,
        "privacy_note": (
            "Raw timetable entries, subjects, rooms and teacher names are intentionally "
            "excluded from diagnostics."
        ),
    }

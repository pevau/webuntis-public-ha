from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.webuntis_public.diagnostics import (
    async_get_config_entry_diagnostics,
)


class FakeCoordinator:
    def __init__(self, class_id: int, class_name: str) -> None:
        self.class_id = class_id
        self.class_name = class_name
        self.diagnostic_state = {
            "data_source": "live",
            "last_successful_fetch": "2026-09-23T10:00:00+00:00",
            "cache_age_minutes": 2,
            "weeks_cached": 1,
            "last_error": None,
        }

    def diagnostic_weeks(self):
        return [
            {
                "week": "2026-09-21",
                "fetched_at": "2026-09-23T10:00:00+00:00",
                "age_minutes": 2,
                "entries": 20,
                "stale": False,
            }
        ]


def test_diagnostics_exposes_runtime_metadata_without_raw_timetable_data() -> None:
    entry = SimpleNamespace(
        title="Example School",
        data={
            "server": "example.webuntis.com",
            "school": "example-school",
            "school_name": "Example School",
            "class_ids": [123, 124],
        },
        options={
            "show_teacher": True,
            "show_room": True,
        },
        runtime_data=[
            FakeCoordinator(123, "5A"),
            FakeCoordinator(124, "5B"),
        ],
    )

    result = asyncio.run(async_get_config_entry_diagnostics(None, entry))

    assert result["entry"] == {
        "title": "Example School",
        "server": "example.webuntis.com",
        "school": "example-school",
        "school_name": "Example School",
        "configured_class_ids": [123, 124],
        "options": {
            "show_teacher": True,
            "show_room": True,
        },
    }
    assert [item["class_name"] for item in result["classes"]] == ["5A", "5B"]
    assert result["classes"][0]["runtime"]["data_source"] == "live"
    assert result["classes"][0]["cache"][0]["entries"] == 20
    assert "Raw timetable entries" in result["privacy_note"]

    serialized = repr(result)
    assert "Mathematik" not in serialized
    assert "Anna Beispiel" not in serialized
    assert "A101" not in serialized

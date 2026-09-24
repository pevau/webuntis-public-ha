from __future__ import annotations

import json
from pathlib import Path

TRANSLATIONS = Path("custom_components/webuntis_public/translations")

EXPECTED_SENSOR_ATTRIBUTE_KEYS = {
    "current_lesson": {
        "start_time", "end_time", "room", "teachers", "changed", "in_progress"
    },
    "next_lesson": {
        "start_time", "end_time", "room", "teachers", "changed", "in_progress"
    },
    "school_day_progress": {
        "school_free", "school_start_time", "school_end_time",
        "elapsed_minutes", "total_minutes", "includes_breaks"
    },
    "data_status": {
        "data_source", "cache_age_minutes", "cached_weeks",
        "last_refresh_attempt", "last_error", "last_error_at",
        "consecutive_failures"
    },
    "cached_weeks": {"weeks"},
    "next_school_day": {
        "school_start_time", "school_end_time", "lessons", "subjects"
    },
    "daily_summary": {
        "school_free", "school_start_time", "school_end_time", "subjects",
        "changes", "changed_subjects", "cancellations", "cancelled_subjects",
        "school_day_progress", "remaining_lessons", "current_lesson",
        "next_lesson", "next_lesson_start_time",
        "scheduled_school_start_time", "scheduled_school_end_time",
        "late_start_minutes", "early_end_minutes",
        "first_lesson_cancelled", "last_lesson_cancelled",
        "instruction_progress", "instruction_elapsed_minutes",
        "instruction_total_minutes"
    },
    "school_status": {
        "school_start_time", "school_end_time", "current_subject",
        "current_lesson_end_time", "next_subject", "next_lesson_start_time",
        "remaining_lessons"
    },
    "next_school_day_summary": {
        "date", "days_until", "school_start_time", "school_end_time",
        "subjects", "teachers", "rooms", "changes", "changed_subjects",
        "cancellations", "cancelled_subjects", "schedule",
        "no_school_tomorrow"
    },
}


def _load(language: str) -> dict:
    return json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))


def test_sensor_attribute_translation_keys_are_language_neutral() -> None:
    for language in ("en", "de"):
        sensor = _load(language)["entity"]["sensor"]
        for translation_key, expected in EXPECTED_SENSOR_ATTRIBUTE_KEYS.items():
            actual = set(sensor[translation_key].get("state_attributes", {}))
            assert actual == expected, (
                f"{language}:{translation_key} has translation keys {sorted(actual)}, "
                f"expected {sorted(expected)}"
            )


def test_translation_files_have_identical_structure() -> None:
    def shape(value):
        if isinstance(value, dict):
            return {key: shape(item) for key, item in value.items()}
        return None

    assert shape(_load("en")) == shape(_load("de"))

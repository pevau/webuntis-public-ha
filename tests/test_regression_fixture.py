from __future__ import annotations

import asyncio
import json
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from custom_components.webuntis_public.coordinator import WebUntisPublicCoordinator
from custom_components.webuntis_public.data import parse_lessons
from custom_components.webuntis_public.schedule import unique_slots


FIXTURE = Path(__file__).parent / "fixtures" / "webuntis_week_sample.json"
TZ = ZoneInfo("Europe/Vienna")


class FixtureResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        return None

    async def json(self, *, content_type=None):
        return self.payload


class FixtureSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def get(self, *_args, **_kwargs):
        return FixtureResponse(self.payload)


def test_anonymized_week_fixture_fetch_parse_and_schedule_pipeline() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    coordinator = object.__new__(WebUntisPublicCoordinator)
    coordinator.server = "example.webuntis.com"
    coordinator.school = "example-school"
    coordinator.class_id = 123
    coordinator._session = FixtureSession(payload)

    raw_entries = asyncio.run(
        coordinator._async_fetch_week(Date(2026, 9, 21))
    )

    assert len(raw_entries) == 5

    lessons = parse_lessons(
        raw_entries,
        datetime(2026, 9, 23, 0, 0, tzinfo=TZ),
        datetime(2026, 9, 25, 0, 0, tzinfo=TZ),
        TZ,
    )

    assert len(lessons) == 4

    math = next(lesson for lesson in lessons if lesson.subject == "Mathematik")
    assert math.teacher == "Anna Beispiel"
    assert math.room == "A101"
    assert math.changed is False

    german = next(lesson for lesson in lessons if lesson.subject == "Deutsch")
    assert german.changed is True
    assert german.teacher == "Max Beispiel"
    assert german.old_teachers == ("Eva Beispiel",)
    assert german.room == "B201"
    assert german.old_rooms == ("B101",)
    assert ("substitution", "Raum- und Lehrerwechsel") in german.texts

    sport = next(lesson for lesson in lessons if lesson.subject == "Sport")
    assert sport.cancelled is True
    assert sport.teacher == "Sam Beispiel"
    assert sport.room == "TH"

    english = next(lesson for lesson in lessons if lesson.subject == "Englisch")
    assert english.raw_count == 2
    assert english.teachers == ("Chris Beispiel", "Dana Beispiel")
    assert english.rooms == ("C301", "C302")

    active = [lesson for lesson in lessons if not lesson.cancelled]
    slots = unique_slots(active)
    assert len(slots) == 3

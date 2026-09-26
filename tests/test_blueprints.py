"""Tests for the shipped WebUntis automation blueprints."""

from pathlib import Path

import yaml


BLUEPRINT = (
    Path(__file__).parents[1]
    / "blueprints"
    / "automation"
    / "webuntis_public"
    / "school-day-live-activity.yaml"
)


class BlueprintLoader(yaml.SafeLoader):
    """YAML loader that preserves Home Assistant !input values as strings."""


def _input(loader: BlueprintLoader, node: yaml.Node) -> str:
    return loader.construct_scalar(node)


BlueprintLoader.add_constructor("!input", _input)


def _load_blueprint() -> dict:
    with BLUEPRINT.open(encoding="utf-8") as file:
        return yaml.load(file, Loader=BlueprintLoader)


def test_live_activity_blueprint_uses_mobile_notify_action_list() -> None:
    """The blueprint accepts one or more direct mobile_app notify actions."""
    blueprint = _load_blueprint()

    notify_input = blueprint["blueprint"]["input"]["notify_services"]
    assert "object" in notify_input["selector"]
    assert "YAML list" in notify_input["description"]
    assert "- notify.mobile_app_iphone" in notify_input["description"]


def test_live_activity_test_button_simulates_school_day() -> None:
    """The diagnostic test runs start, lesson, break, lesson and clear phases."""
    text = BLUEPRINT.read_text(encoding="utf-8")

    assert 'for_each: "{{ notify_services }}"' in text
    assert text.count("tag: webuntis_test") == 5
    assert 'message: "School starts soon · First: Mathematics"' in text
    assert 'message: "Mathematics · Room 204"' in text
    assert 'message: "Break · Next: English"' in text
    assert 'message: "English · Room 105"' in text
    assert "message: clear_notification" in text
    assert 'delay: "00:00:05"' in text
    assert 'delay: "00:00:10"' in text


def test_live_activity_blueprint_notification_appearance() -> None:
    """The blueprint exposes HA-native icon settings and increasing progress."""
    blueprint = _load_blueprint()
    inputs = blueprint["blueprint"]["input"]

    assert inputs["notification_icon"]["default"] == "mdi:school"
    assert "icon" in inputs["notification_icon"]["selector"]
    assert inputs["notification_icon_color"]["default"] == ""

    text = BLUEPRINT.read_text(encoding="utf-8")
    assert 'notification_icon: "{{ notification_icon }}"' in text
    assert 'notification_icon_color: "{{ notification_icon_color }}"' in text
    assert "progress_bar_direction: increasing" in text

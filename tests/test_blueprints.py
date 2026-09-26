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
    """The diagnostic test simulates the school day using the production payload."""
    blueprint = _load_blueprint()
    text = BLUEPRINT.read_text(encoding="utf-8")

    assert "test_steps" in text
    assert "status: before_school" in text
    assert text.count("status: lesson") >= 2
    assert "status: break" in text
    assert "subject: Mathematics" in text
    assert "subject: English" in text
    assert "Room 204" in text
    assert "Room 105" in text
    assert "message: clear_notification" in text

    # Test and production both use the same effective payload fields.
    assert 'message: "{{ effective_message | trim }}"' in text
    assert 'notification_icon: "{{ notification_icon }}"' in text
    assert 'notification_icon_color: "{{ notification_icon_color }}"' in text
    assert "progress_bar_direction: increasing" in text
    assert 'url: "{{ dashboard_url }}"' in text

    actions = blueprint["actions"]
    assert actions


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

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryError

from custom_components.webuntis_public import (
    PLATFORMS,
    _configured_classes,
    _remove_obsolete_entities,
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
import custom_components.webuntis_public as integration_module
from custom_components.webuntis_public.const import (
    CONF_CLASS_ID,
    CONF_CLASS_IDS,
    CONF_CLASS_NAME,
    CONF_CLASS_NAMES,
    CONF_SCHOOL_NAME,
)


def _entry(data: dict, *, version: int = 3, title: str = "Example School"):
    return SimpleNamespace(
        data=data,
        version=version,
        title=title,
        entry_id="entry-1",
        options={},
        runtime_data=None,
    )


def test_configured_classes_supports_legacy_single_class_entry() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
        }
    )

    assert _configured_classes(entry) == [(123, "5A")]


def test_configured_classes_falls_back_to_class_id_for_legacy_name() -> None:
    entry = _entry({CONF_CLASS_ID: 123})

    assert _configured_classes(entry) == [(123, "123")]


def test_configured_classes_returns_multiple_classes_in_configured_order() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
            CONF_CLASS_IDS: [125, 123],
            CONF_CLASS_NAMES: {
                "123": "5A",
                "125": "5C",
            },
        }
    )

    assert _configured_classes(entry) == [(125, "5C"), (123, "5A")]


def test_configured_classes_removes_duplicates_and_invalid_ids() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
            CONF_CLASS_IDS: [123, "123", "invalid", 124],
            CONF_CLASS_NAMES: {
                "123": "5A",
                "124": "5B",
            },
        }
    )

    assert _configured_classes(entry) == [(123, "5A"), (124, "5B")]


def test_configured_classes_rejects_invalid_legacy_class_id() -> None:
    entry = _entry({CONF_CLASS_ID: "invalid", CONF_CLASS_NAME: "5A"})

    assert _configured_classes(entry) == []


def test_configured_classes_rejects_non_positive_ids() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_IDS: [0, -1, None, 124],
            CONF_CLASS_NAMES: {"124": "5B"},
        }
    )

    assert _configured_classes(entry) == [(124, "5B")]


def test_configured_classes_uses_primary_legacy_name_when_mapping_missing() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
            CONF_CLASS_IDS: [123, 124],
            CONF_CLASS_NAMES: {},
        }
    )

    assert _configured_classes(entry) == [(123, "5A"), (124, "124")]


def test_migrate_entry_converts_single_class_schema_to_version_3() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
            CONF_SCHOOL_NAME: "Example School",
        },
        version=2,
        title="Old title",
    )
    calls: list[dict] = []

    def update_entry(target, **kwargs):
        calls.append({"target": target, **kwargs})

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=update_entry)
    )

    result = asyncio.run(async_migrate_entry(hass, entry))

    assert result is True
    assert len(calls) == 1
    assert calls[0]["target"] is entry
    assert calls[0]["version"] == 3
    assert calls[0]["title"] == "Example School"
    assert calls[0]["data"][CONF_CLASS_IDS] == [123]
    assert calls[0]["data"][CONF_CLASS_NAMES] == {"123": "5A"}


def test_migrate_entry_rejects_invalid_legacy_class_id() -> None:
    entry = _entry({CONF_CLASS_ID: "invalid"}, version=2)
    calls: list[dict] = []
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda target, **kwargs: calls.append(kwargs)
        )
    )

    result = asyncio.run(async_migrate_entry(hass, entry))

    assert result is False
    assert calls == []


def test_migrate_entry_preserves_existing_multi_class_values() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
            CONF_CLASS_IDS: [123, 124],
            CONF_CLASS_NAMES: {"123": "5A", "124": "5B"},
        },
        version=2,
    )
    calls: list[dict] = []
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda target, **kwargs: calls.append(kwargs)
        )
    )

    asyncio.run(async_migrate_entry(hass, entry))

    assert calls[0]["data"][CONF_CLASS_IDS] == [123, 124]
    assert calls[0]["data"][CONF_CLASS_NAMES] == {
        "123": "5A",
        "124": "5B",
    }


def test_migrate_entry_does_nothing_for_current_version() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
            CONF_CLASS_IDS: [123],
            CONF_CLASS_NAMES: {"123": "5A"},
        },
        version=3,
    )
    calls: list[dict] = []
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda target, **kwargs: calls.append(kwargs)
        )
    )

    result = asyncio.run(async_migrate_entry(hass, entry))

    assert result is True
    assert calls == []


def test_setup_entry_creates_one_coordinator_per_configured_class(monkeypatch) -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
            CONF_CLASS_IDS: [123, 124],
            CONF_CLASS_NAMES: {"123": "5A", "124": "5B"},
        }
    )
    created: list[object] = []

    class FakeCoordinator:
        def __init__(self, hass, config_entry, class_id, class_name):
            self.hass = hass
            self.entry = config_entry
            self.class_id = class_id
            self.class_name = class_name
            self.refreshed = False
            created.append(self)

        async def async_config_entry_first_refresh(self):
            assert all(item.refreshed for item in created[:-1])
            self.refreshed = True

    forwarded: list[tuple[object, list[str]]] = []

    async def forward(config_entry, platforms):
        forwarded.append((config_entry, platforms))

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_forward_entry_setups=forward,
        )
    )
    monkeypatch.setattr(
        "custom_components.webuntis_public.WebUntisPublicCoordinator",
        FakeCoordinator,
    )
    monkeypatch.setattr(
        "custom_components.webuntis_public._remove_obsolete_entities",
        lambda _hass, _entry, _coordinators: None,
    )

    result = asyncio.run(async_setup_entry(hass, entry))

    assert result is True
    assert [(item.class_id, item.class_name) for item in created] == [
        (123, "5A"),
        (124, "5B"),
    ]
    assert all(item.refreshed for item in created)
    assert entry.runtime_data == created
    assert forwarded == [(entry, PLATFORMS)]



def test_setup_entry_rejects_configuration_without_valid_classes() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: "invalid",
            CONF_CLASS_IDS: ["invalid", None, 0],
        }
    )
    hass = SimpleNamespace()

    with pytest.raises(ConfigEntryError, match="No valid WebUntis class IDs configured"):
        asyncio.run(async_setup_entry(hass, entry))


def test_remove_obsolete_entities_cleans_registry(monkeypatch) -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
        }
    )
    coordinator = SimpleNamespace(device_identifier="example.webuntis.com-123")

    obsolete = SimpleNamespace(
        entity_id="binary_sensor.example_school_5a_school_free_today",
        config_entry_id="entry-1",
        unique_id="example.webuntis.com-123-school_free_today",
    )
    keep = SimpleNamespace(
        entity_id="sensor.example_school_5a_school_status",
        config_entry_id="entry-1",
        unique_id="example.webuntis.com-123-school_status",
    )

    class FakeRegistry:
        def __init__(self):
            self.entities = {
                obsolete.entity_id: obsolete,
                keep.entity_id: keep,
            }
            self.removed = []

        def async_remove(self, entity_id):
            self.removed.append(entity_id)

    registry = FakeRegistry()
    monkeypatch.setattr(integration_module.er, "async_get", lambda _hass: registry)

    _remove_obsolete_entities(SimpleNamespace(), entry, [coordinator])

    assert registry.removed == [obsolete.entity_id]


def test_unload_entry_unloads_all_platforms() -> None:
    entry = _entry(
        {
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
        }
    )
    calls: list[tuple[object, list[str]]] = []

    async def unload(config_entry, platforms):
        calls.append((config_entry, platforms))
        return True

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_unload_platforms=unload,
        )
    )

    result = asyncio.run(async_unload_entry(hass, entry))

    assert result is True
    assert calls == [(entry, PLATFORMS)]

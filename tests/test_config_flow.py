from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.webuntis_public import config_flow as config_module
from custom_components.webuntis_public.config_flow import (
    SchoolResult,
    WebUntisPublicConfigFlow,
    _extract_public_link,
    _find_school_dicts,
    _normalise_server,
    _school_from_record,
)
from custom_components.webuntis_public.const import CONF_CLASS_IDS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ws-kempten.webuntis.com", "ws-kempten.webuntis.com"),
        ("https://ws-kempten.webuntis.com", "ws-kempten.webuntis.com"),
        ("HTTPS://WS-KEMPTEN.WEBUNTIS.COM/WebUntis/", "ws-kempten.webuntis.com"),
        (" ws-kempten.webuntis.com/WebUntis/ ", "ws-kempten.webuntis.com"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalise_server(value: str, expected: str) -> None:
    assert _normalise_server(value) == expected


def test_extract_public_link_reads_server_school_and_class() -> None:
    link = (
        "https://ws-kempten.webuntis.com/WebUntis/"
        "?school=Staatliche%20Wirtschaftsschule%20Kempten"
        "#/basic/timetablePublic/class?entityType=5&entityId=123"
    )

    server, school, class_id = _extract_public_link(link)

    assert server == "ws-kempten.webuntis.com"
    assert school == "Staatliche Wirtschaftsschule Kempten"
    assert class_id == 123


def test_extract_public_link_uses_server_prefix_as_school_fallback() -> None:
    link = (
        "https://demo.webuntis.com/WebUntis/"
        "#/basic/timetablePublic/class?entityId=42"
    )

    server, school, class_id = _extract_public_link(link)

    assert server == "demo.webuntis.com"
    assert school == "demo"
    assert class_id == 42


def test_extract_public_link_accepts_link_without_scheme() -> None:
    link = (
        "demo.webuntis.com/WebUntis/?school=Example"
        "#/basic/timetablePublic/class?entityId=7"
    )

    server, school, class_id = _extract_public_link(link)

    assert server == "demo.webuntis.com"
    assert school == "Example"
    assert class_id == 7


def test_extract_public_link_ignores_invalid_class_id() -> None:
    link = (
        "https://demo.webuntis.com/WebUntis/?school=Example"
        "#/basic/timetablePublic/class?entityId=not-a-number"
    )

    assert _extract_public_link(link) == (
        "demo.webuntis.com",
        "Example",
        None,
    )


def test_find_school_dicts_handles_nested_response_shapes() -> None:
    first = {
        "loginName": "school-a",
        "displayName": "School A",
        "server": "school-a.webuntis.com",
    }
    second = {
        "loginname": "school-b",
        "name": "School B",
        "serverUrl": "https://school-b.webuntis.com",
    }
    payload = {
        "result": {
            "schools": [
                first,
                {"nested": {"items": [second]}},
                {"ignored": "value"},
            ]
        }
    }

    assert _find_school_dicts(payload) == [first, second]


def test_find_school_dicts_ignores_incomplete_records() -> None:
    payload = [
        {"loginName": "missing-server"},
        {"server": "missing-login.webuntis.com"},
        "not-a-dict",
    ]

    assert _find_school_dicts(payload) == []


def test_school_from_record_normalises_fields() -> None:
    school = _school_from_record(
        {
            "loginName": "example-school",
            "displayName": "Example School",
            "address": "Example Street 1",
            "serverUrl": "https://EXAMPLE.webuntis.com/WebUntis/",
        }
    )

    assert school == SchoolResult(
        display_name="Example School",
        login_name="example-school",
        server="example.webuntis.com",
        address="Example Street 1",
    )
    assert school.key == "example.webuntis.com|example-school"
    assert school.label == "Example School — Example Street 1"


def test_school_from_record_falls_back_to_login_for_display_name() -> None:
    school = _school_from_record(
        {
            "loginname": "example-school",
            "server": "example.webuntis.com",
        }
    )

    assert school is not None
    assert school.display_name == "example-school"
    assert school.label == "example-school"


@pytest.mark.parametrize(
    "record",
    [
        {"server": "example.webuntis.com"},
        {"loginName": "example-school"},
        {"loginName": "", "server": "example.webuntis.com"},
        {"loginName": "example-school", "server": ""},
    ],
)
def test_school_from_record_rejects_incomplete_records(record: dict) -> None:
    assert _school_from_record(record) is None


def test_class_select_schema_preselects_class_from_public_link() -> None:
    flow = WebUntisPublicConfigFlow()
    flow._classes = {
        "1": "5A",
        "2": "5B",
    }
    flow._preselected_class_id = "2"

    schema = flow._class_select_schema()
    validated = schema({})

    assert validated[CONF_CLASS_IDS] == ["2"]


def test_class_select_schema_does_not_preselect_unknown_class() -> None:
    flow = WebUntisPublicConfigFlow()
    flow._classes = {
        "1": "5A",
        "2": "5B",
    }
    flow._preselected_class_id = "999"

    schema = flow._class_select_schema()

    with pytest.raises(Exception):
        schema({})


def test_async_load_classes_sorts_and_builds_long_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    flow = WebUntisPublicConfigFlow()
    monkeypatch.setattr(config_module, "_list_public_classes", lambda *_args: [
        SimpleNamespace(id=2, name="5B", long_name="Klasse 5B"),
        SimpleNamespace(id=1, name="5A", long_name="Klasse 5A"),
        SimpleNamespace(id=3, name="6A", long_name="6A"),
    ])
    flow.hass = SimpleNamespace(
        async_add_executor_job=lambda func: asyncio.to_thread(func)
    )
    errors: dict[str, str] = {}

    result = asyncio.run(flow._async_load_classes(errors))

    assert result is True
    assert errors == {}
    assert list(flow._classes) == ["1", "2", "3"]
    assert flow._classes == {
        "1": "5A – Klasse 5A",
        "2": "5B – Klasse 5B",
        "3": "6A",
    }
    assert flow._class_names == {
        "1": "5A",
        "2": "5B",
        "3": "6A",
    }


def test_async_load_classes_reports_empty_public_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    flow = WebUntisPublicConfigFlow()
    monkeypatch.setattr(config_module, "_list_public_classes", lambda *_args: [])
    flow.hass = SimpleNamespace(
        async_add_executor_job=lambda func: asyncio.to_thread(func)
    )
    errors: dict[str, str] = {}

    result = asyncio.run(flow._async_load_classes(errors))

    assert result is False
    assert errors == {"base": "no_public_classes"}


def test_async_load_classes_reports_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    flow = WebUntisPublicConfigFlow()

    def fail(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(config_module, "_list_public_classes", fail)
    flow.hass = SimpleNamespace(
        async_add_executor_job=lambda func: asyncio.to_thread(func)
    )
    errors: dict[str, str] = {}

    result = asyncio.run(flow._async_load_classes(errors))

    assert result is False
    assert errors == {"base": "cannot_load_classes"}


@pytest.mark.parametrize(
    "link",
    [
        "",
        "ftp://demo.webuntis.com/WebUntis/?school=Example",
        "https://example.org/WebUntis/?school=Example",
        "https://demo.webuntis.com/not-webuntis/?school=Example",
        "https://demo.webuntis.com/WebUntis/?school=Example#/other/path?entityId=1",
    ],
)
def test_extract_public_link_rejects_invalid_links(link: str) -> None:
    assert _extract_public_link(link) == ("", "", None)


def test_options_flow_factory_returns_options_flow() -> None:
    assert isinstance(
        WebUntisPublicConfigFlow.async_get_options_flow(SimpleNamespace()),
        config_module.WebUntisPublicOptionsFlow,
    )


def test_manual_flow_derives_school_from_webuntis_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    monkeypatch.setattr(
        flow,
        "_async_load_classes",
        lambda errors: _async_return(False),
    )
    monkeypatch.setattr(flow, "async_show_form", lambda **kwargs: kwargs)

    result = asyncio.run(
        flow.async_step_manual(
            {
                config_module.CONF_SERVER: "demo.webuntis.com",
                config_module.CONF_SCHOOL: "",
            }
        )
    )

    assert flow._school == "demo"
    assert result["step_id"] == "manual"


def test_reconfigure_classes_rejects_unknown_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    flow._classes = {"1": "5A"}
    flow._class_names = {"1": "5A"}
    entry = SimpleNamespace(data={config_module.CONF_CLASS_ID: 1})
    monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: entry)
    monkeypatch.setattr(flow, "async_show_form", lambda **kwargs: kwargs)

    result = asyncio.run(
        flow.async_step_reconfigure_classes({CONF_CLASS_IDS: ["999"]})
    )

    assert result["errors"] == {CONF_CLASS_IDS: "invalid_class"}


def test_reconfigure_classes_falls_back_to_primary_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    flow._classes = {"1": "5A"}
    flow._class_names = {"1": "5A"}
    entry = SimpleNamespace(data={config_module.CONF_CLASS_ID: 1})
    monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: entry)
    monkeypatch.setattr(flow, "async_show_form", lambda **kwargs: kwargs)

    result = asyncio.run(flow.async_step_reconfigure_classes())

    validated = result["data_schema"]({})
    assert validated[CONF_CLASS_IDS] == ["1"]


def test_class_select_schema_filters_invalid_explicit_defaults() -> None:
    flow = WebUntisPublicConfigFlow()
    flow._classes = {"1": "5A", "2": "5B"}

    schema = flow._class_select_schema(["999", "2"])

    assert schema({})[CONF_CLASS_IDS] == ["2"]


def test_options_flow_falls_back_to_primary_class_when_class_ids_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = config_module.WebUntisPublicOptionsFlow()
    flow.config_entry = SimpleNamespace(
        data={
            config_module.CONF_SERVER: "demo.webuntis.com",
            config_module.CONF_CLASS_ID: 1,
            config_module.CONF_CLASS_IDS: [],
        },
        options={},
    )
    flow._class_options = []
    flow._class_names = {"1": "5A"}
    monkeypatch.setattr(flow, "async_show_form", lambda **kwargs: kwargs)

    result = asyncio.run(flow.async_step_init())

    assert result["data_schema"]({})[CONF_CLASS_IDS] == ["1"]


def _async_return(value):
    async def result(*_args, **_kwargs):
        return value
    return result()

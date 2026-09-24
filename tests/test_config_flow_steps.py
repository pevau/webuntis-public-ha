from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.webuntis_public import config_flow as config_module
from custom_components.webuntis_public.config_flow import (
    SchoolResult,
    WebUntisPublicConfigFlow,
    WebUntisPublicOptionsFlow,
)
from custom_components.webuntis_public.const import (
    CONF_CLASS_ID,
    CONF_CLASS_IDS,
    CONF_CLASS_NAME,
    CONF_CLASS_NAMES,
    CONF_PUBLIC_LINK,
    CONF_SCHOOL,
    CONF_SCHOOL_NAME,
    CONF_SCHOOL_RESULT,
    CONF_SEARCH_QUERY,
    CONF_SERVER,
    OPT_NEXT_LESSON_DAYS,
    OPT_SHOW_CANCELLED,
    OPT_SHOW_CLASS,
    OPT_SHOW_ROOM,
    OPT_SHOW_TEACHER,
    OPT_TITLE_FORMAT,
    TITLE_SUBJECT_ROOM,
)


def _patch_flow_renderers(monkeypatch: pytest.MonkeyPatch, flow) -> None:
    monkeypatch.setattr(
        flow,
        "async_show_form",
        lambda **kwargs: {"type": "form", **kwargs},
    )
    monkeypatch.setattr(
        flow,
        "async_show_menu",
        lambda **kwargs: {"type": "menu", **kwargs},
    )
    monkeypatch.setattr(
        flow,
        "async_create_entry",
        lambda **kwargs: {"type": "create_entry", **kwargs},
    )


def test_user_step_offers_all_setup_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)

    result = asyncio.run(flow.async_step_user())

    assert result == {
        "type": "menu",
        "step_id": "user",
        "menu_options": ["school_search", "public_link", "manual"],
    }


def test_school_search_rejects_too_short_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)

    result = asyncio.run(
        flow.async_step_school_search({CONF_SEARCH_QUERY: "ab"})
    )

    assert result["step_id"] == "school_search"
    assert result["errors"] == {CONF_SEARCH_QUERY: "search_too_short"}


def test_school_search_reports_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)
    monkeypatch.setattr(
        flow,
        "_async_search_schools",
        AsyncMock(side_effect=RuntimeError("offline")),
    )

    result = asyncio.run(
        flow.async_step_school_search({CONF_SEARCH_QUERY: "Example"})
    )

    assert result["errors"] == {"base": "cannot_connect"}


def test_school_search_reports_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)
    monkeypatch.setattr(flow, "_async_search_schools", AsyncMock(return_value=[]))

    result = asyncio.run(
        flow.async_step_school_search({CONF_SEARCH_QUERY: "Example"})
    )

    assert result["errors"] == {"base": "no_schools"}


def test_school_search_success_routes_to_school_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    school = SchoolResult(
        display_name="Example School",
        login_name="example-school",
        server="example.webuntis.com",
        address="Example Street 1",
    )
    monkeypatch.setattr(
        flow,
        "_async_search_schools",
        AsyncMock(return_value=[school]),
    )
    next_step = AsyncMock(return_value={"type": "form", "step_id": "school_select"})
    monkeypatch.setattr(flow, "async_step_school_select", next_step)

    result = asyncio.run(
        flow.async_step_school_search({CONF_SEARCH_QUERY: "Example"})
    )

    assert result["step_id"] == "school_select"
    assert flow._school_results == {school.key: school}
    next_step.assert_awaited_once_with()


def test_school_select_rejects_unknown_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)
    school = SchoolResult(
        display_name="Example School",
        login_name="example-school",
        server="example.webuntis.com",
    )
    flow._school_results = {school.key: school}

    result = asyncio.run(
        flow.async_step_school_select({CONF_SCHOOL_RESULT: "missing|school"})
    )

    assert result["errors"] == {CONF_SCHOOL_RESULT: "invalid_school"}


def test_school_select_loads_classes_and_routes_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    school = SchoolResult(
        display_name="Example School",
        login_name="example-school",
        server="example.webuntis.com",
    )
    flow._school_results = {school.key: school}
    monkeypatch.setattr(flow, "_async_load_classes", AsyncMock(return_value=True))
    next_step = AsyncMock(return_value={"type": "form", "step_id": "class_select"})
    monkeypatch.setattr(flow, "async_step_class_select", next_step)

    result = asyncio.run(
        flow.async_step_school_select({CONF_SCHOOL_RESULT: school.key})
    )

    assert result["step_id"] == "class_select"
    assert flow._server == "example.webuntis.com"
    assert flow._school == "example-school"
    assert flow._school_name == "Example School"


def test_public_link_rejects_missing_school(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)

    result = asyncio.run(
        flow.async_step_public_link(
            {CONF_PUBLIC_LINK: "https://example.org/WebUntis/"}
        )
    )

    assert result["errors"] == {CONF_PUBLIC_LINK: "invalid_public_link"}


def test_public_link_rejects_non_webuntis_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)

    result = asyncio.run(
        flow.async_step_public_link(
            {
                CONF_PUBLIC_LINK: (
                    "https://example.org/WebUntis/?school=Example"
                    "#/basic/timetablePublic/class?entityId=42"
                )
            }
        )
    )

    assert result["errors"] == {CONF_PUBLIC_LINK: "invalid_public_link"}


@pytest.mark.parametrize(
    "link",
    [
        "https://demo.webuntis.com/not-webuntis/?school=Example",
        (
            "https://demo.webuntis.com/WebUntis/?school=Example"
            "#/other/page?entityId=42"
        ),
    ],
)
def test_public_link_rejects_malformed_or_unsupported_links(
    monkeypatch: pytest.MonkeyPatch,
    link: str,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)

    result = asyncio.run(flow.async_step_public_link({CONF_PUBLIC_LINK: link}))

    assert result["errors"] == {CONF_PUBLIC_LINK: "invalid_public_link"}


def test_public_link_derives_school_from_webuntis_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    monkeypatch.setattr(flow, "_async_load_classes", AsyncMock(return_value=True))
    next_step = AsyncMock(return_value={"type": "form", "step_id": "class_select"})
    monkeypatch.setattr(flow, "async_step_class_select", next_step)

    result = asyncio.run(
        flow.async_step_public_link(
            {
                CONF_PUBLIC_LINK: (
                    "https://demo.webuntis.com/WebUntis/"
                    "#/basic/timetablePublic/class?entityId=42"
                )
            }
        )
    )

    assert result["step_id"] == "class_select"
    assert flow._server == "demo.webuntis.com"
    assert flow._school == "demo"
    assert flow._preselected_class_id == "42"


def test_public_link_preselects_class_and_routes_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    monkeypatch.setattr(flow, "_async_load_classes", AsyncMock(return_value=True))
    next_step = AsyncMock(return_value={"type": "form", "step_id": "class_select"})
    monkeypatch.setattr(flow, "async_step_class_select", next_step)

    result = asyncio.run(
        flow.async_step_public_link(
            {
                CONF_PUBLIC_LINK: (
                    "https://demo.webuntis.com/WebUntis/?school=Example"
                    "#/basic/timetablePublic/class?entityId=42"
                )
            }
        )
    )

    assert result["step_id"] == "class_select"
    assert flow._server == "demo.webuntis.com"
    assert flow._school == "Example"
    assert flow._preselected_class_id == "42"


def test_manual_setup_rejects_empty_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)

    result = asyncio.run(
        flow.async_step_manual({CONF_SERVER: "   ", CONF_SCHOOL: ""})
    )

    assert result["errors"] == {CONF_SERVER: "invalid_server"}


def test_manual_setup_derives_school_from_webuntis_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    monkeypatch.setattr(flow, "_async_load_classes", AsyncMock(return_value=True))
    next_step = AsyncMock(return_value={"type": "form", "step_id": "class_select"})
    monkeypatch.setattr(flow, "async_step_class_select", next_step)

    result = asyncio.run(
        flow.async_step_manual(
            {
                CONF_SERVER: "https://demo.webuntis.com/WebUntis/",
                CONF_SCHOOL: "",
            }
        )
    )

    assert result["step_id"] == "class_select"
    assert flow._server == "demo.webuntis.com"
    assert flow._school == "demo"
    assert flow._school_name == "demo"


def test_class_select_requires_at_least_one_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)
    flow._classes = {"123": "5A"}
    flow._class_names = {"123": "5A"}

    result = asyncio.run(
        flow.async_step_class_select({CONF_CLASS_IDS: []})
    )

    assert result["errors"] == {CONF_CLASS_IDS: "no_class_selected"}


def test_class_select_creates_multi_class_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = WebUntisPublicConfigFlow()
    _patch_flow_renderers(monkeypatch, flow)
    flow._server = "example.webuntis.com"
    flow._school = "example-school"
    flow._school_name = "Example School"
    flow._classes = {"123": "5A", "124": "5B"}
    flow._class_names = {"123": "5A", "124": "5B"}

    set_unique = AsyncMock()
    monkeypatch.setattr(flow, "async_set_unique_id", set_unique)
    abort_check = lambda: None
    monkeypatch.setattr(flow, "_abort_if_unique_id_configured", abort_check)

    result = asyncio.run(
        flow.async_step_class_select({CONF_CLASS_IDS: ["124", "123"]})
    )

    set_unique.assert_awaited_once_with("example.webuntis.com-124")
    assert result["type"] == "create_entry"
    assert result["title"] == "Example School"
    assert result["data"] == {
        CONF_SERVER: "example.webuntis.com",
        CONF_SCHOOL: "example-school",
        CONF_SCHOOL_NAME: "Example School",
        CONF_CLASS_ID: 124,
        CONF_CLASS_NAME: "5B",
        CONF_CLASS_IDS: [124, 123],
        CONF_CLASS_NAMES: {"124": "5B", "123": "5A"},
    }


class _SearchResponse:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error

    async def json(self, *, content_type=None):
        return self.payload


class _SearchSession:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return self.responses.pop(0)


def test_school_search_falls_back_to_second_endpoint_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _SearchSession(
        [
            _SearchResponse(error=RuntimeError("first endpoint unavailable")),
            _SearchResponse(
                {
                    "result": {
                        "schools": [
                            {
                                "loginName": "example-school",
                                "displayName": "Example School",
                                "server": "example.webuntis.com",
                            },
                            {
                                "loginName": "example-school",
                                "displayName": "Duplicate",
                                "server": "example.webuntis.com",
                            },
                        ]
                    }
                }
            ),
        ]
    )
    monkeypatch.setattr(
        config_module,
        "async_get_clientsession",
        lambda _hass: session,
    )
    flow = WebUntisPublicConfigFlow()
    flow.hass = SimpleNamespace()

    results = asyncio.run(flow._async_search_schools("Example"))

    assert len(results) == 1
    assert results[0].display_name == "Example School"
    assert len(session.calls) == 2
    assert session.calls[0][1]["json"]["method"] == "searchSchool"
    assert session.calls[0][1]["json"]["params"] == [{"search": "Example"}]


def test_school_search_raises_last_endpoint_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _SearchSession(
        [
            _SearchResponse(error=RuntimeError("first")),
            _SearchResponse(error=RuntimeError("second")),
        ]
    )
    monkeypatch.setattr(
        config_module,
        "async_get_clientsession",
        lambda _hass: session,
    )
    flow = WebUntisPublicConfigFlow()
    flow.hass = SimpleNamespace()

    with pytest.raises(RuntimeError, match="second"):
        asyncio.run(flow._async_search_schools("Example"))


def _options_flow(monkeypatch: pytest.MonkeyPatch, *, classes=None):
    entry = SimpleNamespace(
        entry_id="entry-1",
        domain="webuntis_public",
        source="user",
        data={
            CONF_SERVER: "example.webuntis.com",
            CONF_SCHOOL: "example-school",
            CONF_CLASS_ID: 123,
            CONF_CLASS_NAME: "5A",
            CONF_CLASS_IDS: [123],
            CONF_CLASS_NAMES: {"123": "5A"},
        },
        options={
            OPT_TITLE_FORMAT: TITLE_SUBJECT_ROOM,
            OPT_SHOW_CANCELLED: True,
            OPT_SHOW_TEACHER: True,
            OPT_SHOW_ROOM: True,
            OPT_SHOW_CLASS: True,
            OPT_NEXT_LESSON_DAYS: 14,
        },
    )
    updates = []

    class ConfigEntries:
        def async_get_known_entry(self, entry_id):
            assert entry_id == "entry-1"
            return entry

        def async_update_entry(self, target, **kwargs):
            updates.append(kwargs)
            if "data" in kwargs:
                target.data = kwargs["data"]
            return True

    hass = SimpleNamespace(
        config_entries=ConfigEntries(),
        async_add_executor_job=lambda func: asyncio.to_thread(func),
    )
    flow = WebUntisPublicOptionsFlow()
    flow.hass = hass
    flow.handler = "entry-1"
    _patch_flow_renderers(monkeypatch, flow)

    if classes is not None:
        class FakeClient:
            def __init__(self, server, school=None):
                assert server == "example.webuntis.com"
                assert school == "example-school"

            def list_classes(self):
                return classes

        monkeypatch.setattr(config_module, "WebUntisPublicClient", FakeClient)

    return flow, entry, updates


def test_options_flow_shows_current_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classes = [
        SimpleNamespace(id=123, name="5A", long_name="Klasse 5A"),
        SimpleNamespace(id=124, name="5B", long_name="Klasse 5B"),
    ]
    flow, _entry, _updates = _options_flow(
        monkeypatch,
        classes=classes,
    )

    result = asyncio.run(flow.async_step_init())

    assert result["type"] == "form"
    assert result["step_id"] == "init"
    validated = result["data_schema"]({})
    assert validated[CONF_CLASS_IDS] == ["123"]
    assert validated[OPT_TITLE_FORMAT] == TITLE_SUBJECT_ROOM
    assert validated[OPT_NEXT_LESSON_DAYS] == 14


def test_options_flow_rejects_empty_class_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, _entry, _updates = _options_flow(monkeypatch, classes=[])
    flow._class_options = []
    flow._class_names = {"123": "5A"}

    result = asyncio.run(
        flow.async_step_init(
            {
                CONF_CLASS_IDS: [],
                OPT_TITLE_FORMAT: TITLE_SUBJECT_ROOM,
                OPT_SHOW_CANCELLED: True,
                OPT_SHOW_TEACHER: True,
                OPT_SHOW_ROOM: True,
                OPT_SHOW_CLASS: True,
                OPT_NEXT_LESSON_DAYS: 14,
            }
        )
    )

    assert result["errors"] == {CONF_CLASS_IDS: "no_class_selected"}


def test_options_flow_updates_classes_and_keeps_presentation_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, entry, updates = _options_flow(monkeypatch, classes=[])
    flow._class_options = []
    flow._class_names = {"123": "5A", "124": "5B"}

    user_input = {
        CONF_CLASS_IDS: ["124", "123"],
        OPT_TITLE_FORMAT: TITLE_SUBJECT_ROOM,
        OPT_SHOW_CANCELLED: False,
        OPT_SHOW_TEACHER: True,
        OPT_SHOW_ROOM: False,
        OPT_SHOW_CLASS: True,
        OPT_NEXT_LESSON_DAYS: 21,
    }
    result = asyncio.run(flow.async_step_init(dict(user_input)))

    assert result["type"] == "create_entry"
    assert result["data"] == {
        OPT_TITLE_FORMAT: TITLE_SUBJECT_ROOM,
        OPT_SHOW_CANCELLED: False,
        OPT_SHOW_TEACHER: True,
        OPT_SHOW_ROOM: False,
        OPT_SHOW_CLASS: True,
        OPT_NEXT_LESSON_DAYS: 21,
    }
    assert entry.data[CONF_CLASS_ID] == 124
    assert entry.data[CONF_CLASS_NAME] == "5B"
    assert entry.data[CONF_CLASS_IDS] == [124, 123]
    assert entry.data[CONF_CLASS_NAMES] == {"124": "5B", "123": "5A"}
    assert len(updates) == 1


def test_options_class_loading_preserves_stored_classes_when_api_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, _entry, _updates = _options_flow(monkeypatch)

    class FailingClient:
        def __init__(self, _server, school=None):
            pass

        def list_classes(self):
            raise RuntimeError("offline")

    monkeypatch.setattr(config_module, "WebUntisPublicClient", FailingClient)

    asyncio.run(flow._async_load_class_options())

    assert flow._class_names == {"123": "5A"}
    assert len(flow._class_options) == 1
    assert flow._class_options[0]["value"] == "123"
    assert flow._class_options[0]["label"] == "5A"

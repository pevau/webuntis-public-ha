from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from webuntis_public import WebUntisPublicClient

from .const import (
    DEFAULT_NEXT_LESSON_DAYS,
    DEFAULT_SHOW_CANCELLED,
    DEFAULT_SHOW_CLASS,
    DEFAULT_SHOW_ROOM,
    DEFAULT_SHOW_TEACHER,
    DEFAULT_TITLE_FORMAT,
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
    DOMAIN,
    OPT_NEXT_LESSON_DAYS,
    OPT_SHOW_CANCELLED,
    OPT_SHOW_CLASS,
    OPT_SHOW_ROOM,
    OPT_SHOW_TEACHER,
    OPT_TITLE_FORMAT,
    TITLE_SUBJECT,
    TITLE_SUBJECT_ROOM,
    TITLE_SUBJECT_ROOM_TEACHER,
    TITLE_SUBJECT_TEACHER,
)

SCHOOL_SEARCH_ENDPOINTS = (
    "https://schoolsearch.webuntis.com/schoolquery2",
    "https://mobile.webuntis.com/ms/schoolquery2/",
)


@dataclass(frozen=True)
class SchoolResult:
    display_name: str
    login_name: str
    server: str
    address: str = ""

    @property
    def key(self) -> str:
        return f"{self.server}|{self.login_name}"

    @property
    def label(self) -> str:
        if self.address:
            return f"{self.display_name} — {self.address}"
        return self.display_name


def _normalise_server(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    return (parsed.hostname or parsed.path.split("/")[0]).strip().lower()


def _extract_public_link(link: str) -> tuple[str, str, int | None]:
    """Return server, school and optional class id from a public WebUntis URL."""
    value = link.strip()
    if not value:
        return "", "", None

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "", "", None

    server = parsed.hostname.strip().lower()
    if not server.endswith(".webuntis.com"):
        return "", "", None

    path = parsed.path.rstrip("/").lower()
    if path not in {"/webuntis", "/webuntis/"} and not path.startswith("/webuntis/"):
        return "", "", None

    query = parse_qs(parsed.query)
    school = unquote(query.get("school", [""])[0]).strip()

    class_id: int | None = None
    fragment = parsed.fragment or ""
    fragment_path, separator, fragment_query = fragment.partition("?")
    if separator:
        fragment_params = parse_qs(fragment_query)
        raw_entity = fragment_params.get("entityId", [None])[0]
        if raw_entity is not None:
            try:
                parsed_id = int(raw_entity)
            except (TypeError, ValueError):
                return "", "", None
            if parsed_id <= 0:
                return "", "", None
            class_id = parsed_id

    if fragment_path and not fragment_path.lstrip("/").startswith("basic/timetablePublic"):
        return "", "", None

    if not school:
        school = server.removesuffix(".webuntis.com")

    return server, school, class_id


def _find_school_dicts(value: Any) -> list[dict[str, Any]]:
    """Find school records in slightly different schoolquery2 response shapes."""
    found: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            found.extend(_find_school_dicts(item))
    elif isinstance(value, dict):
        keys = {str(k).lower() for k in value}
        if (
            "loginname" in keys
            and ("server" in keys or "serverurl" in keys)
        ):
            found.append(value)
        else:
            for item in value.values():
                found.extend(_find_school_dicts(item))
    return found


def _list_public_classes(server: str, school: str | None):
    """Load public WebUntis classes using the synchronous client."""
    return WebUntisPublicClient(server, school=school or None).list_classes()


async def _async_list_public_classes(hass, server: str, school: str | None):
    """Run the synchronous WebUntis class lookup outside the event loop."""
    return await hass.async_add_executor_job(
        partial(_list_public_classes, server, school)
    )


def _school_from_record(record: dict[str, Any]) -> SchoolResult | None:
    login = str(record.get("loginName") or record.get("loginname") or "").strip()
    display = str(
        record.get("displayName")
        or record.get("displayname")
        or record.get("name")
        or login
    ).strip()
    address = str(record.get("address") or "").strip()
    server = _normalise_server(
        str(record.get("serverUrl") or record.get("serverurl") or record.get("server") or "")
    )
    if not login or not server:
        return None
    return SchoolResult(display_name=display or login, login_name=login, server=server, address=address)


class WebUntisPublicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow."""
        return WebUntisPublicOptionsFlow()

    def __init__(self) -> None:
        self._server = ""
        self._school = ""
        self._school_name = ""
        self._school_results: dict[str, SchoolResult] = {}
        self._classes: dict[str, str] = {}
        self._class_names: dict[str, str] = {}
        self._preselected_class_id: str | None = None

    async def async_step_user(self, user_input=None):
        """Choose how the public timetable should be configured."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["school_search", "public_link", "manual"],
        )

    async def async_step_school_search(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            query = user_input[CONF_SEARCH_QUERY].strip()
            if len(query) < 3:
                errors[CONF_SEARCH_QUERY] = "search_too_short"
            else:
                try:
                    results = await self._async_search_schools(query)
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    if not results:
                        errors["base"] = "no_schools"
                    else:
                        self._school_results = {result.key: result for result in results}
                        return await self.async_step_school_select()

        return self.async_show_form(
            step_id="school_search",
            data_schema=vol.Schema(
                {vol.Required(CONF_SEARCH_QUERY): str}
            ),
            errors=errors,
        )

    async def async_step_school_select(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = self._school_results.get(user_input[CONF_SCHOOL_RESULT])
            if selected is None:
                errors[CONF_SCHOOL_RESULT] = "invalid_school"
            else:
                self._server = selected.server
                self._school = selected.login_name
                self._school_name = selected.display_name
                if await self._async_load_classes(errors):
                    return await self.async_step_class_select()

        choices = {key: value.label for key, value in self._school_results.items()}
        return self.async_show_form(
            step_id="school_select",
            data_schema=vol.Schema({vol.Required(CONF_SCHOOL_RESULT): vol.In(choices)}),
            errors=errors,
        )

    async def async_step_public_link(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                server, school, class_id = _extract_public_link(user_input[CONF_PUBLIC_LINK])
            except Exception:
                server, school, class_id = "", "", None

            if not server or not school:
                errors[CONF_PUBLIC_LINK] = "invalid_public_link"
            else:
                self._server = server
                self._school = school
                self._school_name = school
                self._preselected_class_id = str(class_id) if class_id is not None else None
                if await self._async_load_classes(errors):
                    return await self.async_step_class_select()

        return self.async_show_form(
            step_id="public_link",
            data_schema=vol.Schema({vol.Required(CONF_PUBLIC_LINK): str}),
            errors=errors,
        )

    async def async_step_manual(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._server = _normalise_server(user_input[CONF_SERVER])
            self._school = user_input.get(CONF_SCHOOL, "").strip()
            if not self._school and self._server.endswith(".webuntis.com"):
                self._school = self._server.removesuffix(".webuntis.com")
            self._school_name = self._school

            if not self._server:
                errors[CONF_SERVER] = "invalid_server"
            elif await self._async_load_classes(errors):
                return await self.async_step_class_select()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERVER): str,
                    vol.Optional(CONF_SCHOOL): str,
                }
            ),
            errors=errors,
        )

    async def async_step_class_select(self, user_input=None):
        if user_input is not None:
            selected_ids = [str(value) for value in user_input[CONF_CLASS_IDS]]
            if not selected_ids:
                return self.async_show_form(
                    step_id="class_select",
                    data_schema=self._class_select_schema(),
                    errors={CONF_CLASS_IDS: "no_class_selected"},
                )

            primary_id = selected_ids[0]
            primary_name = self._class_names[primary_id]
            class_names = {class_id: self._class_names[class_id] for class_id in selected_ids}

            await self.async_set_unique_id(f"{self._server}-{primary_id}")
            self._abort_if_unique_id_configured()

            title_prefix = self._school_name or self._school or self._server
            return self.async_create_entry(
                title=title_prefix,
                data={
                    CONF_SERVER: self._server,
                    CONF_SCHOOL: self._school,
                    CONF_SCHOOL_NAME: self._school_name,
                    CONF_CLASS_ID: int(primary_id),
                    CONF_CLASS_NAME: primary_name,
                    CONF_CLASS_IDS: [int(value) for value in selected_ids],
                    CONF_CLASS_NAMES: class_names,
                },
            )

        return self.async_show_form(
            step_id="class_select",
            data_schema=self._class_select_schema(),
        )

    def _class_select_schema(self) -> vol.Schema:
        options = [
            SelectOptionDict(value=class_id, label=label)
            for class_id, label in self._classes.items()
        ]
        default: list[str] | None = None
        if self._preselected_class_id in self._classes:
            default = [self._preselected_class_id]
        key = (
            vol.Required(CONF_CLASS_IDS, default=default)
            if default
            else vol.Required(CONF_CLASS_IDS)
        )
        return vol.Schema(
            {
                key: SelectSelector(
                    SelectSelectorConfig(options=options, multiple=True)
                )
            }
        )

    async def _async_load_classes(self, errors: dict[str, str]) -> bool:
        try:
            classes = await _async_list_public_classes(
                self.hass,
                self._server,
                self._school or None,
            )
        except Exception:
            errors["base"] = "cannot_load_classes"
            return False

        if not classes:
            errors["base"] = "no_public_classes"
            return False

        classes = sorted(classes, key=lambda item: (str(item.name).casefold(), int(item.id)))
        self._classes = {}
        self._class_names = {}
        for item in classes:
            cid = str(item.id)
            name = str(item.name or item.long_name or item.id)
            long_name = str(item.long_name or "").strip()
            label = name if not long_name or long_name == name else f"{name} – {long_name}"
            self._classes[cid] = label
            self._class_names[cid] = name
        return True

    async def _async_search_schools(self, query: str) -> list[SchoolResult]:
        session = async_get_clientsession(self.hass)
        payload = {
            "id": "home-assistant-webuntis-public",
            "jsonrpc": "2.0",
            "method": "searchSchool",
            "params": [{"search": query}],
        }

        last_error: Exception | None = None
        for endpoint in SCHOOL_SEARCH_ENDPOINTS:
            try:
                async with session.post(endpoint, json=payload, timeout=15) as response:
                    response.raise_for_status()
                    data = await response.json(content_type=None)
            except Exception as err:
                last_error = err
                continue

            results: list[SchoolResult] = []
            seen: set[str] = set()
            for record in _find_school_dicts(data.get("result", data)):
                school = _school_from_record(record)
                if school is not None and school.key not in seen:
                    seen.add(school.key)
                    results.append(school)

            if results:
                return results[:50]

        if last_error is not None:
            raise last_error
        return []


class WebUntisPublicOptionsFlow(config_entries.OptionsFlowWithReload):
    """Configure classes and optional presentation behaviour."""

    def __init__(self) -> None:
        self._class_options: list[SelectOptionDict] | None = None
        self._class_names: dict[str, str] = {}

    async def async_step_init(self, user_input=None):
        errors: dict[str, str] = {}
        if self._class_options is None:
            await self._async_load_class_options()

        if user_input is not None:
            selected_ids = [str(value) for value in user_input.pop(CONF_CLASS_IDS, [])]
            if not selected_ids:
                errors[CONF_CLASS_IDS] = "no_class_selected"
            else:
                data = dict(self.config_entry.data)
                data[CONF_CLASS_IDS] = [int(value) for value in selected_ids]
                data[CONF_CLASS_NAMES] = {
                    value: self._class_names.get(value, value) for value in selected_ids
                }
                primary_id = int(selected_ids[0])
                data[CONF_CLASS_ID] = primary_id
                data[CONF_CLASS_NAME] = self._class_names.get(str(primary_id), str(primary_id))
                self.hass.config_entries.async_update_entry(self.config_entry, data=data)
                return self.async_create_entry(data=user_input)

        current = self.config_entry.options
        configured = self.config_entry.data.get(CONF_CLASS_IDS)
        if not isinstance(configured, (list, tuple)) or not configured:
            configured = [self.config_entry.data[CONF_CLASS_ID]]
        selected_default = [str(value) for value in configured]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CLASS_IDS,
                    default=selected_default,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=self._class_options or [
                            SelectOptionDict(value=value, label=self._class_names.get(value, value))
                            for value in selected_default
                        ],
                        multiple=True,
                    )
                ),
                vol.Required(
                    OPT_TITLE_FORMAT,
                    default=current.get(OPT_TITLE_FORMAT, DEFAULT_TITLE_FORMAT),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            TITLE_SUBJECT,
                            TITLE_SUBJECT_ROOM,
                            TITLE_SUBJECT_TEACHER,
                            TITLE_SUBJECT_ROOM_TEACHER,
                        ],
                        translation_key="title_format",
                    )
                ),
                vol.Required(
                    OPT_SHOW_CANCELLED,
                    default=current.get(OPT_SHOW_CANCELLED, DEFAULT_SHOW_CANCELLED),
                ): bool,
                vol.Required(
                    OPT_SHOW_TEACHER,
                    default=current.get(OPT_SHOW_TEACHER, DEFAULT_SHOW_TEACHER),
                ): bool,
                vol.Required(
                    OPT_SHOW_ROOM,
                    default=current.get(OPT_SHOW_ROOM, DEFAULT_SHOW_ROOM),
                ): bool,
                vol.Required(
                    OPT_SHOW_CLASS,
                    default=current.get(OPT_SHOW_CLASS, DEFAULT_SHOW_CLASS),
                ): bool,
                vol.Required(
                    OPT_NEXT_LESSON_DAYS,
                    default=current.get(OPT_NEXT_LESSON_DAYS, DEFAULT_NEXT_LESSON_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=30,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def _async_load_class_options(self) -> None:
        server = self.config_entry.data[CONF_SERVER]
        school = self.config_entry.data.get(CONF_SCHOOL) or None

        try:
            classes = await _async_list_public_classes(self.hass, server, school)
        except Exception:
            classes = []

        names: dict[str, str] = {}
        labels: dict[str, str] = {}
        for item in classes:
            class_id = str(item.id)
            name = str(item.name or item.long_name or item.id)
            long_name = str(item.long_name or "").strip()
            names[class_id] = name
            labels[class_id] = name if not long_name or long_name == name else f"{name} – {long_name}"

        stored_names = self.config_entry.data.get(CONF_CLASS_NAMES, {})
        if isinstance(stored_names, dict):
            for class_id, name in stored_names.items():
                names.setdefault(str(class_id), str(name))
                labels.setdefault(str(class_id), str(name))
        primary_id = str(self.config_entry.data[CONF_CLASS_ID])
        primary_name = str(self.config_entry.data.get(CONF_CLASS_NAME, primary_id))
        names.setdefault(primary_id, primary_name)
        labels.setdefault(primary_id, primary_name)

        self._class_names = names
        self._class_options = [
            SelectOptionDict(value=class_id, label=labels[class_id])
            for class_id in sorted(labels, key=lambda cid: (labels[cid].casefold(), int(cid)))
        ]

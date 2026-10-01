"""Options: the "Benachrichtigungen" section (targets and events)."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import config_validation as cv
from probatio import to_field_list
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import (
    CONF_KEEP_DELIVERED_DAYS,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_SECTION,
    CONF_NOTIFY_TARGETS,
    CONF_POSTCODE,
    DEFAULT_NOTIFY_EVENTS,
    DOMAIN,
    NOTIFY_EVENTS,
)

from .test_config_flow_untouched import _frontend_initial

SETUP = "custom_components.parcel_tracker.async_setup_entry"
PHONE = "notify.mobile_app_handy"
TABLET = "notify.tablet"
BASE = {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3}


def _entry(hass, **options) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={**BASE, **options})
    entry.add_to_hass(hass)
    return entry


async def _form(hass, entry) -> tuple[str, dict]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    return result["flow_id"], {field["name"]: field for field in fields}


async def _save(hass, entry, notify):
    flow_id, _ = await _form(hass, entry)
    user_input = dict(BASE)
    if notify is not None:
        user_input[CONF_NOTIFY_SECTION] = notify
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(flow_id, user_input)
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    return result


async def test_section_offers_targets_and_events_but_no_dashboard_path(hass):
    _, fields = await _form(hass, _entry(hass))
    section = fields[CONF_NOTIFY_SECTION]
    assert section["type"] == "expandable" and section["expanded"] is False
    assert "default" not in section and not section.get("required")
    inner = {field["name"]: field for field in section["schema"]}
    assert list(inner) == [CONF_NOTIFY_ENABLED, CONF_NOTIFY_TARGETS, CONF_NOTIFY_EVENTS]
    assert "notify_url" not in inner
    targets = inner[CONF_NOTIFY_TARGETS]
    assert targets["selector"]["entity"]["multiple"] is True
    assert targets["selector"]["entity"]["domain"] == ["notify"]
    assert targets["default"] == [] and not targets.get("required")
    events = inner[CONF_NOTIFY_EVENTS]["selector"]["select"]
    assert events["multiple"] is True
    assert events["options"] == list(NOTIFY_EVENTS)
    assert events["translation_key"] == "notify_events"
    assert inner[CONF_NOTIFY_EVENTS]["default"] == ["out_for_delivery", "delivered"]
    assert inner[CONF_NOTIFY_ENABLED]["default"] is False


async def test_section_is_open_and_prefilled_once_targets_are_set(hass):
    entry = _entry(hass, notify_targets=[PHONE], notify_events=["exception"])
    _, fields = await _form(hass, entry)
    section = fields[CONF_NOTIFY_SECTION]
    assert section["expanded"] is True
    inner = {field["name"]: field for field in section["schema"]}
    assert inner[CONF_NOTIFY_ENABLED]["default"] is True
    assert inner[CONF_NOTIFY_TARGETS]["default"] == [PHONE]
    assert inner[CONF_NOTIFY_EVENTS]["default"] == ["exception"]


async def test_setting_targets_switches_notifications_on(hass):
    """Nothing is checked against the outside: an entity that does not exist is taken."""
    entry = _entry(hass)
    await _save(
        hass, entry,
        # The switch still shows "off" in a form that had no targets yet.
        {CONF_NOTIFY_ENABLED: False, CONF_NOTIFY_TARGETS: [PHONE, TABLET, PHONE],
         CONF_NOTIFY_EVENTS: list(DEFAULT_NOTIFY_EVENTS)},
    )
    assert entry.options[CONF_NOTIFY_TARGETS] == [PHONE, TABLET]
    assert entry.options[CONF_NOTIFY_EVENTS] == ["out_for_delivery", "delivered"]
    assert entry.options[CONF_POSTCODE] == "10115"


async def test_changing_targets_and_events(hass):
    entry = _entry(hass, notify_targets=[PHONE], notify_events=["delivered"])
    await _save(
        hass, entry,
        {CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_TARGETS: [TABLET],
         CONF_NOTIFY_EVENTS: ["exception", "awaiting_pickup", "delivered"]},
    )
    assert entry.options[CONF_NOTIFY_TARGETS] == [TABLET]
    # Stored in the fixed order of the four events.
    assert entry.options[CONF_NOTIFY_EVENTS] == ["delivered", "awaiting_pickup", "exception"]


async def test_emptying_the_targets_switches_notifications_off(hass):
    entry = _entry(hass, notify_targets=[PHONE, TABLET], notify_events=["delivered"])
    await _save(
        hass, entry,
        {CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_TARGETS: [], CONF_NOTIFY_EVENTS: ["delivered"]},
    )
    assert entry.options[CONF_NOTIFY_TARGETS] == []
    assert entry.options[CONF_NOTIFY_EVENTS] == ["delivered"]


async def test_the_switch_switches_notifications_off(hass):
    """Also works if the frontend were to leave an emptied selection out."""
    entry = _entry(hass, notify_targets=[PHONE, TABLET], notify_events=["delivered"])
    await _save(
        hass, entry,
        {CONF_NOTIFY_ENABLED: False, CONF_NOTIFY_TARGETS: [PHONE, TABLET],
         CONF_NOTIFY_EVENTS: ["delivered"]},
    )
    assert entry.options[CONF_NOTIFY_TARGETS] == []
    assert entry.options[CONF_NOTIFY_EVENTS] == ["delivered"]
    entry2 = _entry(hass, notify_targets=[PHONE])
    await _save(hass, entry2, {CONF_NOTIFY_ENABLED: False})
    assert entry2.options[CONF_NOTIFY_TARGETS] == []


@pytest.mark.parametrize(
    "notify",
    [None, {}, {CONF_NOTIFY_ENABLED: True}, {CONF_NOTIFY_EVENTS: ["delivered", "exception"]}],
    ids=["no-section", "empty-section", "only-switch", "only-events"],
)
async def test_missing_fields_keep_what_is_stored(hass, notify):
    entry = _entry(hass, notify_targets=[PHONE], notify_events=["delivered", "exception"])
    await _save(hass, entry, notify)
    assert entry.options[CONF_NOTIFY_TARGETS] == [PHONE]
    assert entry.options[CONF_NOTIFY_EVENTS] == ["delivered", "exception"]


async def test_no_events_ticked_is_stored_as_none(hass):
    entry = _entry(hass, notify_targets=[PHONE])
    await _save(hass, entry, {CONF_NOTIFY_TARGETS: [PHONE], CONF_NOTIFY_EVENTS: []})
    assert entry.options[CONF_NOTIFY_TARGETS] == [PHONE]
    assert entry.options[CONF_NOTIFY_EVENTS] == []


@pytest.mark.parametrize(
    "notify",
    [
        {CONF_NOTIFY_EVENTS: ["in_transit"]},
        {CONF_NOTIFY_TARGETS: ["sensor.pakete_heute"]},
        {CONF_NOTIFY_TARGETS: ["kein entity"]},
        {"notify_url": "/lovelace/pakete"},
    ],
    ids=["unknown-event", "other-domain", "no-entity-id", "dashboard-path"],
)
async def test_invalid_input_is_rejected(hass, notify):
    entry = _entry(hass, notify_targets=[PHONE])
    flow_id, _ = await _form(hass, entry)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            flow_id, {**BASE, CONF_NOTIFY_SECTION: notify}
        )
    assert entry.options[CONF_NOTIFY_TARGETS] == [PHONE]


def _initial(fields: dict) -> dict:
    """What the frontend submits for the untouched form."""
    return _frontend_initial(list(fields.values()))


@pytest.mark.parametrize(
    ("stored", "targets", "events"),
    [
        ({CONF_NOTIFY_EVENTS: None}, [], list(DEFAULT_NOTIFY_EVENTS)),
        ({CONF_NOTIFY_EVENTS: 7, CONF_NOTIFY_TARGETS: 5}, [], list(DEFAULT_NOTIFY_EVENTS)),
        ({CONF_NOTIFY_TARGETS: "notify.tablet"}, [], list(DEFAULT_NOTIFY_EVENTS)),
        (
            {CONF_NOTIFY_TARGETS: [PHONE, 5, None], CONF_NOTIFY_EVENTS: ["exception", "nope"]},
            [PHONE],
            ["exception"],
        ),
        (
            {CONF_NOTIFY_TARGETS: (PHONE,), CONF_NOTIFY_EVENTS: ("exception", "delivered", 3)},
            [PHONE],
            ["delivered", "exception"],
        ),
    ],
    ids=["events-none", "both-odd", "targets-text", "odd-items", "tuples"],
)
async def test_odd_stored_values_open_the_form_and_an_untouched_save_works(
    hass, stored, targets, events
):
    entry = _entry(hass, **stored)
    flow_id, fields = await _form(hass, entry)
    inner = {field["name"]: field for field in fields[CONF_NOTIFY_SECTION]["schema"]}
    assert inner[CONF_NOTIFY_TARGETS]["default"] == targets
    assert inner[CONF_NOTIFY_EVENTS]["default"] == events
    assert inner[CONF_NOTIFY_ENABLED]["default"] is bool(targets)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(flow_id, _initial(fields))
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NOTIFY_TARGETS] == targets
    assert entry.options[CONF_NOTIFY_EVENTS] == events
    assert entry.options[CONF_POSTCODE] == "10115"


@pytest.mark.parametrize(
    "notify",
    [
        {CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_TARGETS: []},
        {CONF_NOTIFY_ENABLED: True},
        {CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_EVENTS: ["delivered"]},
    ],
    ids=["empty-targets", "no-targets-sent", "only-events"],
)
async def test_switching_on_without_a_target_is_an_error(hass, notify):
    entry = _entry(hass)
    flow_id, _ = await _form(hass, entry)
    result = await hass.config_entries.options.async_configure(
        flow_id, {**BASE, CONF_NOTIFY_SECTION: notify}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "notify_no_target"}
    assert CONF_NOTIFY_TARGETS not in entry.options
    # The form keeps what was entered; with a target it saves.
    fields = to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    section = next(field for field in fields if field["name"] == CONF_NOTIFY_SECTION)
    inner = {field["name"]: field for field in section["schema"]}
    assert inner[CONF_NOTIFY_ENABLED]["default"] is True
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            flow_id,
            {**BASE, CONF_NOTIFY_SECTION: {CONF_NOTIFY_ENABLED: True,
                                           CONF_NOTIFY_TARGETS: [PHONE]}},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NOTIFY_TARGETS] == [PHONE]


async def test_untouched_form_without_targets_is_no_error(hass):
    """The switch shows "off" there: saving anything else must stay possible."""
    entry = _entry(hass)
    flow_id, fields = await _form(hass, entry)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(flow_id, _initial(fields))
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NOTIFY_TARGETS] == []

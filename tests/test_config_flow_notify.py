"""Options: the "Benachrichtigungen" section (targets and events)."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import config_validation as cv
from probatio import to_field_list
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

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
PUSHOVER = "service:pushover"
GONE = " (nicht mehr vorhanden)"
BASE = {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3}


def _entry(hass, present=(PHONE, TABLET), **options) -> MockConfigEntry:
    """An entry; the notify entities in ``present`` exist in Home Assistant."""
    for entity_id in present:
        hass.states.async_set(entity_id, "unknown")
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={**BASE, **options})
    entry.add_to_hass(hass)
    return entry


def _inner(fields: dict) -> dict:
    return {field["name"]: field for field in fields[CONF_NOTIFY_SECTION]["schema"]}


def _offered(fields: dict) -> list[tuple[str, str]]:
    """(value, label) of the targets on offer, in the order shown."""
    options = _inner(fields)[CONF_NOTIFY_TARGETS]["selector"]["select"]["options"]
    return [(option["value"], option["label"]) for option in options]


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
    select = targets["selector"]["select"]
    assert select["multiple"] is True and select["custom_value"] is False
    assert select["sort"] is False and "translation_key" not in select
    assert select["options"] == [
        {"value": PHONE, "label": "mobile app handy"},
        {"value": TABLET, "label": "tablet"},
    ]
    assert targets["default"] == [] and not targets.get("required")
    events = inner[CONF_NOTIFY_EVENTS]["selector"]["select"]
    assert events["multiple"] is True
    assert events["options"] == list(NOTIFY_EVENTS)
    assert events["translation_key"] == "notify_events"
    assert inner[CONF_NOTIFY_EVENTS]["default"] == [
        "out_for_delivery", "delivered", "awaiting_pickup",
    ]
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


async def test_offers_entities_first_then_classic_services(hass):
    """Entities by their name, then the services registered under ``notify`` as
    ``service:<name>``; never ``send_message`` (that is the entity service) and
    ``persistent_notification``; the catch-all ``notify.notify`` comes last."""
    hass.states.async_set("notify.zulu", "unknown", {"friendly_name": "Alpha Tablet"})
    hass.states.async_set("notify.iphone", "unknown", {"friendly_name": "iPhone"})
    hass.states.async_set("notify.alpha", "unavailable", {"friendly_name": "Zulu Handy"})
    hass.states.async_set("sensor.pakete_heute", "0")
    for name in ("notify", "pushover", "send_message", "persistent_notification",
                 "mobile_app_iphone"):
        async_mock_service(hass, "notify", name)
    async_mock_service(hass, "light", "turn_on")
    _, fields = await _form(hass, _entry(hass, present=()))
    assert _offered(fields) == [
        ("notify.zulu", "Alpha Tablet"),
        ("notify.iphone", "iPhone"),
        ("notify.alpha", "Zulu Handy"),
        ("service:mobile_app_iphone", "Dienst notify.mobile_app_iphone"),
        ("service:pushover", "Dienst notify.pushover"),
        ("service:notify", "Dienst notify.notify"),
    ]


async def test_services_with_a_name_that_can_be_no_target_are_not_offered(hass):
    """Only what the stored form ``service:<name>`` can name is on offer: a name with a
    dot or an upper-case letter would be chosen, stored and then never notified."""
    for name in ("pushover", "my.phone"):
        async_mock_service(hass, "notify", name)
    registered = hass.services.async_services_for_domain("notify")
    assert "my.phone" in registered
    # Home Assistant lower-cases names on registering; other sources may not.
    names = {**registered, "Loud": None, "ümlaut": None, "": None}
    with patch.object(type(hass.services), "async_services_for_domain", return_value=names):
        _, fields = await _form(hass, _entry(hass, present=()))
    assert _offered(fields) == [("service:pushover", "Dienst notify.pushover")]


async def test_a_classic_service_can_be_chosen_and_is_stored_with_its_prefix(hass):
    async_mock_service(hass, "notify", "pushover")
    entry = _entry(hass)
    await _save(hass, entry, {CONF_NOTIFY_TARGETS: [PUSHOVER, PHONE, PUSHOVER]})
    assert entry.options[CONF_NOTIFY_TARGETS] == [PUSHOVER, PHONE]
    _, fields = await _form(hass, entry)
    assert _inner(fields)[CONF_NOTIFY_TARGETS]["default"] == [PUSHOVER, PHONE]
    assert _inner(fields)[CONF_NOTIFY_ENABLED]["default"] is True
    assert GONE not in str(_offered(fields))


async def test_vanished_stored_targets_stay_selectable_and_are_kept(hass):
    """A stored target that does not exist (any more, or not yet after a start) is
    offered as "nicht mehr vorhanden" and still ticked: the untouched form saves and
    changes nothing. Values that can be no target at all are dropped."""
    stored = [PHONE, "notify.altes_handy", PUSHOVER, "sensor.pakete_heute", "quatsch",
              "service:", "service:Kein Dienst", "service:send_message",
              "service:persistent_notification"]
    kept = [PHONE, "notify.altes_handy", PUSHOVER]
    entry = _entry(hass, present=(PHONE,), notify_targets=stored)
    flow_id, fields = await _form(hass, entry)
    assert _inner(fields)[CONF_NOTIFY_TARGETS]["default"] == kept
    assert _offered(fields) == [
        (PHONE, "mobile app handy"),
        ("notify.altes_handy", "notify.altes_handy" + GONE),
        (PUSHOVER, "Dienst notify.pushover" + GONE),
    ]
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(flow_id, _initial(fields))
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NOTIFY_TARGETS] == kept

    # Unticked, a vanished target is gone for good: no longer on offer afterwards.
    await _save(hass, entry, {CONF_NOTIFY_TARGETS: [PHONE]})
    assert entry.options[CONF_NOTIFY_TARGETS] == [PHONE]
    _, fields = await _form(hass, entry)
    assert _offered(fields) == [(PHONE, "mobile app handy")]


async def test_form_shown_again_after_an_error_keeps_the_choice(hass):
    """Chosen targets stay ticked (and on offer) when the form comes back with an error."""
    async_mock_service(hass, "notify", "pushover")
    entry = _entry(hass, notify_targets=["notify.altes_handy"])
    flow_id, _ = await _form(hass, entry)
    result = await hass.config_entries.options.async_configure(
        flow_id,
        {**BASE, CONF_POSTCODE: "123",
         CONF_NOTIFY_SECTION: {CONF_NOTIFY_TARGETS: [PUSHOVER, "notify.altes_handy"]}},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_POSTCODE: "invalid_postcode"}
    fields = {
        field["name"]: field
        for field in to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    }
    assert _inner(fields)[CONF_NOTIFY_TARGETS]["default"] == [PUSHOVER, "notify.altes_handy"]
    assert ("notify.altes_handy", "notify.altes_handy" + GONE) in _offered(fields)
    assert (PUSHOVER, "Dienst notify.pushover") in _offered(fields)


async def test_setting_targets_switches_notifications_on(hass):
    entry = _entry(hass)
    await _save(
        hass, entry,
        # The switch still shows "off" in a form that had no targets yet.
        {CONF_NOTIFY_ENABLED: False, CONF_NOTIFY_TARGETS: [PHONE, TABLET, PHONE],
         CONF_NOTIFY_EVENTS: list(DEFAULT_NOTIFY_EVENTS)},
    )
    assert entry.options[CONF_NOTIFY_TARGETS] == [PHONE, TABLET]
    assert entry.options[CONF_NOTIFY_EVENTS] == [
        "out_for_delivery", "delivered", "awaiting_pickup",
    ]
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
        {CONF_NOTIFY_TARGETS: ["notify.gibt_es_nicht"]},
        {CONF_NOTIFY_TARGETS: ["service:gibt_es_nicht"]},
        {CONF_NOTIFY_TARGETS: ["service:send_message"]},
        {CONF_NOTIFY_TARGETS: ["service:persistent_notification"]},
        {CONF_NOTIFY_TARGETS: ["pushover"]},
        {"notify_url": "/lovelace/pakete"},
    ],
    ids=["unknown-event", "other-domain", "no-entity-id", "unknown-entity", "unknown-service",
         "entity-service", "persistent-notification", "service-without-prefix",
         "dashboard-path"],
)
async def test_invalid_input_is_rejected(hass, notify):
    for name in ("pushover", "send_message", "persistent_notification"):
        async_mock_service(hass, "notify", name)
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

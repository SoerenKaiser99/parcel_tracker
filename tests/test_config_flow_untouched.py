"""Options: a form saved untouched (or with a section the frontend sent incomplete)
must never delete or blank a stored secret or login.

Regression for v0.3.3: the frontend sent the mail section without ``imap_user``
(only the keys carrying a ``default``), which the flow read as "mail import off"
and dropped user and password; the UPS section had the same flaw.
"""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from probatio import to_field_list
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.parcel_tracker.carriers.track17 import Quota
from custom_components.parcel_tracker.const import (
    CONF_COUNTRY,
    CONF_DHL_API_KEY,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_INTERVAL,
    CONF_MAIL_SECTION,
    CONF_MOVE_PROCESSED,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_SECTION,
    CONF_NOTIFY_TARGETS,
    CONF_POSTCODE,
    CONF_READ_OTP,
    CONF_TRACK17_API_KEY,
    CONF_UPS_BUDGET,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    CONF_UPS_SECTION,
    DEFAULT_NOTIFY_EVENTS,
    DOMAIN,
)

SETUP = "custom_components.parcel_tracker.async_setup_entry"
FLOW = "custom_components.parcel_tracker.config_flow."
CHECKS = {
    "dhl": FLOW + "DhlCarrier.validate_key",
    "track17": FLOW + "Track17Client.getquota",
    "imap": FLOW + "MailboxClient.check_login",
    "ups": FLOW + "UpsCarrier.validate",
}

DATA = {
    CONF_DHL_API_KEY: "dhl-key",
    CONF_POSTCODE: "10115",
    CONF_KEEP_DELIVERED_DAYS: 3,
    CONF_TRACK17_API_KEY: "t17-key",
    CONF_IMAP_PASSWORD: "imap-pw",
    CONF_UPS_CLIENT_ID: "ups-id",
    CONF_UPS_CLIENT_SECRET: "ups-secret",
}
OPTIONS = {
    CONF_POSTCODE: "20095",
    CONF_KEEP_DELIVERED_DAYS: 7,
    CONF_IMAP_HOST: "imap.example.org",
    CONF_IMAP_USER: "pakete@example.org",
    CONF_MOVE_PROCESSED: False,
    CONF_READ_OTP: True,
    CONF_MAIL_INTERVAL: 15,
    CONF_UPS_BUDGET: 250,
    CONF_NOTIFY_TARGETS: ["notify.mobile_app_handy", "notify.tablet"],
    CONF_NOTIFY_EVENTS: ["delivered", "exception"],
}


def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=dict(DATA), options=dict(OPTIONS))
    entry.add_to_hass(hass)
    return entry


def _fields(result) -> list[dict]:
    """The form schema as Home Assistant sends it to the frontend."""
    return to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)


def _frontend_initial(fields: list[dict]) -> dict:
    """What the frontend submits for an untouched form.

    Mirrors ``computeInitialHaFormData`` of the HA frontend: a suggested value
    wins, then ``default``; a section is only walked when it has no ``default``.
    """
    data: dict = {}
    for field in fields:
        suggested = (field.get("description") or {}).get("suggested_value")
        if suggested is not None:
            data[field["name"]] = suggested
        elif "default" in field:
            data[field["name"]] = field["default"]
        elif field.get("type") == "expandable":
            inner = _frontend_initial(field["schema"])
            if field.get("required") or inner:
                data[field["name"]] = inner
        else:
            assert not field.get("required"), field
    return data


def _defaults_only(fields: list[dict]) -> dict:
    """Only the keys carrying a ``default`` – what arrived in production."""
    data: dict = {}
    for field in fields:
        if field.get("type") == "expandable":
            data[field["name"]] = _defaults_only(field["schema"])
        elif "default" in field:
            data[field["name"]] = field["default"]
    return data


async def _save(hass, entry, user_input):
    """Submit the options form; every online check would fail if it were called."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    if callable(user_input):
        user_input = user_input(_fields(result))
    with (
        patch(CHECKS["dhl"], return_value=False) as dhl,
        patch(CHECKS["track17"], side_effect=AssertionError) as track17,
        patch(CHECKS["imap"], side_effect=AssertionError) as imap,
        patch(CHECKS["ups"], return_value=False) as ups,
        patch(SETUP, return_value=True),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input
        )
        await hass.async_block_till_done()
    return result, (dhl, track17, imap, ups)


async def test_sections_without_user_and_client_id_keep_the_stored_logins(hass):
    """The payload of the v0.3.3 bug: sections with only their defaulted keys."""
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {
        CONF_TRACK17_API_KEY: "new-17track-key",
        CONF_POSTCODE: "20095",
        CONF_KEEP_DELIVERED_DAYS: 7,
        CONF_MAIL_SECTION: {
            CONF_IMAP_HOST: "imap.example.org",
            CONF_MOVE_PROCESSED: False,
            CONF_READ_OTP: True,
            CONF_MAIL_INTERVAL: 15,
        },
        CONF_UPS_SECTION: {CONF_UPS_BUDGET: 250},
        CONF_NOTIFY_SECTION: {CONF_NOTIFY_EVENTS: ["delivered", "exception"]},
    }
    with (
        patch(CHECKS["track17"], return_value=Quota(200, 0, 200)),
        patch(CHECKS["imap"], side_effect=AssertionError) as imap,
        patch(CHECKS["ups"], return_value=False) as ups,
        patch(SETUP, return_value=True),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    imap.assert_not_called()
    ups.assert_not_called()
    assert entry.options[CONF_IMAP_USER] == "pakete@example.org"
    assert entry.data[CONF_IMAP_PASSWORD] == "imap-pw"
    assert entry.data[CONF_UPS_CLIENT_ID] == "ups-id"
    assert entry.data[CONF_UPS_CLIENT_SECRET] == "ups-secret"
    assert entry.data == {**DATA, CONF_TRACK17_API_KEY: "new-17track-key"}
    assert entry.options == OPTIONS


async def test_untouched_form_changes_nothing(hass):
    """Open, save: data and options stay exactly as they were, nothing is checked online."""
    entry = _entry(hass)
    result, checks = await _save(hass, entry, _frontend_initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    for check in checks:
        check.assert_not_called()
    assert entry.data == DATA
    assert entry.options == OPTIONS


@pytest.mark.parametrize(
    "payload",
    [
        _defaults_only,
        lambda fields: {CONF_KEEP_DELIVERED_DAYS: 7, CONF_POSTCODE: "20095"},
        lambda fields: {
            CONF_KEEP_DELIVERED_DAYS: 7,
            CONF_POSTCODE: "20095",
            CONF_MAIL_SECTION: {},
            CONF_UPS_SECTION: {},
            CONF_NOTIFY_SECTION: {},
        },
        lambda fields: {
            CONF_KEEP_DELIVERED_DAYS: 7,
            CONF_POSTCODE: "20095",
            CONF_DHL_API_KEY: "",
            CONF_TRACK17_API_KEY: "",
            CONF_MAIL_SECTION: {CONF_IMAP_HOST: "", CONF_IMAP_USER: " ", CONF_IMAP_PASSWORD: ""},
            CONF_UPS_SECTION: {CONF_UPS_CLIENT_ID: "", CONF_UPS_CLIENT_SECRET: ""},
            CONF_NOTIFY_SECTION: {CONF_NOTIFY_ENABLED: True},
        },
    ],
    ids=["defaults-only", "no-sections", "empty-sections", "empty-strings"],
)
async def test_incomplete_form_never_deletes_secrets_or_logins(hass, payload):
    """Whatever the frontend leaves out or sends empty: no secret, no login is lost."""
    entry = _entry(hass)
    result, checks = await _save(hass, entry, payload)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    for check in checks:
        check.assert_not_called()
    assert entry.data == DATA
    # The postcode is the one field a user can empty (the frontend then omits it).
    assert {**entry.options, CONF_POSTCODE: "20095"} == OPTIONS


@pytest.mark.parametrize(
    "present", [(), ("notify.tablet",), ("notify.mobile_app_handy", "notify.tablet")],
    ids=["all-gone", "one-gone", "all-there"],
)
async def test_untouched_form_keeps_entities_and_classic_services(hass, present):
    """Targets stored by v0.3.5 (entity IDs only) next to classic services: whether they
    (still) exist in Home Assistant or not, open and save changes nothing."""
    for entity_id in present:
        hass.states.async_set(entity_id, "unknown", {"friendly_name": "Gerät"})
    async_mock_service(hass, "notify", "mobile_app_handy")
    entry = _entry(hass)
    options = {
        **OPTIONS,
        CONF_NOTIFY_TARGETS: [
            "notify.mobile_app_handy", "service:pushover", "notify.tablet",
            "service:mobile_app_handy",
        ],
    }
    hass.config_entries.async_update_entry(entry, options=dict(options))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    initial = _frontend_initial(_fields(result))
    assert initial[CONF_NOTIFY_SECTION] == {
        CONF_NOTIFY_ENABLED: True,
        CONF_NOTIFY_TARGETS: options[CONF_NOTIFY_TARGETS],
        CONF_NOTIFY_EVENTS: ["delivered", "exception"],
    }
    result, checks = await _save(hass, entry, _frontend_initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    for check in checks:
        check.assert_not_called()
    assert entry.data == DATA
    assert entry.options == options


def test_frontend_prefills_the_sections(hass):
    """No ``default`` on a section: the frontend then walks into it and prefills
    user, client ID and the switches instead of starting from an empty section."""
    from custom_components.parcel_tracker.config_flow import _schema

    current = {**DATA, **OPTIONS}
    fields = to_field_list(
        _schema(current, True, suggested_postcode="20095", mail=current, ups=current,
                track17=True, notify=current),
        custom_serializer=cv.custom_serializer,
    )
    sections = {f["name"]: f for f in fields if f.get("type") == "expandable"}
    assert set(sections) == {CONF_MAIL_SECTION, CONF_UPS_SECTION, CONF_NOTIFY_SECTION}
    for field in sections.values():
        assert "default" not in field
    initial = _frontend_initial(fields)
    assert initial[CONF_MAIL_SECTION][CONF_IMAP_USER] == "pakete@example.org"
    assert initial[CONF_UPS_SECTION][CONF_UPS_CLIENT_ID] == "ups-id"
    assert CONF_IMAP_PASSWORD not in initial[CONF_MAIL_SECTION]
    assert CONF_UPS_CLIENT_SECRET not in initial[CONF_UPS_SECTION]
    assert initial[CONF_NOTIFY_SECTION] == {
        CONF_NOTIFY_ENABLED: True,
        CONF_NOTIFY_TARGETS: ["notify.mobile_app_handy", "notify.tablet"],
        CONF_NOTIFY_EVENTS: ["delivered", "exception"],
    }


async def test_untouched_form_of_an_entry_from_before_notifications(hass):
    """An entry saved by v0.3.4 has no notification settings: opening and saving the
    form leaves notifications off, with the default events, and touches nothing else."""
    before = {k: v for k, v in OPTIONS.items() if not k.startswith("notify_")}
    entry = MockConfigEntry(domain=DOMAIN, data=dict(DATA), options=dict(before))
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    initial = _frontend_initial(_fields(result))
    assert initial[CONF_NOTIFY_SECTION] == {
        CONF_NOTIFY_ENABLED: False,
        CONF_NOTIFY_TARGETS: [],
        CONF_NOTIFY_EVENTS: list(DEFAULT_NOTIFY_EVENTS),
    }
    result, checks = await _save(hass, entry, _frontend_initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    for check in checks:
        check.assert_not_called()
    assert entry.data == DATA
    assert entry.options == {
        **before,
        CONF_NOTIFY_TARGETS: [],
        CONF_NOTIFY_EVENTS: list(DEFAULT_NOTIFY_EVENTS),
    }


async def test_untouched_form_of_an_entry_without_country_stores_no_country(hass):
    """An entry from before v0.3.13 has no country: the form shows Germany, and open
    and save neither adds a country nor touches the 5-digit postcode."""
    hass.config.country = "AT"  # the country of Home Assistant is only a prefill at setup
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    initial = _frontend_initial(_fields(result))
    assert initial[CONF_COUNTRY] == "de"
    assert initial[CONF_POSTCODE] == "20095"
    result, checks = await _save(hass, entry, _frontend_initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    for check in checks:
        check.assert_not_called()
    assert entry.data == DATA
    assert entry.options == OPTIONS
    assert CONF_COUNTRY not in entry.options


@pytest.mark.parametrize(
    ("country", "postcode", "in_data"),
    [("de", "20095", False), ("at", "1010", False), ("ch", "8001", False), ("at", "1010", True)],
    ids=["de", "at", "ch", "at-from-setup"],
)
async def test_untouched_form_with_a_stored_country_changes_nothing(
    hass, country, postcode, in_data
):
    """Country stored by the options (or, ``in_data``, only by the setup): open, save."""
    data = {**DATA, CONF_COUNTRY: country} if in_data else dict(DATA)
    options = {**OPTIONS, CONF_POSTCODE: postcode}
    if not in_data:
        options[CONF_COUNTRY] = country
    entry = MockConfigEntry(domain=DOMAIN, data=dict(data), options=dict(options))
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    initial = _frontend_initial(_fields(result))
    assert initial[CONF_COUNTRY] == country
    assert initial[CONF_POSTCODE] == postcode
    for payload in (_frontend_initial, _defaults_only):
        result, checks = await _save(hass, entry, payload)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        for check in checks:
            check.assert_not_called()
        assert entry.data == data
        if payload is _frontend_initial:
            assert entry.options == options
        else:  # the postcode has no ``default``: left out, it is removed (as before)
            assert entry.options == {**options, CONF_POSTCODE: ""}

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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.track17 import Quota
from custom_components.parcel_tracker.const import (
    CONF_DHL_API_KEY,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_INTERVAL,
    CONF_MAIL_SECTION,
    CONF_MOVE_PROCESSED,
    CONF_POSTCODE,
    CONF_READ_OTP,
    CONF_TRACK17_API_KEY,
    CONF_UPS_BUDGET,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    CONF_UPS_SECTION,
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
        },
        lambda fields: {
            CONF_KEEP_DELIVERED_DAYS: 7,
            CONF_POSTCODE: "20095",
            CONF_DHL_API_KEY: "",
            CONF_TRACK17_API_KEY: "",
            CONF_MAIL_SECTION: {CONF_IMAP_HOST: "", CONF_IMAP_USER: " ", CONF_IMAP_PASSWORD: ""},
            CONF_UPS_SECTION: {CONF_UPS_CLIENT_ID: "", CONF_UPS_CLIENT_SECRET: ""},
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


def test_frontend_prefills_the_sections(hass):
    """No ``default`` on a section: the frontend then walks into it and prefills
    user, client ID and the switches instead of starting from an empty section."""
    from custom_components.parcel_tracker.config_flow import _schema

    current = {**DATA, **OPTIONS}
    fields = to_field_list(
        _schema(current, True, suggested_postcode="20095", mail=current, ups=current,
                track17=True),
        custom_serializer=cv.custom_serializer,
    )
    sections = {f["name"]: f for f in fields if f.get("type") == "expandable"}
    assert set(sections) == {CONF_MAIL_SECTION, CONF_UPS_SECTION}
    for field in sections.values():
        assert "default" not in field
    initial = _frontend_initial(fields)
    assert initial[CONF_MAIL_SECTION][CONF_IMAP_USER] == "pakete@example.org"
    assert initial[CONF_UPS_SECTION][CONF_UPS_CLIENT_ID] == "ups-id"
    assert CONF_IMAP_PASSWORD not in initial[CONF_MAIL_SECTION]
    assert CONF_UPS_CLIENT_SECRET not in initial[CONF_UPS_SECTION]

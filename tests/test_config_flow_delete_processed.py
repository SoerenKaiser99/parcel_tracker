"""Options: "Erkannte Mails löschen nach (Tagen)" in the mail section (v0.3.46).

0 (off) is the default and is never stored; 1 to 365 days are; an untouched form keeps
what is stored and writes nothing new.
"""

from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import (
    CONF_DELETE_PROCESSED_DAYS,
    CONF_IMAP_HOST,
    CONF_IMAP_USER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_SECTION,
    CONF_POSTCODE,
    DOMAIN,
)

from .conftest import open_options
from .test_config_flow_untouched import DATA, OPTIONS, _fields, _frontend_initial, _save

SETUP = "custom_components.parcel_tracker.async_setup_entry"


def _entry(hass, **options) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=dict(DATA), options={**OPTIONS, **options})
    entry.add_to_hass(hass)
    return entry


def _mail_field(fields, name):
    mail = next(f for f in fields if f["name"] == CONF_MAIL_SECTION)
    return next(f for f in mail["schema"] if f["name"] == name)


async def test_the_field_defaults_to_zero_and_allows_up_to_365(hass):
    entry = _entry(hass)
    result = await open_options(hass, entry)
    field = _mail_field(_fields(result), CONF_DELETE_PROCESSED_DAYS)
    assert field["default"] == 0
    number = field["selector"]["number"]
    assert (number["min"], number["max"], number["mode"]) == (0, 365, "box")


async def test_untouched_form_stores_no_delete_option(hass):
    entry = _entry(hass)
    result, checks = await _save(hass, entry, _frontend_initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_DELETE_PROCESSED_DAYS not in entry.options
    assert entry.options == OPTIONS
    assert entry.data == DATA


async def test_untouched_form_keeps_stored_days(hass):
    entry = _entry(hass, **{CONF_DELETE_PROCESSED_DAYS: 30})
    result, _ = await _save(hass, entry, _frontend_initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**OPTIONS, CONF_DELETE_PROCESSED_DAYS: 30}


async def test_a_form_without_the_field_keeps_stored_days(hass):
    entry = _entry(hass, **{CONF_DELETE_PROCESSED_DAYS: 30})
    result, _ = await _save(
        hass, entry, {CONF_KEEP_DELIVERED_DAYS: 7, CONF_POSTCODE: "20095", CONF_MAIL_SECTION: {}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DELETE_PROCESSED_DAYS] == 30


def _with_days(days):
    def payload(fields):
        data = _frontend_initial(fields)
        data[CONF_MAIL_SECTION] = {**data[CONF_MAIL_SECTION], CONF_DELETE_PROCESSED_DAYS: days}
        return data

    return payload


@pytest.mark.parametrize("days", [1, 30, 30.0, 365])
async def test_days_are_stored_as_whole_numbers(hass, days):
    entry = _entry(hass)
    result, checks = await _save(hass, entry, _with_days(days))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    for check in checks:
        check.assert_not_called()  # no login check for this setting
    stored = entry.options[CONF_DELETE_PROCESSED_DAYS]
    assert stored == int(days) and type(stored) is int


async def test_back_to_zero_removes_the_option(hass):
    entry = _entry(hass, **{CONF_DELETE_PROCESSED_DAYS: 30})
    result, _ = await _save(hass, entry, _with_days(0))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_DELETE_PROCESSED_DAYS not in entry.options
    assert entry.options == OPTIONS


@pytest.mark.parametrize("days", [-1, 366])
async def test_out_of_range_is_refused(hass, days):
    entry = _entry(hass)
    result = await open_options(hass, entry)
    data = _with_days(days)(_fields(result))
    with (
        patch(SETUP, return_value=True),
        pytest.raises((InvalidData, vol.Invalid)),
    ):
        await hass.config_entries.options.async_configure(result["flow_id"], data)
    assert CONF_DELETE_PROCESSED_DAYS not in entry.options


async def test_a_broken_number_is_off_never_more(hass):
    """Not a whole number (the box only offers those): stored as off, nothing deleted."""
    entry = _entry(hass)
    result, _ = await _save(hass, entry, _with_days(1.5))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_DELETE_PROCESSED_DAYS not in entry.options


async def test_the_option_is_kept_while_the_mail_import_is_off(hass):
    """Without a mailbox nothing is deleted anyway; the setting is not thrown away."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115"},
        options={CONF_IMAP_HOST: "", CONF_IMAP_USER: "", CONF_DELETE_PROCESSED_DAYS: 14},
    )
    entry.add_to_hass(hass)
    result = await open_options(hass, entry)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DELETE_PROCESSED_DAYS] == 14

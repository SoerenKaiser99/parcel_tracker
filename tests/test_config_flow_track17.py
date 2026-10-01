"""Options: 17track API key (checked with getquota, stored in entry.data)."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.base import AuthError, CarrierUnavailable
from custom_components.parcel_tracker.carriers.track17 import Quota
from custom_components.parcel_tracker.const import (
    CONF_KEEP_DELIVERED_DAYS,
    CONF_POSTCODE,
    CONF_TRACK17_API_KEY,
    DOMAIN,
)

GETQUOTA = "custom_components.parcel_tracker.config_flow.Track17Client.getquota"
SETUP = "custom_components.parcel_tracker.async_setup_entry"


def _input(key=None):
    data = {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3}
    if key is not None:
        data[CONF_TRACK17_API_KEY] = key
    return data


async def _configure(hass, entry, user_input, **quota):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(GETQUOTA, **quota) as check, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
        await hass.async_block_till_done()
    return result, check


async def test_key_field_only_in_the_options(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert CONF_TRACK17_API_KEY not in result["data_schema"].schema
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert CONF_TRACK17_API_KEY in result["data_schema"].schema


async def test_valid_key_is_checked_and_stored_in_data(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result, check = await _configure(
        hass, entry, _input(" synthetic-17track-key "), return_value=Quota(200, 0, 200)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    check.assert_called_once()
    assert entry.data[CONF_TRACK17_API_KEY] == "synthetic-17track-key"
    assert CONF_TRACK17_API_KEY not in entry.options


@pytest.mark.parametrize(
    ("quota", "error"),
    [
        ({"side_effect": AuthError("rejected")}, "track17_invalid_key"),
        ({"side_effect": CarrierUnavailable("down")}, "track17_cannot_connect"),
    ],
)
async def test_rejected_or_unreachable(hass, quota, error):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result, _ = await _configure(hass, entry, _input("bad"), **quota)
    assert result["errors"] == {CONF_TRACK17_API_KEY: error}
    assert CONF_TRACK17_API_KEY not in entry.data


async def test_empty_field_keeps_the_saved_key_without_a_check(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_POSTCODE: "10115", CONF_TRACK17_API_KEY: "saved"}
    )
    entry.add_to_hass(hass)
    result, check = await _configure(
        hass, entry, _input(""), side_effect=CarrierUnavailable("down")
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    check.assert_not_called()
    assert entry.data[CONF_TRACK17_API_KEY] == "saved"

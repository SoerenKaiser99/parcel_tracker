"""Options: UPS Client ID/Secret (checked by a token request) and the monthly budget."""

from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.base import CarrierUnavailable
from custom_components.parcel_tracker.const import (
    CONF_KEEP_DELIVERED_DAYS,
    CONF_POSTCODE,
    CONF_UPS_BUDGET,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    CONF_UPS_ENABLED,
    CONF_UPS_SECTION,
    DOMAIN,
)

VALIDATE = "custom_components.parcel_tracker.config_flow.UpsCarrier.validate"
SETUP = "custom_components.parcel_tracker.async_setup_entry"


def _input(**ups):
    return {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3, CONF_UPS_SECTION: ups}


async def _configure(hass, entry, user_input, **validate):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(VALIDATE, **validate) as check, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
        await hass.async_block_till_done()
    return result, check


async def test_defaults_without_ups(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert CONF_UPS_SECTION in result["data_schema"].schema
    result, check = await _configure(
        hass, entry, {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    check.assert_not_called()
    assert entry.options[CONF_UPS_BUDGET] == 100
    assert CONF_UPS_CLIENT_ID not in entry.data


async def test_new_credentials_are_checked_and_stored_in_data(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result, check = await _configure(
        hass,
        entry,
        _input(**{CONF_UPS_CLIENT_ID: " id ", CONF_UPS_CLIENT_SECRET: "sec",
                  CONF_UPS_BUDGET: 250}),
        return_value=True,
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    check.assert_called_once()
    assert (entry.data[CONF_UPS_CLIENT_ID], entry.data[CONF_UPS_CLIENT_SECRET]) == ("id", "sec")
    assert entry.options[CONF_UPS_BUDGET] == 250
    assert CONF_UPS_CLIENT_SECRET not in entry.options


@pytest.mark.parametrize(
    ("validate", "error"),
    [({"return_value": False}, "ups_auth"),
     ({"side_effect": CarrierUnavailable("down")}, "ups_cannot_connect")],
)
async def test_rejected_or_unreachable(hass, validate, error):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result, _ = await _configure(
        hass, entry, _input(**{CONF_UPS_CLIENT_ID: "id", CONF_UPS_CLIENT_SECRET: "bad"}),
        **validate,
    )
    assert result["errors"] == {"base": error}
    assert CONF_UPS_CLIENT_ID not in entry.data


async def test_empty_secret_keeps_the_stored_one_without_a_new_check(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_UPS_CLIENT_ID: "id", CONF_UPS_CLIENT_SECRET: "sec"},
    )
    entry.add_to_hass(hass)
    result, check = await _configure(
        hass, entry, _input(**{CONF_UPS_CLIENT_ID: "id", CONF_UPS_CLIENT_SECRET: "",
                               CONF_UPS_BUDGET: 50}),
        side_effect=CarrierUnavailable("down"),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    check.assert_not_called()
    assert entry.data[CONF_UPS_CLIENT_SECRET] == "sec"
    assert entry.options[CONF_UPS_BUDGET] == 50


async def test_client_id_without_any_secret(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result, check = await _configure(hass, entry, _input(**{CONF_UPS_CLIENT_ID: "id"}))
    assert result["errors"] == {"base": "ups_secret_missing"}
    check.assert_not_called()


async def test_switch_off_removes_id_and_secret(hass):
    """Only the explicit switch turns the UPS API off."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_UPS_CLIENT_ID: "id", CONF_UPS_CLIENT_SECRET: "sec"},
    )
    entry.add_to_hass(hass)
    result, check = await _configure(
        hass, entry, _input(**{CONF_UPS_ENABLED: False, CONF_UPS_CLIENT_ID: "id"})
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    check.assert_not_called()
    assert CONF_UPS_CLIENT_ID not in entry.data
    assert CONF_UPS_CLIENT_SECRET not in entry.data
    assert CONF_UPS_ENABLED not in entry.data
    assert CONF_UPS_ENABLED not in entry.options


@pytest.mark.parametrize("ups", [{CONF_UPS_CLIENT_ID: ""}, {}, {CONF_UPS_ENABLED: True}])
async def test_empty_or_missing_client_id_keeps_the_api(hass, ups):
    """An emptied Client ID (the frontend then omits it) is no longer "off"."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_UPS_CLIENT_ID: "id", CONF_UPS_CLIENT_SECRET: "sec"},
    )
    entry.add_to_hass(hass)
    result, check = await _configure(
        hass, entry, _input(**ups), side_effect=CarrierUnavailable("down")
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    check.assert_not_called()
    assert (entry.data[CONF_UPS_CLIENT_ID], entry.data[CONF_UPS_CLIENT_SECRET]) == ("id", "sec")


async def test_switch_defaults_to_whether_a_client_id_is_stored(hass):
    def defaults(result):
        section = result["data_schema"].schema[CONF_UPS_SECTION].schema.schema
        enabled = next(key for key in section if key == CONF_UPS_ENABLED)
        client_id = next(key for key in section if key == CONF_UPS_CLIENT_ID)
        return enabled.default(), client_id

    empty = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    empty.add_to_hass(hass)
    enabled, _ = defaults(await hass.config_entries.options.async_init(empty.entry_id))
    assert enabled is False
    await hass.config_entries.async_remove(empty.entry_id)
    configured = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_UPS_CLIENT_ID: "id", CONF_UPS_CLIENT_SECRET: "sec"},
    )
    configured.add_to_hass(hass)
    enabled, client_id = defaults(
        await hass.config_entries.options.async_init(configured.entry_id)
    )
    assert enabled is True
    assert client_id.default() == "id"  # visibly prefilled, not a suggested value
    assert not client_id.description


async def test_enabled_without_any_client_id_configures_nothing(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result, check = await _configure(hass, entry, _input(**{CONF_UPS_ENABLED: True}))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    check.assert_not_called()
    assert CONF_UPS_CLIENT_ID not in entry.data
    assert CONF_UPS_CLIENT_SECRET not in entry.data


@pytest.mark.parametrize("budget", [-1, 10001])
async def test_budget_out_of_range(hass, budget):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"], _input(**{CONF_UPS_BUDGET: budget})
        )

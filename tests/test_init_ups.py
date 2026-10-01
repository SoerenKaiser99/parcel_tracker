"""Setup wires Hermes and the optional UPS API; services and sensors know the new carriers."""

from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker import _ups_carrier
from custom_components.parcel_tracker.carriers.ups import ApiBudget, UpsCarrier
from custom_components.parcel_tracker.const import (
    CONF_POSTCODE,
    CONF_UPS_BUDGET,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    DOMAIN,
)
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

HERMES_FETCH = "custom_components.parcel_tracker.carriers.hermes.HermesCarrier.fetch"
CREDS = {CONF_UPS_CLIENT_ID: "id", CONF_UPS_CLIENT_SECRET: "secret"}


def _res(status=ParcelStatus.IN_TRANSIT):
    return TrackingResult(status, "x", None, None, None, None, None, None, None, [])


async def test_ups_carrier_needs_both_credentials_and_a_budget(hass):
    budget = ApiBudget()
    none = MockConfigEntry(domain=DOMAIN, data={}, options={})
    assert _ups_carrier(hass, none, budget) is None
    only_id = MockConfigEntry(domain=DOMAIN, data={CONF_UPS_CLIENT_ID: "id"}, options={})
    assert _ups_carrier(hass, only_id, budget) is None
    zero = MockConfigEntry(domain=DOMAIN, data=CREDS, options={CONF_UPS_BUDGET: 0})
    assert _ups_carrier(hass, zero, budget) is None
    default = _ups_carrier(hass, MockConfigEntry(domain=DOMAIN, data=CREDS, options={}), budget)
    assert isinstance(default, UpsCarrier)
    assert (default.limit, default.budget) == (100, budget)
    custom = MockConfigEntry(domain=DOMAIN, data=CREDS, options={CONF_UPS_BUDGET: 250})
    assert _ups_carrier(hass, custom, budget).limit == 250


async def test_setup_with_credentials_adds_ups_and_uses_the_stored_budget(hass, hass_storage):
    hass_storage["parcel_tracker"] = {
        "version": 1,
        "key": "parcel_tracker",
        "data": {"parcels": [], "ups_budget": {"month": "2026-09", "count": 7}},
    }
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "", **CREDS}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert list(coordinator.carriers) == ["dhl", "dpd", "hermes", "gls", "ups"]
    assert coordinator.carriers["ups"].budget is coordinator.store.ups_budget
    assert coordinator.store.ups_budget.count == 7


async def test_setup_without_credentials_clears_ups_issues(hass):
    for issue in ("ups_auth", "ups_budget"):
        ir.async_create_issue(
            hass, DOMAIN, issue, is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key=issue,
        )
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: ""}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert "ups" not in entry.runtime_data.carriers
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "ups_auth") is None
    assert registry.async_get_issue(DOMAIN, "ups_budget") is None


async def test_add_service_accepts_hermes_and_ups(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: ""}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    with patch(HERMES_FETCH, return_value=_res()):
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": "H9999999999999999901", "carrier": "hermes"},
            blocking=True,
        )
    await hass.services.async_call(
        DOMAIN, "add_parcel", {"number": "1Z999AA10123456784", "carrier": "ups"}, blocking=True
    )
    store = entry.runtime_data.store
    assert store.get("H9999999999999999901").status is ParcelStatus.IN_TRANSIT
    assert store.get("1Z999AA10123456784").carrier == "ups"
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": "1", "carrier": "fedex"}, blocking=True
        )


async def test_sensor_shows_hint_and_shop_name(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: ""}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    now = dt_util.utcnow()
    coordinator.store.add(
        Parcel("EBAY990000000001", "ebay", "mail", None, now, now, result=_res(),
               shipping_carrier_hint="hermes")
    )
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()
    state = hass.states.get("sensor.paket_ebay990000000001")
    assert state.attributes["friendly_name"] == "eBay EBAY990000000001"
    assert state.attributes["shipping_carrier_hint"] == "hermes"
    assert state.attributes["carrier"] == "ebay"

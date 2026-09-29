from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.models import ParcelStatus, TrackingResult

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"


async def test_calendar_event(hass):
    tomorrow = dt_util.now().date() + timedelta(days=1)
    res = TrackingResult(
        ParcelStatus.IN_TRANSIT, "x", tomorrow, None, None, None, None, None, None, []
    )
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=res):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": "00340999999999999901", "name": "Oma"}, blocking=True
        )
        await hass.async_block_till_done()

    result = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": "calendar.pakete", "duration": {"days": 3}},
        blocking=True, return_response=True,
    )
    events = result["calendar.pakete"]["events"]
    assert len(events) == 1
    assert events[0]["summary"] == "Paket: Oma"
    assert events[0]["start"] == tomorrow.isoformat()


async def test_calendar_skips_past_eta_for_non_delivered_parcel(hass):
    """A parcel that's overdue (eta_date before today) and not yet delivered
    must not create a calendar event ("In -1 Tagen" territory)."""
    yesterday = dt_util.now().date() - timedelta(days=1)
    res = TrackingResult(
        ParcelStatus.IN_TRANSIT, "x", yesterday, None, None, None, None, None, None, []
    )
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=res):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": "00340999999999999901", "name": "Oma"}, blocking=True
        )
        await hass.async_block_till_done()

    result = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": "calendar.pakete", "duration": {"days": 3}},
        blocking=True, return_response=True,
    )
    assert result["calendar.pakete"]["events"] == []

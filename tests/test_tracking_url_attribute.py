"""Sensor attribute ``tracking_url``: the carrier's tracking page, built in ``links``."""

from datetime import UTC, datetime
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_HIDE_NAMES, CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
DHL = "00340999999999999901"
ORDER = "AMZ99991565342587125"
DHL_URL = f"https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode={DHL}"


def _result():
    return TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, "Bonn", None, None, None, []
    )


def _stored(*parcels):
    return {
        "version": 1,
        "minor_version": 1,
        "key": DOMAIN,
        "data": {"parcels": [p.to_dict() for p in parcels]},
    }


async def _setup(hass, hass_storage, parcels, options=None):
    hass_storage[DOMAIN] = _stored(*parcels)
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"}, options=options or {}
    )
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_result()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_parcel_sensor_names_the_tracking_page(hass, hass_storage):
    parcels = [
        Parcel(DHL, "dhl", "manual", "Oma", NOW, NOW, result=_result()),
        Parcel(ORDER, "amazon", "mail", "Buch", NOW, NOW, result=_result()),
        Parcel(
            "EBAY990000000001", "ebay", "mail", "Lampe", NOW, NOW, result=_result(),
            tracking_ref="00340999999999999902", tracking_carrier="dhl",
        ),
    ]
    await _setup(hass, hass_storage, parcels)

    assert hass.states.get(f"sensor.paket_{DHL}").attributes["tracking_url"] == DHL_URL
    # A shop order without a carrier number has no page; the attribute is there, empty.
    order = hass.states.get(f"sensor.paket_{ORDER.lower()}").attributes
    assert "tracking_url" in order and order["tracking_url"] is None
    merged = hass.states.get("sensor.paket_ebay990000000001").attributes
    assert merged["tracking_url"] == DHL_URL.replace(DHL, "00340999999999999902")


async def test_tracking_page_stays_with_hidden_names(hass, hass_storage):
    parcels = [Parcel(DHL, "dhl", "mail", "Geschenk", NOW, NOW, result=_result())]
    await _setup(hass, hass_storage, parcels, options={CONF_HIDE_NAMES: True})

    attributes = hass.states.get(f"sensor.paket_{DHL}").attributes
    assert attributes["name"] == "DHL-Paket …9901"
    # Only the number is in the link, and that is an attribute of its own anyway.
    assert attributes["tracking_url"] == DHL_URL

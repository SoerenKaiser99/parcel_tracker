from datetime import timedelta
from unittest.mock import patch

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.sensor import ParcelSensor
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
NUMBER = "00340999999999999901"


def _res(status, eta_today=False):
    today = dt_util.now().date() if eta_today else None
    return TrackingResult(
        status, "Zustellfahrzeug", today, None, None, "Bonn", None, None, None, []
    )


async def test_parcel_and_today_sensor(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.OUT_FOR_DELIVERY, eta_today=True)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": NUMBER, "name": "Oma"}, blocking=True
        )
        await hass.async_block_till_done()

    state = hass.states.get(f"sensor.paket_{NUMBER}")
    assert state.state == "out_for_delivery"
    assert state.attributes["name"] == "Oma"
    assert state.attributes["days_until"] == 0
    assert state.attributes["progress"] == 4
    assert state.attributes["friendly_name"] == "Oma"

    today = hass.states.get("sensor.pakete_heute")
    assert today.state == "1"
    assert today.attributes["parcels"][0]["name"] == "Oma"

    await hass.services.async_call(DOMAIN, "remove_parcel", {"number": NUMBER}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.paket_{NUMBER}") is None
    assert er.async_get(hass).async_get(f"sensor.paket_{NUMBER}") is None
    assert hass.states.get("sensor.pakete_heute").state == "0"


async def test_sensors_stay_available_when_refresh_fails(hass, freezer):
    """A failed coordinator update (e.g. a store save error) must not make
    the collective sensor, parcel sensors, or the calendar unavailable."""
    freezer.move_to(DAYTIME)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.OUT_FOR_DELIVERY, eta_today=True)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": NUMBER, "name": "Oma"}, blocking=True
        )
        await hass.async_block_till_done()

        coordinator = entry.runtime_data
        freezer.tick(timedelta(minutes=11))  # OUT_FOR_DELIVERY polls every 10 minutes
        with patch.object(ParcelStore, "async_save", side_effect=OSError("disk full")):
            await coordinator.async_refresh()

    assert coordinator.last_update_success is False

    today = hass.states.get("sensor.pakete_heute")
    assert today.state != "unavailable"

    parcel_state = hass.states.get(f"sensor.paket_{NUMBER}")
    assert parcel_state.state != "unavailable"

    calendar_state = hass.states.get("calendar.pakete")
    assert calendar_state.state != "unavailable"


async def test_add_parcel_builds_valid_entity_id_via_slugify(hass):
    """Entity ids are built with slugify so unexpected characters (dots,
    slashes) in a tracking number don't produce an invalid entity id."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.IN_TRANSIT)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN,
            "add_parcel",
            {"number": "JJD0003.9/7", "carrier": "dhl", "name": "Test"},
            blocking=True,
        )
        await hass.async_block_till_done()

    state = hass.states.get("sensor.paket_jjd0003_9_7")
    assert state is not None
    assert state.state == "in_transit"


async def test_ghost_sensor_removed_on_setup(hass):
    """A stale registry entry for a parcel that's no longer in the store
    (e.g. removed during the first refresh, before platforms loaded) must
    not linger as a restored, attribute-less `unavailable` sensor."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_GHOST0000000",
        config_entry=entry,
        suggested_object_id="paket_ghost0000000",
    )

    with patch(FETCH, return_value=_res(ParcelStatus.IN_TRANSIT)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id) is None


async def test_mail_parcel_sensor_shows_code_and_carrier_name(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.IN_TRANSIT)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    now = dt_util.utcnow()
    today = dt_util.now().date()
    coordinator.store.add(
        Parcel(
            "AMZ99905626221455530", "amazon", "mail", None, now, now,
            result=_res(ParcelStatus.OUT_FOR_DELIVERY, eta_today=True),
            tracking_ref="JJD000012978217606560", tracking_carrier="dhl",
            delivery_code="123456", delivery_code_day=today,
        )
    )
    coordinator.store.add(
        Parcel(
            "AMZ99991565342587125", "amazon", "mail", None, now, now,
            delivery_code="999999", delivery_code_day=today - timedelta(days=1),
        )
    )
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()

    state = hass.states.get("sensor.paket_amz99905626221455530")
    assert state.attributes["friendly_name"] == "Amazon AMZ99905626221455530"
    assert state.attributes["carrier"] == "amazon"
    assert state.attributes["tracking_ref"] == "JJD000012978217606560"
    assert state.attributes["delivery_code"] == "123456"
    expired = hass.states.get("sensor.paket_amz99991565342587125")
    assert expired.attributes["delivery_code"] is None
    assert "delivery_code" in ParcelSensor._unrecorded_attributes

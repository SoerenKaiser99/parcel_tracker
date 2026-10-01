"""Setup wires the optional 17track key; services, parcel attributes and the quota sensor."""

import pytest
import voluptuous as vol
from aioresponses import aioresponses
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker import _track17_client
from custom_components.parcel_tracker.carriers.track17 import TRACK17_URL, Track17Client
from custom_components.parcel_tracker.const import CONF_POSTCODE, CONF_TRACK17_API_KEY, DOMAIN
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.sensor import _remove_ghost_entities

NUMBER = "99999999999901"
REGISTER = f"{TRACK17_URL}/register"
QUOTA = f"{TRACK17_URL}/getquota"
QUOTA_ENTITY = "sensor.paket_tracker_17track_kontingent"
KEY = {CONF_TRACK17_API_KEY: "synthetic-17track-key"}
QUOTA_OK = {"code": 0, "data": {"quota_total": 200, "quota_used": 50, "quota_remain": 150}}
ISSUES = ("track17_auth", "track17_quota_low", "track17_quota_exhausted")


def _accepted(carrier):
    return {"code": 0, "data": {
        "accepted": [{"origin": 1, "number": NUMBER, "carrier": carrier}], "rejected": [],
    }}


def _rejected(code):
    return {"code": 0, "data": {"accepted": [], "rejected": [
        {"number": NUMBER, "error": {"code": code, "message": "synthetic"}},
    ]}}


def _res(status=ParcelStatus.IN_TRANSIT, location=None, enriched=()):
    return TrackingResult(
        status, "Unterwegs", None, None, None, location, None, None, None, [], enriched=enriched
    )


async def _setup(hass, data=None):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "", **(data or {})}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _add(entry, number=NUMBER, carrier="dpd", **kwargs):
    now = dt_util.utcnow()
    kwargs.setdefault("result", _res())
    parcel = Parcel(number, carrier, "manual", None, now, now, **kwargs)
    coordinator = entry.runtime_data
    coordinator.store.add(parcel)
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    return parcel


async def _call(hass, service, data):
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_client_only_with_a_key(hass):
    assert _track17_client(hass, MockConfigEntry(domain=DOMAIN, data={})) is None
    assert isinstance(_track17_client(hass, MockConfigEntry(domain=DOMAIN, data=KEY)),
                      Track17Client)


async def test_setup_without_key_clears_repairs_and_quota_is_unavailable(hass):
    for issue in ISSUES:
        ir.async_create_issue(
            hass, DOMAIN, issue, is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key=issue,
        )
    entry = await _setup(hass)
    assert entry.runtime_data.track17 is None
    registry = ir.async_get(hass)
    assert all(registry.async_get_issue(DOMAIN, issue) is None for issue in ISSUES)
    assert hass.states.get(QUOTA_ENTITY).state == "unavailable"


async def test_quota_sensor_counts_the_numbers_left(hass):
    entry = await _setup(hass, KEY)
    assert hass.states.get(QUOTA_ENTITY).state == "unknown"
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    state = hass.states.get(QUOTA_ENTITY)
    assert state.state == "150"
    assert (state.attributes["total"], state.attributes["used"]) == (200, 50)


async def test_quota_sensor_is_unavailable_while_the_coordinator_fails(hass):
    entry = await _setup(hass, KEY)
    coordinator = entry.runtime_data
    assert hass.states.get(QUOTA_ENTITY).state == "unknown"
    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(QUOTA_ENTITY).state == "unavailable"


async def test_track_17track_service(hass):
    entry = await _setup(hass, KEY)
    parcel = _add(entry)
    with aioresponses() as m:
        m.post(REGISTER, payload=_accepted(100007))
        m.post(QUOTA, payload=QUOTA_OK)
        await _call(hass, "track_17track", {"number": NUMBER})
    assert parcel.track17 is True


@pytest.mark.parametrize(
    ("code", "key"),
    [
        (-18019903, "track17_carrier"),
        (-18019908, "track17_quota"),
        (-18010002, "track17_auth"),
        (-18019911, "track17_unavailable"),
    ],
)
async def test_track_17track_errors(hass, code, key):
    entry = await _setup(hass, KEY)
    _add(entry)
    with aioresponses() as m:
        m.post(REGISTER, payload=_rejected(code))
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, "track_17track", {"number": NUMBER})
    assert err.value.translation_key == key


async def test_track_17track_unknown_or_delivered(hass):
    entry = await _setup(hass, KEY)
    _add(entry, result=_res(ParcelStatus.DELIVERED))
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "track_17track", {"number": NUMBER})
    assert err.value.translation_key == "track17_not_possible"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "track_17track", {"number": "99999999999999"})
    assert err.value.translation_key == "not_tracked"


async def test_track_17track_without_key(hass):
    entry = await _setup(hass)
    _add(entry)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "track_17track", {"number": NUMBER})
    assert err.value.translation_key == "track17_off"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "add_parcel", {"number": "99999999999902", "carrier": "other"})
    assert err.value.translation_key == "track17_off"


async def test_add_parcel_with_carrier_other(hass):
    entry = await _setup(hass, KEY)
    with aioresponses() as m:
        m.post(REGISTER, payload=_accepted(101070))
        m.post(QUOTA, payload=QUOTA_OK)
        await _call(hass, "add_parcel", {"number": NUMBER, "carrier": "other"})
    assert entry.runtime_data.store.get(NUMBER).carrier == "other"
    with aioresponses() as m:
        m.post(REGISTER, payload={"code": 0, "data": {"accepted": [], "rejected": [
            {"number": "99999999999902", "error": {"code": -18019903, "message": "x"}},
        ]}})
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, "add_parcel", {"number": "99999999999902", "carrier": "other"})
    assert err.value.translation_key == "track17_carrier"
    assert entry.runtime_data.store.get("99999999999902") is None
    with pytest.raises(vol.Invalid):
        await _call(hass, "add_parcel", {"number": "1", "carrier": "fedex"})


async def test_parcel_sensors_show_17track_fields(hass):
    entry = await _setup(hass, KEY)
    _add(entry, carrier="other", result=_res(location="Köln"), track17=True,
         track17_carrier=101070)
    _add(entry, "99999999999902", result=_res(location="Köln", enriched=("location",)),
         track17=True, track17_carrier=100007)
    _add(entry, "99999999999903", result=_res(location="Bonn"))
    _add(entry, "99999999999904", carrier="other", result=_res(), track17=True,
         track17_carrier=999999)
    await hass.async_block_till_done()
    other = hass.states.get(f"sensor.paket_{NUMBER}").attributes
    assert (other["friendly_name"], other["carrier_name"], other["location_source"]) == (
        f"GLS {NUMBER}", "GLS", "17track",
    )
    assert (other["track17"], other["track17_carrier"]) == (True, 101070)
    enriched = hass.states.get("sensor.paket_99999999999902").attributes
    assert (enriched["carrier_name"], enriched["location_source"]) == ("DPD", "17track")
    own = hass.states.get("sensor.paket_99999999999903").attributes
    assert (own["location_source"], own["track17"], own["track17_carrier"]) == (
        None, False, None,
    )
    unknown = hass.states.get("sensor.paket_99999999999904").attributes
    assert unknown["carrier_name"] == "17track"


async def test_ghost_cleanup_keeps_the_quota_sensor(hass):
    entry = await _setup(hass, KEY)
    _remove_ghost_entities(hass, entry.entry_id, {})
    registry = er.async_get(hass)
    assert registry.async_get(QUOTA_ENTITY) is not None
    assert registry.async_get("sensor.pakete_heute") is not None

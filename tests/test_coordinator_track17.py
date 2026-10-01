"""Coordinator: 17track registration on request, carrier 'other', quota and key repairs."""

import asyncio
from datetime import timedelta

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from custom_components.parcel_tracker.carriers.base import AuthError, CarrierUnavailable
from custom_components.parcel_tracker.carriers.track17 import (
    TRACK17_URL,
    CarrierNotDetected,
    QuotaExhausted,
    Track17Client,
    Track17Disabled,
)
from custom_components.parcel_tracker.const import DOMAIN
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.store import DuplicateParcel, ParcelStore

from .conftest import DAYTIME

NUMBER = "99999999999901"
REGISTER = f"{TRACK17_URL}/register"
QUOTA = f"{TRACK17_URL}/getquota"


def _quota(remain, total=200):
    return {"code": 0, "data": {
        "quota_total": total, "quota_used": total - remain, "quota_remain": remain,
    }}


def _accepted(number, carrier):
    return {"code": 0, "data": {
        "accepted": [{"origin": 1, "number": number, "carrier": carrier}], "rejected": [],
    }}


def _rejected(number, code):
    return {"code": 0, "data": {
        "accepted": [],
        "rejected": [{"number": number, "error": {"code": code, "message": "synthetic"}}],
    }}


def _sent(m, url):
    return [call.kwargs["json"] for call in m.requests.get(("POST", URL(url)), [])]


def _res(status=ParcelStatus.IN_TRANSIT):
    return TrackingResult(status, "Unterwegs", None, None, None, None, None, None, None, [])


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


async def _coordinator(hass, session, key="synthetic-17track-key"):
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": ""}, options={})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    client = Track17Client(session, key) if key else None
    return ParcelCoordinator(hass, entry, store, {}, None, track17=client)


def _parcel(coord, number=NUMBER, carrier="dpd", **kwargs):
    now = dt_util.utcnow()
    kwargs.setdefault("result", _res())
    parcel = Parcel(number, carrier, "manual", None, now, now, **kwargs)
    coord.store.add(parcel)
    return parcel


async def test_register_spends_one_number_and_marks_the_parcel(
    hass, session, freezer, hass_storage
):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    parcel = _parcel(coord)
    with aioresponses() as m:
        m.post(REGISTER, payload=_accepted(NUMBER, 100007))
        m.post(QUOTA, payload=_quota(150))
        await coord.async_track17(NUMBER)
        assert _sent(m, REGISTER) == [[{"number": NUMBER, "carrier": 100007}]]
    assert (parcel.track17, parcel.track17_carrier) == (True, 100007)
    assert parcel.track17_next_at == dt_util.utcnow() + timedelta(minutes=2)
    assert coord.track17_quota.remain == 150
    assert hass_storage["parcel_tracker"]["data"]["parcels"][0]["track17"] is True


async def test_already_registered_costs_nothing_and_keeps_our_code(hass, session):
    coord = await _coordinator(hass, session)
    parcel = _parcel(coord)
    with aioresponses() as m:
        m.post(REGISTER, payload=_rejected(NUMBER, -18019901))
        m.post(QUOTA, payload=_quota(150))
        await coord.async_track17(NUMBER)
    assert (parcel.track17, parcel.track17_carrier) == (True, 100007)


async def test_shop_order_registers_its_carrier_number(hass, session):
    coord = await _coordinator(hass, session)
    parcel = _parcel(
        coord, "AMZ99990000000001", "amazon",
        tracking_ref="H9999999999999999901", tracking_carrier="hermes",
    )
    with aioresponses() as m:
        m.post(REGISTER, payload=_accepted("H9999999999999999901", 100031))
        m.post(QUOTA, payload=_quota(150))
        await coord.async_track17("AMZ99990000000001")
        assert _sent(m, REGISTER) == [[{"number": "H9999999999999999901", "carrier": 100031}]]
    assert parcel.track17 is True


async def test_unknown_carrier_lets_17track_detect_it(hass, session):
    coord = await _coordinator(hass, session)
    parcel = _parcel(coord, carrier=None)
    with aioresponses() as m:
        m.post(REGISTER, payload=_accepted(NUMBER, 100007))
        m.post(QUOTA, payload=_quota(150))
        await coord.async_track17(NUMBER)
        assert _sent(m, REGISTER) == [[{"number": NUMBER}]]
    assert parcel.track17_carrier == 100007


async def test_nothing_is_spent_when_registering_makes_no_sense(hass, session):
    coord = await _coordinator(hass, session)
    _parcel(coord, "AMZ99990000000001", "amazon")
    _parcel(coord, "99999999999902", result=_res(ParcelStatus.DELIVERED))
    done = _parcel(coord, "99999999999903", track17=True, track17_carrier=100007)
    with aioresponses() as m:
        with pytest.raises(ValueError):
            await coord.async_track17("AMZ99990000000001")
        with pytest.raises(ValueError):
            await coord.async_track17("99999999999902")
        assert await coord.async_track17("99999999999903") is done
        with pytest.raises(KeyError):
            await coord.async_track17("99999999999999")
        assert not m.requests


@pytest.mark.parametrize(
    ("code", "error"), [(-18019903, CarrierNotDetected), (-18019911, CarrierUnavailable)]
)
async def test_failed_registration_leaves_the_parcel_alone(hass, session, code, error):
    coord = await _coordinator(hass, session)
    parcel = _parcel(coord)
    with aioresponses() as m:
        m.post(REGISTER, payload=_rejected(NUMBER, code))
        with pytest.raises(error):
            await coord.async_track17(NUMBER)
    assert (parcel.track17, parcel.track17_carrier, parcel.track17_next_at) == (
        False, None, None,
    )


async def test_exhausted_quota_raises_a_repair(hass, session):
    coord = await _coordinator(hass, session)
    _parcel(coord)
    with aioresponses() as m:
        m.post(REGISTER, payload=_rejected(NUMBER, -18019908))
        with pytest.raises(QuotaExhausted):
            await coord.async_track17(NUMBER)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "track17_quota_exhausted") is not None


async def test_exhausted_quota_also_refreshes_the_quota(hass, session):
    coord = await _coordinator(hass, session)
    _parcel(coord)
    with aioresponses() as m:
        m.post(REGISTER, payload=_rejected(NUMBER, -18019908))
        m.post(QUOTA, payload=_quota(0))
        with pytest.raises(QuotaExhausted):
            await coord.async_track17(NUMBER)
    assert coord.track17_quota.remain == 0


@pytest.mark.parametrize("meanwhile", ["registered", "removed"])
async def test_waiting_registration_rechecks_the_parcel(hass, session, meanwhile):
    coord = await _coordinator(hass, session)
    parcel = _parcel(coord)
    with aioresponses() as m:
        m.post(REGISTER, payload=_accepted(NUMBER, 100007), repeat=True)
        m.post(QUOTA, payload=_quota(150), repeat=True)
        async with coord._lock:
            task = asyncio.create_task(coord.async_track17(NUMBER))
            await asyncio.sleep(0)  # the call now waits for the lock
            if meanwhile == "registered":  # a concurrent call won the race
                parcel.track17, parcel.track17_carrier = True, 4242
            else:
                coord.store.remove(NUMBER)
        await task
        assert not m.requests.get(("POST", URL(REGISTER)))
    if meanwhile == "registered":
        assert parcel.track17_carrier == 4242
    else:
        assert parcel.track17 is False and coord.store.get(NUMBER) is None


async def test_rejected_key_stops_all_17track_calls_until_reload(hass, session):
    coord = await _coordinator(hass, session)
    _parcel(coord)
    with aioresponses() as m:
        m.post(REGISTER, payload=_rejected(NUMBER, -18010002))
        with pytest.raises(AuthError):
            await coord.async_track17(NUMBER)
    assert coord.track17_blocked is True
    assert ir.async_get(hass).async_get_issue(DOMAIN, "track17_auth") is not None
    with aioresponses() as m:
        with pytest.raises(AuthError):
            await coord.async_track17(NUMBER)
        await coord.async_update_quota()
        assert not m.requests


async def test_add_other_registers_before_creating_the_parcel(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.post(REGISTER, payload=_accepted(NUMBER, 101070))
        m.post(QUOTA, payload=_quota(199))
        parcel = await coord.async_add("9999 9999 9999 01", "other", "Schuhe")
        assert _sent(m, REGISTER) == [[{"number": NUMBER}]]
    assert (parcel.carrier, parcel.carrier_mode, parcel.name) == ("other", "manual", "Schuhe")
    assert (parcel.track17, parcel.track17_carrier) == (True, 101070)
    assert parcel.track17_next_at == dt_util.utcnow() + timedelta(minutes=2)
    assert (parcel.poll_target, parcel.result) == (None, None)
    assert coord.store.get(NUMBER) is parcel
    assert coord.track17_quota.remain == 199


async def test_add_other_fails_without_creating_a_parcel(hass, session):
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.post(REGISTER, payload=_rejected(NUMBER, -18019903))
        with pytest.raises(CarrierNotDetected):
            await coord.async_add(NUMBER, "other", None)
    assert coord.store.get(NUMBER) is None
    _parcel(coord)
    with aioresponses() as m:
        with pytest.raises(DuplicateParcel):
            await coord.async_add(NUMBER, "other", None)
        assert not m.requests


async def test_without_key_17track_is_off(hass, session):
    coord = await _coordinator(hass, session, key=None)
    _parcel(coord)
    with aioresponses() as m:
        with pytest.raises(Track17Disabled):
            await coord.async_track17(NUMBER)
        with pytest.raises(Track17Disabled):
            await coord.async_add("99999999999902", "other", None)
        await coord.async_update_quota()
        assert not m.requests
    assert coord.track17_quota is None


@pytest.mark.parametrize(
    ("remain", "low", "exhausted"),
    [(200, False, False), (11, False, False), (10, True, False), (1, True, False),
     (0, False, True)],
)
async def test_quota_repairs(hass, session, remain, low, exhausted):
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.post(QUOTA, payload=_quota(remain))
        await coord.async_update_quota()
    registry = ir.async_get(hass)
    assert (registry.async_get_issue(DOMAIN, "track17_quota_low") is not None) is low
    assert (registry.async_get_issue(DOMAIN, "track17_quota_exhausted") is not None) is exhausted


async def test_low_quota_repair_disappears_above_10(hass, session):
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.post(QUOTA, payload=_quota(5))
        m.post(QUOTA, payload=_quota(50, total=250))
        await coord.async_update_quota()
        issue = ir.async_get(hass).async_get_issue(DOMAIN, "track17_quota_low")
        assert issue.translation_placeholders == {"remain": "5"}
        await coord.async_update_quota()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "track17_quota_low") is None


async def test_quota_is_read_after_start_and_then_daily(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.post(QUOTA, payload=_quota(150), repeat=True)
        await coord.async_refresh()  # first refresh (setup): no 17track call
        assert not _sent(m, QUOTA)
        freezer.tick(timedelta(minutes=1))
        await coord.async_refresh()
        assert len(_sent(m, QUOTA)) == 1
        freezer.tick(timedelta(hours=23))
        await coord.async_refresh()
        assert len(_sent(m, QUOTA)) == 1
        freezer.tick(timedelta(hours=1))
        await coord.async_refresh()
        assert len(_sent(m, QUOTA)) == 2
    assert coord.track17_quota.remain == 150


async def test_unreachable_quota_is_asked_again_after_an_hour(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    await coord.async_refresh()
    with aioresponses() as m:
        m.post(QUOTA, status=503, repeat=True)
        freezer.tick(timedelta(minutes=1))
        await coord.async_refresh()
        freezer.tick(timedelta(minutes=59))
        await coord.async_refresh()
        assert len(_sent(m, QUOTA)) == 1
        freezer.tick(timedelta(minutes=1))
        await coord.async_refresh()
        assert len(_sent(m, QUOTA)) == 2
    assert coord.track17_quota is None


async def test_waiting_registration_spends_nothing_once_the_parcel_is_delivered(hass, session):
    coord = await _coordinator(hass, session)
    parcel = _parcel(coord)
    with aioresponses() as m:
        m.post(REGISTER, payload=_accepted(NUMBER, 100007), repeat=True)
        m.post(QUOTA, payload=_quota(150), repeat=True)
        async with coord._lock:
            task = asyncio.create_task(coord.async_track17(NUMBER))
            await asyncio.sleep(0)  # the call now waits for the lock
            parcel.result = _res(ParcelStatus.DELIVERED)  # a poll delivered it meanwhile
        with pytest.raises(ValueError):
            await task
        assert not m.requests.get(("POST", URL(REGISTER)))
    assert parcel.track17 is False


async def test_registering_again_clears_the_not_registered_error(hass, session):
    coord = await _coordinator(hass, session)
    parcel = _parcel(coord, carrier="other", last_error="track17_not_registered")
    other = _parcel(coord, "99999999999902", last_error="unavailable")
    with aioresponses() as m:
        m.post(REGISTER, payload=_accepted(NUMBER, 101070))
        m.post(REGISTER, payload=_accepted("99999999999902", 100007))
        m.post(QUOTA, payload=_quota(150), repeat=True)
        await coord.async_track17(NUMBER)
        await coord.async_track17("99999999999902")
    assert (parcel.track17, parcel.last_error) == (True, None)
    assert other.last_error == "unavailable"  # a carrier error is not 17track's to clear


async def test_remove_waits_for_a_running_refresh(hass, session):
    coord = await _coordinator(hass, session)
    _parcel(coord)
    async with coord._lock:
        task = asyncio.create_task(coord.async_remove(NUMBER))
        await asyncio.sleep(0)
        assert coord.store.get(NUMBER) is not None  # not under the refresh's feet
    await task
    assert coord.store.get(NUMBER) is None
    with pytest.raises(KeyError):
        await coord.async_remove(NUMBER)

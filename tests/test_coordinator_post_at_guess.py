"""A number that is only a guess at Österreichische Post (24 digits, "…AT")."""

import re
from datetime import timedelta

import aiohttp
import pytest
from aioresponses import aioresponses
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.dhl import DHL_URL, DhlCarrier
from custom_components.parcel_tracker.carriers.post_at import POST_AT_URL, PostAtCarrier
from custom_components.parcel_tracker.const import DOMAIN
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.models import ParcelStatus
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME

DHL = re.compile(rf"^{re.escape(DHL_URL)}\?")
S10 = "RR123456789AT"
NOT_FOUND = {
    "errors": [{"extensions": {"code": "INVALID_ARGUMENT_IDENTITY_CODE"}}],
    "data": None,
}


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


async def _coordinator(hass, carriers):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    return ParcelCoordinator(hass, entry, store, carriers)


def _count(mock, url) -> int:
    return sum(len(calls) for (method, u), calls in mock.requests.items() if str(u).startswith(url))


async def test_guess_post_does_not_know_falls_back_to_dhl(hass, session, freezer):
    freezer.move_to(DAYTIME)
    status = {"timestamp": "2026-09-29T08:00:00+02:00", "statusCode": "transit", "status": "x"}
    coord = await _coordinator(
        hass, {"dhl": DhlCarrier(session, "key"), "post_at": PostAtCarrier(session)}
    )
    with aioresponses() as m:
        m.post(POST_AT_URL, payload=NOT_FOUND, repeat=True)
        m.get(DHL, payload={"shipments": [{"id": S10, "status": status}]}, repeat=True)
        parcel = await coord.async_add(S10, "auto", None)
        assert _count(m, POST_AT_URL) == 1 and _count(m, DHL_URL) == 1
    assert (parcel.carrier, parcel.status) == ("dhl", ParcelStatus.IN_TRANSIT)


async def test_guess_nobody_knows_is_asked_once(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"post_at": PostAtCarrier(session)})
    with aioresponses() as m:
        m.post(POST_AT_URL, payload=NOT_FOUND, repeat=True)
        parcel = await coord.async_add(S10, "auto", None)
        assert (parcel.carrier, parcel.last_error) == (None, "carrier_not_found")
        for _ in range(3):  # the hourly look costs no further call
            freezer.tick(timedelta(hours=1, minutes=1))
            await coord.async_refresh()
        assert _count(m, POST_AT_URL) == 1


async def test_sure_post_number_is_not_sent_to_dhl(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(
        hass, {"dhl": DhlCarrier(session, "key"), "post_at": PostAtCarrier(session)}
    )
    with aioresponses() as m:
        m.post(POST_AT_URL, payload=NOT_FOUND, repeat=True)
        m.get(DHL, status=404, repeat=True)
        parcel = await coord.async_add("1099999999999999012301", "auto", None)
        assert _count(m, DHL_URL) == 0
    assert parcel.last_error == "not_found"

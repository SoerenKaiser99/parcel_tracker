"""v0.3.17: DHL's estimate between polls and DHL as the last candidate of "Automatisch"
(HTTP mocked, invented numbers and answers)."""

import re
from datetime import date, datetime, timedelta
from unittest.mock import patch

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.base import BERLIN, Carrier, Match, NotFound
from custom_components.parcel_tracker.carriers.dhl import DHL_URL, DhlCarrier
from custom_components.parcel_tracker.const import DOMAIN
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME

DHL = re.compile(rf"^{re.escape(DHL_URL)}\?")
EXPRESS = "9999999901"  # ten digits: no rule of this integration takes it
TODAY = date(2026, 9, 29)  # the day of DAYTIME
FROM = datetime(2026, 9, 29, 14, 0, tzinfo=BERLIN)
TO = datetime(2026, 9, 29, 16, 0, tzinfo=BERLIN)


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


def _answer(text="Die Sendung wurde im Start-Paketzentrum bearbeitet.") -> dict:
    status = {"timestamp": "2026-09-29T08:00:00+02:00", "statusCode": "transit", "status": text}
    return {"shipments": [{"id": EXPRESS, "service": "express", "status": status}]}


def _calls(mock: aioresponses) -> list[dict]:
    """The query of every request made (aioresponses groups them by URL)."""
    return [dict(url.query) for (_, url), calls in mock.requests.items() for _ in calls]


def _issues(hass) -> list[str]:
    return sorted(issue_id for _, issue_id in ir.async_get(hass).issues)


# ----- "Automatisch": DHL as the last candidate -----


async def test_unmatched_number_is_asked_at_dhl_when_a_key_is_set(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"dhl": DhlCarrier(session, "key")})
    with aioresponses() as m:
        m.get(DHL, payload=_answer(), repeat=True)
        parcel = await coord.async_add("99 9999 9901", "auto", "Express")
        assert _calls(m) == [{"trackingNumber": EXPRESS, "language": "de"}]  # no "service"
        assert (parcel.carrier, parcel.carrier_mode) == ("dhl", "auto")
        assert (parcel.status, parcel.last_error) == (ParcelStatus.IN_TRANSIT, None)
        # From now on an ordinary DHL parcel on the ordinary schedule.
        freezer.tick(parcel.next_poll_at - dt_util.utcnow() + timedelta(seconds=1))
        await coord.async_refresh()
        assert len(_calls(m)) == 2
    assert coord.diagnostics()["dhl_calls_today"] == 2


async def test_number_dhl_does_not_know_stays_unknown_and_is_asked_once(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"dhl": DhlCarrier(session, "key")})
    with aioresponses() as m:
        m.get(DHL, status=404, repeat=True)
        parcel = await coord.async_add(EXPRESS, "auto", None)
        assert len(_calls(m)) == 1
        assert (parcel.carrier, parcel.status) == (None, None)
        assert (parcel.last_error, parcel.error_streak) == ("carrier_not_found", 0)
        assert parcel.next_poll_at - parcel.last_poll_at == timedelta(hours=1)
        for _ in range(5):  # the hourly look at an unknown number costs no call
            freezer.tick(timedelta(hours=1, minutes=1))
            await coord.async_refresh()
        await coord.async_refresh_parcels(EXPRESS)  # "Aktualisieren" neither
        await coord.async_refresh_parcels(None)
        assert len(_calls(m)) == 1
    assert (parcel.carrier, parcel.last_error) == (None, "carrier_not_found")
    assert _issues(hass) == []


async def test_without_a_key_nothing_is_asked(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"dhl": DhlCarrier(session, None)})
    with aioresponses() as m:
        parcel = await coord.async_add(EXPRESS, "auto", None)
        freezer.tick(timedelta(hours=1, minutes=1))
        await coord.async_refresh()
        assert _calls(m) == []
    assert (parcel.carrier, parcel.last_error) == (None, "carrier_not_found")
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(hours=1)
    assert _issues(hass) == []


async def test_unknown_parcel_from_an_older_version_is_not_asked(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"dhl": DhlCarrier(session, "key")})
    now = dt_util.utcnow()
    coord.store.add(
        Parcel(EXPRESS, None, "auto", None, now, now, last_error="carrier_not_found")
    )
    with aioresponses() as m:
        await coord.async_refresh()
        await coord.async_refresh_parcels(EXPRESS)
        assert _calls(m) == []


async def test_dhl_out_of_reach_at_add_time_is_asked_again_but_only_a_few_times(
    hass, session, freezer
):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"dhl": DhlCarrier(session, "key")})
    with aioresponses() as m:
        m.get(DHL, status=503)
        parcel = await coord.async_add(EXPRESS, "auto", None)
        assert (parcel.carrier, parcel.last_error) == (None, "unavailable")
        assert parcel.next_poll_at - parcel.last_poll_at == timedelta(minutes=5)
        m.get(DHL, status=404)
        freezer.tick(timedelta(minutes=6))
        await coord.async_refresh()
        assert len(_calls(m)) == 2
        assert (parcel.carrier, parcel.last_error) == (None, "carrier_not_found")
        freezer.tick(timedelta(hours=2))
        await coord.async_refresh()
        assert len(_calls(m)) == 2
    assert _issues(hass) == []


@pytest.mark.parametrize(
    "failure",
    [{"status": 503}, {"status": 429, "headers": {"Retry-After": "60"}}, {"status": 401}],
    ids=["unavailable", "rate_limited", "auth"],
)
async def test_a_dhl_that_keeps_failing_is_asked_three_times_at_most(
    hass, session, freezer, failure
):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"dhl": DhlCarrier(session, "key")})
    # A rejected key starts the reauth flow: not for real here (it would outlive the test).
    with aioresponses() as m, patch.object(coord.entry, "async_start_reauth") as reauth:
        m.get(DHL, repeat=True, **failure)
        parcel = await coord.async_add(EXPRESS, "auto", None)
        for _ in range(8):
            freezer.tick(timedelta(hours=3))
            await coord.async_refresh()
        assert len(_calls(m)) == 3
    assert (parcel.carrier, parcel.last_error) == (None, "carrier_not_found")
    assert not [i for i in _issues(hass) if i.startswith("carrier_broken")]
    assert reauth.called is (failure["status"] == 401)


class Other(Carrier):
    """A carrier whose rule takes the number but that does not know it."""

    key = "gls"
    name = "GLS"

    @staticmethod
    def matches(number):
        return Match.POSSIBLE if len(number) == 11 else Match.NO

    async def fetch(self, number, postcode):
        raise NotFound(number)


async def test_dhl_is_no_fallback_for_numbers_another_carrier_takes(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"dhl": DhlCarrier(session, "key"), "gls": Other()})
    with aioresponses() as m:
        parcel = await coord.async_add("99999999902", "auto", None)
        assert (parcel.carrier, parcel.last_error) == (None, "not_found")
        with pytest.raises(ValueError):
            await coord.async_add("TBA999999999901", "auto", None)  # Amazon: as before
        assert _calls(m) == []


async def test_found_dhl_parcel_that_vanishes_is_an_ordinary_not_found(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"dhl": DhlCarrier(session, "key")})
    with aioresponses() as m:
        m.get(DHL, payload=_answer())
        parcel = await coord.async_add(EXPRESS, "auto", None)
        m.get(DHL, status=404, repeat=True)
        freezer.tick(parcel.next_poll_at - dt_util.utcnow() + timedelta(seconds=1))
        await coord.async_refresh()
        assert (parcel.carrier, parcel.last_error) == ("dhl", "not_found")
        assert parcel.next_poll_at - parcel.last_poll_at == timedelta(hours=1)
        freezer.tick(timedelta(hours=1, minutes=1))
        await coord.async_refresh()
        assert len(_calls(m)) == 3  # assigned to DHL: the normal not-found schedule


# ----- an estimate DHL takes back between two polls -----


class Dhl(Carrier):
    """DHL lookup answering whatever the test sets."""

    key = "dhl"
    name = "DHL"

    def __init__(self):
        self.answer: TrackingResult | None = None

    @staticmethod
    def matches(number):
        return Match.SURE

    async def fetch(self, number, postcode):
        return self.answer


def _result(status, day=None, start=None, end=None) -> TrackingResult:
    return TrackingResult(status, "x", day, start, end, None, None, None, None, [])


async def _tracked(hass, freezer, first: TrackingResult):
    freezer.move_to(DAYTIME)
    dhl = Dhl()
    dhl.answer = first
    coord = await _coordinator(hass, {"dhl": dhl})
    parcel = await coord.async_add("00340999999999999901", "auto", None)
    return coord, dhl, parcel


async def _next(coord, parcel, freezer, wait=timedelta(0)):
    freezer.tick(max(parcel.next_poll_at - dt_util.utcnow(), wait) + timedelta(seconds=1))
    await coord.async_refresh()
    r = parcel.result
    return r.eta_date, r.eta_from, r.eta_to


async def test_estimate_dhl_takes_back_stays_for_its_day(hass, freezer):
    coord, dhl, parcel = await _tracked(
        hass, freezer, _result(ParcelStatus.OUT_FOR_DELIVERY, TODAY, FROM, TO)
    )
    dhl.answer = _result(ParcelStatus.OUT_FOR_DELIVERY)
    assert await _next(coord, parcel, freezer) == (TODAY, FROM, TO)
    assert await _next(coord, parcel, freezer) == (TODAY, FROM, TO)  # also a second time
    # DHL computes it anew: its answer counts.
    later = FROM + timedelta(hours=2)
    dhl.answer = _result(ParcelStatus.OUT_FOR_DELIVERY, TODAY, later, None)
    assert await _next(coord, parcel, freezer) == (TODAY, later, None)


async def test_window_stays_when_dhl_only_repeats_the_same_day(hass, freezer):
    coord, dhl, parcel = await _tracked(
        hass, freezer, _result(ParcelStatus.OUT_FOR_DELIVERY, TODAY, FROM, TO)
    )
    dhl.answer = _result(ParcelStatus.OUT_FOR_DELIVERY, TODAY)
    assert await _next(coord, parcel, freezer) == (TODAY, FROM, TO)
    # Another day: the old window belongs to the old day.
    tomorrow = TODAY + timedelta(days=1)
    dhl.answer = _result(ParcelStatus.IN_TRANSIT, tomorrow)
    assert await _next(coord, parcel, freezer) == (tomorrow, None, None)


@pytest.mark.parametrize(
    "status",
    [ParcelStatus.DELIVERED, ParcelStatus.AWAITING_PICKUP, ParcelStatus.EXCEPTION],
)
async def test_estimate_is_not_kept_once_the_parcel_is_no_longer_on_its_way(
    hass, freezer, status
):
    coord, dhl, parcel = await _tracked(
        hass, freezer, _result(ParcelStatus.OUT_FOR_DELIVERY, TODAY, FROM, TO)
    )
    dhl.answer = _result(status)
    assert await _next(coord, parcel, freezer) == (None, None, None)


async def test_estimate_is_not_kept_once_its_day_is_over(hass, freezer):
    await hass.config.async_set_time_zone("Europe/Berlin")  # "today" is Home Assistant's
    tomorrow = TODAY + timedelta(days=1)
    coord, dhl, parcel = await _tracked(hass, freezer, _result(ParcelStatus.IN_TRANSIT, tomorrow))
    dhl.answer = _result(ParcelStatus.IN_TRANSIT)
    assert await _next(coord, parcel, freezer) == (tomorrow, None, None)  # a day ahead stays
    # 23:30 in Berlin on that day: still kept; half an hour later it is yesterday's.
    freezer.move_to(datetime(2026, 9, 30, 23, 30, tzinfo=BERLIN))
    await coord.async_refresh()
    assert parcel.result.eta_date == tomorrow
    freezer.move_to(datetime(2026, 10, 1, 0, 30, tzinfo=BERLIN))
    await coord.async_refresh()
    assert parcel.last_poll_at == dt_util.utcnow()
    assert parcel.result.eta_date is None

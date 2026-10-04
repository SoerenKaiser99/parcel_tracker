"""Coordinator with the UPS API (budget, auth issue), mail-only UPS and ETA keeping."""

from datetime import UTC, date, datetime, timedelta

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.base import (
    BERLIN,
    Carrier,
    CarrierUnavailable,
    Match,
    NotFound,
    ParseError,
    RateLimited,
)
from custom_components.parcel_tracker.carriers.ups import (
    UPS_TOKEN_URL,
    UPS_TRACK_URL,
    UpsCarrier,
)
from custom_components.parcel_tracker.const import DOMAIN
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME, load_fixture

NUMBER = "1Z999AA10123456784"
TRACK = f"{UPS_TRACK_URL}/{NUMBER}?locale=de_DE"


def _body(name: str) -> dict:
    return load_fixture(name)["response"]


async def _coordinator(hass, carriers_factory):
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"}, options={})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    return ParcelCoordinator(hass, entry, store, carriers_factory(store))


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


def _ups(session, limit=100):
    return lambda store: {"ups": UpsCarrier(session, "id", "secret", store.ups_budget, limit)}


async def test_ups_parcel_is_polled_sparingly(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, _ups(session))
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_body("ups_synthetic_token.json"))
        m.get(TRACK, payload=_body("ups_synthetic_in_transit.json"))
        parcel = await coord.async_add(NUMBER, "auto", None)
    assert (parcel.carrier, parcel.status) == ("ups", ParcelStatus.IN_TRANSIT)
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(hours=4)
    assert coord.store.ups_budget.count == 1


async def test_budget_exhausted_waits_for_next_month_and_raises_issue(hass, session, freezer):
    freezer.move_to(DAYTIME)  # 29 September
    coord = await _coordinator(hass, _ups(session, limit=1))
    registry = ir.async_get(hass)
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_body("ups_synthetic_token.json"), repeat=True)
        m.get(TRACK, payload=_body("ups_synthetic_in_transit.json"), repeat=True)
        await coord.async_add(NUMBER, "auto", None)
        await coord.async_refresh_parcels(NUMBER)  # manual refresh: would be the 2nd call
        parcel = coord.store.get(NUMBER)
        assert parcel.last_error == "ups_budget"
        assert parcel.status is ParcelStatus.IN_TRANSIT
        assert parcel.next_poll_at == datetime(2026, 10, 1, tzinfo=BERLIN)
        assert registry.async_get_issue(DOMAIN, "ups_budget") is not None
        freezer.move_to("2026-10-01 06:00:00+00:00")  # 08:00 Berlin, new month
        await coord.async_refresh()
    assert registry.async_get_issue(DOMAIN, "ups_budget") is None
    assert parcel.last_error is None
    assert (coord.store.ups_budget.month, coord.store.ups_budget.count) == ("2026-10", 1)


async def test_rejected_ups_credentials_raise_ups_auth_issue(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, _ups(session))
    registry = ir.async_get(hass)
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, status=401, payload={})
        parcel = await coord.async_add(NUMBER, "ups", None)
    assert parcel.last_error == "auth"
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(hours=4)
    assert registry.async_get_issue(DOMAIN, "ups_auth") is not None
    assert registry.async_get_issue(DOMAIN, "dhl_auth") is None
    with aioresponses() as m:  # no UPS call at all until the integration reloads
        await coord.async_refresh_parcels(NUMBER)
        assert not m.requests
    assert parcel.last_error == "auth"
    assert registry.async_get_issue(DOMAIN, "ups_auth") is not None
    # A reload builds a new UPS client (e.g. after new credentials in the options).
    coord.carriers["ups"] = UpsCarrier(session, "id", "secret", coord.store.ups_budget, 100)
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_body("ups_synthetic_token.json"))
        m.get(TRACK, payload=_body("ups_synthetic_delivered.json"))
        await coord.async_refresh_parcels(NUMBER)
    assert parcel.status is ParcelStatus.DELIVERED
    assert registry.async_get_issue(DOMAIN, "ups_auth") is None


async def test_ups_without_api_is_added_as_mail_only(hass):
    coord = await _coordinator(hass, lambda store: {})
    parcel = await coord.async_add(NUMBER, "auto", None)
    assert (parcel.carrier, parcel.carrier_mode) == ("ups", "auto")
    # Never asked, and marked like a DHL parcel without key: the card says so (v0.3.14).
    assert (parcel.last_error, parcel.last_poll_at, parcel.next_poll_at) == (
        "missing_key", None, None,
    )
    other = await coord.async_add("1Z999AA10123456785", "ups", "Schuhe")
    assert (other.carrier, other.carrier_mode, other.last_error) == (
        "ups", "manual", "missing_key",
    )
    with pytest.raises(ValueError):
        await coord.async_add("H9999999999999999901", "hermes", None)


async def test_ups_credentials_entered_later_replace_the_missing_key_marker(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, lambda store: {})
    parcel = await coord.async_add(NUMBER, "ups", None)
    assert parcel.last_error == "missing_key"
    await coord.async_refresh()  # still no API: not asked, the marker stays
    assert (parcel.last_error, parcel.last_poll_at) == ("missing_key", None)
    coord.carriers["ups"] = UpsCarrier(session, "id", "secret", coord.store.ups_budget, 100)
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_body("ups_synthetic_token.json"))
        m.get(TRACK, payload=_body("ups_synthetic_in_transit.json"))
        await coord.async_refresh()
    assert (parcel.last_error, parcel.status) == (None, ParcelStatus.IN_TRANSIT)


class NoEtaCarrier(Carrier):
    name = "NoEta"

    def __init__(self, key="hermes"):
        self.key = key
        self.status = ParcelStatus.IN_TRANSIT

    @staticmethod
    def matches(number):
        return Match.SURE

    async def fetch(self, number, postcode):
        return TrackingResult(self.status, "x", None, None, None, None, None, None, None, [])


def _known_day() -> TrackingResult:
    return TrackingResult(
        ParcelStatus.PRE_TRANSIT, "Angekündigt", date(2026, 10, 1), None, None, None, None,
        None, None, [], eta_latest=date(2026, 10, 2),
    )


async def test_hermes_answer_without_day_keeps_the_mail_day(hass, freezer):
    freezer.move_to(DAYTIME)
    hermes = NoEtaCarrier("hermes")
    coord = await _coordinator(hass, lambda store: {"hermes": hermes})
    now = dt_util.utcnow()
    number = "H9999999999999999901"
    coord.store.add(Parcel(number, "hermes", "mail", None, now, now, result=_known_day()))
    await coord.async_refresh()
    parcel = coord.store.get(number)
    assert parcel.status is ParcelStatus.IN_TRANSIT
    assert (parcel.result.eta_date, parcel.result.eta_latest) == (
        date(2026, 10, 1),
        date(2026, 10, 2),
    )
    hermes.status = ParcelStatus.DELIVERED
    freezer.tick(timedelta(minutes=31))
    await coord.async_refresh()
    assert parcel.result.eta_date is None


async def test_other_carrier_without_day_drops_the_mail_day(hass, freezer):
    freezer.move_to(DAYTIME)
    dhl = NoEtaCarrier("dhl")
    coord = await _coordinator(hass, lambda store: {"dhl": dhl})
    now = dt_util.utcnow()
    number = "JJD000012978217606560"
    coord.store.add(Parcel(number, "dhl", "mail", None, now, now, result=_known_day()))
    await coord.async_refresh()
    parcel = coord.store.get(number)
    assert parcel.status is ParcelStatus.IN_TRANSIT
    assert (parcel.result.eta_date, parcel.result.eta_latest) == (None, None)


async def test_night_rule_uses_ups_intervals(hass, session, freezer):
    freezer.move_to(datetime(2026, 9, 29, 22, 30, tzinfo=UTC))  # 00:30 Berlin
    coord = await _coordinator(hass, _ups(session))
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_body("ups_synthetic_token.json"))
        m.get(TRACK, payload=_body("ups_synthetic_out_for_delivery.json"))
        parcel = await coord.async_add(NUMBER, "auto", None)
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(minutes=60)


class CountingUps(Carrier):
    """Fake UPS API: counts calls, answers with a fixed result or error."""

    key = "ups"
    name = "UPS"

    def __init__(self, error=None, status=ParcelStatus.IN_TRANSIT):
        self.calls = 0
        self.error = error
        self.status = status

    @staticmethod
    def matches(number):
        return Match.SURE if number.startswith("1Z") else Match.NO

    async def fetch(self, number, postcode):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return TrackingResult(self.status, "x", None, None, None, None, None, None, None, [])


async def _simulate_day(coord, freezer, step=timedelta(minutes=10)):
    for _ in range(int(timedelta(hours=24) / step) - 1):
        freezer.tick(step)
        await coord.async_refresh()


@pytest.mark.parametrize(
    "error",
    [
        NotFound("not yet"),
        CarrierUnavailable("HTTP 503"),
        ParseError("odd"),
        RateLimited(60),
    ],
    ids=["not_found", "unavailable", "parse_error", "rate_limited"],
)
async def test_ups_errors_never_poll_faster_than_every_4_hours(hass, freezer, error):
    freezer.move_to(DAYTIME)
    ups = CountingUps(error)
    coord = await _coordinator(hass, lambda store: {"ups": ups})
    parcel = await coord.async_add(NUMBER, "auto", None)
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(hours=4)
    await _simulate_day(coord, freezer)
    assert ups.calls == 6  # 0 h, 4 h, … 20 h (night rule never shortens it)


async def test_ups_out_for_delivery_with_errors_polls_every_30_minutes(hass, freezer):
    freezer.move_to(DAYTIME)  # 12:00 Berlin
    ups = CountingUps(status=ParcelStatus.OUT_FOR_DELIVERY)
    coord = await _coordinator(hass, lambda store: {"ups": ups})
    await coord.async_add(NUMBER, "auto", None)
    ups.error = CarrierUnavailable("HTTP 500")
    for _ in range(5):  # 12:10 … 12:50 Berlin: backoff (5, 10 min) would be sooner
        freezer.tick(timedelta(minutes=10))
        await coord.async_refresh()
    assert ups.calls == 2  # 12:00 and 12:30


async def test_ups_auth_error_stops_all_calls_until_reload(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, _ups(session))
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_body("ups_synthetic_token.json"), repeat=True)
        m.get(TRACK, status=401, repeat=True)
        parcel = await coord.async_add(NUMBER, "auto", None)
        await coord.async_add("1Z999AA10123456785", "ups", None)
        await _simulate_day(coord, freezer, timedelta(minutes=30))
        await coord.async_refresh_parcels(None)
        track_calls = sum(len(v) for (method, _), v in m.requests.items() if method == "GET")
    assert track_calls == 2  # the first call and its one retry after a new token
    assert coord.store.ups_budget.count == 2
    assert parcel.last_error == "auth"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "ups_auth") is not None


async def test_raised_budget_polls_waiting_parcels_on_the_next_tick(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, _ups(session, limit=1))
    coord.store.ups_budget.spend(dt_util.utcnow())
    now = dt_util.utcnow()
    waiting = datetime(2026, 10, 1, tzinfo=BERLIN)
    parcel = Parcel(NUMBER, "ups", "manual", None, now, now, last_error="ups_budget",
                    next_poll_at=waiting)
    coord.store.add(parcel)
    with aioresponses() as m:
        await coord.async_refresh()
        assert not m.requests
    assert parcel.next_poll_at == waiting  # still used up
    # Reload after raising the budget in the options: a new client with a larger limit.
    coord.carriers["ups"] = UpsCarrier(session, "id", "secret", coord.store.ups_budget, 5)
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_body("ups_synthetic_token.json"))
        m.get(TRACK, payload=_body("ups_synthetic_in_transit.json"))
        await coord.async_refresh()
    assert (parcel.last_error, parcel.status) == (None, ParcelStatus.IN_TRANSIT)
    assert coord.store.ups_budget.count == 2
    assert ir.async_get(hass).async_get_issue(DOMAIN, "ups_budget") is None

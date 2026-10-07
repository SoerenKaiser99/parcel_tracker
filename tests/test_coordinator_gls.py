"""Coordinator and services with the real GLS carrier (HTTP mocked, synthetic answers)."""

import copy
import re
from datetime import date, datetime, timedelta
from unittest.mock import patch

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.carriers.dhl import DHL_URL, DhlCarrier
from custom_components.parcel_tracker.carriers.gls import GLS_URL, GlsCarrier
from custom_components.parcel_tracker.carriers.track17 import TRACK17_URL, Track17Client
from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.store import DuplicateParcel, ParcelStore

from .conftest import DAYTIME, load_fixture

NUMBER = "99999999902"
DETAIL = re.compile(rf"^{re.escape(GLS_URL)}/rstt028/")
SEARCH = re.compile(rf"^{re.escape(GLS_URL)}/rstt029\?")
FETCH = "custom_components.parcel_tracker.carriers.gls.GlsCarrier.fetch"


def _search(status="INDELIVERY", arrival=True) -> dict:
    data = copy.deepcopy(load_fixture("gls_synthetic_search.json")["response"])
    data["tuStatus"][0]["progressBar"]["statusInfo"] = status
    if not arrival:
        del data["tuStatus"][0]["arrivalTime"]
    return data


def _detail(status="DELIVERED") -> dict:
    data = copy.deepcopy(load_fixture("gls_synthetic_detail.json")["response"])
    data["progressBar"]["statusInfo"] = status
    return data


def _urls(mock: aioresponses) -> list[str]:
    return [str(url) for _, url in mock.requests]


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


async def _coordinator(hass, session, data=None, options=None, track17=None):
    entry = MockConfigEntry(domain=DOMAIN, data=data or {}, options=options or {})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    carriers = {"gls": GlsCarrier(session)}
    return ParcelCoordinator(hass, entry, store, carriers, None, track17=track17)


async def test_eleven_digits_become_a_gls_parcel_asked_every_30_minutes(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.get(SEARCH, payload=_search())
        parcel = await coord.async_add("999 9999-9902", "auto", None)
    assert (parcel.number, parcel.carrier, parcel.carrier_mode) == (NUMBER, "gls", "auto")
    assert parcel.status is ParcelStatus.OUT_FOR_DELIVERY
    # Out for delivery: other carriers are asked every 10 minutes, GLS never below 30.
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(minutes=30)


async def test_track_id_needs_the_manual_carrier_choice(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        parcel = await coord.async_add("zabcd123", "auto", None)
        assert (parcel.carrier, parcel.last_error) == (None, "carrier_not_found")
        assert _urls(m) == []
        await coord.async_remove("ZABCD123")
        m.get(SEARCH, payload=_search("INTRANSIT"))
        parcel = await coord.async_add("zabcd123", "gls", "Schuhe")
        assert "match=ZABCD123" in _urls(m)[0]
    assert (parcel.number, parcel.carrier, parcel.carrier_mode) == ("ZABCD123", "gls", "manual")
    assert parcel.status is ParcelStatus.IN_TRANSIT


@pytest.mark.parametrize(
    ("data", "options", "endpoint"),
    [
        ({CONF_POSTCODE: "10115"}, {}, "rstt028"),
        ({}, {CONF_POSTCODE: "10115"}, "rstt028"),
        ({CONF_POSTCODE: "10115"}, {CONF_POSTCODE: ""}, "rstt029"),  # postcode removed later
        ({}, {}, "rstt029"),
    ],
)
async def test_postcode_setting_chooses_the_endpoint(hass, session, data, options, endpoint):
    coord = await _coordinator(hass, session, data, options)
    with aioresponses() as m:
        m.get(DETAIL, payload=_detail())
        m.get(SEARCH, payload=_search())
        parcel = await coord.async_add(NUMBER, "gls", None)
        [url] = _urls(m)
    assert f"/{endpoint}" in url
    assert ("postalCode=10115" in url) is (endpoint == "rstt028")
    assert len(parcel.result.events) == (6 if endpoint == "rstt028" else 0)


async def test_mail_day_stays_until_gls_names_one(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    day = date(2026, 10, 1)
    window = (
        datetime(2026, 10, 1, 10, 0, tzinfo=BERLIN),
        datetime(2026, 10, 1, 12, 30, tzinfo=BERLIN),
    )
    mail = MailUpdate(
        NUMBER, "gls", ParcelStatus.IN_TRANSIT, datetime(2026, 9, 29, 9, 0, tzinfo=BERLIN),
        eta_date=day, eta_from=window[0], eta_to=window[1],
    )
    apply_update(coord.store.parcels, mail, dt_util.utcnow())
    parcel = coord.store.get(NUMBER)
    assert (parcel.carrier, parcel.result.status_text) == ("gls", "Unterwegs")

    with aioresponses() as m:
        # GLS answers without a day: the mail's day and window stay.
        m.get(SEARCH, payload=_search("INTRANSIT", arrival=False))
        await coord.async_refresh()
        r = parcel.result
        assert r.status_text == "Das Paket wird voraussichtlich im Laufe des Tages zugestellt."
        assert (r.eta_date, r.eta_from, r.eta_to) == (day, *window)

        # GLS names a day itself: it wins.
        m.get(SEARCH, payload=_search("INDELIVERY"))
        freezer.tick(timedelta(minutes=31))
        await coord.async_refresh()
        r = parcel.result
        assert r.status is ParcelStatus.OUT_FOR_DELIVERY
        assert (r.eta_date, r.eta_from) == (
            date(2026, 9, 30), datetime(2026, 9, 30, 10, 0, tzinfo=BERLIN),
        )

        # Delivered: no day is carried over any more.
        m.get(SEARCH, payload=_search("DELIVERED", arrival=False))
        freezer.tick(timedelta(minutes=31))
        await coord.async_refresh()
        r = parcel.result
        assert (r.status, r.eta_date, r.delivered_at) == (
            ParcelStatus.DELIVERED, None, dt_util.utcnow(),
        )
    assert parcel.next_poll_at is None


async def test_closed_lookup_raises_carrier_broken_gls_after_24h(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session, {CONF_POSTCODE: "10115"})
    registry = ir.async_get(hass)
    with aioresponses() as m:
        m.get(DETAIL, payload=_detail("INTRANSIT"))
        parcel = await coord.async_add(NUMBER, "gls", None)
    with aioresponses() as m:
        closed = {"Location": "https://example.org/register-api-access"}
        m.get(DETAIL, status=303, headers=closed, repeat=True)
        for _ in range(30):
            freezer.tick(timedelta(hours=1))
            await coord.async_refresh()
    issue = registry.async_get_issue(DOMAIN, "carrier_broken_gls")
    assert issue is not None and issue.translation_placeholders == {"carrier": "GLS"}
    assert (parcel.last_error, parcel.status) == ("unavailable", ParcelStatus.IN_TRANSIT)
    with aioresponses() as m:
        m.get(DETAIL, payload=_detail("INTRANSIT"))
        freezer.tick(timedelta(hours=2))
        await coord.async_refresh()
    assert registry.async_get_issue(DOMAIN, "carrier_broken_gls") is None
    assert parcel.last_error is None


async def test_blocked_lookup_waits_an_hour_without_a_repair(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.get(SEARCH, status=403, body="<html>blocked</html>")
        parcel = await coord.async_add(NUMBER, "gls", None)
    assert parcel.last_error == "rate_limited"
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(hours=1)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "carrier_broken_gls") is None


NIGHT = "2026-09-29 21:30:00+00:00"  # 23:30 in Berlin


@pytest.mark.parametrize("start", [DAYTIME, NIGHT], ids=["day", "night"])
@pytest.mark.parametrize("mode", ["gls", "auto"])
@pytest.mark.parametrize(
    "answer",
    [
        {"status": 503, "body": "<html>maintenance</html>"},
        {"payload": {"tuStatus": "unexpected"}},
        {"status": 404, "payload": {"lastError": "E206"}},
        {"status": 429, "headers": {"Retry-After": "5"}, "body": "slow down"},
        {"status": 429, "headers": {"Retry-After": "0"}, "body": "slow down"},
        {"exception": aiohttp.ClientConnectionError("down")},
        {"exception": RuntimeError("bug")},
    ],
    ids=["unavailable", "parse_error", "not_found", "retry_5s", "retry_0s", "network", "bug"],
)
async def test_gls_is_never_asked_again_within_30_minutes_after_an_error(
    hass, session, freezer, start, mode, answer
):
    freezer.move_to(start)
    coord = await _coordinator(hass, session)
    asked: list[datetime] = []
    with aioresponses() as m:
        m.get(SEARCH, repeat=True, **answer)
        parcel = await coord.async_add(NUMBER, mode, None)
        assert parcel.last_error is not None
        for _ in range(6 * 60 + 1):  # six hours, minute by minute
            count = sum(len(calls) for calls in m.requests.values())
            if count > len(asked):
                assert count == len(asked) + 1
                asked.append(dt_util.utcnow())
            freezer.tick(timedelta(minutes=1))
            await coord.async_refresh()
    gaps = [later - earlier for earlier, later in zip(asked, asked[1:], strict=False)]
    assert len(asked) >= 2  # it does keep asking
    assert min(gaps) >= timedelta(minutes=30)
    assert len(asked) <= 13  # at most one request per 30 minutes over six hours


async def test_absurd_retry_after_waits_a_day_at_most(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.get(SEARCH, status=429, headers={"Retry-After": "9" * 400}, body="slow down")
        parcel = await coord.async_add(NUMBER, "gls", None)
    assert parcel.last_error == "rate_limited"
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(hours=24)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("NOTDELIVERED", ParcelStatus.EXCEPTION),
        ("RETURNED", ParcelStatus.EXCEPTION),
        ("DELIVEREDPS", ParcelStatus.AWAITING_PICKUP),
    ],
)
async def test_day_is_not_carried_into_an_exception_or_a_pickup(
    hass, session, freezer, code, status
):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.get(SEARCH, payload=_search("INDELIVERY"))  # names day and window itself
        parcel = await coord.async_add(NUMBER, "gls", None)
        assert parcel.result.eta_date == date(2026, 9, 30)
        assert parcel.result.eta_from is not None

        # Still on its way without a day in the answer: the earlier lookup's day stays.
        m.get(SEARCH, payload=_search("INDELIVERY", arrival=False))
        freezer.tick(timedelta(minutes=31))
        await coord.async_refresh()
        assert parcel.result.eta_date == date(2026, 9, 30)

        m.get(SEARCH, payload=_search(code, arrival=False))
        freezer.tick(timedelta(minutes=31))
        await coord.async_refresh()
    r = parcel.result
    assert r.status is status
    assert (r.eta_date, r.eta_latest, r.eta_from, r.eta_to) == (None, None, None, None)


async def test_17track_registration_sends_the_gls_code(hass, session):
    client = Track17Client(session, "synthetic-17track-key")
    coord = await _coordinator(hass, session, track17=client)
    now = dt_util.utcnow()
    result = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, None, None, None, None, []
    )
    coord.store.add(Parcel(NUMBER, "gls", "manual", None, now, now, result=result))
    register = f"{TRACK17_URL}/register"
    with aioresponses() as m:
        m.post(register, payload={"code": 0, "data": {
            "accepted": [{"origin": 1, "number": NUMBER, "carrier": 101070}], "rejected": [],
        }})
        m.post(f"{TRACK17_URL}/getquota", payload={"code": 0, "data": {
            "quota_total": 200, "quota_used": 1, "quota_remain": 199,
        }})
        parcel = await coord.async_track17(NUMBER)
        [call] = m.requests[("POST", URL(register))]
    assert call.kwargs["json"] == [{"number": NUMBER, "carrier": 101070}]
    assert (parcel.track17, parcel.track17_carrier) == (True, 101070)


async def test_add_parcel_service_accepts_gls_and_names_the_carrier(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: ""})
    entry.add_to_hass(hass)
    answer = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, None, None, None, None, []
    )
    with patch(FETCH, return_value=answer) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": "zabcd123", "carrier": "gls"}, blocking=True
        )
        await hass.async_block_till_done()
    fetch.assert_awaited_once_with("ZABCD123", "")
    state = hass.states.get("sensor.paket_zabcd123")
    assert state.state == "in_transit"
    assert (state.attributes["carrier"], state.attributes["carrier_name"]) == ("gls", "GLS")
    assert state.attributes["friendly_name"] == "GLS ZABCD123"


# ----- v0.3.19 (issue 8): the 12-digit number of GLS mails and links -----
TWELVE = f"{NUMBER}7"  # the parcel number plus an invented check digit
DHL = re.compile(rf"^{re.escape(DHL_URL)}\?")


async def _with_dhl(hass, session, key):
    coord = await _coordinator(hass, session)
    coord.carriers = {"dhl": DhlCarrier(session, key), "gls": coord.carriers["gls"]}
    return coord


async def test_twelve_digits_are_kept_but_gls_is_asked_with_eleven(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.get(SEARCH, payload=_search("INTRANSIT"))
        parcel = await coord.async_add(TWELVE, "gls", None)
        [url] = _urls(m)
    assert f"match={NUMBER}&" in url and TWELVE not in url
    assert (parcel.number, parcel.carrier, parcel.carrier_mode) == (TWELVE, "gls", "manual")
    assert (parcel.status, parcel.last_error) == (ParcelStatus.IN_TRANSIT, None)


async def test_stored_parcel_with_twelve_digits_starts_working(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session, {CONF_POSTCODE: "10115"})
    now = dt_util.utcnow()
    stored = Parcel(TWELVE, "gls", "manual", None, now, now)
    stored.last_error = "not_found"
    coord.store.add(stored)
    with aioresponses() as m:
        m.get(DETAIL, payload=_detail("INTRANSIT"))
        await coord.async_refresh()
        [url] = _urls(m)
    assert f"/rstt028/{NUMBER}?" in url
    assert (stored.number, stored.status, stored.last_error) == (
        TWELVE, ParcelStatus.IN_TRANSIT, None,
    )


@pytest.mark.parametrize("key", [None, "key"])
async def test_auto_never_asks_gls_about_twelve_digits(hass, session, freezer, key):
    """Without a verified check digit 12 digits may be DHL's or an eBay item number."""
    freezer.move_to(DAYTIME)
    coord = await _with_dhl(hass, session, key)
    with aioresponses() as m:
        m.get(DHL, status=404, payload={"status": 404}, repeat=True)
        m.get(SEARCH, payload=_search("INTRANSIT"), repeat=True)
        parcel = await coord.async_add(TWELVE, "auto", None)
        freezer.tick(timedelta(hours=2))
        await coord.async_refresh()
        assert not any("gls-group" in url for url in _urls(m))
    assert parcel.carrier is None
    assert parcel.last_error == ("not_found" if key else "missing_key")


@pytest.mark.parametrize(("first", "second"), [(NUMBER, TWELVE), (TWELVE, NUMBER)])
async def test_other_form_of_a_gls_number_is_a_duplicate(hass, session, freezer, first, second):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.get(SEARCH, payload=_search("INTRANSIT"))
        await coord.async_add(first, "gls", None)
        with pytest.raises(DuplicateParcel):
            await coord.async_add(second, "gls", None)
        assert len(_urls(m)) == 1
    assert list(coord.store.parcels) == [first]


async def test_twelve_digits_of_another_carrier_are_no_duplicate_of_a_gls_parcel(
    hass, session, freezer
):
    freezer.move_to(DAYTIME)
    coord = await _with_dhl(hass, session, None)
    with aioresponses() as m:
        m.get(SEARCH, payload=_search("INTRANSIT"))
        await coord.async_add(NUMBER, "gls", None)
        parcel = await coord.async_add(TWELVE, "dhl", None)
        # "Automatisch" is no duplicate either: 12 digits may be another carrier's.
        auto = await coord.async_add(f"{NUMBER}8", "auto", None)
    assert (parcel.carrier, parcel.last_error) == ("dhl", "missing_key")
    assert (auto.carrier, auto.last_error) == (None, "missing_key")
    assert list(coord.store.parcels) == [NUMBER, TWELVE, f"{NUMBER}8"]


async def test_gls_mail_updates_the_parcel_stored_with_twelve_digits(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, session)
    with aioresponses() as m:
        m.get(SEARCH, payload=_search("INTRANSIT"), repeat=True)
        parcel = await coord.async_add(TWELVE, "gls", None)
    sent = datetime(2026, 9, 29, 9, 0, tzinfo=BERLIN)
    mail = MailUpdate(NUMBER, "gls", ParcelStatus.OUT_FOR_DELIVERY, sent, eta_date=sent.date())
    change = apply_update(coord.store.parcels, mail, dt_util.utcnow())
    assert change.parcel is parcel and not change.created
    assert list(coord.store.parcels) == [TWELVE]
    assert parcel.status is ParcelStatus.OUT_FOR_DELIVERY
    # Another carrier's mail with the same eleven digits is a parcel of its own.
    other = MailUpdate(NUMBER, "hermes", ParcelStatus.IN_TRANSIT, sent)
    assert apply_update(coord.store.parcels, other, dt_util.utcnow()).created


async def test_gls_mail_leaves_an_unresolved_twelve_digit_parcel_alone(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _with_dhl(hass, session, None)
    parcel = await coord.async_add(TWELVE, "auto", None)
    sent = datetime(2026, 9, 29, 9, 0, tzinfo=BERLIN)
    mail = MailUpdate(NUMBER, "gls", ParcelStatus.IN_TRANSIT, sent)
    change = apply_update(coord.store.parcels, mail, dt_util.utcnow())
    assert change.created and change.parcel is not parcel
    assert list(coord.store.parcels) == [TWELVE, NUMBER]

"""Coordinator: 17track polls (2 min, then 6 h, batched), filling gaps, 'other' status, errors."""

from dataclasses import replace
from datetime import date, datetime, timedelta

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events
from yarl import URL

from custom_components.parcel_tracker.carriers.base import (
    BERLIN,
    Carrier,
    Match,
    MissingCredentials,
    NotFound,
)
from custom_components.parcel_tracker.carriers.track17 import TRACK17_URL, Track17Client
from custom_components.parcel_tracker.const import (
    DEFAULT_KEEP_DELIVERED_DAYS,
    DOMAIN,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)
from custom_components.parcel_tracker.sensor import _location_source
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME, load_fixture

NUMBER = "99999999999901"
SECOND = "99999999999902"
INFO = f"{TRACK17_URL}/gettrackinfo"
QUOTA = f"{TRACK17_URL}/getquota"
REGISTER = f"{TRACK17_URL}/register"
QUOTA_OK = {"code": 0, "data": {"quota_total": 200, "quota_used": 1, "quota_remain": 199}}
SIX_HOURS = timedelta(hours=6)


def _item(number=NUMBER, status="InTransit"):
    item = load_fixture("track17_synthetic_trackinfo.json")["response"]["data"]["accepted"][0]
    item["number"] = number
    item["track_info"]["latest_status"]["status"] = status
    return item


def _echo(status="InTransit"):
    def callback(url, **kwargs):
        accepted = [_item(entry["number"], status) for entry in kwargs["json"]]
        return CallbackResult(payload={"code": 0, "data": {"accepted": accepted, "rejected": []}})

    return callback


class Answer:
    """gettrackinfo answers whose status, place and estimate a test can change."""

    def __init__(self, status="InTransit", place="Köln", estimate=True):
        self.status, self.place, self.estimate = status, place, estimate

    def __call__(self, url, **kwargs):
        accepted = []
        for entry in kwargs["json"]:
            item = _item(entry["number"], self.status)
            info = item["track_info"]
            info["latest_event"]["location"] = self.place
            if not self.estimate:
                info["time_metrics"]["estimated_delivery_date"] = None
            accepted.append(item)
        return CallbackResult(payload={"code": 0, "data": {"accepted": accepted, "rejected": []}})


def _rejected(code):
    return {"code": 0, "data": {"accepted": [], "rejected": [
        {"number": NUMBER, "error": {"code": code, "message": "synthetic"}},
    ]}}


def _asked(m):
    """Numbers per gettrackinfo call."""
    return [
        [entry["number"] for entry in call.kwargs["json"]]
        for call in m.requests.get(("POST", URL(INFO)), [])
    ]


def _mock(m, status="InTransit"):
    m.post(QUOTA, payload=QUOTA_OK, repeat=True)
    m.post(INFO, callback=_echo(status), repeat=True)


class FakeCarrier(Carrier):
    name = "Fake"

    def __init__(self, key, result):
        self.key = key
        self.result = result
        self.calls = 0

    @staticmethod
    def matches(number):
        return Match.POSSIBLE

    async def fetch(self, number, postcode):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


async def _ready(hass, session, carriers=None):
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": ""}, options={})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    coord = ParcelCoordinator(
        hass, entry, store, carriers or {}, None,
        track17=Track17Client(session, "synthetic-17track-key"),
    )
    await coord.async_refresh()  # first refresh (setup): never asks 17track
    return coord


def _registered(coord, number=NUMBER, carrier="other", due_in=timedelta(0), **kwargs):
    now = dt_util.utcnow()
    parcel = Parcel(
        number, carrier, "manual", None, now, now,
        track17=True, track17_carrier=100007, track17_next_at=now + due_in, **kwargs,
    )
    coord.store.add(parcel)
    return parcel


def _pre_transit():
    return TrackingResult(
        ParcelStatus.PRE_TRANSIT, "Angekündigt", None, None, None, None, None, None, None, []
    )


async def test_first_poll_two_minutes_after_registering_then_every_6_hours(
    hass, session, freezer
):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    _registered(coord, due_in=timedelta(minutes=2))
    _registered(coord, SECOND, due_in=timedelta(minutes=2))
    with aioresponses() as m:
        _mock(m)
        freezer.tick(timedelta(minutes=1))
        await coord.async_refresh()
        assert _asked(m) == []
        freezer.tick(timedelta(minutes=1))
        await coord.async_refresh()
        assert _asked(m) == [[NUMBER, SECOND]]
        freezer.tick(timedelta(hours=5, minutes=50))
        await coord.async_refresh()
        assert len(_asked(m)) == 1
        freezer.tick(timedelta(minutes=10))
        await coord.async_refresh()
        assert len(_asked(m)) == 2
        assert not m.requests.get(("POST", URL(REGISTER)))


async def test_more_than_40_parcels_are_asked_in_batches(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    for i in range(1, 42):
        _registered(coord, f"999999999999{i:02d}")
    with aioresponses() as m:
        _mock(m)
        await coord.async_refresh()
        assert [len(numbers) for numbers in _asked(m)] == [40, 1]
    assert all(p.status is ParcelStatus.IN_TRANSIT for p in coord.store.parcels.values())


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("InfoReceived", ParcelStatus.PRE_TRANSIT),
        ("InTransit", ParcelStatus.IN_TRANSIT),
        ("OutForDelivery", ParcelStatus.OUT_FOR_DELIVERY),
        ("AvailableForPickup", ParcelStatus.AWAITING_PICKUP),
        ("DeliveryFailure", ParcelStatus.EXCEPTION),
        ("Exception", ParcelStatus.EXCEPTION),
        ("NotFound", ParcelStatus.UNKNOWN),
    ],
)
async def test_other_parcel_takes_its_whole_status_from_17track(
    hass, session, freezer, status, expected
):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    parcel = _registered(coord)
    with aioresponses() as m:
        _mock(m, status)
        await coord.async_refresh()
    assert parcel.status is expected
    assert parcel.result.status_text == "Das Paket ist im Zustelldepot eingetroffen."
    assert parcel.result.location == "Köln"
    assert parcel.track17_next_at == dt_util.utcnow() + SIX_HOURS


@pytest.mark.parametrize(
    ("status", "expected"),
    [("Delivered", ParcelStatus.DELIVERED), ("Expired", ParcelStatus.UNKNOWN)],
)
async def test_delivered_or_expired_ends_the_17track_polls(
    hass, session, freezer, status, expected
):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    parcel = _registered(coord)
    with aioresponses() as m:
        _mock(m, status)
        await coord.async_refresh()
        freezer.tick(timedelta(hours=7))
        await coord.async_refresh()
        assert len(_asked(m)) == 1
    assert (parcel.status, parcel.track17_next_at, parcel.track17) == (expected, None, True)


async def test_status_change_of_an_other_parcel_fires_the_event(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    _registered(coord, result=_pre_transit())
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    with aioresponses() as m:
        _mock(m)
        await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert (events[0].data["carrier"], events[0].data["old_status"],
            events[0].data["new_status"]) == ("other", "pre_transit", "in_transit")


async def test_carrier_stays_in_charge_and_17track_only_fills_gaps(hass, session, freezer):
    freezer.move_to(DAYTIME)
    own_event = TrackingEvent(datetime(2026, 9, 29, 20, 0, tzinfo=BERLIN), "Im Paketzentrum", None)
    own = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", date(2026, 10, 1), None, None, None, None, None,
        None, [own_event],
    )
    dpd = FakeCarrier("dpd", own)
    coord = await _ready(hass, session, {"dpd": dpd})
    parcel = _registered(
        coord, carrier="dpd", result=own, next_poll_at=dt_util.utcnow() + timedelta(hours=1)
    )
    with aioresponses() as m:
        _mock(m, "OutForDelivery")
        await coord.async_refresh()
        r = parcel.result
        assert (r.status, r.status_text) == (ParcelStatus.IN_TRANSIT, "Unterwegs")
        assert r.location == "Köln"
        assert (r.eta_date, r.eta_from, r.eta_to) == (
            date(2026, 10, 1),
            datetime(2026, 10, 1, 10, 0, tzinfo=BERLIN),
            datetime(2026, 10, 1, 14, 0, tzinfo=BERLIN),
        )
        assert [e.text for e in r.events] == ["Im Paketzentrum"]
        assert set(r.enriched) == {"location", "window"}
        assert dpd.calls == 0
        # The carrier answers again without a place: the 17track place stays.
        freezer.tick(timedelta(hours=1))
        await coord.async_refresh()
        assert (dpd.calls, parcel.result.location) == (1, "Köln")
        # The carrier knows the place itself: it wins.
        dpd.result = replace(own, location="Bonn")
        freezer.tick(timedelta(minutes=31))
        await coord.async_refresh()
        assert parcel.result.location == "Bonn"
        assert "location" not in parcel.result.enriched
        assert len(_asked(m)) == 1


async def test_hermes_without_a_day_gets_the_17track_day_again(hass, session, freezer):
    freezer.move_to(DAYTIME)
    own = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, "Hub", None, None, None, []
    )
    hermes = FakeCarrier("hermes", own)
    coord = await _ready(hass, session, {"hermes": hermes})
    parcel = _registered(
        coord, "H9999999999999999901", carrier="hermes", result=own,
        next_poll_at=dt_util.utcnow() + timedelta(hours=1),
    )
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, callback=_echo(), repeat=True)
        await coord.async_refresh()
        assert (parcel.result.eta_date, parcel.result.enriched) == (
            date(2026, 10, 1), ("eta", "events"),
        )
        freezer.tick(timedelta(hours=1))
        await coord.async_refresh()
    assert hermes.calls == 1
    assert parcel.result.eta_date == date(2026, 10, 1)
    assert "eta" in parcel.result.enriched


async def test_no_data_yet_is_asked_again_in_6_hours_quietly(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    parcel = _registered(coord, result=_pre_transit())
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, payload=_rejected(-18019909))
        await coord.async_refresh()
    assert parcel.track17_next_at == dt_util.utcnow() + SIX_HOURS
    assert (parcel.status, parcel.last_error) == (ParcelStatus.PRE_TRANSIT, None)


async def test_number_unknown_at_17track_is_never_registered_again(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    parcel = _registered(coord)
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, payload=_rejected(-18019902))
        await coord.async_refresh()
        assert not m.requests.get(("POST", URL(REGISTER)))
    assert (parcel.track17, parcel.track17_next_at) == (False, None)
    assert parcel.last_error == "track17_not_registered"


async def test_17track_unreachable_backs_off_and_never_registers(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    parcel = _registered(coord)
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, status=500, repeat=True)
        await coord.async_refresh()
        assert parcel.track17_next_at == dt_util.utcnow() + timedelta(minutes=5)
        freezer.tick(timedelta(minutes=5))
        await coord.async_refresh()
        assert parcel.track17_next_at == dt_util.utcnow() + timedelta(minutes=10)
        assert not m.requests.get(("POST", URL(REGISTER)))
    assert parcel.track17 is True


async def test_rejected_key_while_polling_stops_until_reload(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    _registered(coord)
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, payload={"code": -18010002, "data": None}, repeat=True)
        await coord.async_refresh()
        freezer.tick(timedelta(hours=7))
        await coord.async_refresh()
        assert len(_asked(m)) == 1
        assert not m.requests.get(("POST", URL(QUOTA)))
    assert coord.track17_blocked is True
    assert ir.async_get(hass).async_get_issue(DOMAIN, "track17_auth") is not None


async def test_refresh_asks_17track_now_but_not_right_after_registering(hass, session, freezer):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)
    _registered(coord, due_in=timedelta(hours=5))
    fresh = _registered(coord, SECOND, due_in=timedelta(minutes=2))
    with aioresponses() as m:
        _mock(m)
        await coord.async_refresh_parcels(None)
        assert _asked(m) == [[NUMBER]]
    assert fresh.track17_next_at == dt_util.utcnow() + timedelta(minutes=2)


async def test_mail_update_does_not_turn_17track_values_into_carrier_values(
    hass, session, freezer
):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)  # no UPS API: the parcel lives from mails
    sent = datetime(2026, 9, 29, 9, 0, tzinfo=BERLIN)
    from_mail = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, None, None, None, None,
        [TrackingEvent(sent, "Unterwegs", None)],
    )
    number = "1Z999AA19999999901"
    parcel = _registered(coord, number, carrier="ups", result=from_mail)
    parcel.carrier_mode = "mail"
    answer = Answer(place="Köln")
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, callback=answer, repeat=True)
        await coord.async_refresh()
        assert (parcel.result.location, _location_source(parcel)) == ("Köln", "17track")

        update = MailUpdate(
            number, "ups", ParcelStatus.OUT_FOR_DELIVERY, sent + timedelta(days=1)
        )
        assert apply_update(coord.store.parcels, update, dt_util.utcnow()) is not None
        r = parcel.result
        assert (r.status, r.status_text) == (ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung")
        assert r.location == "Köln" and "location" in r.enriched
        assert r.eta_date == date(2026, 10, 1) and "eta" in r.enriched
        assert [e.text for e in r.events] == ["In Zustellung", "Unterwegs"]
        # The same mail again changes nothing.
        assert apply_update(coord.store.parcels, update, dt_util.utcnow()) is None

        answer.place, answer.estimate = "Bonn", False
        freezer.tick(SIX_HOURS)
        await coord.async_refresh()
    r = parcel.result
    assert (r.location, _location_source(parcel)) == ("Bonn", "17track")
    assert r.eta_date is None  # 17track took its day back: no mail ever named one
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY


async def test_hermes_keeps_a_mail_day_but_never_a_17track_day(hass, session, freezer):
    freezer.move_to(DAYTIME)
    own = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, "Hub", None, None, None, []
    )
    hermes = FakeCarrier("hermes", own)
    coord = await _ready(hass, session, {"hermes": hermes})
    number = "H9999999999999999901"
    parcel = _registered(
        coord, number, carrier="hermes", result=own,
        next_poll_at=dt_util.utcnow() + timedelta(hours=1),
    )
    answer = Answer()
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, callback=answer, repeat=True)
        await coord.async_refresh()
        assert (parcel.result.eta_date, "eta" in parcel.result.enriched) == (
            date(2026, 10, 1), True,
        )
        # A mail without a day, then the Hermes API (which never tells a day).
        update = MailUpdate(
            number, "hermes", ParcelStatus.IN_TRANSIT, datetime(2026, 9, 30, 9, 0, tzinfo=BERLIN)
        )
        apply_update(coord.store.parcels, update, dt_util.utcnow())
        assert "eta" in parcel.result.enriched
        freezer.tick(timedelta(minutes=1))
        await coord.async_refresh()
        assert hermes.calls == 1
        assert (parcel.result.eta_date, "eta" in parcel.result.enriched) == (
            date(2026, 10, 1), True,
        )
        # 17track has no day any more: nothing may be left of it.
        answer.estimate = False
        freezer.tick(SIX_HOURS)
        await coord.async_refresh()
    assert parcel.result.eta_date is None


async def test_parcel_without_a_carrier_answer_shows_the_whole_17track_answer(
    hass, session, freezer
):
    freezer.move_to(DAYTIME)
    dhl = FakeCarrier("dhl", MissingCredentials("no key"))  # DHL without an API key
    coord = await _ready(hass, session, {"dhl": dhl})
    parcel = _registered(coord, "00999999999999999901", carrier="dhl")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    answer = Answer("InTransit")
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, callback=answer, repeat=True)
        await coord.async_refresh()
        r = parcel.result
        assert (r.status, r.status_text, r.location) == (
            ParcelStatus.IN_TRANSIT, "Das Paket ist im Zustelldepot eingetroffen.", "Köln",
        )
        assert r.eta_date == date(2026, 10, 1) and len(r.events) == 3
        assert set(r.enriched) == {"status", "location", "eta", "events"}
        assert _location_source(parcel) == "17track"
        assert parcel.last_error == "missing_key"  # still true, and still said
        # The store round trip keeps it.
        again = Parcel.from_dict(parcel.to_dict())
        assert (again.result, again.track17_result) == (parcel.result, parcel.track17_result)

        # 17track moves on: so does the parcel.
        answer.status = "OutForDelivery"
        freezer.tick(SIX_HOURS)
        await coord.async_refresh()
        assert parcel.status is ParcelStatus.OUT_FOR_DELIVERY
        assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
            ("in_transit", "out_for_delivery")
        ]

        # The carrier answers itself: it takes over, 17track only fills its gaps again.
        dhl.result = TrackingResult(
            ParcelStatus.IN_TRANSIT, "Im Paketzentrum bearbeitet", None, None, None, None,
            None, None, None, [],
        )
        freezer.tick(timedelta(hours=1))
        await coord.async_refresh()
    r = parcel.result
    assert (r.status, r.status_text) == (ParcelStatus.IN_TRANSIT, "Im Paketzentrum bearbeitet")
    assert r.location == "Köln"
    assert set(r.enriched) == {"location", "eta", "events"}
    assert parcel.last_error is None


async def test_number_gone_at_17track_takes_its_values_from_a_carrier_parcel(
    hass, session, freezer
):
    freezer.move_to(DAYTIME)
    coord = await _ready(hass, session)  # no carrier connected: nothing polls
    own = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, None, None, None, None, []
    )
    parcel = _registered(coord, carrier="dpd", result=own, due_in=timedelta(hours=1))
    alone = _registered(coord, SECOND, carrier="dhl", due_in=timedelta(hours=1))
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, callback=_echo())
        freezer.tick(timedelta(hours=1))
        await coord.async_refresh()
        assert parcel.result.location == "Köln" and parcel.track17_result is not None
        assert alone.status is ParcelStatus.IN_TRANSIT
        errors = (parcel.last_error, alone.last_error)
        m.post(INFO, payload={"code": 0, "data": {"accepted": [], "rejected": [
            {"number": n, "error": {"code": -18019902, "message": "synthetic"}}
            for n in (NUMBER, SECOND)
        ]}})
        freezer.tick(SIX_HOURS)
        await coord.async_refresh()
        assert not m.requests.get(("POST", URL(REGISTER)))
    for p in (parcel, alone):
        assert (p.track17, p.track17_next_at, p.track17_result) == (False, None, None)
    assert parcel.result == own  # the carrier's own answer again
    assert alone.result is None  # nothing of its own to show
    assert (parcel.last_error, alone.last_error) == errors
    assert "track17_not_registered" not in errors


async def test_carrier_delivered_ends_the_17track_polls(hass, session, freezer):
    freezer.move_to(DAYTIME)
    own = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, None, None, None, None, []
    )
    delivered = replace(
        own, status=ParcelStatus.DELIVERED, status_text="Zugestellt",
        delivered_at=dt_util.utcnow(),
    )
    dpd = FakeCarrier("dpd", delivered)
    coord = await _ready(hass, session, {"dpd": dpd})
    parcel = _registered(coord, carrier="dpd", result=own, due_in=timedelta(hours=3))
    with aioresponses() as m:
        _mock(m)
        freezer.tick(timedelta(minutes=1))
        await coord.async_refresh()
        assert (dpd.calls, parcel.status) == (1, ParcelStatus.DELIVERED)
        assert parcel.track17_next_at is None
        freezer.tick(SIX_HOURS)
        await coord.async_refresh()
        assert _asked(m) == []


def _own(status, text, delivered_at=None):
    return TrackingResult(status, text, None, None, None, None, None, None, delivered_at, [])


async def test_17track_status_never_shortens_the_ups_interval(hass, session, freezer):
    freezer.move_to(DAYTIME)
    ups = FakeCarrier("ups", NotFound("no data yet"))  # UPS API knows nothing of the parcel
    coord = await _ready(hass, session, {"ups": ups})
    parcel = _registered(coord, "1Z999AA19999999901", carrier="ups")
    with aioresponses() as m:
        _mock(m, "OutForDelivery")
        await coord.async_refresh()
        assert (ups.calls, parcel.status) == (1, ParcelStatus.OUT_FOR_DELIVERY)
        assert "status" in parcel.result.enriched  # shown from 17track alone
        freezer.tick(timedelta(hours=4))
        await coord.async_refresh()
    # 17track says "out for delivery", UPS itself said nothing: the 4 h floor stays.
    assert ups.calls == 2
    assert parcel.next_poll_at == dt_util.utcnow() + timedelta(hours=4)


async def test_carrier_taking_over_from_17track_does_not_announce_a_status_twice(
    hass, session, freezer
):
    freezer.move_to(DAYTIME)
    dhl = FakeCarrier("dhl", MissingCredentials("no key"))
    coord = await _ready(hass, session, {"dhl": dhl})
    parcel = _registered(coord, "00999999999999999901", carrier="dhl")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)

    def fired():
        return [(e.data["old_status"], e.data["new_status"]) for e in events]

    answer = Answer("InTransit")
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, callback=answer, repeat=True)
        await coord.async_refresh()
        answer.status = "OutForDelivery"
        freezer.tick(SIX_HOURS)
        await coord.async_refresh()
        assert fired() == [("in_transit", "out_for_delivery")]

        # The carrier answers itself and is a step behind 17track: shown, but no event.
        dhl.result = _own(ParcelStatus.IN_TRANSIT, "Im Paketzentrum bearbeitet")
        freezer.tick(timedelta(hours=1))
        await coord.async_refresh()
        assert parcel.status is ParcelStatus.IN_TRANSIT
        assert "status" not in parcel.result.enriched
        assert len(events) == 1

        # It catches up to what 17track already announced: no second event for it.
        dhl.result = _own(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung")
        freezer.tick(timedelta(minutes=30))
        await coord.async_refresh()
        assert parcel.status is ParcelStatus.OUT_FOR_DELIVERY
        assert len(events) == 1

        # From here on everything is news again.
        dhl.result = _own(
            ParcelStatus.DELIVERED, "Zugestellt", delivered_at=dt_util.utcnow()
        )
        freezer.tick(timedelta(minutes=10))
        await coord.async_refresh()
    assert fired() == [("in_transit", "out_for_delivery"), ("out_for_delivery", "delivered")]


async def test_carrier_taking_over_with_a_newer_status_fires_the_event(hass, session, freezer):
    freezer.move_to(DAYTIME)
    dhl = FakeCarrier("dhl", MissingCredentials("no key"))
    coord = await _ready(hass, session, {"dhl": dhl})
    parcel = _registered(coord, "00999999999999999901", carrier="dhl")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    with aioresponses() as m:
        _mock(m)
        await coord.async_refresh()
        assert parcel.status is ParcelStatus.IN_TRANSIT
        dhl.result = _own(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung")
        freezer.tick(timedelta(hours=1))
        await coord.async_refresh()
    assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
        ("in_transit", "out_for_delivery")
    ]


async def test_delivered_by_17track_alone_ends_everything_and_is_cleaned_up(
    hass, session, freezer
):
    freezer.move_to(DAYTIME)
    dhl = FakeCarrier("dhl", MissingCredentials("no key"))  # DHL without an API key
    coord = await _ready(hass, session, {"dhl": dhl})
    number = "00999999999999999901"
    parcel = _registered(coord, number, carrier="dhl")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    answer = Answer("InTransit")
    with aioresponses() as m:
        m.post(QUOTA, payload=QUOTA_OK, repeat=True)
        m.post(INFO, callback=answer, repeat=True)
        await coord.async_refresh()
        assert parcel.status is ParcelStatus.IN_TRANSIT
        answer.status = "Delivered"
        freezer.tick(SIX_HOURS)
        await coord.async_refresh()
        delivered_at = datetime(2026, 9, 30, 6, 12, tzinfo=BERLIN)  # 17track's newest event
        assert (parcel.status, parcel.result.delivered_at) == (
            ParcelStatus.DELIVERED, delivered_at,
        )
        assert parcel.result.eta_date is None
        assert parcel.track17_next_at is None and parcel.track17 is True
        asked, polled = len(_asked(m)), dhl.calls
        # Neither 17track nor the carrier is asked again.
        freezer.tick(timedelta(hours=7))
        await coord.async_refresh()
        assert (len(_asked(m)), dhl.calls) == (asked, polled)
        assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
            ("in_transit", "delivered")
        ]
        # Kept for keep_delivered_days after the delivery, then removed.
        keep = timedelta(days=DEFAULT_KEEP_DELIVERED_DAYS)
        freezer.move_to(delivered_at + keep - timedelta(minutes=1))
        await coord.async_refresh()
        assert coord.store.get(number) is parcel
        freezer.tick(timedelta(minutes=2))
        await coord.async_refresh()
        assert coord.store.get(number) is None
        assert len(_asked(m)) == asked
    assert len(events) == 1

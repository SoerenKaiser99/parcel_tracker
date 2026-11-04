"""Sent parcels (``Parcel.outgoing``, v0.3.48): out of the counters and the calendar,
one arrival push at most, never a gift, ``outgoing`` in attributes and events."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.const import (
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    CONF_POSTCODE,
    CONF_READ_OTP,
    DOMAIN,
    EVENT_PARCEL_ADDED,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.notification import build_notification
from custom_components.parcel_tracker.schedule import ParcelSummary, summarize

from .conftest import DAYTIME
from .test_coordinator_notify import PHONE, _change, _sent, _setup, result

TODAY = date(2026, 10, 2)
TODAY_NOON = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
SENT = "00340999999999999931"
OTHER = "00340999999999999932"


def _parcel(status, number=SENT, eta=TODAY, delivered_at=None, outgoing=True) -> Parcel:
    res = TrackingResult(status, None, eta, None, None, None, None, None, delivered_at, [])
    parcel = Parcel(number, "dhl", "mail", None, TODAY_NOON, TODAY_NOON, result=res)
    parcel.outgoing = outgoing
    return parcel


# ----- counters -----
@pytest.mark.parametrize(
    "status",
    [
        ParcelStatus.IN_TRANSIT,
        ParcelStatus.OUT_FOR_DELIVERY,
        ParcelStatus.AWAITING_PICKUP,
        ParcelStatus.DELIVERED,
    ],
)
def test_summarize_leaves_a_sent_parcel_out_of_every_list(status):
    sent = _parcel(status, delivered_at=TODAY_NOON)
    assert summarize([sent], TODAY) == ParcelSummary([], [], [], [], [])
    # An incoming parcel just like it still counts.
    incoming = _parcel(status, OTHER, delivered_at=TODAY_NOON, outgoing=False)
    assert summarize([sent, incoming], TODAY) != ParcelSummary([], [], [], [], [])


# ----- push text -----
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _message(parcel, old):
    built = build_notification(parcel, old, NOW)
    return None if built is None else built[1]


def test_sent_parcel_texts():
    pickup = _parcel(ParcelStatus.AWAITING_PICKUP)
    pickup.name = "Buch für Oma"
    pickup.result.pickup_point = "Packstation 123"
    pickup.result.pickup_until = datetime(2026, 10, 9, tzinfo=UTC)
    assert _message(pickup, ParcelStatus.IN_TRANSIT) == (
        "✅ Dein verschicktes Paket Buch für Oma (DHL) liegt beim Empfänger zur Abholung bereit"
    )
    done = _parcel(ParcelStatus.DELIVERED)
    assert _message(done, ParcelStatus.IN_TRANSIT) == (
        "✅ Dein verschicktes Paket Paket …9931 (DHL) wurde zugestellt"
    )
    # Ready for pickup, then delivered: one arrival only.
    assert _message(done, ParcelStatus.AWAITING_PICKUP) is None


@pytest.mark.parametrize(
    "status",
    [
        ParcelStatus.OUT_FOR_DELIVERY,
        ParcelStatus.EXCEPTION,
        ParcelStatus.AT_DELIVERY_DEPOT,
        ParcelStatus.IN_TRANSIT,
    ],
)
def test_sent_parcel_has_no_other_text(status):
    assert _message(_parcel(status), ParcelStatus.PRE_TRANSIT) is None


# ----- push through the coordinator -----
async def _sent_setup(hass, events=None):
    options = {CONF_NOTIFY_TARGETS: [PHONE]}
    if events is not None:
        options[CONF_NOTIFY_EVENTS] = events
    coord, carrier, parcel = await _setup(hass, options)
    parcel.outgoing = True
    return coord, carrier, parcel


async def test_pickup_then_delivered_gives_one_push(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, carrier, _ = await _sent_setup(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await _change(
        hass, coord, carrier, freezer,
        result(ParcelStatus.AWAITING_PICKUP, pickup_point="Bonn", pickup_until=date(2026, 10, 6)),
    )
    assert [m for _, _, m in _sent(calls)] == [
        "✅ Dein verschicktes Paket Kopfhörer (DHL) liegt beim Empfänger zur Abholung bereit"
    ]
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert len(_sent(calls)) == 1
    # Events keep firing, with the flag.
    assert len(events) == 2
    assert all(e.data["outgoing"] is True for e in events)


async def test_delivered_directly_gives_one_push(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, carrier, _ = await _sent_setup(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert [m for _, _, m in _sent(calls)] == [
        "✅ Dein verschicktes Paket Kopfhörer (DHL) wurde zugestellt"
    ]


async def test_out_for_delivery_and_problem_give_no_push(hass, freezer):
    freezer.move_to(DAYTIME)
    events_chosen = ["out_for_delivery", "exception", "delivered", "awaiting_pickup"]
    coord, carrier, _ = await _sent_setup(hass, events_chosen)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.EXCEPTION))
    assert calls == []
    assert len(events) == 2


@pytest.mark.parametrize(
    "chosen", [["awaiting_pickup", "out_for_delivery"], []], ids=["without-delivered", "none"]
)
async def test_no_push_without_delivered_chosen(hass, freezer, chosen):
    freezer.move_to(DAYTIME)
    coord, carrier, _ = await _sent_setup(hass, chosen)
    calls = async_mock_service(hass, "notify", "send_message")
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.AWAITING_PICKUP))
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert calls == []


async def test_incoming_parcel_is_pushed_as_before(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass, {CONF_NOTIFY_TARGETS: [PHONE]})
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    calls = async_mock_service(hass, "notify", "send_message")
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.AWAITING_PICKUP))
    assert [m for _, _, m in _sent(calls)] == ["📍 Kopfhörer (DHL) liegt zur Abholung bereit"]
    assert events[0].data["outgoing"] is False


# ----- the integration set up -----
async def _entry(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"}, options=options or {}
    )
    entry.add_to_hass(hass)
    in_transit = TrackingResult(ParcelStatus.IN_TRANSIT, "x", None, None, None, None, None,
                                None, None, [])
    with patch(FETCH, return_value=in_transit):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _store_sent(coordinator, number=SENT, eta=None, status=ParcelStatus.IN_TRANSIT, **kwargs):
    now = dt_util.utcnow()
    res = TrackingResult(status, "x", eta, None, None, None, None, None, None, [])
    parcel = Parcel(number, "dhl", "mail", "Paket an Oma", now, now, result=res, **kwargs)
    parcel.outgoing = True
    coordinator.store.add(parcel)
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    return parcel


async def test_calendar_has_no_event_for_a_sent_parcel(hass):
    entry = await _entry(hass)
    tomorrow = dt_util.now().date() + timedelta(days=1)
    _store_sent(entry.runtime_data, eta=tomorrow)
    await hass.async_block_till_done()
    answer = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": "calendar.pakete", "duration": {"days": 3}},
        blocking=True, return_response=True,
    )
    assert answer["calendar.pakete"]["events"] == []


async def test_sensor_attribute_outgoing_and_no_delivery_code(hass):
    entry = await _entry(hass, {CONF_READ_OTP: True})
    today = dt_util.now().date()
    _store_sent(
        entry.runtime_data, eta=today, status=ParcelStatus.OUT_FOR_DELIVERY,
        delivery_code="123456", delivery_code_day=today,
    )
    await hass.async_block_till_done()
    attrs = hass.states.get(f"sensor.paket_{SENT}").attributes
    assert attrs["outgoing"] is True
    assert attrs["has_delivery_code"] is False
    assert entry.runtime_data.delivery_code(entry.runtime_data.store.parcels[SENT], today) is None
    # Not counted today, not on the way.
    assert hass.states.get("sensor.pakete_heute").state == "0"
    assert hass.states.get("sensor.pakete_unterwegs").state == "0"


async def test_added_event_carries_outgoing(hass):
    entry = await _entry(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    in_transit = TrackingResult(ParcelStatus.IN_TRANSIT, "x", None, None, None, None, None,
                                None, None, [])
    with patch(FETCH, return_value=in_transit):
        await coordinator.async_add(OTHER, "dhl", "Lampe")
    await hass.async_block_till_done()
    assert events[-1].data["outgoing"] is False
    parcel = coordinator.store.parcels[OTHER]
    parcel.outgoing = True
    coordinator._fire_added(parcel)
    await hass.async_block_till_done()
    assert events[-1].data["outgoing"] is True


async def test_set_gift_refuses_a_sent_parcel(hass):
    entry = await _entry(hass)
    parcel = _store_sent(entry.runtime_data)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "set_gift", {"number": SENT, "gift": True}, blocking=True
        )
    assert err.value.translation_key == "gift_outgoing"
    assert parcel.gift is False


async def test_set_gift_for_all_open_parcels_skips_a_sent_one(hass):
    entry = await _entry(hass)
    coordinator = entry.runtime_data
    parcel = _store_sent(coordinator)
    in_transit = TrackingResult(ParcelStatus.IN_TRANSIT, "x", None, None, None, None, None,
                                None, None, [])
    with patch(FETCH, return_value=in_transit):
        await coordinator.async_add(OTHER, "dhl", "Lampe")
    await hass.services.async_call(
        DOMAIN, "set_gift", {"open_parcels": True, "gift": True}, blocking=True
    )
    assert coordinator.store.parcels[OTHER].gift is True
    assert parcel.gift is False


# ----- fix round 1: one arrival only, no pickup hints, no customs -----
def test_arrival_told_before_gives_no_second_text():
    parcel = _parcel(ParcelStatus.DELIVERED)
    parcel.arrival_told = True
    assert _message(parcel, ParcelStatus.IN_TRANSIT) is None


def test_arrival_told_is_stored_and_old_stores_load_without_it():
    parcel = _parcel(ParcelStatus.DELIVERED)
    parcel.arrival_told = True
    assert Parcel.from_dict(parcel.to_dict()).arrival_told is True
    data = parcel.to_dict()
    del data["arrival_told"]
    assert Parcel.from_dict(data).arrival_told is False


async def test_pickup_step_back_then_delivered_gives_one_push(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _sent_setup(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.AWAITING_PICKUP))
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.IN_TRANSIT))
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert [m for _, _, m in _sent(calls)] == [
        "✅ Dein verschicktes Paket Kopfhörer (DHL) liegt beim Empfänger zur Abholung bereit"
    ]
    assert parcel.arrival_told is True


async def test_arrival_without_delivered_chosen_still_counts_as_told(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _sent_setup(hass, ["out_for_delivery"])
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert parcel.arrival_told is True


async def test_incoming_parcel_never_sets_arrival_told(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass, {CONF_NOTIFY_TARGETS: [PHONE]})
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert parcel.arrival_told is False


async def test_sensor_hides_pickup_hints_and_customs_of_a_sent_parcel(hass):
    entry = await _entry(hass)
    parcel = _store_sent(
        entry.runtime_data, status=ParcelStatus.AWAITING_PICKUP,
        customs_amount=12.5, customs_currency="EUR", customs_cash=True,
    )
    parcel.result.pickup_point = "Packstation 123"
    parcel.result.pickup_until = dt_util.utcnow() + timedelta(days=5)
    assert parcel.customs_due is None
    entry.runtime_data.async_set_updated_data(dict(entry.runtime_data.store.parcels))
    await hass.async_block_till_done()
    attrs = hass.states.get(f"sensor.paket_{SENT}").attributes
    assert attrs["pickup_point"] is None and attrs["pickup_until"] is None
    assert attrs["customs_amount"] is None and attrs["customs_currency"] is None
    assert attrs["customs_cash"] is False
    # An incoming parcel keeps them.
    parcel.outgoing = False
    assert parcel.customs_due == (12.5, "EUR", True)


def test_gift_outgoing_text_ends_like_its_neighbours():
    import json
    from pathlib import Path

    base = Path(__file__).parents[1] / "custom_components" / "parcel_tracker"
    for name in ("strings.json", "translations/de.json", "translations/en.json"):
        exceptions = json.loads((base / name).read_text(encoding="utf-8"))["exceptions"]
        assert exceptions["gift_outgoing"]["message"].endswith(".")

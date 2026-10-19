"""v0.3.30: "Erhalten" - a parcel is marked as received by hand.

For orders without a delivery mail, parcels whose delivery mail never came and parcels
nobody can ask about. The hand mark wins: the parcel is delivered now and stays exactly
as marked, whatever a carrier, 17track or a mail says afterwards.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.core import CoreState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.carriers.track17 import Track17Info
from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.device_trigger import _event_data
from custom_components.parcel_tracker.diagnostics import async_get_config_entry_diagnostics
from custom_components.parcel_tracker.mail.apply import (
    MANUAL_TEXT,
    apply_update,
    close_unconfirmed,
    mark_received,
)
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)
from custom_components.parcel_tracker.notification import build_notification
from custom_components.parcel_tracker.schedule import (
    delivered_today,
    order_overdue,
    poll_interval,
    should_remove,
    summarize,
)

from .test_coordinator_notify import _start
from .test_order_closing import (
    BRAND,
    DHL,
    NOW,
    ORDER,
    TODAY,
    FakeCarrier,
    _carrier_parcel,
    _coordinator,
    _days,
    _order,
    _prepared,
    _refresh,
    _result,
)

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
TEXT = "Erhalten (von Hand markiert)"


def _waiting(status=ParcelStatus.AWAITING_PICKUP) -> Parcel:
    """A DHL parcel added by hand that never gets its "delivered"."""
    result = TrackingResult(
        status, "Abholbereit", TODAY, None, None, "Bonn", "Filiale", TODAY + _days(5), None,
        [TrackingEvent(NOW - _days(1), "Abholbereit", "Bonn")],
    )
    return Parcel(DHL, "dhl", "manual", "Oma", NOW - _days(3), NOW - _days(1), result=result,
                  next_poll_at=NOW + timedelta(minutes=30), last_error="unavailable",
                  error_streak=2, first_error_at=NOW - _days(1))


# ----- the mark itself -----
def test_the_mark_makes_the_parcel_delivered_now():
    parcel = _waiting()
    parcel.delivery_code, parcel.delivery_code_day = "1234", TODAY
    parcel.track17, parcel.track17_next_at = True, NOW + timedelta(hours=1)
    mark_received(parcel, NOW)

    result = parcel.result
    assert MANUAL_TEXT == TEXT
    assert (result.status, result.status_text) == (ParcelStatus.DELIVERED, TEXT)
    assert result.delivered_at == NOW and parcel.last_change_at == NOW
    assert [(e.timestamp, e.text) for e in result.events] == [
        (NOW, TEXT), (NOW - _days(1), "Abholbereit"),
    ]
    # Nothing of the way there is left: no day, no pickup point, no error, no code.
    assert (result.eta_date, result.eta_latest, result.eta_from, result.eta_to) == (None,) * 4
    assert (result.pickup_point, result.pickup_until, result.enriched) == (None, None, ())
    assert (parcel.last_error, parcel.error_streak, parcel.first_error_at) == (None, 0, None)
    assert (parcel.delivery_code, parcel.delivery_code_day) == (None, None)
    assert parcel.manual_delivered is True and parcel.assumed_delivered is False
    # Nobody is asked any more, like for every delivered parcel.
    assert parcel.next_poll_at is None and parcel.track17_next_at is None
    assert poll_interval(parcel.status, NOW) is None


def test_the_mark_works_without_any_status_and_keeps_a_long_history():
    bare = Parcel(DHL, None, "auto", None, NOW, NOW, last_error="carrier_not_found")
    mark_received(bare, NOW)
    assert bare.status is ParcelStatus.DELIVERED
    assert [e.text for e in bare.result.events] == [TEXT]

    events = [TrackingEvent(NOW - timedelta(hours=n), f"Scan {n}", None) for n in range(1, 21)]
    long = _waiting()
    long.result.events = events
    mark_received(long, NOW)
    assert len(long.result.events) == 20 and long.result.events[0].text == TEXT
    assert long.result.events[1].text == "Scan 1"


def test_the_mark_confirms_an_order_closed_without_a_delivery_mail():
    order = _order(first=TODAY - _days(6), changed=NOW - _days(8))
    close_unconfirmed(order, NOW - _days(1))
    assert order.assumed_delivered is True and not delivered_today(order, TODAY, BERLIN)
    mark_received(order, NOW)
    assert (order.assumed_delivered, order.manual_delivered) == (False, True)
    # Confirmed, but nobody knows when it came (v0.3.31): never "delivered today".
    assert order.result.delivered_at is None and not delivered_today(order, TODAY, BERLIN)


def test_counts_as_delivered_today_and_goes_after_the_days_it_is_kept():
    parcel = _waiting()
    mark_received(parcel, NOW)
    summary = summarize([parcel], TODAY, BERLIN)
    assert summary.delivered_today == [parcel]
    assert summary.active == [] and summary.awaiting_pickup == []
    assert not should_remove(parcel, NOW + _days(3), 3)
    assert should_remove(parcel, NOW + _days(3) + timedelta(minutes=1), 3)
    assert not order_overdue(parcel, TODAY + _days(30))


def test_flag_is_stored_and_old_stores_load_without_it():
    parcel = _waiting()
    assert parcel.to_dict()["manual_delivered"] is False
    mark_received(parcel, NOW)
    stored = parcel.to_dict()
    assert stored["manual_delivered"] is True
    again = Parcel.from_dict(stored)
    assert again.manual_delivered is True and again.result.status_text == TEXT
    assert again.result.delivered_at == NOW
    del stored["manual_delivered"]
    assert Parcel.from_dict(stored).manual_delivered is False
    assert Parcel.from_dict({**stored, "manual_delivered": "yes"}).manual_delivered is False


def test_no_notification_for_a_hand_mark():
    parcel = _waiting()
    mark_received(parcel, NOW)
    assert build_notification(parcel, ParcelStatus.AWAITING_PICKUP, NOW) is None
    real = _carrier_parcel()
    assert build_notification(real, ParcelStatus.IN_TRANSIT, NOW) is not None


# ----- the hand mark wins over mails -----
def _mail(status, number=DHL, carrier="dhl", sent=None, **fields) -> MailUpdate:
    return MailUpdate(number, carrier, status, sent or NOW + timedelta(hours=2), **fields)


@pytest.mark.parametrize(
    "status",
    [
        ParcelStatus.IN_TRANSIT,
        ParcelStatus.OUT_FOR_DELIVERY,
        ParcelStatus.AWAITING_PICKUP,
        ParcelStatus.DELIVERED,
        ParcelStatus.EXCEPTION,
    ],
)
def test_no_carrier_mail_changes_a_hand_marked_parcel(status):
    parcel = _waiting()
    mark_received(parcel, NOW)
    before = parcel.to_dict()
    later = NOW + timedelta(hours=3)
    update = _mail(status, eta_date=TODAY + _days(1), delivery_code="4711",
                   delivered_at=later, status_text="Ganz anders", postponed=True)
    assert apply_update({DHL: parcel}, update, later) is None
    assert parcel.to_dict() == before
    assert parcel.delivery_code is None


def test_no_shop_mail_changes_a_hand_marked_order():
    order = _order(status=ParcelStatus.PRE_TRANSIT)
    mark_received(order, NOW)
    before = order.to_dict()
    parcels = {ORDER: order}
    later = NOW + timedelta(hours=3)
    for update in (
        _mail(ParcelStatus.DELIVERED, ORDER, "amazon", title=order.mail_title,
              delivered_at=later),
        _mail(ParcelStatus.IN_TRANSIT, ORDER, "amazon", title=order.mail_title,
              eta_date=TODAY + _days(2), tracking_ref="00340999999999999902",
              tracking_carrier="dhl", shipping_carrier_hint="dhl"),
        _mail(ParcelStatus.DELIVERED, ORDER, "amazon", title=order.mail_title,
              confirmation=True),
    ):
        assert apply_update(parcels, update, later) is None
    assert order.to_dict() == before and list(parcels) == [ORDER]
    # No carrier number was taken: nobody is asked about a parcel that is here.
    assert order.tracking_ref is None and order.poll_target is None


def test_a_carrier_mail_is_never_merged_into_a_hand_marked_order():
    order = _order(first=TODAY, status=ParcelStatus.IN_TRANSIT)
    mark_received(order, NOW)
    parcels = {ORDER: order}
    update = _mail(ParcelStatus.OUT_FOR_DELIVERY, title="Amazon", shop="amazon",
                   eta_date=TODAY)
    change = apply_update(parcels, update, NOW + timedelta(hours=1))
    # The mail's parcel stands on its own; the order stays as marked.
    assert change.created and set(parcels) == {ORDER, DHL}
    assert order.result.status_text == TEXT and order.tracking_ref is None


# ----- the coordinator -----
async def _mail_in(hass, coord, index, update):
    async with coord._lock:
        folder = coord._handle_mail(
            _ParsedMail(message_id=f"<{index}@synthetic.example>", result=MailResult([update])),
            dt_util.utcnow(),
        )
        coord._settle_orders(dt_util.utcnow())
    await hass.async_block_till_done()
    return folder


async def test_marking_fires_the_event_marked_manual_and_sends_nothing(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    coord = await _coordinator(hass, hass_storage, [_waiting()], FakeCarrier(None))
    coord.store.parcels[DHL].next_poll_at = NOW + _days(1)  # not asked by the first refresh
    await _refresh(hass, coord)
    await _start(hass)

    await coord.async_mark_delivered("0034 0999 9999 9999 9901")
    await hass.async_block_till_done()

    parcel = coord.store.parcels[DHL]
    assert parcel.status is ParcelStatus.DELIVERED and parcel.manual_delivered is True
    assert parcel.result.status_text == TEXT
    assert parcel.result.delivered_at == dt_util.utcnow()
    (event,) = events
    assert event.data == {
        "entry_id": coord.entry.entry_id,
        "number": DHL,
        "name": "Oma",
        "carrier": "dhl",
        "carrier_name": "DHL",
        "old_status": "awaiting_pickup",
        "new_status": "delivered",
        "eta_date": None,
        "eta_from": None,
        "eta_to": None,
        "location": None,
        "assumed": False,
        "manual": True,
    }
    assert calls == []  # the user tapped it: no push
    saved = {p["number"]: p for p in hass_storage[DOMAIN]["data"]["parcels"]}
    assert saved[DHL]["manual_delivered"] is True
    assert saved[DHL]["result"]["status_text"] == TEXT
    assert coord.data[DHL].status is ParcelStatus.DELIVERED  # the sensors were told
    await coord.async_shutdown()


async def test_every_other_event_says_manual_false(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    answer = _result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=NOW)
    parcel = _waiting(ParcelStatus.OUT_FOR_DELIVERY)
    parcel.next_poll_at = parcel.last_error = None
    coord = await _coordinator(hass, hass_storage, [parcel], FakeCarrier(answer))
    await _refresh(hass, coord)
    await _start(hass)
    (event,) = events
    assert (event.data["new_status"], event.data["manual"]) == ("delivered", False)
    assert len(calls) == 1  # a real delivery is still pushed
    await coord.async_shutdown()


async def test_unknown_and_delivered_parcels_cannot_be_marked(hass, hass_storage, freezer):
    _calls, events = await _prepared(hass, freezer)
    delivered = _carrier_parcel(mode="manual")
    coord = await _coordinator(hass, hass_storage, [delivered])
    await _refresh(hass, coord)
    await _start(hass)
    before = delivered.to_dict()

    with pytest.raises(KeyError):
        await coord.async_mark_delivered("00340999999999999977")
    with pytest.raises(ValueError, match="already_delivered"):
        await coord.async_mark_delivered(DHL)
    assert coord.store.parcels[DHL].to_dict() == {**before, "order_checked": True}
    assert events == []

    # Marked once, a second tap is refused too.
    freezer.tick(timedelta(minutes=1))
    coord.store.parcels[DHL].result = _result(ParcelStatus.IN_TRANSIT)
    await coord.async_mark_delivered(DHL)
    marked = coord.store.parcels[DHL].to_dict()
    freezer.tick(timedelta(minutes=1))
    with pytest.raises(ValueError, match="already_delivered"):
        await coord.async_mark_delivered(DHL)
    assert coord.store.parcels[DHL].to_dict() == marked
    await coord.async_shutdown()


async def test_a_parcel_without_any_status_fires_from_unknown(hass, hass_storage, freezer):
    _calls, events = await _prepared(hass, freezer)
    bare = Parcel(DHL, None, "auto", None, NOW, NOW, last_error="carrier_not_found",
                  next_poll_at=NOW + _days(1))
    coord = await _coordinator(hass, hass_storage, [bare])
    await _refresh(hass, coord)
    await _start(hass)
    await coord.async_mark_delivered(DHL)
    await hass.async_block_till_done()
    assert [(e.data["old_status"], e.data["new_status"], e.data["manual"]) for e in events] == [
        ("unknown", "delivered", True)
    ]
    await coord.async_shutdown()


async def test_a_mark_while_starting_is_announced_after_the_start(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    hass.set_state(CoreState.starting)
    parcel = _waiting()
    parcel.next_poll_at = NOW + _days(1)
    coord = await _coordinator(hass, hass_storage, [parcel])
    await _refresh(hass, coord)
    await coord.async_mark_delivered(DHL)
    assert events == []
    await _start(hass)
    assert [(e.data["new_status"], e.data["manual"]) for e in events] == [("delivered", True)]
    assert calls == []
    await coord.async_shutdown()


async def test_polls_and_17track_never_revert_the_mark(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(ParcelStatus.IN_TRANSIT, "Unterwegs", first=TODAY + _days(1)))
    parcel = _waiting()
    parcel.next_poll_at = NOW + _days(1)
    parcel.track17, parcel.track17_carrier = True, 7041
    coord = await _coordinator(hass, hass_storage, [parcel], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    await coord.async_mark_delivered(DHL)
    await hass.async_block_till_done()
    marked = coord.store.parcels[DHL].to_dict()
    assert len(events) == 1

    # Ticks and "Aktualisieren" ask nobody about it any more.
    for _ in range(3):
        freezer.tick(timedelta(hours=2))
        await coord.async_refresh_parcels(DHL)
        await hass.async_block_till_done()
    assert carrier.calls == 0
    assert coord.store.parcels[DHL].to_dict() == marked

    # Even an answer that got through (a poll or 17track call under way while the user
    # tapped) changes nothing.
    now = dt_util.utcnow()
    parcel = coord.store.parcels[DHL]
    coord._success(parcel, now, "dhl", carrier.answer)
    delivered = _result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=now)
    coord._success(parcel, now, "dhl", delivered)
    coord._apply_track17(parcel, Track17Info(carrier.answer, False, 7041), now)
    assert parcel.to_dict() == marked
    assert parcel.next_poll_at is None and parcel.track17_next_at is None
    assert len(events) == 1 and calls == []
    await coord.async_shutdown()


async def test_mails_after_the_mark_change_nothing(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    parcel = _waiting()
    parcel.next_poll_at = NOW + _days(1)
    order = _order(status=ParcelStatus.PRE_TRANSIT)
    coord = await _coordinator(hass, hass_storage, [parcel, order])
    await _refresh(hass, coord)
    await _start(hass)
    await coord.async_mark_delivered(DHL)
    await coord.async_mark_delivered(ORDER)
    await hass.async_block_till_done()
    marked = {n: p.to_dict() for n, p in coord.store.parcels.items()}
    assert len(events) == 2

    freezer.tick(timedelta(hours=5))
    sent = dt_util.utcnow()
    folder = await _mail_in(hass, coord, 1, _mail(ParcelStatus.DELIVERED, sent=sent,
                                                  delivered_at=sent))
    assert folder == "Paket-Tracker-Verarbeitet"  # known parcel: filed, not "unrecognised"
    await _mail_in(hass, coord, 2, _mail(ParcelStatus.EXCEPTION, sent=sent))
    await _mail_in(hass, coord, 3, _mail(ParcelStatus.IN_TRANSIT, ORDER, "amazon", sent=sent,
                                         title=order.mail_title, eta_date=TODAY + _days(3)))
    assert {n: p.to_dict() for n, p in coord.store.parcels.items()} == marked
    assert len(events) == 2 and calls == []

    # The order is not closed "without confirmation" later on, and both go after the
    # days delivered parcels are kept.
    freezer.tick(timedelta(days=2))
    await _refresh(hass, coord)
    assert coord.store.parcels[ORDER].assumed_delivered is False
    freezer.tick(timedelta(days=1, hours=1))
    await _refresh(hass, coord)
    assert coord.store.parcels == {}
    assert len(events) == 2
    await coord.async_shutdown()


async def test_a_hand_marked_mail_parcel_closes_no_order(hass, hass_storage, freezer):
    """The mark is about the one entry that was tapped (v0.3.31): the order the parcel
    might belong to stays open and is never frozen by it."""
    _calls, events = await _prepared(hass, freezer)
    parcel = _carrier_parcel(BRAND, ParcelStatus.OUT_FOR_DELIVERY, delivered_at=None)
    parcel.next_poll_at = NOW + _days(1)
    order = _order(first=TODAY, changed=NOW - _days(2))
    coord = await _coordinator(hass, hass_storage, [order, parcel])
    await _refresh(hass, coord)
    await _start(hass)
    await coord.async_mark_delivered(DHL)
    await hass.async_block_till_done()

    assert set(coord.store.parcels) == {ORDER, DHL}
    order = coord.store.parcels[ORDER]
    assert (order.status, order.manual_delivered) == (ParcelStatus.IN_TRANSIT, False)
    assert order.tracking_ref is None
    assert coord.store.parcels[DHL].result.status_text == TEXT
    assert [(e.data["number"], e.data["manual"]) for e in events] == [(DHL, True)]
    # Also not later: the marked parcel is looked at once.
    freezer.tick(timedelta(hours=2))
    await coord.async_refresh_parcels(None)
    assert set(coord.store.parcels) == {ORDER, DHL}
    await coord.async_shutdown()


# ----- service, sensor, diagnostics, trigger -----
@pytest.fixture
async def entry(hass, hass_storage, freezer):
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("Europe/Berlin")
    parcel = _waiting()
    parcel.next_poll_at = NOW + _days(1)
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {"parcels": [parcel.to_dict()], "message_ids": []},
    }
    e = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    e.add_to_hass(hass)
    with patch(FETCH, return_value=_result(ParcelStatus.IN_TRANSIT)):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    return e


async def test_service_marks_the_parcel(hass, entry):
    sensor = f"sensor.paket_{DHL}"
    assert hass.states.get(sensor).attributes["manual_delivered"] is False
    assert hass.services.has_service(DOMAIN, "mark_delivered")
    with patch(FETCH) as fetch:
        await hass.services.async_call(
            DOMAIN, "mark_delivered", {"number": "0034 0999 9999 9999 9901"}, blocking=True
        )
        await hass.async_block_till_done()
    assert fetch.call_count == 0

    state = hass.states.get(sensor)
    assert state.state == "delivered"
    assert state.attributes["manual_delivered"] is True
    assert state.attributes["assumed_delivered"] is False
    assert state.attributes["status_text"] == TEXT
    assert state.attributes["delivered_at"] == NOW.isoformat()
    assert state.attributes["events"][0]["text"] == TEXT
    assert state.attributes["progress"] == 5
    assert state.attributes["pickup_point"] is None and state.attributes["last_error"] is None
    assert hass.states.get("sensor.pakete_zugestellt_heute").state == "1"
    assert hass.states.get("sensor.pakete_unterwegs").state == "0"
    assert hass.states.get("sensor.pakete_abholbereit").state == "0"

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert [p["manual_delivered"] for p in diagnostics["parcels"]] == [True]


async def test_a_cancelled_order_cannot_be_marked(hass, hass_storage, freezer):
    _calls, events = await _prepared(hass, freezer)
    coord = await _coordinator(hass, hass_storage, [_order(status=ParcelStatus.CANCELLED)])
    await _refresh(hass, coord)
    await _start(hass)
    before = coord.store.parcels[ORDER].to_dict()
    with pytest.raises(ValueError, match="cancelled"):
        await coord.async_mark_delivered(ORDER)  # nothing comes: never "delivered today"
    assert coord.store.parcels[ORDER].to_dict() == before
    assert events == []
    await coord.async_shutdown()


async def test_the_service_tells_a_cancelled_order_apart(hass, entry):
    parcel = entry.runtime_data.store.parcels[DHL]
    parcel.result = _result(ParcelStatus.CANCELLED, "Storniert")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "mark_delivered", {"number": DHL}, blocking=True)
    assert (err.value.translation_domain, err.value.translation_key) == (DOMAIN, "cancelled")


async def test_service_errors(hass, entry):
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "mark_delivered", {"number": "00340999999999999977"}, blocking=True
        )
    assert err.value.translation_key == "not_tracked"

    await hass.services.async_call(DOMAIN, "mark_delivered", {"number": DHL}, blocking=True)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "mark_delivered", {"number": DHL}, blocking=True)
    assert err.value.translation_key == "already_delivered"
    assert err.value.translation_domain == DOMAIN

    for bad in ({}, {"number": ""}, {"number": DHL, "name": "x"}):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(DOMAIN, "mark_delivered", bad, blocking=True)


def test_the_delivered_trigger_asks_for_a_delivery_nobody_marked_by_hand():
    assert _event_data("abc", "delivered") == {
        "entry_id": "abc", "new_status": "delivered", "assumed": False, "manual": False,
    }
    assert _event_data("abc", "status_changed") == {"entry_id": "abc"}
    assert _event_data("abc", "exception") == {"entry_id": "abc", "new_status": "exception"}


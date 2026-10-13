"""v0.3.31: corrections after a code review - one box for several orders, carrier numbers
of shop orders and the words of same-status mails."""

from datetime import timedelta

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util

from custom_components.parcel_tracker.carriers.base import BERLIN, NotFound
from custom_components.parcel_tracker.carriers.track17 import Track17Client
from custom_components.parcel_tracker.carriers.ups import UpsCarrier
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.mail.aliexpress import PARCEL_NAME
from custom_components.parcel_tracker.mail.amazon import ATTEMPT_TEXT
from custom_components.parcel_tracker.mail.apply import (
    ASSUMED_TEXT,
    apply_update,
    close_unconfirmed,
)
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)
from custom_components.parcel_tracker.schedule import order_overdue, summarize

from .test_coordinator_notify import _start
from .test_coordinator_track17 import QUOTA, REGISTER, _accepted, _quota, _sent
from .test_order_closing import (
    DHL,
    NOW,
    ORDER,
    TODAY,
    FakeCarrier,
    _coordinator,
    _days,
    _order,
    _prepared,
    _refresh,
    _result,
)

ALI_A, ALI_B, ALI_C = "ALI9999999999990901", "ALI9999999999990902", "ALI9999999999990903"
OTHER_DHL = "00340999999999999902"
OUT = ParcelStatus.OUT_FOR_DELIVERY
MOVING = ParcelStatus.IN_TRANSIT


def _ali(number=ALI_A, ref=DHL, status=MOVING, title="Beispiel-Kabel", **fields) -> Parcel:
    order = _order(number, title, carrier="aliexpress", status=status, **fields)
    order.tracking_ref, order.tracking_carrier = ref, "dhl" if ref else None
    return order


def _local(moment):
    return moment.astimezone(BERLIN)


# ----- C1: one box with several orders is asked, pushed and counted once -----
async def test_one_box_of_several_orders_is_asked_once_per_cycle(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(MOVING, "Unterwegs"))
    orders = [_ali(ALI_A), _ali(ALI_B), _ali(ALI_C)]
    coord = await _coordinator(hass, hass_storage, orders, carrier)
    await _refresh(hass, coord)
    await _start(hass)
    assert carrier.calls == 1
    polled = {p.number: (p.last_poll_at, p.next_poll_at) for p in coord.store.parcels.values()}
    assert len(set(polled.values())) == 1 and polled[ALI_A][0] == NOW

    # The box goes into delivery: every order tells it, one notification names the box.
    carrier.answer = _result(OUT, "In Zustellung", first=TODAY)
    freezer.tick(timedelta(minutes=31))
    await _refresh(hass, coord)
    assert carrier.calls == 2
    assert {p.status for p in coord.store.parcels.values()} == {OUT}
    assert sorted(e.data["number"] for e in events) == [ALI_A, ALI_B, ALI_C]
    assert {e.data["new_status"] for e in events} == {"out_for_delivery"}
    assert [call.data["message"] for call in calls] == [
        "📦 Beispiel-Kabel (AliExpress) ist in Zustellung"
    ]

    # ... and is delivered: again one notification, and nobody is asked any more.
    carrier.answer = _result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=dt_util.utcnow())
    freezer.tick(timedelta(minutes=11))
    await _refresh(hass, coord)
    assert carrier.calls == 3 and len(events) == 6 and len(calls) == 2
    freezer.tick(timedelta(hours=3))
    await _refresh(hass, coord)
    assert carrier.calls == 3
    await coord.async_shutdown()


async def test_a_box_that_is_not_found_is_asked_once_too(hass, hass_storage, freezer):
    await _prepared(hass, freezer)

    class Unknown(FakeCarrier):
        async def fetch(self, number, postcode):
            self.calls += 1
            raise NotFound(number)

    carrier = Unknown()
    coord = await _coordinator(hass, hass_storage, [_ali(ALI_A), _ali(ALI_B)], carrier)
    await _refresh(hass, coord)
    assert carrier.calls == 1
    assert [p.last_error for p in coord.store.parcels.values()] == ["not_found", "not_found"]
    freezer.tick(timedelta(minutes=61))
    await _refresh(hass, coord)
    assert carrier.calls == 2
    await coord.async_shutdown()


async def test_refresh_of_all_parcels_asks_about_a_box_once(hass, hass_storage, freezer):
    await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(MOVING, "Unterwegs"))
    coord = await _coordinator(hass, hass_storage, [_ali(ALI_A), _ali(ALI_B)], carrier)
    await _refresh(hass, coord)
    await coord.async_refresh_parcels(None)
    assert carrier.calls == 2
    await coord.async_shutdown()


async def test_a_hand_marked_order_of_the_box_stays_as_marked(hass, hass_storage, freezer):
    await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(OUT, "In Zustellung"))
    coord = await _coordinator(hass, hass_storage, [_ali(ALI_A), _ali(ALI_B)], carrier)
    coord.store.parcels[ALI_A].next_poll_at = NOW + _days(1)
    coord.store.parcels[ALI_B].next_poll_at = NOW + _days(1)
    await _refresh(hass, coord)
    await coord.async_mark_delivered(ALI_A)
    coord.store.parcels[ALI_B].next_poll_at = None
    await _refresh(hass, coord)
    assert coord.store.parcels[ALI_A].manual_delivered is True
    assert coord.store.parcels[ALI_A].status is ParcelStatus.DELIVERED
    assert coord.store.parcels[ALI_B].status is OUT
    await coord.async_shutdown()


async def test_a_hand_mark_on_one_order_does_not_swallow_the_boxs_delivery(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(MOVING, "Unterwegs"))
    coord = await _coordinator(hass, hass_storage, [_ali(ALI_A), _ali(ALI_B)], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    await coord.async_mark_delivered(ALI_A)
    carrier.answer = _result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=NOW)
    freezer.tick(timedelta(minutes=31))
    await _refresh(hass, coord)
    assert [(e.data["number"], e.data["manual"]) for e in events] == [
        (ALI_A, True), (ALI_B, False),
    ]
    assert [call.data["message"] for call in calls] == [
        "✅ Beispiel-Kabel (AliExpress) wurde zugestellt"
    ]
    await coord.async_shutdown()


async def test_changes_found_while_starting_are_one_notification_for_the_box(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    hass.set_state(CoreState.starting)
    carrier = FakeCarrier(_result(OUT, "In Zustellung", first=TODAY))
    coord = await _coordinator(hass, hass_storage, [_ali(ALI_A), _ali(ALI_B)], carrier)
    await _refresh(hass, coord)
    assert events == [] and calls == []
    await _start(hass)
    assert sorted(e.data["number"] for e in events) == [ALI_A, ALI_B]
    assert len(calls) == 1
    await coord.async_shutdown()


async def test_the_same_status_is_pushed_again_after_a_step_back(hass, hass_storage, freezer):
    """In delivery, back on its way, in delivery again the next day: two notifications."""
    calls, _events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(MOVING, "Unterwegs"))
    coord = await _coordinator(hass, hass_storage, [_ali(ALI_A), _ali(ALI_B)], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    for answer in (_result(OUT, "In Zustellung"), _result(MOVING, "Unterwegs"),
                   _result(OUT, "In Zustellung")):
        carrier.answer = answer
        freezer.tick(timedelta(minutes=61))
        await _refresh(hass, coord)
    assert len(calls) == 2
    await coord.async_shutdown()


async def test_a_parcel_mail_about_several_orders_is_one_notification(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    orders = [_ali(ALI_A, changed=NOW - _days(1)), _ali(ALI_B, changed=NOW - _days(1))]
    for order in orders:
        order.next_poll_at = NOW + _days(1)
    coord = await _coordinator(hass, hass_storage, orders)
    await _refresh(hass, coord)
    await _start(hass)
    updates = [
        MailUpdate(number, "aliexpress", OUT, _local(NOW), tracking_ref=DHL,
                   tracking_carrier="dhl")
        for number in (ALI_A, ALI_B)
    ]
    async with coord._lock:
        coord._handle_mail(
            _ParsedMail(message_id="<1@synthetic.example>", result=MailResult(updates)), NOW
        )
    await hass.async_block_till_done()
    assert [e.data["number"] for e in events] == [ALI_A, ALI_B]
    assert len(calls) == 1
    await coord.async_shutdown()


def test_a_box_counts_once_in_the_lists_of_today():
    day = dict(first=TODAY, last=TODAY)
    sure = [_ali(ALI_A, status=OUT, **day), _ali(ALI_B, status=OUT, **day)]
    window = dict(first=TODAY - _days(1), last=TODAY + _days(1))
    possible = [_ali(ALI_A, OTHER_DHL, **window), _ali(ALI_B, OTHER_DHL, **window)]
    alone = _ali(ALI_C, None, status=OUT, **day)
    summary = summarize([*sure, *possible, alone], TODAY, BERLIN)
    assert summary.sure == [sure[0], alone]
    assert summary.possible == [possible[0]]
    # Every order is still on its way.
    assert len(summary.active) == 5
    for order in sure:
        order.result = _result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=NOW)
    assert summarize(sure, TODAY, BERLIN).delivered_today == [sure[0]]


def test_orders_without_a_carrier_number_are_counted_each():
    orders = [_ali(ALI_A, None, status=OUT, first=TODAY), _ali(ALI_B, None, status=OUT,
                                                                 first=TODAY)]
    assert summarize(orders, TODAY, BERLIN).sure == orders


async def test_17track_registers_the_number_of_a_box_once(hass, hass_storage, freezer):
    await _prepared(hass, freezer)
    coord = await _coordinator(hass, hass_storage, [_ali(ALI_A), _ali(ALI_B)])
    async with aiohttp.ClientSession() as session:
        coord.track17 = Track17Client(session, "synthetic-17track-key")
        with aioresponses() as m:
            m.post(REGISTER, payload=_accepted(DHL, 7041))
            m.post(QUOTA, payload=_quota(150), repeat=True)
            await coord.async_track17(ALI_A)
            await coord.async_track17(ALI_B)
            assert len(_sent(m, REGISTER)) == 1
    first, second = coord.store.parcels[ALI_A], coord.store.parcels[ALI_B]
    assert (second.track17, second.track17_carrier) == (True, 7041)
    assert second.track17_next_at == first.track17_next_at
    await coord.async_shutdown()


# ----- C2: an order whose carrier cannot be asked is closed like one without a number
# (what "cannot be asked" means: see test_review_second) -----
def _old_order(error=None, polled=True) -> Parcel:
    order = _ali(first=TODAY - _days(9), changed=NOW - _days(12))
    order.last_poll_at = NOW - timedelta(hours=1) if polled else None
    order.last_error = error
    return order


def test_an_order_whose_days_are_not_over_is_never_overdue_whatever_the_carrier_says():
    order = _ali(first=TODAY, changed=NOW - _days(1))
    order.last_error = "not_found"
    assert not order_overdue(order, TODAY, BERLIN, True)
    assert not order_overdue(order, TODAY, BERLIN, False)


async def test_order_with_a_ups_number_and_no_ups_api_is_closed(hass, hass_storage, freezer):
    _calls, events = await _prepared(hass, freezer)
    order = _old_order(polled=False)
    order.tracking_ref, order.tracking_carrier = "1Z999AA10123456784", "ups"
    coord = await _coordinator(hass, hass_storage, [order])
    assert "ups" not in coord.carriers and UpsCarrier.key == "ups"
    await _refresh(hass, coord)
    await _start(hass)
    closed = coord.store.parcels[ALI_A]
    assert (closed.status, closed.assumed_delivered) == (ParcelStatus.DELIVERED, True)
    assert closed.result.status_text == ASSUMED_TEXT
    assert [(e.data["number"], e.data["assumed"]) for e in events] == [(ALI_A, True)]
    await coord.async_shutdown()


async def test_order_whose_carrier_answers_stays_open(hass, hass_storage, freezer):
    await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(MOVING, "Unterwegs"))
    coord = await _coordinator(hass, hass_storage, [_old_order()], carrier)
    await _refresh(hass, coord)
    assert coord.store.parcels[ALI_A].status is MOVING
    await coord.async_shutdown()


# ----- C3: the second parcel of an order -----
def _parcel_mail(ref, number=ALI_A, words="Im Zielland angekommen") -> MailUpdate:
    return MailUpdate(number, "aliexpress", MOVING, _local(NOW), tracking_ref=ref,
                      tracking_carrier="dhl", status_text=words)


def test_a_second_carrier_number_of_an_order_is_a_parcel_of_its_own():
    parcels = {ALI_A: _ali(ALI_A), ALI_B: _ali(ALI_B, None)}
    change = apply_update(parcels, _parcel_mail(OTHER_DHL), NOW)
    assert set(parcels) == {ALI_A, ALI_B, OTHER_DHL}
    assert change is not None and change.parcel is parcels[ALI_A]
    assert parcels[ALI_A].tracking_ref == DHL  # the first number stays the order's
    extra = parcels[OTHER_DHL]
    assert (extra.carrier, extra.carrier_mode, extra.name) == ("dhl", "mail", PARCEL_NAME)
    assert (extra.status, extra.result.status_text) == (MOVING, "Im Zielland angekommen")
    assert extra.name_manual is False and extra.tracking_ref is None
    # Never folded into another order of the shop: its own order has a number already.
    assert extra.order_checked is True and parcels[ALI_B].tracking_ref is None
    # The same mail once more makes no third entry.
    apply_update(parcels, _parcel_mail(OTHER_DHL), NOW)
    assert set(parcels) == {ALI_A, ALI_B, OTHER_DHL}


def test_no_parcel_of_its_own_for_a_number_that_is_tracked_already():
    parcels = {ALI_A: _ali(ALI_A), ALI_B: _ali(ALI_B, OTHER_DHL)}
    apply_update(parcels, _parcel_mail(OTHER_DHL), NOW)
    assert set(parcels) == {ALI_A, ALI_B}
    parcels = {ALI_A: _ali(ALI_A)}
    apply_update(parcels, _parcel_mail(DHL), NOW)  # its own number again
    assert set(parcels) == {ALI_A}


def test_an_amazon_order_keeps_its_one_number():
    order = _order()
    order.tracking_ref, order.tracking_carrier = DHL, "dhl"
    parcels = {ORDER: order}
    mail = MailUpdate(ORDER, "amazon", MOVING, _local(NOW), title=order.mail_title,
                      tracking_ref=OTHER_DHL, tracking_carrier="dhl")
    apply_update(parcels, mail, NOW)
    assert set(parcels) == {ORDER} and order.tracking_ref == DHL


# ----- C7: the order's number is tracked on its own already -----
def _standalone(mode="mail", status=OUT, **fields) -> Parcel:
    events = [TrackingEvent(NOW - timedelta(hours=1), "In Zustellung", "Bonn")]
    result = TrackingResult(status, "Die Sendung wird heute zugestellt.", TODAY, None, None,
                            "Bonn", None, None, None, events)
    return Parcel(DHL, "dhl", mode, "AliExpress-Sendung", NOW - _days(2),
                  NOW - timedelta(hours=1), last_poll_at=NOW - timedelta(minutes=5),
                  next_poll_at=NOW + timedelta(minutes=5), result=result, **fields)


def test_a_parcel_a_mail_made_is_folded_into_the_order_that_names_its_number():
    parcel = _standalone()
    carrier_result = parcel.result
    parcels = {ALI_A: _ali(ALI_A, None, status=ParcelStatus.PRE_TRANSIT), DHL: parcel}
    change = apply_update(parcels, _parcel_mail(DHL), NOW)
    order = parcels[ALI_A]
    assert list(parcels) == [ALI_A]
    assert (order.tracking_ref, order.tracking_carrier) == (DHL, "dhl")
    # The carrier's result, as if the number had been the order's from the start.
    assert order.status is OUT and order.result.location == "Bonn"
    assert order.result.events[-1] == carrier_result.events[0]
    assert order.last_poll_at == NOW - timedelta(minutes=5) and order.next_poll_at is None
    # "Bestellt" -> "In Zustellung" is the order's own step: it is told as that (the
    # coordinator sends no second notification for the box, see below).
    assert change is not None and change.old_status is ParcelStatus.PRE_TRANSIT
    assert order.unannounced_from is None


def test_such_a_fold_never_loses_an_announcement_that_still_waits():
    """The parcel's "in Zustellung" was not told yet: the order's change tells it."""
    parcel = _standalone(unannounced_from=MOVING)
    parcels = {ALI_A: _ali(ALI_A, None), DHL: parcel}
    change = apply_update(parcels, _parcel_mail(DHL), NOW)
    assert list(parcels) == [ALI_A]
    assert (change.old_status, parcels[ALI_A].status) == (MOVING, OUT)


def test_a_new_order_takes_its_parcel_in_as_well():
    parcels = {DHL: _standalone()}
    change = apply_update(parcels, _parcel_mail(DHL), NOW)
    assert list(parcels) == [ALI_A] and change.created
    assert (parcels[ALI_A].tracking_ref, parcels[ALI_A].status) == (DHL, OUT)


def test_an_order_closed_on_its_own_follows_the_carriers_parcel_it_takes_in():
    order = _ali(ALI_A, None, first=TODAY - _days(9), changed=NOW - _days(12))
    close_unconfirmed(order, NOW - _days(1))
    parcels = {ALI_A: order, DHL: _standalone()}
    apply_update(parcels, _parcel_mail(DHL), NOW)
    assert list(parcels) == [ALI_A]
    assert (order.status, order.assumed_delivered, order.tracking_ref) == (OUT, False, DHL)


@pytest.mark.parametrize("mode", ["manual", "auto"])
def test_a_parcel_added_by_hand_wins_and_the_order_does_not_take_the_number(mode):
    parcel = _standalone(mode)
    before = parcel.to_dict()
    parcels = {ALI_A: _ali(ALI_A, None), DHL: parcel}
    apply_update(parcels, _parcel_mail(DHL), NOW)
    assert set(parcels) == {ALI_A, DHL} and parcel.to_dict() == before
    # No second lookup of the same number: the order stays without it.
    assert parcels[ALI_A].tracking_ref is None and parcels[ALI_A].poll_target is None


def test_a_hand_marked_parcel_is_left_alone_too():
    parcel = _standalone(manual_delivered=True)
    parcels = {ALI_A: _ali(ALI_A, None), DHL: parcel}
    apply_update(parcels, _parcel_mail(DHL), NOW)
    assert set(parcels) == {ALI_A, DHL} and parcels[ALI_A].tracking_ref is None


async def test_order_and_parcel_of_one_number_are_asked_and_told_once(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(OUT, "In Zustellung", first=TODAY))
    parcel = _standalone(status=MOVING)
    parcel.next_poll_at = None
    order = _ali(ALI_A, None, changed=NOW - _days(1))
    coord = await _coordinator(hass, hass_storage, [order, parcel], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    # The parcel tells "in Zustellung" itself, with its own notification.
    assert carrier.calls == 1 and len(calls) == 1
    assert [(e.data["number"], e.data["new_status"]) for e in events] == [
        (DHL, "out_for_delivery")
    ]
    async with coord._lock:
        coord._handle_mail(
            _ParsedMail(message_id="<1@synthetic.example>",
                        result=MailResult([_parcel_mail(DHL)])),
            dt_util.utcnow(),
        )
        coord._settle_orders(dt_util.utcnow())
    await hass.async_block_till_done()
    # Folded into the order: one entry. The order tells its own step with an event, but
    # no second notification goes out for the box.
    assert list(coord.store.parcels) == [ALI_A]
    assert coord.store.parcels[ALI_A].status is OUT
    assert [(e.data["number"], e.data["new_status"]) for e in events][1:] == [
        (ALI_A, "out_for_delivery")
    ]
    assert len(calls) == 1
    carrier.answer = _result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=NOW)
    freezer.tick(timedelta(minutes=11))
    await _refresh(hass, coord)
    assert carrier.calls == 2
    assert [(e.data["number"], e.data["new_status"]) for e in events] == [
        (DHL, "out_for_delivery"),
        (ALI_A, "out_for_delivery"),
        (ALI_A, "delivered"),
    ]
    assert [call.data["message"] for call in calls][1:] == [
        "✅ Beispiel-Kabel (AliExpress) wurde zugestellt"
    ]
    await coord.async_shutdown()


# ----- C10: words and history lines only from a mail that is not older than the history -----
def _shop_order(text, at, status=MOVING) -> Parcel:
    order = _order(first=TODAY + _days(1), status=status, changed=at)
    order.result.status_text = text
    order.result.events = [TrackingEvent(at, text, None)]
    return order


def _amazon(sent, status=MOVING, **fields) -> MailUpdate:
    return MailUpdate(ORDER, "amazon", status, _local(sent), **fields)


def test_an_older_mail_with_its_own_words_does_not_replace_newer_words():
    """Read four days late: the carrier's newer text and the top of the history stay."""
    order = _shop_order("Im Zustellfahrzeug", NOW - timedelta(hours=2), OUT)
    order.tracking_ref, order.tracking_carrier = DHL, "dhl"
    before = order.result.to_dict()
    old = _amazon(NOW - _days(4), OUT, status_text="Wird heute zugestellt")
    assert apply_update({ORDER: order}, old, NOW) is None
    assert order.result.to_dict() == before


def test_a_newer_mail_with_its_own_words_still_replaces_them():
    order = _shop_order("Versendet", NOW - _days(1))
    change = apply_update({ORDER: order}, _amazon(NOW, status_text="Im Zielland"), NOW)
    assert change is not None and order.result.status_text == "Im Zielland"
    assert [e.text for e in order.result.events] == ["Im Zielland", "Versendet"]


def test_a_later_plain_mail_ends_the_words_of_a_postponed_delivery():
    """ "Zustellung versucht" told one moment: the next "Versendet" mail is plain again."""
    order = _shop_order(ATTEMPT_TEXT, NOW - _days(1))
    change = apply_update({ORDER: order}, _amazon(NOW), NOW)
    assert change is not None and order.result.status_text == "Versendet"
    assert [(e.timestamp, e.text) for e in order.result.events] == [
        (_local(NOW), "Versendet"),
        (NOW - _days(1), ATTEMPT_TEXT),
    ]


def test_an_older_plain_mail_leaves_the_postponed_delivery_as_it_is():
    order = _shop_order(ATTEMPT_TEXT, NOW - _days(1))
    before = order.result.to_dict()
    assert apply_update({ORDER: order}, _amazon(NOW - _days(3)), NOW) is None
    assert order.result.to_dict() == before


def test_a_mail_that_only_repeats_the_status_still_keeps_other_words():
    order = _shop_order("Im Zielland angekommen", NOW - _days(1))
    assert apply_update({ORDER: order}, _amazon(NOW), NOW) is None
    assert order.result.status_text == "Im Zielland angekommen"


def test_history_lines_without_a_time_zone_never_break_a_mail():
    order = _shop_order("Versendet", NOW - _days(1))
    order.result.events = [TrackingEvent(NOW.replace(tzinfo=None), "Versendet", None)]
    change = apply_update({ORDER: order}, _amazon(NOW, status_text="Im Zielland"), NOW)
    assert change is not None and order.result.status_text == "Im Zielland"

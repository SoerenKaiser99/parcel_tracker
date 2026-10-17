"""v0.3.32: four leftovers of the review of v0.3.31.

An order closed on the shop's word stays closed while its carrier tells nothing newer; a
delivery that was announced with the carrier's parcel is not pushed again by the order
after a restart; mails that only repeated a status count as known; and a "zugestellt"
mail for an unknown number is only merged into an order whose days fit.
"""

from datetime import datetime, time, timedelta

import pytest
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util

from custom_components.parcel_tracker.carriers.track17 import Track17Info
from custom_components.parcel_tracker.const import FOLD_DAYS_AFTER, FOLD_DAYS_BEFORE
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.mail.aliexpress import CONFIRMED_TEXT
from custom_components.parcel_tracker.mail.apply import apply_update, close_unconfirmed
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingEvent

from .test_coordinator_notify import _start
from .test_order_closing import (
    BERLIN,
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
from .test_review_second import Unknown, _old
from .test_review_shared import ALI_A, MOVING, OUT, _ali, _local, _parcel_mail

DONE = ParcelStatus.DELIVERED
STUCK = NOW - _days(6)


def _moving(*events, status=MOVING, text="Unterwegs"):
    """A carrier's answer with a dated history (newest first)."""
    lines = [TrackingEvent(at, words, "Bonn") for at, words in events]
    return _result(status, text, events=lines)


def _stuck_order() -> Parcel:
    """An AliExpress order whose carrier has said "Unterwegs" for days."""
    order = _ali(ALI_A, first=TODAY - _days(2), changed=STUCK)
    order.result = _moving((STUCK, "Unterwegs"))
    return order


def _confirmation(sent=NOW) -> MailUpdate:
    return MailUpdate(ALI_A, "aliexpress", DONE, _local(sent), status_text=CONFIRMED_TEXT,
                      confirmation=True)


async def _confirmed(hass, hass_storage, carrier):
    """The order above, asked once and then closed by the shop's confirmation."""
    coord = await _coordinator(hass, hass_storage, [_stuck_order()], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    async with coord._lock:
        coord._handle_mail(
            _ParsedMail(message_id="<c@synthetic.example>",
                        result=MailResult([_confirmation()])),
            dt_util.utcnow(),
        )
    await hass.async_block_till_done()
    order = coord.store.parcels[ALI_A]
    assert (order.status, order.assumed_delivered) == (DONE, True)
    return coord, order


# ----- L1: a closed order is not reopened by an answer that tells nothing newer -----
async def test_the_same_old_answer_does_not_reopen_an_order_the_shop_confirmed(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_moving((STUCK, "Unterwegs")))
    coord, order = await _confirmed(hass, hass_storage, carrier)
    closed = order.to_dict()
    told = len(events)
    for _ in range(3):
        freezer.tick(timedelta(hours=2))
        await _refresh(hass, coord)
    # Asked again each time, and the answer is the old one: closed it stays.
    assert carrier.calls == 4
    assert (order.status, order.assumed_delivered) == (DONE, True)
    assert order.result.status_text == CONFIRMED_TEXT
    assert order.last_change_at == NOW  # the days it is kept count from the closing
    assert order.result.to_dict() == closed["result"]
    assert (order.last_error, order.error_streak) == (None, 0)
    assert order.next_poll_at is not None and order.next_poll_at > dt_util.utcnow()
    assert len(events) == told and calls == []
    await coord.async_shutdown()


async def test_an_event_after_the_closing_reopens_the_order(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_moving((STUCK, "Unterwegs")))
    coord, order = await _confirmed(hass, hass_storage, carrier)
    told = len(events)
    freezer.tick(timedelta(hours=2))
    carrier.answer = _moving((dt_util.utcnow(), "Im Zustellzentrum"), (STUCK, "Unterwegs"))
    await _refresh(hass, coord)
    assert (order.status, order.assumed_delivered) == (MOVING, False)
    assert [(e.data["old_status"], e.data["new_status"]) for e in events[told:]] == [
        ("delivered", "in_transit")
    ]
    await coord.async_shutdown()


async def test_a_new_status_without_a_newer_line_reopens_the_order_too(
    hass, hass_storage, freezer
):
    """DPD dates its lines by the day only: the status is what tells the change."""
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_moving((STUCK, "Unterwegs")))
    coord, order = await _confirmed(hass, hass_storage, carrier)
    freezer.tick(timedelta(hours=2))
    await _refresh(hass, coord)  # the old answer once more, seen while closed
    assert order.assumed_delivered is True
    freezer.tick(timedelta(hours=2))
    carrier.answer = _moving((STUCK, "Unterwegs"), status=OUT, text="In Zustellung")
    await _refresh(hass, coord)
    assert (order.status, order.assumed_delivered) == (OUT, False)
    assert [call.data["message"] for call in calls] == [
        "📦 Beispiel-Kabel (AliExpress) ist in Zustellung"
    ]
    await coord.async_shutdown()


async def test_a_stuck_carrier_does_not_reopen_the_order_after_a_restart(
    hass, hass_storage, freezer
):
    """What the carrier said when the order was closed is stored with the order."""
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_moving((STUCK, "Unterwegs")))
    coord, order = await _confirmed(hass, hass_storage, carrier)
    assert order.carrier_status is MOVING
    async with coord._lock:
        await coord.store.async_save()
    stored = hass_storage["parcel_tracker"]["data"]["parcels"]
    assert stored[0]["carrier_status"] == "in_transit"
    await coord.async_shutdown()
    told = len(events)
    again = await _coordinator(hass, hass_storage, [Parcel.from_dict(p) for p in stored], carrier)
    for _ in range(2):
        freezer.tick(timedelta(hours=2))
        await _refresh(hass, again)
    order = again.store.parcels[ALI_A]
    assert carrier.calls >= 3
    assert (order.status, order.assumed_delivered) == (DONE, True)
    assert len(events) == told and calls == []
    # ... and a new status right after a restart opens it, without any newer line.
    stored = [p.to_dict() for p in again.store.parcels.values()]
    await again.async_shutdown()
    carrier.answer = _moving((STUCK, "Unterwegs"), status=OUT, text="In Zustellung")
    third = await _coordinator(hass, hass_storage, [Parcel.from_dict(p) for p in stored], carrier)
    freezer.tick(timedelta(hours=2))
    await _refresh(hass, third)
    await _start(hass)
    order = third.store.parcels[ALI_A]
    assert (order.status, order.assumed_delivered) == (OUT, False)
    await third.async_shutdown()


async def test_the_first_answer_ever_opens_a_closed_order_also_with_a_day_only_line(
    hass, hass_storage, freezer
):
    """Closed two hours ago while the carrier did not know the number. Its first answer
    is "In Zustellung", with a line dated 00:00 today, as DPD dates them."""
    calls, events = await _prepared(hass, freezer)
    carrier = Unknown()
    order = _old()
    close_unconfirmed(order, NOW - timedelta(hours=2))
    order.next_poll_at = None
    coord = await _coordinator(hass, hass_storage, [order], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    order = coord.store.parcels[ALI_A]
    assert (order.assumed_delivered, order.carrier_status) == (True, None)
    midnight = datetime.combine(TODAY, time(0), BERLIN)
    carrier.answer = _moving((midnight, "In Zustellung"), status=OUT, text="In Zustellung")
    freezer.tick(timedelta(minutes=61))
    await _refresh(hass, coord)
    assert (order.status, order.assumed_delivered) == (OUT, False)
    assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
        ("delivered", "out_for_delivery")
    ]
    assert [call.data["message"] for call in calls] == [
        "📦 Beispiel-Kabel (AliExpress) ist in Zustellung"
    ]
    await coord.async_shutdown()


async def test_a_day_only_line_of_the_closing_day_counts_as_newer(hass, hass_storage, freezer):
    """The same status as before, but a line dated 00:00 on the day of the closing: the
    carrier may well have written it after the closing."""
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_moving((STUCK, "Unterwegs")))
    coord, order = await _confirmed(hass, hass_storage, carrier)
    yesterday = datetime.combine(TODAY - _days(1), time(0), BERLIN)
    carrier.answer = _moving((yesterday, "Im Depot"), (STUCK, "Unterwegs"))
    freezer.tick(timedelta(hours=2))
    await _refresh(hass, coord)
    assert order.assumed_delivered is True  # a line of the day before is not newer
    today = datetime.combine(TODAY, time(0), BERLIN)
    carrier.answer = _moving((today, "Im Zustelldepot"), (yesterday, "Im Depot"))
    freezer.tick(timedelta(hours=2))
    await _refresh(hass, coord)
    assert (order.status, order.assumed_delivered) == (MOVING, False)
    await coord.async_shutdown()


async def test_a_17track_answer_with_a_new_status_opens_the_order_without_a_newer_line(
    hass, hass_storage, freezer
):
    _calls, events = await _prepared(hass, freezer)
    order = _stuck_order()
    order.tracking_ref, order.tracking_carrier = "H1000999999999999901", "hermes"
    close_unconfirmed(order, NOW - _days(1), CONFIRMED_TEXT)
    order.track17, order.track17_carrier = True, 100031
    order.track17_result = _moving((STUCK, "In transit"))
    coord = await _coordinator(hass, hass_storage, [order])
    await _refresh(hass, coord)
    await _start(hass)
    order = coord.store.parcels[ALI_A]
    out = Track17Info(_moving((STUCK, "In transit"), status=OUT), False, 100031)
    coord._apply_track17(order, out, dt_util.utcnow())
    assert (order.status, order.assumed_delivered) == (OUT, False)
    await coord.async_shutdown()


async def test_a_live_delivery_still_replaces_the_shops_word(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_moving((STUCK, "Unterwegs")))
    coord, order = await _confirmed(hass, hass_storage, carrier)
    came = STUCK + _days(1)  # the carrier tells it late; older than the closing
    carrier.answer = _result(DONE, "Zugestellt", delivered_at=came,
                             events=[TrackingEvent(came, "Zugestellt", "Bonn")])
    freezer.tick(timedelta(hours=2))
    await _refresh(hass, coord)
    assert (order.status, order.assumed_delivered) == (DONE, False)
    assert order.result.delivered_at == came
    await coord.async_shutdown()


async def test_the_same_old_17track_answer_does_not_reopen_the_order_either(
    hass, hass_storage, freezer
):
    _calls, events = await _prepared(hass, freezer)
    order = _stuck_order()
    order.tracking_ref, order.tracking_carrier = "H1000999999999999901", "hermes"
    close_unconfirmed(order, NOW - _days(1), CONFIRMED_TEXT)
    order.track17, order.track17_carrier = True, 100031
    order.track17_result = _moving((STUCK, "In transit"))  # what 17track said before
    coord = await _coordinator(hass, hass_storage, [order])
    await _refresh(hass, coord)
    await _start(hass)
    order = coord.store.parcels[ALI_A]
    closed = order.result.to_dict()
    old = Track17Info(_moving((STUCK, "In transit")), False, 100031)
    for _ in range(2):
        coord._apply_track17(coord.store.parcels[ALI_A], old, dt_util.utcnow())
        assert (order.status, order.assumed_delivered) == (DONE, True)
        assert order.result.to_dict() == closed
        assert order.track17_next_at is not None  # asked again
    assert events == []
    newer = Track17Info(_moving((NOW, "Out for delivery"), (STUCK, "In transit"), status=OUT),
                        False, 100031)
    coord._apply_track17(order, newer, dt_util.utcnow())
    assert (order.status, order.assumed_delivered) == (OUT, False)
    await coord.async_shutdown()


# ----- L2: a delivery told with the carrier's parcel is not pushed again by the order -----
def _delivered_parcel(**fields) -> Parcel:
    came = NOW - timedelta(hours=3)
    result = _result(DONE, "Die Sendung wurde zugestellt.", delivered_at=came,
                     events=[TrackingEvent(came, "Zugestellt", "Bonn")])
    return Parcel(DHL, "dhl", "mail", "AliExpress-Sendung", NOW - _days(2), came,
                  last_poll_at=came, result=result, order_checked=True, **fields)


def test_apply_tells_that_the_folded_delivery_was_announced_already():
    parcels = {ALI_A: _ali(ALI_A, None), DHL: _delivered_parcel(delivery_announced=True)}
    change = apply_update(parcels, _parcel_mail(DHL), NOW)
    assert list(parcels) == [ALI_A]
    assert (change.old_status, parcels[ALI_A].status, change.told) == (MOVING, DONE, True)


@pytest.mark.parametrize(
    "parcel",
    [
        # its delivery still waits to be told
        _delivered_parcel(unannounced_from=OUT, delivery_announced=True),
        # delivered was its first status: nobody was ever told
        _delivered_parcel(delivery_announced=False),
        # stored by an older version with a single line: it never had another status
        _delivered_parcel(),
        Parcel(DHL, "dhl", "mail", None, NOW, NOW, order_checked=True,
               result=_result(OUT, "In Zustellung")),  # not delivered at all
    ],
    ids=["waiting", "never-told", "old-store-one-line", "not-delivered"],
)
def test_apply_tells_nothing_like_that_for_any_other_fold(parcel):
    parcels = {ALI_A: _ali(ALI_A, None), DHL: parcel}
    change = apply_update(parcels, _parcel_mail(DHL), NOW)
    assert list(parcels) == [ALI_A] and change.told is False


def test_a_mail_that_folds_nothing_tells_nothing_like_that():
    order = _ali(ALI_A)
    change = apply_update({ALI_A: order}, _parcel_mail(DHL, words="Neu"), NOW)
    assert change is not None and change.told is False


async def test_after_a_restart_the_order_does_not_push_the_parcels_delivery_again(
    hass, hass_storage, freezer
):
    """The DHL parcel was delivered and pushed before the restart; the push memory of
    the box is gone. Now AliExpress names the number for its order."""
    calls, events = await _prepared(hass, freezer)
    order = _ali(ALI_A, None, changed=NOW - _days(1))
    parcel = _delivered_parcel(delivery_announced=True)
    coord = await _coordinator(hass, hass_storage, [order, parcel])
    await _refresh(hass, coord)
    await _start(hass)
    assert set(coord.store.parcels) == {ALI_A, DHL} and calls == [] and events == []
    assert coord._box_told == {}
    async with coord._lock:
        coord._handle_mail(
            _ParsedMail(message_id="<1@synthetic.example>",
                        result=MailResult([_parcel_mail(DHL)])),
            dt_util.utcnow(),
        )
        coord._settle_orders(dt_util.utcnow())
    await hass.async_block_till_done()
    assert list(coord.store.parcels) == [ALI_A]
    assert coord.store.parcels[ALI_A].status is DONE
    # The order's own step is an event as before; nothing is pushed a second time.
    assert [(e.data["number"], e.data["old_status"], e.data["new_status"]) for e in events] == [
        (ALI_A, "in_transit", "delivered")
    ]
    assert calls == []
    await coord.async_shutdown()


def test_a_parcel_of_an_older_version_counts_as_told_if_it_had_a_status_before():
    """No mark stored: its history tells whether "delivered" was a change."""
    parcel = _delivered_parcel()
    parcel.result.events.append(TrackingEvent(NOW - _days(1), "Unterwegs", "Bonn"))
    stored = parcel.to_dict()
    del stored["delivery_announced"]
    parcel = Parcel.from_dict(stored)
    assert parcel.delivery_announced is None
    parcels = {ALI_A: _ali(ALI_A, None), DHL: parcel}
    assert apply_update(parcels, _parcel_mail(DHL), NOW).told is True


def test_the_mark_is_stored_in_all_three_states():
    for mark in (True, False, None):
        parcel = _delivered_parcel(delivery_announced=mark)
        assert Parcel.from_dict(parcel.to_dict()).delivery_announced is mark


async def test_a_delivery_that_is_announced_leaves_its_mark(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    parcel = Parcel(DHL, "dhl", "manual", "Paket", NOW - _days(1), NOW - _days(1),
                    result=_result(MOVING, "Unterwegs"))
    carrier = FakeCarrier(_result(DONE, "Zugestellt", delivered_at=NOW))
    coord = await _coordinator(hass, hass_storage, [parcel], carrier)
    assert coord.store.parcels[DHL].delivery_announced is None
    await _refresh(hass, coord)
    await _start(hass)
    assert len(calls) == 1 and coord.store.parcels[DHL].delivery_announced is True
    assert hass_storage["parcel_tracker"]["data"]["parcels"][0]["delivery_announced"] is True
    await coord.async_shutdown()


async def test_a_delivery_nobody_was_told_about_is_pushed_by_the_order_in_a_later_import(
    hass, hass_storage, freezer
):
    """A carrier's "zugestellt" mail for a number nobody knows makes a delivered parcel
    without a word (a first status is no news). Days later the shop names that number."""
    calls, events = await _prepared(hass, freezer)
    order = _ali(ALI_A, None, changed=NOW - _days(1))
    coord = await _coordinator(hass, hass_storage, [order])
    await _refresh(hass, coord)
    await _start(hass)
    delivered = MailUpdate(DHL, "dhl", DONE, _local(NOW), delivered_at=_local(NOW))
    async with coord._lock:
        coord._handle_mail(
            _ParsedMail(message_id="<1@synthetic.example>", result=MailResult([delivered])), NOW
        )
        coord._settle_orders(NOW)
        await coord.store.async_save()
    await hass.async_block_till_done()
    assert set(coord.store.parcels) == {ALI_A, DHL} and events == [] and calls == []
    assert coord.store.parcels[DHL].delivery_announced is False
    stored = hass_storage["parcel_tracker"]["data"]["parcels"]
    await coord.async_shutdown()
    # ... after a restart in between, so nothing is left in memory.
    again = await _coordinator(hass, hass_storage, [Parcel.from_dict(p) for p in stored])
    await _refresh(hass, again)
    freezer.tick(timedelta(hours=5))
    async with again._lock:
        again._handle_mail(
            _ParsedMail(message_id="<2@synthetic.example>",
                        result=MailResult([_parcel_mail(DHL, words=None)])),
            dt_util.utcnow(),
        )
        again._settle_orders(dt_util.utcnow())
    await hass.async_block_till_done()
    assert list(again.store.parcels) == [ALI_A]
    assert [(e.data["number"], e.data["old_status"], e.data["new_status"]) for e in events] == [
        (ALI_A, "in_transit", "delivered")
    ]
    assert [call.data["message"] for call in calls] == [
        "✅ Beispiel-Kabel (AliExpress) wurde zugestellt"
    ]
    await again.async_shutdown()


# ----- L3: mails that only repeated a status are known, too -----
def _repeated_then_closed() -> Parcel:
    """An Amazon order "Versendet" 9 days ago; a mail 3 days ago only repeated that."""
    order = _order(first=TODAY - _days(5), changed=NOW - _days(9))
    order.result.events = [TrackingEvent(_local(NOW - _days(9)), "Versendet", None)]
    parcels = {ORDER: order}
    again = MailUpdate(ORDER, "amazon", MOVING, _local(NOW - _days(3)))
    lines = list(order.result.events)
    apply_update(parcels, again, NOW - _days(3))
    assert order.result.events == lines  # no line of its own in the history
    close_unconfirmed(order, NOW - _days(1))
    return order


def test_the_time_of_the_newest_mail_is_stored_with_the_order():
    order = _repeated_then_closed()
    assert order.last_mail_at == NOW - _days(3)
    stored = order.to_dict()
    assert stored["last_mail_at"] == _local(NOW - _days(3)).isoformat()
    assert Parcel.from_dict(stored).last_mail_at == NOW - _days(3)
    # A parcel stored by an older version has no such time.
    del stored["last_mail_at"]
    assert Parcel.from_dict(stored).last_mail_at is None


def test_a_mail_older_than_a_repeated_status_never_reopens_the_order():
    """Forwarded by hand a week late: sent after the one history line, but before the
    last mail that was read."""
    order = _repeated_then_closed()
    before = order.to_dict()
    old = MailUpdate(ORDER, "amazon", OUT, _local(NOW - _days(5)), eta_date=TODAY - _days(5))
    assert apply_update({ORDER: order}, old, NOW) is None
    assert order.to_dict() == before
    assert (order.status, order.assumed_delivered) == (DONE, True)


def test_a_mail_newer_than_the_repeated_status_still_reopens_the_order():
    order = _repeated_then_closed()
    newer = MailUpdate(ORDER, "amazon", OUT, _local(NOW - _days(2)))
    change = apply_update({ORDER: order}, newer, NOW)
    assert change is not None and (order.status, order.assumed_delivered) == (OUT, False)
    assert order.last_mail_at == NOW - _days(2)


def test_an_order_from_before_this_version_is_judged_by_its_history_as_before():
    order = _repeated_then_closed()
    order.last_mail_at = None
    old = MailUpdate(ORDER, "amazon", OUT, _local(NOW - _days(5)))
    assert apply_update({ORDER: order}, old, NOW) is not None


def test_an_older_mail_never_moves_the_stored_time_back():
    order = _order(changed=NOW - _days(2))
    parcels = {ORDER: order}
    apply_update(parcels, MailUpdate(ORDER, "amazon", MOVING, _local(NOW - _days(1))), NOW)
    apply_update(parcels, MailUpdate(ORDER, "amazon", MOVING, _local(NOW - _days(4))), NOW)
    assert order.last_mail_at == NOW - _days(1)


def test_a_mail_that_is_not_applied_is_not_remembered():
    """A step back is ignored altogether, so it is nothing that was known."""
    order = _order(status=OUT, changed=NOW - _days(2))
    apply_update({ORDER: order}, MailUpdate(ORDER, "amazon", MOVING, _local(NOW)), NOW)
    assert order.status is OUT and order.last_mail_at is None


def test_the_shops_confirmation_is_the_closing_and_not_something_known_before():
    """As before: a mail older than the confirmation, but newer than what was known
    when the order was closed, is news (see test_review_second)."""
    order = _ali(ALI_A, None, first=TODAY - _days(9), changed=NOW - _days(12))
    order.result.events = [TrackingEvent(_local(NOW - _days(12)), "Versendet", None)]
    parcels = {ALI_A: order}
    assert apply_update(parcels, _confirmation(NOW - _days(1)), NOW) is not None
    assert order.assumed_delivered is True and order.last_mail_at is None
    waited = MailUpdate(ALI_A, "aliexpress", OUT, _local(NOW - _days(3)))
    assert apply_update(parcels, waited, NOW) is not None
    assert (order.status, order.assumed_delivered) == (OUT, False)


# ----- L4: a "zugestellt" mail for an unknown number and the order's days -----
def _delivered_mail(sent=NOW, **fields) -> MailUpdate:
    return MailUpdate(DHL, "dhl", DONE, _local(sent), shop="amazon", **fields)


def test_a_delivery_mail_is_not_merged_into_an_order_for_quite_other_days():
    """Another Amazon parcel comes today; the one open order names the 13th to 15th."""
    order = _order(first=TODAY + _days(6), last=TODAY + _days(8))
    before = order.to_dict()
    parcels = {ORDER: order}
    change = apply_update(parcels, _delivered_mail(), NOW)
    assert set(parcels) == {ORDER, DHL} and order.to_dict() == before
    assert change.created and change.parcel is parcels[DHL]
    assert parcels[DHL].status is DONE


@pytest.mark.parametrize(
    ("first", "last", "merged"),
    [
        (0, 0, True),
        (1, 3, True),  # delivered the day before the window starts
        (FOLD_DAYS_BEFORE, FOLD_DAYS_BEFORE + 2, True),
        (FOLD_DAYS_BEFORE + 1, FOLD_DAYS_BEFORE + 3, False),
        (-5, -FOLD_DAYS_AFTER, True),
        (-5, -FOLD_DAYS_AFTER - 1, False),
        (None, None, True),  # the order names no day at all: as before
    ],
)
def test_a_delivery_mail_is_merged_within_the_same_days_as_a_fold(first, last, merged):
    order = _order(
        first=None if first is None else TODAY + _days(first),
        last=None if last is None else TODAY + _days(last),
    )
    parcels = {ORDER: order}
    apply_update(parcels, _delivered_mail(), NOW)
    assert (list(parcels) == [ORDER]) is merged
    assert (order.status is DONE and order.tracking_ref == DHL) is merged


def test_the_day_of_the_mail_is_the_day_of_the_delivery():
    order = _order(first=TODAY + _days(6), last=TODAY + _days(8))
    parcels = {ORDER: order}
    apply_update(parcels, _delivered_mail(NOW + _days(4)), NOW + _days(4))
    assert list(parcels) == [ORDER] and order.status is DONE


def test_a_delivery_mail_never_takes_an_order_that_is_only_ordered():
    order = _order(first=TODAY, last=TODAY, status=ParcelStatus.PRE_TRANSIT)
    parcels = {ORDER: order}
    apply_update(parcels, _delivered_mail(), NOW)
    assert set(parcels) == {ORDER, DHL} and order.tracking_ref is None


@pytest.mark.parametrize("status", [MOVING, OUT])
def test_other_carrier_mails_are_merged_by_their_old_rule(status):
    """Not delivered and no day in the mail: the one order "Versendet", whatever its days."""
    order = _order(first=TODAY + _days(6), last=TODAY + _days(8))
    parcels = {ORDER: order}
    apply_update(parcels, MailUpdate(DHL, "dhl", status, _local(NOW), shop="amazon"), NOW)
    assert list(parcels) == [ORDER] and order.tracking_ref == DHL


def test_a_delivery_mail_that_names_a_day_keeps_its_old_rule():
    order = _order(first=TODAY + _days(1), last=TODAY + _days(3))
    parcels = {ORDER: order}
    apply_update(parcels, _delivered_mail(eta_date=TODAY), NOW)
    assert set(parcels) == {ORDER, DHL}  # the day it names is not one of the order's


# ----- L4, second look: such a delivery is not swallowed, the parcel tells it itself -----
async def _import(coord, hass, *updates, at=None):
    async with coord._lock:
        coord._handle_mail(
            _ParsedMail(message_id=f"<{len(updates)}-{at}@synthetic.example>",
                        result=MailResult(list(updates))),
            at or dt_util.utcnow(),
        )
        coord._settle_orders(at or dt_util.utcnow())
    await hass.async_block_till_done()


async def _far_order(hass, hass_storage, start=True):
    order = _order(first=TODAY + _days(6), last=TODAY + _days(8), changed=NOW - _days(1))
    coord = await _coordinator(hass, hass_storage, [order])
    await _refresh(hass, coord)
    if start:
        await _start(hass)
    return coord


async def test_a_delivery_that_fits_no_order_is_told_by_its_own_parcel(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    coord = await _far_order(hass, hass_storage)
    await _import(coord, hass, _delivered_mail(delivered_at=_local(NOW)))
    parcels = coord.store.parcels
    assert set(parcels) == {ORDER, DHL} and parcels[ORDER].status is MOVING
    assert [(e.data["number"], e.data["old_status"], e.data["new_status"]) for e in events] == [
        (DHL, "unknown", "delivered")
    ]
    (call,) = calls
    assert call.data["message"].startswith("✅ ") and call.data["message"].endswith(
        "wurde zugestellt"
    )
    assert parcels[DHL].delivery_announced is True and parcels[DHL].unannounced_from is None
    # Told once: nothing more with the next refresh.
    freezer.tick(timedelta(minutes=5))
    await _refresh(hass, coord)
    assert len(events) == 1 and len(calls) == 1
    await coord.async_shutdown()


async def test_a_company_name_is_enough_and_names_the_parcel(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    coord = await _far_order(hass, hass_storage)
    mail = MailUpdate(DHL, "dhl", DONE, _local(NOW), title="Musterfirma GmbH")
    await _import(coord, hass, mail)
    assert [call.data["message"] for call in calls] == [
        "✅ Musterfirma GmbH (DHL) wurde zugestellt"
    ]
    await coord.async_shutdown()


@pytest.mark.parametrize(
    "mail",
    [
        MailUpdate(DHL, "dhl", DONE, _local(NOW)),  # names nothing but the number
        _delivered_mail(NOW - timedelta(hours=25)),  # an old mail, read late
        MailUpdate(DHL, "dhl", MOVING, _local(NOW), shop="amazon",
                   eta_date=TODAY - _days(9)),  # not delivered: a first status is no news
    ],
    ids=["number-only", "old-mail", "not-delivered"],
)
async def test_other_parcels_a_mail_makes_stay_silent(hass, hass_storage, freezer, mail):
    calls, events = await _prepared(hass, freezer)
    coord = await _far_order(hass, hass_storage)
    await _import(coord, hass, mail)
    assert set(coord.store.parcels) == {ORDER, DHL}
    assert events == [] and calls == []
    await coord.async_shutdown()


async def test_such_a_delivery_found_while_starting_is_told_once_after_the_start(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    hass.set_state(CoreState.starting)
    coord = await _far_order(hass, hass_storage, start=False)
    await _import(coord, hass, _delivered_mail())
    assert events == [] and calls == []
    await _start(hass)
    assert [(e.data["number"], e.data["new_status"]) for e in events] == [(DHL, "delivered")]
    assert len(calls) == 1
    await coord.async_shutdown()


async def test_a_delivery_that_closes_its_order_at_once_is_told_by_the_order_alone(
    hass, hass_storage, freezer
):
    """Merged right away, as before: one event, one notification, the order's."""
    calls, events = await _prepared(hass, freezer)
    order = _order(first=TODAY, last=TODAY, changed=NOW - _days(1))
    coord = await _coordinator(hass, hass_storage, [order])
    await _refresh(hass, coord)
    await _start(hass)
    await _import(coord, hass, _delivered_mail())
    assert list(coord.store.parcels) == [ORDER]
    assert [(e.data["number"], e.data["new_status"]) for e in events] == [(ORDER, "delivered")]
    assert len(calls) == 1
    await coord.async_shutdown()


def test_apply_says_which_new_parcel_is_news():
    def change(mail, now=NOW):
        return apply_update({}, mail, now)

    assert change(_delivered_mail()).announce is True
    assert change(MailUpdate(DHL, "dhl", DONE, _local(NOW), title="Musterfirma GmbH")).announce
    assert change(MailUpdate(DHL, "dhl", DONE, _local(NOW))).announce is False
    # A carrier's own display name is no name.
    assert change(MailUpdate(DHL, "dhl", DONE, _local(NOW), title="DHL")).announce is False
    assert change(_delivered_mail(NOW - timedelta(hours=25))).announce is False
    assert change(_delivered_mail(NOW - timedelta(hours=23))).announce is True
    assert change(MailUpdate(DHL, "dhl", OUT, _local(NOW), shop="amazon")).announce is False

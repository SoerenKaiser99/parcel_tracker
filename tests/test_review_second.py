"""v0.3.31: what a second review found in the corrections themselves.

An order with a carrier number is closed on its own only when nobody can be asked about
it at all; mails read late after a pause still count; a parcel taken in by its order at
once keeps what the order knew; one odd parcel never stops a refresh.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.parcel_tracker.carriers.base import BERLIN, NotFound
from custom_components.parcel_tracker.carriers.track17 import Track17Info
from custom_components.parcel_tracker.const import (
    FOLD_DAYS_AFTER,
    FOLD_DAYS_BEFORE,
    ORDER_OVERDUE_DAYS,
)
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.mail.aliexpress import CONFIRMED_TEXT
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
from custom_components.parcel_tracker.schedule import delivered_today, order_overdue

from .test_coordinator_mail import FakeMailbox
from .test_coordinator_notify import _start
from .test_order_closing import (
    DHL,
    NOW,
    ORDER,
    TODAY,
    FakeCarrier,
    _carrier_parcel,
    _coordinator,
    _days,
    _fold,
    _order,
    _prepared,
    _refresh,
    _result,
)
from .test_review_shared import ALI_A, ALI_B, MOVING, OUT, _ali, _local, _parcel_mail

DONE = ParcelStatus.DELIVERED
PARSE = "custom_components.parcel_tracker.coordinator._parse_mails"


def _old(number=ALI_A, **fields) -> Parcel:
    """An order with a DHL number whose day is long over."""
    return _ali(number, first=TODAY - _days(9), changed=NOW - _days(12), **fields)


class Unknown(FakeCarrier):
    """A carrier that can be asked but does not know the number."""

    async def fetch(self, number, postcode):
        self.calls += 1
        if self.answer is None:
            raise NotFound(number)
        return self.answer


class NoKey(Unknown):
    """DHL without an API key."""

    configured = False


# ----- 1. an order with a carrier number: closed only when nobody can be asked -----
@pytest.mark.parametrize("error", [None, "not_found", "missing_key", "carrier_not_found",
                                   "unavailable"])
def test_overdue_with_a_carrier_number_follows_what_can_be_asked_not_the_last_error(error):
    order = _old()
    order.last_poll_at, order.last_error = NOW, error
    assert not order_overdue(order, TODAY, BERLIN, askable=True)
    assert order_overdue(order, TODAY, BERLIN, askable=False)
    # Without a number nobody can be asked anyway.
    order.tracking_ref = order.tracking_carrier = None
    assert order_overdue(order, TODAY, BERLIN, askable=True)


async def test_a_number_the_carrier_does_not_know_yet_never_closes_the_order(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    carrier = Unknown()
    coord = await _coordinator(hass, hass_storage, [_old()], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    for _ in range(3):
        freezer.tick(timedelta(hours=2))
        await _refresh(hass, coord)
    order = coord.store.parcels[ALI_A]
    assert (order.status, order.assumed_delivered, order.last_error) == (
        MOVING, False, "not_found",
    )
    assert events == []
    # Days later the carrier knows it: asked, told and pushed like any parcel.
    carrier.answer = _result(OUT, "In Zustellung", first=dt_util.now().date())
    asked = carrier.calls
    freezer.tick(timedelta(hours=2))
    await _refresh(hass, coord)
    assert carrier.calls == asked + 1
    assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
        ("in_transit", "out_for_delivery")
    ]
    assert len(calls) == 1
    await coord.async_shutdown()


async def test_one_answer_not_found_after_good_ones_closes_nothing(hass, hass_storage, freezer):
    _calls, events = await _prepared(hass, freezer)
    carrier = Unknown(_result(MOVING, "Unterwegs"))
    coord = await _coordinator(hass, hass_storage, [_old()], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    carrier.answer = None
    freezer.tick(timedelta(hours=1))
    await _refresh(hass, coord)
    order = coord.store.parcels[ALI_A]
    assert (order.last_error, order.status, order.assumed_delivered) == (
        "not_found", MOVING, False,
    )
    assert events == []
    await coord.async_shutdown()


async def test_order_followed_through_17track_is_not_closed(hass, hass_storage, freezer):
    await _prepared(hass, freezer)
    order = _old()
    order.tracking_ref, order.tracking_carrier = "H1000999999999999901", "hermes"
    order.track17, order.track17_next_at = True, NOW + _days(1)
    plain = _old(ALI_B)
    plain.tracking_ref, plain.tracking_carrier = "H1000999999999999902", "hermes"
    coord = await _coordinator(hass, hass_storage, [order, plain])  # no client for Hermes
    coord.track17 = object()  # a 17track key is set (the first refresh asks nothing there)
    await _refresh(hass, coord)
    assert coord.store.parcels[ALI_A].status is MOVING
    # The same order without 17track: nobody can be asked, so it is closed.
    assert coord.store.parcels[ALI_B].assumed_delivered is True
    await coord.async_shutdown()


async def test_order_with_a_dhl_number_and_no_dhl_key_is_closed(hass, hass_storage, freezer):
    await _prepared(hass, freezer)
    coord = await _coordinator(hass, hass_storage, [_old()], NoKey())
    await _refresh(hass, coord)
    order = coord.store.parcels[ALI_A]
    assert (order.status, order.assumed_delivered) == (DONE, True)
    await coord.async_shutdown()


async def _closed_with_number(hass, hass_storage, carrier):
    """An order closed while its carrier could not be asked; now it can."""
    order = _old()
    close_unconfirmed(order, NOW - _days(1))
    order.next_poll_at = None
    coord = await _coordinator(hass, hass_storage, [order], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    return coord


async def test_a_closed_order_with_a_number_is_still_asked_and_a_live_answer_wins(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    carrier = Unknown()
    coord = await _closed_with_number(hass, hass_storage, carrier)
    order = coord.store.parcels[ALI_A]
    assert carrier.calls == 1 and order.assumed_delivered is True and events == []
    freezer.tick(timedelta(minutes=61))
    await _refresh(hass, coord)
    assert carrier.calls == 2 and order.assumed_delivered is True

    carrier.answer = _result(OUT, "In Zustellung", first=dt_util.now().date())
    freezer.tick(timedelta(minutes=61))
    await _refresh(hass, coord)
    assert (order.status, order.assumed_delivered) == (OUT, False)
    (event,) = events
    assert (event.data["old_status"], event.data["new_status"], event.data["assumed"]) == (
        "delivered", "out_for_delivery", False,
    )
    assert [call.data["message"] for call in calls] == [
        "📦 Beispiel-Kabel (AliExpress) ist in Zustellung"
    ]
    await coord.async_shutdown()


async def test_a_live_delivery_replaces_the_assumed_one(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    carrier = Unknown(_result(DONE, "Zugestellt", delivered_at=NOW - timedelta(hours=1)))
    coord = await _closed_with_number(hass, hass_storage, carrier)
    order = coord.store.parcels[ALI_A]
    assert (order.status, order.assumed_delivered) == (DONE, False)
    assert order.result.delivered_at == NOW - timedelta(hours=1)
    assert delivered_today(order, TODAY, BERLIN)
    # Delivered before and after: nothing to announce, and nobody is asked again.
    assert events == [] and calls == []
    freezer.tick(timedelta(hours=3))
    await _refresh(hass, coord)
    assert carrier.calls == 1
    await coord.async_shutdown()


async def test_a_17track_answer_replaces_the_assumption_and_polling_goes_on(
    hass, hass_storage, freezer
):
    _calls, events = await _prepared(hass, freezer)
    order = _old()
    order.tracking_ref, order.tracking_carrier = "H1000999999999999901", "hermes"
    close_unconfirmed(order, NOW - _days(1))
    order.track17, order.track17_carrier = True, 100031
    coord = await _coordinator(hass, hass_storage, [order])
    await _refresh(hass, coord)
    await _start(hass)
    order = coord.store.parcels[ALI_A]
    # Nothing known at 17track yet: the assumption stays, and it is asked again.
    unknown = TrackingResult(ParcelStatus.UNKNOWN, None, None, None, None, None, None, None, None)
    coord._apply_track17(order, Track17Info(unknown, False, 100031), NOW)
    assert (order.status, order.assumed_delivered) == (DONE, True)
    assert order.track17_next_at is not None
    coord._apply_track17(order, Track17Info(_result(OUT, "In Zustellung"), False, 100031), NOW)
    assert (order.status, order.assumed_delivered) == (OUT, False)
    assert order.track17_next_at is not None
    assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
        ("delivered", "out_for_delivery")
    ]
    await coord.async_shutdown()


# ----- 2. mails read late still count against what was known before the closing -----
def _known(last_mail, closed) -> Parcel:
    """An Amazon order whose last mail came at ``last_mail``, closed on its own later."""
    order = _order(first=TODAY - _days(5), changed=last_mail)
    order.result.events = [TrackingEvent(_local(last_mail), "Versendet", None)]
    close_unconfirmed(order, closed)
    return order


def _amazon(status, sent, **fields) -> MailUpdate:
    return MailUpdate(ORDER, "amazon", status, _local(sent), **fields)


@pytest.mark.parametrize(
    "mail",
    [
        _amazon(MOVING, NOW - _days(1), eta_date=TODAY + _days(1)),  # a new day, yesterday
        _amazon(OUT, NOW - timedelta(hours=2)),  # "in Zustellung", before the start
    ],
)
def test_a_backlog_mail_newer_than_the_last_known_one_reopens_the_order(mail):
    """Home Assistant was down for days: the first refresh closes the order, then the
    mails that waited are read. They were sent before the closing, and still tell news."""
    order = _known(NOW - _days(6), closed=NOW - timedelta(minutes=1))
    change = apply_update({ORDER: order}, mail, NOW)
    assert change is not None and change.old_status is DONE
    assert (order.status, order.assumed_delivered) == (mail.status, False)


def test_a_mail_older_than_the_last_known_one_never_reopens_the_order():
    order = _known(NOW - _days(6), closed=NOW - _days(1))
    before = order.to_dict()
    stale = _amazon(OUT, NOW - _days(7), eta_date=TODAY - _days(7))
    assert apply_update({ORDER: order}, stale, NOW) is None
    assert order.to_dict() == before


def test_the_same_rule_after_the_shops_confirmation_changed_the_words():
    order = _known(NOW - _days(6), closed=NOW - _days(2))
    confirmation = _amazon(DONE, NOW - _days(1), status_text=CONFIRMED_TEXT, confirmation=True)
    assert apply_update({ORDER: order}, confirmation, NOW) is not None
    assert [e.text for e in order.result.events][:2] == [CONFIRMED_TEXT, ASSUMED_TEXT]
    assert apply_update({ORDER: order}, _amazon(OUT, NOW - _days(7)), NOW) is None
    assert apply_update({ORDER: order}, _amazon(OUT, NOW - _days(3)), NOW) is not None
    assert (order.status, order.assumed_delivered) == (OUT, False)


async def _with_mailbox(hass, hass_storage, order, update):
    coord = await _coordinator(hass, hass_storage, [order])
    coord.mailbox = FakeMailbox([(1, b"raw")])
    parsed = [_ParsedMail(message_id="<1@synthetic.example>", result=MailResult([update]))]
    return coord, patch(PARSE, return_value=parsed)


async def test_an_order_is_settled_after_the_mails_of_the_same_cycle(
    hass, hass_storage, freezer
):
    """Due for closing in the very cycle that reads its "new day" mail: never closed."""
    _calls, events = await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(ORDER_OVERDUE_DAYS), changed=NOW - _days(8))
    order.result.events = [TrackingEvent(_local(NOW - _days(8)), "Versendet", None)]
    new_day = TODAY + _days(2)
    mail = _amazon(MOVING, NOW + timedelta(hours=23), eta_date=new_day)
    coord, parse = await _with_mailbox(hass, hass_storage, order, mail)
    with parse:
        coord.mailbox.mails = []
        await _refresh(hass, coord)  # the first refresh reads no mail
        await _start(hass)
        assert coord.store.parcels[ORDER].status is MOVING
        coord.mailbox.mails = [(1, b"raw")]
        freezer.tick(timedelta(days=1))
        await _refresh(hass, coord)
    order = coord.store.parcels[ORDER]
    assert (order.status, order.assumed_delivered) == (MOVING, False)
    assert order.result.eta_date == new_day
    assert events == []
    await coord.async_shutdown()


async def test_an_overdue_order_is_still_closed_in_a_cycle_without_news(
    hass, hass_storage, freezer
):
    _calls, events = await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(ORDER_OVERDUE_DAYS), changed=NOW - _days(8))
    coord = await _coordinator(hass, hass_storage, [order])
    coord.mailbox = FakeMailbox([])
    await _refresh(hass, coord)
    await _start(hass)
    freezer.tick(timedelta(days=1))
    await _refresh(hass, coord)
    assert coord.store.parcels[ORDER].assumed_delivered is True
    assert [e.data["assumed"] for e in events] == [True]
    assert hass_storage["parcel_tracker"]["data"]["parcels"][0]["assumed_delivered"] is True
    await coord.async_shutdown()


async def test_backlog_after_a_pause_reopens_what_the_first_refresh_closed(
    hass, hass_storage, freezer
):
    _calls, events = await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(4), changed=NOW - _days(6))
    order.result.events = [TrackingEvent(_local(NOW - _days(6)), "Versendet", None)]
    mail = _amazon(MOVING, NOW - _days(1), eta_date=TODAY + _days(1))
    coord, parse = await _with_mailbox(hass, hass_storage, order, mail)
    with parse:
        await _refresh(hass, coord)
        assert coord.store.parcels[ORDER].assumed_delivered is True
        await _start(hass)
        freezer.tick(timedelta(minutes=1))
        await _refresh(hass, coord)
    order = coord.store.parcels[ORDER]
    assert (order.status, order.assumed_delivered) == (MOVING, False)
    assert order.result.eta_date == TODAY + _days(1)
    await coord.async_shutdown()


# ----- 3. an order that takes its carrier's parcel in at once keeps what it knew -----
def _dhl_parcel(status=MOVING, **fields) -> Parcel:
    events = [TrackingEvent(NOW - timedelta(hours=3), "Unterwegs", "Bonn")]
    result = None
    if status is not None:
        result = TrackingResult(status, "Die Sendung ist unterwegs.", None, None, None, "Bonn",
                                None, None, NOW if status is DONE else None, events)
    return Parcel(DHL, "dhl", "mail", "AliExpress-Sendung", NOW - _days(1),
                  NOW - timedelta(hours=3), result=result, **fields)


def _ordered() -> Parcel:
    order = _ali(ALI_A, None, status=ParcelStatus.PRE_TRANSIT, first=TODAY + _days(2),
                 last=TODAY + _days(4), changed=NOW - _days(2))
    order.result.status_text = "Bestellt"
    order.result.events = [TrackingEvent(_local(NOW - _days(2)), "Bestellt", None)]
    return order


def test_the_order_tells_its_own_step_and_keeps_its_day_when_it_takes_the_parcel_in():
    order = _ordered()
    parcels = {ALI_A: order, DHL: _dhl_parcel()}
    change = apply_update(parcels, _parcel_mail(DHL, words=None), NOW)
    assert list(parcels) == [ALI_A]
    # "Bestellt" -> "Unterwegs" is the order's own news.
    assert (change.old_status, order.status) == (ParcelStatus.PRE_TRANSIT, MOVING)
    # The parcel named no day: the order's days stay.
    assert (order.result.eta_date, order.result.eta_latest) == (TODAY + _days(2),
                                                               TODAY + _days(4))
    # One history, newest first, the order's lines with the carrier's.
    assert [e.text for e in order.result.events] == ["Unterwegs", "Bestellt"]
    assert order.result.location == "Bonn"


def test_a_parcel_without_any_status_takes_nothing_away_from_the_order():
    order = _ordered()
    order.result.status = MOVING
    before = order.result.to_dict()
    parcels = {ALI_A: order, DHL: _dhl_parcel(None)}
    apply_update(parcels, _parcel_mail(DHL, words=None), NOW)
    assert list(parcels) == [ALI_A] and order.tracking_ref == DHL
    assert order.result.to_dict() == before


def test_the_carriers_day_wins_over_the_orders():
    order = _ordered()
    parcel = _dhl_parcel()
    parcel.result.eta_date = TODAY + _days(1)
    parcels = {ALI_A: order, DHL: parcel}
    apply_update(parcels, _parcel_mail(DHL, words=None), NOW)
    assert (order.result.eta_date, order.result.eta_latest) == (TODAY + _days(1), None)


async def test_a_parcel_delivered_as_its_first_status_is_told_by_the_order(
    hass, hass_storage, freezer
):
    """Both mails in one import: the carrier's "zugestellt" (a first status is no news)
    and the shop mail that names the number. The order tells the delivery."""
    calls, events = await _prepared(hass, freezer)
    order = _ali(ALI_A, None, changed=NOW - _days(1))
    coord = await _coordinator(hass, hass_storage, [order])
    await _refresh(hass, coord)
    await _start(hass)
    delivered = MailUpdate(DHL, "dhl", DONE, _local(NOW), delivered_at=_local(NOW))
    named = _parcel_mail(DHL, words=None)
    async with coord._lock:
        coord._handle_mail(
            _ParsedMail(message_id="<1@synthetic.example>",
                        result=MailResult([delivered, named])), NOW,
        )
        coord._settle_orders(NOW)
    await hass.async_block_till_done()
    assert list(coord.store.parcels) == [ALI_A]
    assert coord.store.parcels[ALI_A].status is DONE
    assert [(e.data["number"], e.data["old_status"], e.data["new_status"]) for e in events] == [
        (ALI_A, "in_transit", "delivered")
    ]
    assert len(calls) == 1
    await coord.async_shutdown()


# ----- 4. a delivery a little outside the order's days still belongs to it -----
@pytest.mark.parametrize(
    ("first", "last", "folds"),
    [
        (1, 3, True),  # delivered the day before the window starts
        (FOLD_DAYS_BEFORE, FOLD_DAYS_BEFORE + 2, True),
        (FOLD_DAYS_BEFORE + 1, FOLD_DAYS_BEFORE + 3, False),
        (-1, None, True),  # delivered a day late
        (-5, -FOLD_DAYS_AFTER, True),
        (-5, -FOLD_DAYS_AFTER - 1, False),
        (6, 8, False),  # the box of another shop, a week before
    ],
)
def test_fold_allows_a_few_days_around_the_orders_days(first, last, folds):
    def day(ahead):
        return None if ahead is None else TODAY + _days(ahead)

    order = _order(title="Kopfhörer", first=day(first), last=day(last))
    order.shipping_carrier_hint = "dhl"
    parcels = {ORDER: order, DHL: _carrier_parcel(name="Musterfirma GmbH")}
    assert (_fold(parcels, parcels[DHL]) is order) is folds
    assert (FOLD_DAYS_BEFORE, FOLD_DAYS_AFTER) == (3, 3)


# ----- 5. only a notification that went out counts for the box -----
async def test_an_assumed_closing_of_one_order_does_not_swallow_the_boxs_delivery(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    carrier = Unknown(_result(MOVING, "Unterwegs"))
    coord = await _coordinator(hass, hass_storage, [_ali(ALI_A), _ali(ALI_B)], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    first = coord.store.parcels[ALI_A]
    old = first.status
    close_unconfirmed(first, dt_util.utcnow())
    coord._fire(first, old)  # the event of the closing: nothing is pushed
    assert [e.data["assumed"] for e in events] == [True] and calls == []
    carrier.answer = _result(DONE, "Zugestellt", delivered_at=NOW)
    freezer.tick(timedelta(minutes=61))
    await _refresh(hass, coord)
    assert coord.store.parcels[ALI_B].status is DONE
    assert len(calls) == 1
    await coord.async_shutdown()


# ----- 6. one odd order of a box never stops the refresh -----
async def test_a_failure_for_one_order_of_a_box_leaves_the_others_and_the_refresh_alone(
    hass, hass_storage, freezer, caplog
):
    await _prepared(hass, freezer)
    carrier = Unknown(_result(OUT, "In Zustellung"))
    third = "ALI9999999999990903"
    orders = [_ali(ALI_A), _ali(ALI_B), _ali(third)]
    coord = await _coordinator(hass, hass_storage, orders, carrier)
    real = coord._success

    def odd(parcel, *args):
        if parcel.number == ALI_B:
            raise RuntimeError("synthetic")
        real(parcel, *args)

    with patch.object(coord, "_success", side_effect=odd):
        await coord.async_refresh()
        await hass.async_block_till_done()
    assert coord.last_update_success is True
    parcels = coord.store.parcels
    assert (parcels[ALI_A].status, parcels[third].status) == (OUT, OUT)
    assert (parcels[ALI_B].status, parcels[ALI_B].last_error) == (MOVING, "unavailable")
    assert parcels[ALI_B].next_poll_at is not None and carrier.calls == 1
    assert "Unexpected error" in caplog.text
    await coord.async_shutdown()


# ----- 7. a confirmation counts once the carrier has been silent for days -----
def _confirmation(sent=NOW) -> MailUpdate:
    return MailUpdate(ALI_A, "aliexpress", DONE, _local(sent), status_text=CONFIRMED_TEXT,
                      confirmation=True)


def _followed(changed) -> Parcel:
    order = _ali(ALI_A, changed=changed)
    order.last_poll_at, order.last_error = NOW - timedelta(minutes=20), None
    return order


def test_confirmation_is_left_to_a_carrier_that_told_something_lately():
    order = _followed(NOW - _days(ORDER_OVERDUE_DAYS))
    before = order.to_dict()
    assert apply_update({ALI_A: order}, _confirmation(), NOW) is None
    assert order.to_dict() == before


@pytest.mark.parametrize("error", [None, "not_found", "unavailable"])
def test_confirmation_closes_an_order_whose_carrier_tells_nothing_new_for_days(error):
    """The carrier answers but never says "delivered": the order would stay open."""
    order = _followed(NOW - _days(ORDER_OVERDUE_DAYS) - timedelta(minutes=1))
    order.last_error = error
    change = apply_update({ALI_A: order}, _confirmation(), NOW)
    assert change.old_status is MOVING
    assert (order.status, order.assumed_delivered) == (DONE, True)
    assert order.result.status_text == CONFIRMED_TEXT and order.result.delivered_at is None
    assert not delivered_today(order, TODAY, BERLIN)

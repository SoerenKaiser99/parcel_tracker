"""v0.3.31: corrections after a code review - folding a delivered carrier parcel into an
order (``fold_delivered``) and what mails do to an order closed on its own.

The conservative outcome wins everywhere: in doubt a parcel and an order stay as they
are and nothing is announced.
"""

from datetime import timedelta

from homeassistant.core import CoreState

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail.aliexpress import CONFIRMED_TEXT
from custom_components.parcel_tracker.mail.apply import (
    ASSUMED_TEXT,
    apply_update,
    close_unconfirmed,
)
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus
from custom_components.parcel_tracker.schedule import delivered_today, should_remove

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
    _fold,
    _order,
    _prepared,
    _refresh,
    _result,
)

ALI = "ALI9999999999999901"


# ----- A1: the delivery day must lie in the order's days -----
def test_fold_never_into_an_order_that_named_the_carrier_for_other_days():
    """Another shop's DHL parcel comes on the 7th; the only open Amazon order says "via
    DHL" for the 13th to the 15th."""
    order = _order(title="Kopfhörer", first=TODAY + _days(6), last=TODAY + _days(8))
    order.shipping_carrier_hint = "dhl"
    parcel = _carrier_parcel(name="Musterfirma GmbH")
    parcels = {ORDER: order, DHL: parcel}
    before = order.to_dict()
    assert _fold(parcels, parcel) is None
    assert set(parcels) == {ORDER, DHL} and order.to_dict() == before


def test_fold_never_by_the_shop_name_into_an_order_for_other_days():
    order = _order(title="Kopfhörer", first=TODAY + _days(6), last=TODAY + _days(8))
    parcels = {ORDER: order, DHL: _carrier_parcel(name="Amazon")}
    assert _fold(parcels, parcels[DHL]) is None
    assert order.status is ParcelStatus.IN_TRANSIT and order.tracking_ref is None


def test_fold_by_carrier_and_shop_while_the_day_lies_in_the_orders_days():
    for name, hint in (("Musterfirma GmbH", "dhl"), ("Amazon", None)):
        order = _order(title="Kopfhörer", first=TODAY - _days(1), last=TODAY + _days(1))
        order.shipping_carrier_hint = hint
        parcels = {ORDER: order, DHL: _carrier_parcel(name=name)}
        assert _fold(parcels, parcels[DHL]) is order, name


def test_fold_into_a_dated_order_only_while_it_is_shipped():
    """As before: the shop and carrier paths take an order that is "Versendet" only."""
    order = _order(title="Kopfhörer", first=TODAY, status=ParcelStatus.PRE_TRANSIT)
    parcels = {ORDER: order, DHL: _carrier_parcel(name="Amazon")}
    assert _fold(parcels, parcels[DHL]) is None


# ----- A2: a hand mark never folds -----
def test_a_hand_marked_parcel_is_never_folded():
    order = _order(first=TODAY, last=TODAY)
    parcel = _carrier_parcel()
    parcel.manual_delivered = True
    parcels = {ORDER: order, DHL: parcel}
    assert _fold(parcels, parcel) is None
    assert set(parcels) == {ORDER, DHL}
    assert (order.status, order.manual_delivered) == (ParcelStatus.IN_TRANSIT, False)


async def test_erhalten_on_a_carrier_parcel_leaves_the_order_alone(hass, hass_storage, freezer):
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
    assert coord.store.parcels[DHL].manual_delivered is True
    assert [(e.data["number"], e.data["manual"]) for e in events] == [(DHL, True)]
    await coord.async_shutdown()


# ----- A3: only a mail newer than what was known changes an order closed on its own -----
CLOSED = NOW - _days(1)


def _closed(carrier="amazon", number=ORDER, closed=CLOSED) -> Parcel:
    order = _order(number, first=TODAY - _days(8), changed=NOW - _days(9), carrier=carrier)
    close_unconfirmed(order, closed)
    return order


def _mail(status, sent, number=ORDER, carrier="amazon", **fields) -> MailUpdate:
    return MailUpdate(number, carrier, status, sent.astimezone(BERLIN), **fields)


def test_a_mail_older_than_what_was_known_never_reopens_the_order():
    """The order's last news is nine days old; an older "in Zustellung" mail is read
    after the closing (see test_review_second for mails that are newer than that)."""
    order = _closed()
    parcels = {ORDER: order}
    before = order.to_dict()
    old = _mail(ParcelStatus.OUT_FOR_DELIVERY, NOW - _days(10), eta_date=TODAY - _days(10))
    assert apply_update(parcels, old, NOW) is None
    assert order.to_dict() == before
    assert (order.status, order.assumed_delivered) == (ParcelStatus.DELIVERED, True)


def test_a_mail_sent_after_the_closing_still_reopens_the_order():
    order = _closed()
    change = apply_update({ORDER: order}, _mail(ParcelStatus.OUT_FOR_DELIVERY, NOW), NOW)
    assert change.old_status is ParcelStatus.DELIVERED
    assert (order.status, order.assumed_delivered) == (ParcelStatus.OUT_FOR_DELIVERY, False)


def test_an_older_delivery_mail_still_tells_when_the_order_came():
    """The real "zugestellt" mail, read late: it is delivered for sure then, on that day."""
    order = _closed()
    came = NOW - _days(5)
    change = apply_update({ORDER: order}, _mail(ParcelStatus.DELIVERED, came), NOW)
    assert (order.status, order.assumed_delivered) == (ParcelStatus.DELIVERED, False)
    assert order.result.delivered_at == came
    assert change.old_status is ParcelStatus.DELIVERED  # nothing to announce
    assert not delivered_today(order, TODAY, BERLIN)


# ----- A4: a delivery nobody announced is announced by the order -----
async def test_fold_of_a_parcel_that_never_had_a_status_is_announced_by_the_order(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(1), last=TODAY, changed=NOW - _days(3))
    parcel = Parcel(DHL, "dhl", "mail", BRAND, NOW - _days(2), NOW - _days(2),
                    next_poll_at=NOW + _days(1))
    carrier = FakeCarrier(_result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=NOW))
    coord = await _coordinator(hass, hass_storage, [order, parcel], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    assert events == [] and carrier.calls == 0

    coord.store.parcels[DHL].next_poll_at = None
    await _refresh(hass, coord)
    assert list(coord.store.parcels) == [ORDER]
    assert coord.store.parcels[ORDER].unannounced_from is None
    assert [(e.data["number"], e.data["old_status"], e.data["new_status"]) for e in events] == [
        (ORDER, "in_transit", "delivered")
    ]
    assert len(calls) == 1
    await coord.async_shutdown()


async def test_such_a_fold_while_starting_is_announced_once_after_the_start(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    hass.set_state(CoreState.starting)
    order = _order(first=TODAY - _days(1), last=TODAY, changed=NOW - _days(3))
    parcel = Parcel(DHL, "dhl", "mail", BRAND, NOW - _days(2), NOW - _days(2))
    carrier = FakeCarrier(_result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=NOW))
    coord = await _coordinator(hass, hass_storage, [order, parcel], carrier)
    await _refresh(hass, coord)
    assert list(coord.store.parcels) == [ORDER] and events == []
    assert coord.store.parcels[ORDER].unannounced_from is ParcelStatus.IN_TRANSIT
    await _start(hass)
    assert [(e.data["number"], e.data["new_status"]) for e in events] == [(ORDER, "delivered")]
    assert len(calls) == 1
    await coord.async_shutdown()


# ----- A5: a late confirmation never makes an order "delivered today" -----
def test_a_late_confirmation_of_a_closed_order_is_not_a_delivery_today():
    order = _closed("aliexpress", ALI, closed=NOW - _days(2))
    confirmation = _mail(ParcelStatus.DELIVERED, NOW, ALI, "aliexpress",
                         delivered_at=NOW.astimezone(BERLIN), status_text=CONFIRMED_TEXT,
                         confirmation=True)
    change = apply_update({ALI: order}, confirmation, NOW)
    assert change is not None and change.old_status is ParcelStatus.DELIVERED
    assert order.status is ParcelStatus.DELIVERED
    assert order.result.status_text == CONFIRMED_TEXT
    assert [e.text for e in order.result.events][:2] == [CONFIRMED_TEXT, ASSUMED_TEXT]
    assert order.result.delivered_at is None
    assert not delivered_today(order, TODAY, BERLIN)
    # The days it is kept count from the closing, not from the confirmation.
    assert order.last_change_at == NOW - _days(2)
    assert should_remove(order, NOW + _days(2), 3)
    # A second one tells nothing new.
    assert apply_update({ALI: order}, confirmation, NOW + timedelta(hours=1)) is None


def test_a_confirmation_older_than_what_was_known_changes_nothing():
    order = _closed("aliexpress", ALI)
    before = order.to_dict()
    confirmation = _mail(ParcelStatus.DELIVERED, NOW - _days(10), ALI, "aliexpress",
                         status_text=CONFIRMED_TEXT, confirmation=True)
    assert apply_update({ALI: order}, confirmation, NOW) is None
    assert order.to_dict() == before


# ----- A6: a name the user typed in survives the fold -----
def test_fold_keeps_a_name_the_user_typed_on_the_carrier_parcel():
    order = _order(first=TODAY, last=TODAY)
    parcel = _carrier_parcel()
    parcels = {ORDER: order, DHL: parcel}
    # Renamed after the mail made it; matched by the shop the order named instead.
    order.shipping_carrier_hint = "dhl"
    parcel.name, parcel.name_manual = "Geschenk für Oma", True
    assert _fold(parcels, parcel) is order
    assert (order.name, order.name_manual) == ("Geschenk für Oma", True)


def test_fold_keeps_the_orders_name_when_the_parcels_name_is_a_mails():
    order = _order(first=TODAY, last=TODAY)
    parcels = {ORDER: order, DHL: _carrier_parcel()}
    assert _fold(parcels, parcels[DHL]) is order
    assert (order.name, order.name_manual) == (order.mail_title, False)

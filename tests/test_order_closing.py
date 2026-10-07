"""v0.3.20: shop orders that never get a "delivered" mail.

A delivered carrier parcel is folded into the one open order it belongs to (by the rules
a carrier mail is merged with at once), and an order nobody can ask about is closed on
its own once its delivery day is long over.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from homeassistant.core import CoreState
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.carriers.base import BERLIN, Carrier, Match
from custom_components.parcel_tracker.const import (
    CONF_NOTIFY_TARGETS,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    ORDER_NO_ETA_DAYS,
    ORDER_OVERDUE_DAYS,
)
from custom_components.parcel_tracker.coordinator import ParcelCoordinator, _ParsedMail
from custom_components.parcel_tracker.diagnostics import async_get_config_entry_diagnostics
from custom_components.parcel_tracker.mail.apply import (
    ASSUMED_TEXT,
    apply_update,
    close_unconfirmed,
    fold_delivered,
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
    should_remove,
    summarize,
)
from custom_components.parcel_tracker.store import ParcelStore

from .test_coordinator_notify import _start

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)  # 12:00 in Berlin
TODAY = NOW.astimezone(BERLIN).date()
ORDER = "AMZ99999999999999901"
OTHER_ORDER = "AMZ99999999999999902"
EBAY_ORDER = "EBAY999999999901"
DHL = "00340999999999999901"
TITLE = "Beispielmarke Trinkflasche 600 ml Edelstahl…"
BRAND = "Beispielmarke GmbH"
PHONE = "notify.mobile_app_handy"


def _days(count: int) -> timedelta:
    return timedelta(days=count)


def _result(status, text="Versendet", first=None, last=None, delivered_at=None, events=()):
    return TrackingResult(status, text, first, None, None, None, None, None, delivered_at,
                          list(events), eta_latest=last)


def _order(number=ORDER, title=TITLE, first=None, last=None, carrier="amazon",
           status=ParcelStatus.IN_TRANSIT, changed=NOW) -> Parcel:
    return Parcel(number, carrier, "mail", title, changed, changed,
                  result=_result(status, first=first, last=last), mail_title=title)


def _carrier_parcel(name=BRAND, status=ParcelStatus.DELIVERED, delivered_at=NOW, mode="mail",
                    carrier="dhl") -> Parcel:
    events = [TrackingEvent(NOW, "Zugestellt", "Bonn")]
    result = _result(status, "Die Sendung wurde zugestellt.", delivered_at=delivered_at,
                     events=events)
    return Parcel(DHL, carrier, mode, name, NOW - _days(2), NOW, last_poll_at=NOW, result=result)


def _fold(parcels, parcel):
    delivered = parcel.result.delivered_at or parcel.last_change_at
    return fold_delivered(parcels, parcel, delivered.astimezone(BERLIN))


# ----- 1. a delivered carrier parcel closes its order -----
def test_delivered_carrier_parcel_is_folded_into_the_one_order_of_its_brand():
    order = _order(first=TODAY - _days(1), last=TODAY + _days(1))
    parcel = _carrier_parcel()
    carrier_result = parcel.result
    parcels = {ORDER: order, DHL: parcel}

    assert _fold(parcels, parcel) is order
    # The same end state a merge at once gives: one entry, the order with the number.
    assert list(parcels) == [ORDER]
    assert (order.tracking_ref, order.tracking_carrier) == (DHL, "dhl")
    assert order.status is ParcelStatus.DELIVERED
    assert order.result is carrier_result
    assert order.result.delivered_at == NOW
    assert order.last_change_at == NOW
    assert (order.name, order.carrier, order.number) == (TITLE, "amazon", ORDER)
    assert order.next_poll_at is None
    assert order.assumed_delivered is False
    # Already announced with the carrier parcel: the order tells nothing more.
    assert order.unannounced_from is None
    # Nothing left to do a second time.
    assert [_fold(parcels, p) for p in list(parcels.values())] == [None]


def test_fold_takes_over_an_announcement_that_still_waits():
    order = _order(first=TODAY, last=TODAY)
    parcel = _carrier_parcel()
    parcel.unannounced_from = ParcelStatus.OUT_FOR_DELIVERY
    parcels = {ORDER: order, DHL: parcel}
    assert _fold(parcels, parcel) is order
    assert order.unannounced_from is ParcelStatus.IN_TRANSIT  # the order's own old status


def test_fold_drops_an_older_announcement_of_the_order():
    order = _order(first=TODAY, last=TODAY)
    order.unannounced_from = ParcelStatus.PRE_TRANSIT
    parcel = _carrier_parcel()
    parcels = {ORDER: order, DHL: parcel}
    assert _fold(parcels, parcel) is order
    assert order.unannounced_from is None  # the delivery was announced already


def test_fold_moves_a_17track_registration_along():
    order = _order(first=TODAY, last=TODAY)
    parcel = _carrier_parcel()
    parcel.track17, parcel.track17_carrier = True, 7041
    parcel.track17_result = _result(ParcelStatus.DELIVERED)
    parcels = {ORDER: order, DHL: parcel}
    assert _fold(parcels, parcel) is order
    assert (order.track17, order.track17_carrier, order.track17_next_at) == (True, 7041, None)
    assert order.track17_result is parcel.track17_result


def test_fold_never_on_an_ambiguous_match():
    parcels = {
        ORDER: _order(first=TODAY, last=TODAY),
        OTHER_ORDER: _order(OTHER_ORDER, "Beispielmarke Filter", TODAY, TODAY),
        DHL: _carrier_parcel(),
    }
    assert _fold(parcels, parcels[DHL]) is None
    assert set(parcels) == {ORDER, OTHER_ORDER, DHL}
    assert parcels[ORDER].status is ParcelStatus.IN_TRANSIT
    assert parcels[ORDER].tracking_ref is None


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda o, p: setattr(p, "name", None), "the parcel names no company"),
        (lambda o, p: setattr(p, "name", "Musterfirma GmbH"), "another brand"),
        (lambda o, p: setattr(p, "name", "Neu GmbH"), "a common word is no brand"),
        (lambda o, p: setattr(p, "carrier_mode", "manual"), "added by hand"),
        (lambda o, p: setattr(p, "carrier_mode", "auto"), "added by hand"),
        (lambda o, p: setattr(p.result, "status", ParcelStatus.OUT_FOR_DELIVERY),
         "not delivered yet"),
        (lambda o, p: setattr(o, "carrier", "ebay"), "the brand rule is for Amazon only"),
        (lambda o, p: setattr(o, "tracking_ref", "00340999999999999902"),
         "the order has a number already"),
        (lambda o, p: setattr(o.result, "status", ParcelStatus.PRE_TRANSIT), "only ordered"),
        (lambda o, p: setattr(o.result, "status", ParcelStatus.DELIVERED), "closed already"),
        (lambda o, p: setattr(o, "shipping_carrier_hint", "hermes"), "names another carrier"),
        (lambda o, p: (setattr(o.result, "eta_date", TODAY - _days(3)),
                       setattr(o.result, "eta_latest", TODAY - _days(2))),
         "delivered outside the order's days"),
    ],
)
def test_fold_follows_the_rules_of_the_merge_at_once(change, reason):
    order = _order(first=TODAY - _days(1), last=TODAY)
    parcel = _carrier_parcel()
    change(order, parcel)
    parcels = {ORDER: order, DHL: parcel}
    before = order.to_dict()
    assert _fold(parcels, parcel) is None, reason
    assert set(parcels) == {ORDER, DHL}
    assert order.to_dict() == before


def test_fold_never_into_an_order_a_mail_changed_after_the_delivery():
    """Kept for days after its delivery, the parcel must not take an order shipped since."""
    delivered = NOW - _days(2)
    parcel = _carrier_parcel(delivered_at=delivered)
    later = _order(changed=NOW - _days(1))  # no day: the rules alone would take it
    parcels = {ORDER: later, DHL: parcel}
    assert _fold(parcels, parcel) is None
    assert later.status is ParcelStatus.IN_TRANSIT and set(parcels) == {ORDER, DHL}
    before = _order(changed=delivered - timedelta(hours=1))
    parcels = {ORDER: before, DHL: parcel}
    assert _fold(parcels, parcel) is before


def test_fold_matches_exactly_like_the_delivered_mail_would():
    """One matcher: whatever a "zugestellt" mail of the carrier would be merged into now."""
    for first, last, status in [
        (TODAY, TODAY, ParcelStatus.IN_TRANSIT),
        (None, None, ParcelStatus.IN_TRANSIT),
        (None, None, ParcelStatus.OUT_FOR_DELIVERY),
        (TODAY - _days(5), TODAY - _days(4), ParcelStatus.IN_TRANSIT),
        (TODAY - _days(1), TODAY + _days(1), ParcelStatus.OUT_FOR_DELIVERY),
    ]:
        by_mail = {ORDER: _order(first=first, last=last, status=status)}
        mail = MailUpdate(DHL, "dhl", ParcelStatus.DELIVERED, NOW.astimezone(BERLIN), title=BRAND)
        merged = not apply_update(by_mail, mail, NOW).created
        folded = {ORDER: _order(first=first, last=last, status=status), DHL: _carrier_parcel()}
        assert (_fold(folded, folded[DHL]) is not None) is merged, (first, last, status)


def test_fold_by_the_shop_the_carrier_mail_named_and_by_the_carrier_the_order_named():
    # "Amazon" as the name: the mail named the shop.
    parcels = {ORDER: _order(title="Kopfhörer"), DHL: _carrier_parcel(name="Amazon")}
    assert _fold(parcels, parcels[DHL]) is parcels[ORDER]
    # The eBay mail named the carrier; the parcel has no name at all.
    order = _order(EBAY_ORDER, "Kopfhörer", carrier="ebay")
    order.shipping_carrier_hint = "hermes"
    parcels = {EBAY_ORDER: order, DHL: _carrier_parcel(name=None, carrier="hermes")}
    assert _fold(parcels, parcels[DHL]) is order
    assert (order.tracking_ref, order.tracking_carrier) == (DHL, "hermes")


# ----- 2. an order without a delivery mail is closed -----
@pytest.mark.parametrize(
    ("first", "last", "changed_days_ago", "overdue"),
    [
        (ORDER_OVERDUE_DAYS + 1, None, 10, True),  # 3 full days lie in between
        (ORDER_OVERDUE_DAYS, None, 10, False),
        (9, ORDER_OVERDUE_DAYS + 1, 10, True),  # the last day of a window counts
        (9, ORDER_OVERDUE_DAYS, 10, False),
        (9, 8, ORDER_OVERDUE_DAYS, False),  # a mail changed it since: counted from then
        (9, 8, ORDER_OVERDUE_DAYS + 1, True),
        (None, None, ORDER_NO_ETA_DAYS, True),  # no day at all: after the last change
        (None, None, ORDER_NO_ETA_DAYS - 1, False),
        (-1, None, 20, False),  # still to come
    ],
)
def test_order_overdue_days(first, last, changed_days_ago, overdue):
    def day(ago):
        return None if ago is None else TODAY - _days(ago)

    order = _order(first=day(first), last=day(last), changed=NOW - _days(changed_days_ago))
    assert order_overdue(order, TODAY, BERLIN) is overdue


def test_overdue_constants():
    assert (ORDER_OVERDUE_DAYS, ORDER_NO_ETA_DAYS) == (3, 14)


@pytest.mark.parametrize("carrier", ["amazon", "ebay"])
@pytest.mark.parametrize(
    "status",
    [ParcelStatus.PRE_TRANSIT, ParcelStatus.IN_TRANSIT, ParcelStatus.OUT_FOR_DELIVERY],
)
def test_every_open_shop_order_can_be_overdue(carrier, status):
    order = _order(first=TODAY - _days(9), carrier=carrier, status=status,
                   changed=NOW - _days(12))
    assert order_overdue(order, TODAY, BERLIN)


def test_an_order_without_any_status_is_closed_by_its_last_change():
    order = Parcel(ORDER, "amazon", "mail", TITLE, NOW - _days(20), NOW - _days(20))
    assert order_overdue(order, TODAY, BERLIN)
    close_unconfirmed(order, NOW)
    assert (order.status, order.result.status_text) == (ParcelStatus.DELIVERED, ASSUMED_TEXT)


@pytest.mark.parametrize(
    "status",
    [ParcelStatus.DELIVERED, ParcelStatus.AWAITING_PICKUP, ParcelStatus.EXCEPTION],
)
def test_final_statuses_are_never_overdue(status):
    order = _order(first=TODAY - _days(9), status=status, changed=NOW - _days(20))
    assert not order_overdue(order, TODAY, BERLIN)


def test_only_orders_nobody_can_ask_about_are_overdue():
    old = NOW - _days(20)
    with_number = _order(first=TODAY - _days(9), changed=old)
    with_number.tracking_ref, with_number.tracking_carrier = DHL, "dhl"
    assert not order_overdue(with_number, TODAY, BERLIN)
    carrier_parcel = Parcel(DHL, "dhl", "mail", None, old, old,
                            result=_result(ParcelStatus.IN_TRANSIT, first=TODAY - _days(9)))
    assert not order_overdue(carrier_parcel, TODAY, BERLIN)
    by_hand = Parcel("H1000999999999999901", "hermes", "manual", None, old, old)
    assert not order_overdue(by_hand, TODAY, BERLIN)


def test_overdue_uses_the_day_in_the_given_time_zone():
    # Changed at 23:30 UTC = the next day in Berlin.
    changed = datetime(2026, 9, 22, 23, 30, tzinfo=UTC)
    order = _order(changed=changed)
    assert order_overdue(order, date(2026, 10, 7), BERLIN)  # 23 Sep + 14
    assert not order_overdue(order, date(2026, 10, 6), BERLIN)
    assert order_overdue(order, date(2026, 10, 6), UTC)


def test_close_unconfirmed_marks_the_order_and_keeps_its_day():
    first, last = TODAY - _days(8), TODAY - _days(6)
    order = _order(first=first, last=last, changed=NOW - _days(9))
    order.result.events.append(TrackingEvent(NOW - _days(9), "Versendet", None))
    order.delivery_code, order.delivery_code_day = "123456", TODAY
    close_unconfirmed(order, NOW)
    result = order.result
    assert order.assumed_delivered is True
    assert result.status is ParcelStatus.DELIVERED
    assert result.status_text == ASSUMED_TEXT == "Abgeschlossen ohne Zustellbestätigung"
    assert result.delivered_at is None  # nobody knows when it came
    assert (result.eta_date, result.eta_latest) == (first, last)
    assert [e.text for e in result.events] == [ASSUMED_TEXT, "Versendet"]
    assert order.last_change_at == NOW
    assert order.delivery_code is None
    # Tidied up like every delivered parcel, counted from the closing.
    assert not should_remove(order, NOW + _days(3), 3)
    assert should_remove(order, NOW + _days(3) + timedelta(minutes=1), 3)


def test_assumed_delivery_is_not_delivered_today():
    order = _order(first=TODAY - _days(8), changed=NOW - _days(9))
    close_unconfirmed(order, NOW)
    assert not delivered_today(order, TODAY, BERLIN)
    summary = summarize([order], TODAY, BERLIN)
    assert summary.delivered_today == [] and summary.active == []
    real = _order(OTHER_ORDER, status=ParcelStatus.DELIVERED)
    assert delivered_today(real, TODAY, BERLIN)


def test_assumed_delivery_builds_no_notification():
    order = _order(first=TODAY - _days(8), changed=NOW - _days(9))
    close_unconfirmed(order, NOW)
    assert build_notification(order, ParcelStatus.IN_TRANSIT, NOW) is None
    order.assumed_delivered = False
    assert build_notification(order, ParcelStatus.IN_TRANSIT, NOW) is not None


def test_assumed_flag_is_stored_and_old_stores_load_without_it():
    order = _order(first=TODAY - _days(8), changed=NOW - _days(9))
    assert order.to_dict()["assumed_delivered"] is False
    close_unconfirmed(order, NOW)
    data = order.to_dict()
    assert data["assumed_delivered"] is True
    assert Parcel.from_dict(data).assumed_delivered is True
    del data["assumed_delivered"]  # written by v0.3.19
    assert Parcel.from_dict(data).assumed_delivered is False
    assert Parcel.from_dict({**data, "assumed_delivered": "yes"}).assumed_delivered is False


def _closed_order() -> Parcel:
    order = _order(first=TODAY - _days(8), changed=NOW - _days(9))
    close_unconfirmed(order, NOW - _days(1))
    return order


def _shop_mail(status, sent=NOW, **fields) -> MailUpdate:
    return MailUpdate(ORDER, "amazon", status, sent.astimezone(BERLIN), title=TITLE, **fields)


def test_a_real_delivery_mail_replaces_the_assumed_one():
    parcels = {ORDER: _closed_order()}
    delivered_at = NOW - timedelta(hours=2)
    mail = _shop_mail(ParcelStatus.DELIVERED, delivered_at=delivered_at.astimezone(BERLIN))
    change = apply_update(parcels, mail, NOW)
    order = parcels[ORDER]
    assert order.assumed_delivered is False
    assert (order.status, order.result.status_text) == (ParcelStatus.DELIVERED, "Zugestellt")
    assert order.result.delivered_at == delivered_at
    assert [e.text for e in order.result.events][:2] == ["Zugestellt", ASSUMED_TEXT]
    # Delivered before and after: no status change, so nothing is announced.
    assert change.old_status is ParcelStatus.DELIVERED
    assert delivered_today(order, TODAY, BERLIN)


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (ParcelStatus.IN_TRANSIT, "Versendet"),
        (ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung"),
    ],
)
def test_a_later_mail_with_a_new_day_reopens_the_order(status, text):
    parcels = {ORDER: _closed_order()}
    new_day = TODAY + _days(2)
    change = apply_update(parcels, _shop_mail(status, eta_date=new_day), NOW)
    order = parcels[ORDER]
    assert order.assumed_delivered is False
    assert (order.status, order.result.status_text) == (status, text)
    assert order.result.eta_date == new_day
    assert order.result.delivered_at is None
    assert change.old_status is ParcelStatus.DELIVERED
    assert order.last_change_at == NOW
    assert not order_overdue(order, TODAY, BERLIN)
    assert len(parcels) == 1


def test_a_reopening_mail_without_a_day_starts_the_wait_anew():
    """ "Verspätet" without a new day: open again, and closed again only days later."""
    parcels = {ORDER: _closed_order()}
    apply_update(parcels, _shop_mail(ParcelStatus.IN_TRANSIT), NOW)
    order = parcels[ORDER]
    assert (order.status, order.assumed_delivered) == (ParcelStatus.IN_TRANSIT, False)
    assert order.result.eta_date == TODAY - _days(8)  # the day named before stays
    assert not order_overdue(order, TODAY + _days(ORDER_OVERDUE_DAYS), BERLIN)
    assert order_overdue(order, TODAY + _days(ORDER_OVERDUE_DAYS + 1), BERLIN)


def test_a_really_delivered_order_still_never_goes_backwards():
    order = _order(status=ParcelStatus.DELIVERED)
    parcels = {ORDER: order}
    assert apply_update(parcels, _shop_mail(ParcelStatus.IN_TRANSIT, eta_date=TODAY), NOW) is None
    assert order.status is ParcelStatus.DELIVERED


# ----- the coordinator -----
class FakeCarrier(Carrier):
    key = "dhl"
    name = "DHL"

    def __init__(self, answer=None):
        self.answer = answer
        self.calls = 0

    @staticmethod
    def matches(number):
        return Match.SURE

    async def fetch(self, number, postcode):
        self.calls += 1
        return self.answer


async def _coordinator(hass, hass_storage, parcels, carrier=None, targets=(PHONE,)):
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {"parcels": [p.to_dict() for p in parcels], "message_ids": []},
    }
    entry = MockConfigEntry(
        domain=DOMAIN, data={"postcode": "10115"}, options={CONF_NOTIFY_TARGETS: list(targets)}
    )
    entry.add_to_hass(hass)
    for target in targets:
        hass.states.async_set(target, "unknown")
    store = ParcelStore(hass)
    await store.async_load()
    carriers = {"dhl": carrier} if carrier else {}
    return ParcelCoordinator(hass, entry, store, carriers)


async def _refresh(hass, coord):
    await coord.async_refresh()
    await hass.async_block_till_done()


async def _prepared(hass, freezer):
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("Europe/Berlin")
    return (
        async_mock_service(hass, "notify", "send_message"),
        async_capture_events(hass, EVENT_STATUS_CHANGED),
    )


async def test_stored_delivered_carrier_parcel_is_folded_at_the_first_refresh(
    hass, hass_storage, freezer
):
    """The double seen live: the order stays "Versendet", its DHL parcel was delivered."""
    calls, events = await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(1), last=TODAY, changed=NOW - _days(3))
    coord = await _coordinator(hass, hass_storage, [order, _carrier_parcel()])
    await _refresh(hass, coord)

    stored = coord.store.parcels
    assert list(stored) == [ORDER]
    assert stored[ORDER].status is ParcelStatus.DELIVERED
    assert (stored[ORDER].tracking_ref, stored[ORDER].tracking_carrier) == (DHL, "dhl")
    assert stored[ORDER].result.delivered_at == NOW
    assert list(coord.data) == [ORDER]
    assert events == [] and calls == []  # the delivery was announced with the DHL parcel
    saved = hass_storage[DOMAIN]["data"]["parcels"]
    assert [p["number"] for p in saved] == [ORDER]
    assert saved[0]["tracking_ref"] == DHL

    # After a restart: nothing left to do, nothing told.
    again = await _coordinator(hass, hass_storage, [Parcel.from_dict(p) for p in saved])
    await _refresh(hass, again)
    assert list(again.store.parcels) == [ORDER]
    assert events == [] and calls == []


async def test_delivery_found_by_a_lookup_closes_the_order_with_one_announcement(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(1), last=TODAY, changed=NOW - _days(3))
    carrier = FakeCarrier(_result(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung"))
    parcel = _carrier_parcel(status=ParcelStatus.OUT_FOR_DELIVERY, delivered_at=None)
    coord = await _coordinator(hass, hass_storage, [order, parcel], carrier)
    await _refresh(hass, coord)
    assert set(coord.store.parcels) == {ORDER, DHL}  # not delivered: both stay

    carrier.answer = _result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=NOW)
    coord.store.parcels[DHL].next_poll_at = None
    await _refresh(hass, coord)
    assert list(coord.store.parcels) == [ORDER]
    assert coord.store.parcels[ORDER].status is ParcelStatus.DELIVERED
    assert coord.store.parcels[ORDER].tracking_ref == DHL
    # Once for the box: the carrier parcel's delivery, nothing for the order.
    assert [(e.data["number"], e.data["new_status"]) for e in events] == [(DHL, "delivered")]
    assert len(calls) == 1
    assert calls[0].data["message"] == "✅ Beispielmarke GmbH (DHL) wurde zugestellt"

    # The order has a number now, but a delivered parcel is never asked again.
    asked = carrier.calls
    freezer.tick(timedelta(hours=5))
    await _refresh(hass, coord)
    assert carrier.calls == asked and len(events) == 1 and len(calls) == 1


async def test_delivery_found_while_starting_is_announced_once_with_the_order(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    hass.set_state(CoreState.starting)
    order = _order(first=TODAY - _days(1), last=TODAY, changed=NOW - _days(3))
    carrier = FakeCarrier(_result(ParcelStatus.DELIVERED, "Zugestellt", delivered_at=NOW))
    parcel = _carrier_parcel(status=ParcelStatus.OUT_FOR_DELIVERY, delivered_at=None)
    parcel.next_poll_at = None
    coord = await _coordinator(hass, hass_storage, [order, parcel], carrier)
    await _refresh(hass, coord)
    assert list(coord.store.parcels) == [ORDER]
    assert events == [] and calls == []
    # Kept with the order, also across another restart.
    assert hass_storage[DOMAIN]["data"]["parcels"][0]["unannounced_from"] == "in_transit"

    await _start(hass)
    assert [(e.data["number"], e.data["old_status"], e.data["new_status"]) for e in events] == [
        (ORDER, "in_transit", "delivered")
    ]
    assert events[0].data["assumed"] is False
    assert [call.data["message"] for call in calls] == [
        f"✅ {TITLE[:39].rstrip()}… (Amazon) wurde zugestellt"
    ]
    await coord.async_shutdown()


async def test_delivery_from_a_carrier_mail_closes_the_order(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(1), last=TODAY + _days(1), changed=NOW - _days(3))
    other = _order(OTHER_ORDER, "Beispielmarke Filter", TODAY, TODAY, changed=NOW - _days(1))
    parcel = _carrier_parcel(status=ParcelStatus.OUT_FOR_DELIVERY, delivered_at=None)
    parcel.next_poll_at = NOW + _days(1)
    # Two orders of the brand when the parcel was created: a parcel of its own.
    coord = await _coordinator(hass, hass_storage, [order, other, parcel])
    await _refresh(hass, coord)
    assert set(coord.store.parcels) == {ORDER, OTHER_ORDER, DHL}

    # The other order got its own delivery meanwhile; now the DHL mail says "zugestellt".
    coord.store.parcels[OTHER_ORDER].result.status = ParcelStatus.DELIVERED
    mail = MailUpdate(DHL, "dhl", ParcelStatus.DELIVERED, dt_util.now(), title=BRAND)
    async with coord._lock:
        coord._handle_mail(_ParsedMail(message_id="<1@synthetic.example>",
                                       result=MailResult([mail])), dt_util.utcnow())
        coord._settle_orders(dt_util.utcnow())
    await hass.async_block_till_done()
    assert set(coord.store.parcels) == {ORDER, OTHER_ORDER}
    folded = coord.store.parcels[ORDER]
    assert (folded.status, folded.tracking_ref) == (ParcelStatus.DELIVERED, DHL)
    assert [(e.data["number"], e.data["new_status"]) for e in events] == [(DHL, "delivered")]
    assert len(calls) == 1


async def test_a_delivered_parcel_is_looked_at_once(hass, hass_storage, freezer):
    """Two orders of the brand at the delivery: no fold. When one of them is closed later,
    the parcel must not fall to the other by elimination - also not after a restart."""
    calls, events = await _prepared(hass, freezer)
    one = _order(first=TODAY - _days(1), last=TODAY + _days(1), changed=NOW - _days(3))
    two = _order(OTHER_ORDER, "Beispielmarke Filter", TODAY, TODAY, changed=NOW - _days(1))
    coord = await _coordinator(hass, hass_storage, [one, two, _carrier_parcel()])
    await _refresh(hass, coord)
    assert set(coord.store.parcels) == {ORDER, OTHER_ORDER, DHL}
    assert coord.store.parcels[DHL].order_checked is True
    saved = {p["number"]: p for p in hass_storage[DOMAIN]["data"]["parcels"]}
    assert saved[DHL]["order_checked"] is True

    coord.store.parcels[OTHER_ORDER].result.status = ParcelStatus.DELIVERED
    freezer.tick(timedelta(minutes=1))
    await _refresh(hass, coord)
    assert set(coord.store.parcels) == {ORDER, OTHER_ORDER, DHL}
    assert coord.store.parcels[ORDER].status is ParcelStatus.IN_TRANSIT

    await coord.store.async_save()
    stored = [Parcel.from_dict(p) for p in hass_storage[DOMAIN]["data"]["parcels"]]
    again = await _coordinator(hass, hass_storage, stored)
    await _refresh(hass, again)
    assert set(again.store.parcels) == {ORDER, OTHER_ORDER, DHL}
    assert events == [] and calls == []


def test_check_flag_is_stored_and_old_stores_load_without_it():
    parcel = _carrier_parcel()
    data = parcel.to_dict()
    assert data["order_checked"] is False
    assert Parcel.from_dict({**data, "order_checked": True}).order_checked is True
    del data["order_checked"]  # written by v0.3.19
    assert Parcel.from_dict(data).order_checked is False


async def test_parcel_added_by_hand_is_never_folded(hass, hass_storage, freezer):
    await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(1), last=TODAY, changed=NOW - _days(1))
    coord = await _coordinator(hass, hass_storage, [order, _carrier_parcel(mode="manual")])
    await _refresh(hass, coord)
    assert set(coord.store.parcels) == {ORDER, DHL}
    assert coord.store.parcels[ORDER].status is ParcelStatus.IN_TRANSIT


async def test_overdue_order_is_closed_without_a_notification(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    overdue = _order(first=TODAY - _days(6), last=TODAY - _days(4), changed=NOW - _days(8))
    in_time = _order(OTHER_ORDER, "Kopfhörer", TODAY - _days(3), changed=NOW - _days(8))
    asked = _order(EBAY_ORDER, "Lampe", TODAY - _days(9), carrier="ebay", changed=NOW - _days(9))
    asked.tracking_ref, asked.tracking_carrier = "H1000999999999999901", "hermes"
    coord = await _coordinator(hass, hass_storage, [overdue, in_time, asked])
    await _refresh(hass, coord)  # the first refresh: closed, told once announcing starts
    await hass.async_block_till_done()

    order = coord.store.parcels[ORDER]
    assert order.status is ParcelStatus.DELIVERED and order.assumed_delivered is True
    assert order.result.status_text == "Abgeschlossen ohne Zustellbestätigung"
    assert coord.store.parcels[OTHER_ORDER].status is ParcelStatus.IN_TRANSIT
    assert coord.store.parcels[EBAY_ORDER].status is ParcelStatus.IN_TRANSIT  # has a number
    assert coord.store.parcels[EBAY_ORDER].assumed_delivered is False
    saved = {p["number"]: p for p in hass_storage[DOMAIN]["data"]["parcels"]}
    assert saved[ORDER]["assumed_delivered"] is True

    # The event tells automations, marked as assumed; no push.
    assert [
        (e.data["number"], e.data["old_status"], e.data["new_status"], e.data["assumed"])
        for e in events
    ] == [(ORDER, "in_transit", "delivered", True)]
    assert calls == []
    assert summarize(coord.store.parcels.values(), TODAY, BERLIN).delivered_today == []

    # Nothing more with the next refreshes; one day later the second order is due.
    freezer.tick(timedelta(hours=1))
    await _refresh(hass, coord)
    assert len(events) == 1
    freezer.tick(timedelta(days=1))
    await _refresh(hass, coord)
    assert coord.store.parcels[OTHER_ORDER].assumed_delivered is True
    assert [e.data["number"] for e in events] == [ORDER, OTHER_ORDER]
    assert calls == []

    # Gone like every delivered parcel after the days it is kept (default 3).
    freezer.tick(timedelta(days=3, minutes=1))
    await _refresh(hass, coord)
    assert ORDER not in coord.store.parcels
    await coord.async_shutdown()


async def test_closing_found_while_starting_stays_without_a_notification(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    hass.set_state(CoreState.starting)
    overdue = _order(first=TODAY - _days(6), changed=NOW - _days(8))
    coord = await _coordinator(hass, hass_storage, [overdue])
    await _refresh(hass, coord)
    assert coord.store.parcels[ORDER].assumed_delivered is True
    assert events == [] and calls == []
    await _start(hass)
    assert [(e.data["new_status"], e.data["assumed"]) for e in events] == [("delivered", True)]
    assert calls == []
    await coord.async_shutdown()


async def test_mails_after_the_closing(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    overdue = _order(first=TODAY - _days(6), changed=NOW - _days(8))
    coord = await _coordinator(hass, hass_storage, [overdue])
    await _refresh(hass, coord)
    await hass.async_block_till_done()
    assert len(events) == 1 and events[0].data["assumed"] is True

    async def mail(index, update):
        async with coord._lock:
            coord._handle_mail(
                _ParsedMail(message_id=f"<{index}@synthetic.example>",
                            result=MailResult([update])),
                dt_util.utcnow(),
            )
        await hass.async_block_till_done()

    # A new day: open again, told as a normal change (no push for "Versendet").
    freezer.tick(timedelta(hours=1))
    await mail(1, _shop_mail(ParcelStatus.IN_TRANSIT, dt_util.utcnow(),
                             eta_date=TODAY + _days(1)))
    order = coord.store.parcels[ORDER]
    assert (order.status, order.assumed_delivered) == (ParcelStatus.IN_TRANSIT, False)
    assert [(e.data["old_status"], e.data["new_status"], e.data["assumed"])
            for e in events[1:]] == [("delivered", "in_transit", False)]
    assert calls == []
    await _refresh(hass, coord)
    assert order.status is ParcelStatus.IN_TRANSIT  # not closed again right away

    # Closed once more, then the real delivery mail: the time is taken, nothing is pushed.
    freezer.tick(timedelta(days=5))
    await _refresh(hass, coord)
    assert order.assumed_delivered is True and len(events) == 3
    freezer.tick(timedelta(hours=1))
    sent = dt_util.utcnow()
    await mail(2, _shop_mail(ParcelStatus.DELIVERED, sent, delivered_at=sent))
    assert (order.status, order.assumed_delivered) == (ParcelStatus.DELIVERED, False)
    assert order.result.delivered_at == sent
    assert len(events) == 3 and calls == []
    await coord.async_shutdown()


async def test_sensor_and_diagnostics_show_the_assumed_delivery(hass, hass_storage, freezer):
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("Europe/Berlin")
    overdue = _order(first=TODAY - _days(6), changed=NOW - _days(8))
    in_time = _order(OTHER_ORDER, "Kopfhörer", TODAY, changed=NOW - _days(1))
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {"parcels": [overdue.to_dict(), in_time.to_dict()], "message_ids": []},
    }
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    closed = hass.states.get(f"sensor.paket_{ORDER.lower()}")
    assert closed.state == "delivered"
    assert closed.attributes["assumed_delivered"] is True
    assert closed.attributes["status_text"] == "Abgeschlossen ohne Zustellbestätigung"
    assert closed.attributes["delivered_at"] is None
    assert hass.states.get(f"sensor.paket_{OTHER_ORDER.lower()}").attributes[
        "assumed_delivered"
    ] is False
    assert hass.states.get("sensor.pakete_zugestellt_heute").state == "0"
    assert hass.states.get("sensor.pakete_heute").attributes["delivered_today_count"] == 0
    assert hass.states.get("sensor.pakete_unterwegs").state == "1"

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert [p["assumed_delivered"] for p in diagnostics["parcels"]] == [True, False]


async def test_folded_carrier_parcel_loses_its_sensor(hass, hass_storage, freezer):
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("Europe/Berlin")
    order = _order(first=TODAY - _days(1), last=TODAY + _days(1), changed=NOW - _days(1))
    parcel = _carrier_parcel(status=ParcelStatus.OUT_FOR_DELIVERY, delivered_at=None)
    parcel.next_poll_at = NOW + _days(1)
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {"parcels": [order.to_dict(), parcel.to_dict()], "message_ids": []},
    }
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.paket_{DHL}").state == "out_for_delivery"

    coord = entry.runtime_data
    stored = coord.store.parcels[DHL]
    stored.result.status, stored.result.delivered_at = ParcelStatus.DELIVERED, NOW
    freezer.tick(timedelta(minutes=1))
    await coord.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(f"sensor.paket_{DHL}") is None
    assert er.async_get(hass).async_get(f"sensor.paket_{DHL}") is None
    state = hass.states.get(f"sensor.paket_{ORDER.lower()}")
    assert state.state == "delivered"
    assert (state.attributes["tracking_ref"], state.attributes["tracking_carrier"]) == (DHL, "dhl")
    assert state.attributes["assumed_delivered"] is False
    assert hass.states.get("sensor.pakete_zugestellt_heute").state == "1"

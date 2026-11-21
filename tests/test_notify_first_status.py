"""The first status of a parcel a mail made is news; the order that takes the parcel in does
not push the status again."""

from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus

from .test_coordinator_notify import _start
from .test_order_closing import (
    DHL,
    NOW,
    FakeCarrier,
    _coordinator,
    _prepared,
    _refresh,
    _result,
)
from .test_review_shared import ALI_A, MOVING, OUT, _ali, _local
from .test_review_third import _import

ORDERED = ParcelStatus.PRE_TRANSIT


def _without_status(mode="mail") -> Parcel:
    """A carrier's parcel whose mail told no status (DPD's mails without a word for it)."""
    return Parcel(DHL, "dhl", mode, None, NOW, NOW)


def _events(events):
    return [(e.data["number"], e.data["old_status"], e.data["new_status"]) for e in events]


# ----- a first status that comes later -----
async def test_the_carriers_first_answer_tells_the_first_status(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(OUT, "In Zustellung"))
    coord = await _coordinator(hass, hass_storage, [_without_status()], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    assert coord.store.parcels[DHL].status is OUT
    assert _events(events) == [(DHL, "unknown", "out_for_delivery")]
    assert len(calls) == 1  # "In Zustellung" is ticked by default
    await coord.async_shutdown()


async def test_a_parcel_the_user_added_tells_no_first_status(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    carrier = FakeCarrier(_result(OUT, "In Zustellung"))
    coord = await _coordinator(hass, hass_storage, [_without_status("manual")], carrier)
    await _refresh(hass, coord)
    await _start(hass)
    assert coord.store.parcels[DHL].status is OUT
    assert events == [] and calls == []
    await coord.async_shutdown()


async def test_the_next_mail_tells_the_first_status(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    coord = await _coordinator(hass, hass_storage, [_without_status()])
    await _refresh(hass, coord)
    await _start(hass)
    await _import(coord, hass, MailUpdate(DHL, "dhl", OUT, _local(NOW)))
    assert _events(events) == [(DHL, "unknown", "out_for_delivery")]
    assert len(calls) == 1
    await coord.async_shutdown()


# ----- the order takes the parcel in -----
def _told_parcel(status=OUT) -> Parcel:
    """A carrier's parcel a mail made; its status was told (nothing waits)."""
    parcel = Parcel(DHL, "dhl", "mail", None, NOW, NOW, order_checked=True,
                    result=_result(status, "In Zustellung"))
    assert parcel.unannounced_from is None
    return parcel


def _box_mail(status=OUT) -> MailUpdate:
    return MailUpdate(ALI_A, "aliexpress", status, _local(NOW), tracking_ref=DHL,
                      tracking_carrier="dhl")


def test_the_order_takes_over_a_status_the_parcel_told():
    parcels = {ALI_A: _ali(ALI_A, None, status=ORDERED), DHL: _told_parcel()}
    change = apply_update(parcels, _box_mail(), NOW)
    assert list(parcels) == [ALI_A]
    assert (change.old_status, parcels[ALI_A].status, change.told) == (ORDERED, OUT, True)


def test_a_status_the_parcel_did_not_have_is_the_orders_news():
    parcels = {ALI_A: _ali(ALI_A, None, status=ORDERED), DHL: _told_parcel(MOVING)}
    change = apply_update(parcels, _box_mail(OUT), NOW)
    assert list(parcels) == [ALI_A]
    assert (parcels[ALI_A].status, change.told) == (OUT, False)


def test_a_status_still_waiting_to_be_told_is_the_orders_news():
    parcel = _told_parcel()
    parcel.unannounced_from = MOVING
    parcels = {ALI_A: _ali(ALI_A, None, status=ORDERED), DHL: parcel}
    change = apply_update(parcels, _box_mail(), NOW)
    assert list(parcels) == [ALI_A] and change.told is False


async def test_after_a_restart_the_order_does_not_push_the_parcels_status_again(
    hass, hass_storage, freezer
):
    """The DHL mail made the parcel, "In Zustellung" was pushed, Home Assistant restarted
    (the push memory of the box is gone). Now the order's mail names the number."""
    calls, events = await _prepared(hass, freezer)
    order = _ali(ALI_A, None, status=ORDERED)
    coord = await _coordinator(hass, hass_storage, [order, _told_parcel()])
    await _refresh(hass, coord)
    await _start(hass)
    assert coord._box_told == {} and calls == []
    await _import(coord, hass, _box_mail())
    assert list(coord.store.parcels) == [ALI_A]
    assert coord.store.parcels[ALI_A].status is OUT
    # The order's own step is an event; the box is not pushed a second time.
    assert _events(events) == [(ALI_A, "pre_transit", "out_for_delivery")]
    assert calls == []
    await coord.async_shutdown()

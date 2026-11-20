"""v0.3.56: "0" hides a delivered parcel at the midnight after its delivery (simon42 #153)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.parcel_tracker.const import MIN_KEEP_DELIVERED_DAYS
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.schedule import should_remove

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")


def _parcel(status: ParcelStatus, delivered_at: datetime | None, changed: datetime) -> Parcel:
    result = TrackingResult(status, "x", None, None, None, None, None, None, delivered_at)
    return Parcel("00340434161234567890", "dhl", "manual", None, changed, changed, result=result)


def _local(day: int, hour: int, minute: int = 0, tz=BERLIN) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=tz).astimezone(UTC)


def test_zero_is_allowed():
    assert MIN_KEEP_DELIVERED_DAYS == 0


def test_delivered_today_stays_until_midnight():
    delivered = _local(17, 15)
    parcel = _parcel(ParcelStatus.DELIVERED, delivered, delivered)
    assert not should_remove(parcel, _local(17, 23, 59), 0, BERLIN)
    assert should_remove(parcel, _local(18, 0, 0), 0, BERLIN)


def test_delivered_late_in_the_evening_goes_at_midnight_too():
    delivered = _local(17, 23, 30)
    parcel = _parcel(ParcelStatus.DELIVERED, delivered, delivered)
    assert not should_remove(parcel, _local(17, 23, 45), 0, BERLIN)
    assert should_remove(parcel, _local(18, 0, 1), 0, BERLIN)


def test_the_local_day_decides_not_utc():
    # 00:30 in Berlin is still the evening before in UTC.
    delivered = _local(17, 0, 30)
    parcel = _parcel(ParcelStatus.DELIVERED, delivered, delivered)
    assert not should_remove(parcel, _local(17, 22), 0, BERLIN)
    delivered_ny = _local(17, 20, tz=NEW_YORK)  # already the 18th in UTC
    parcel_ny = _parcel(ParcelStatus.DELIVERED, delivered_ny, delivered_ny)
    assert not should_remove(parcel_ny, _local(17, 23, tz=NEW_YORK), 0, NEW_YORK)
    assert should_remove(parcel_ny, _local(18, 0, 5, tz=NEW_YORK), 0, NEW_YORK)


def test_without_a_time_of_delivery_the_last_change_counts():
    changed = _local(17, 10)
    parcel = _parcel(ParcelStatus.DELIVERED, None, changed)
    assert not should_remove(parcel, _local(17, 20), 0, BERLIN)
    assert should_remove(parcel, _local(18, 0, 1), 0, BERLIN)


def test_a_cancelled_order_goes_at_midnight_as_well():
    changed = _local(17, 9)
    parcel = _parcel(ParcelStatus.CANCELLED, None, changed)
    assert not should_remove(parcel, _local(17, 23), 0, BERLIN)
    assert should_remove(parcel, _local(18, 0, 1), 0, BERLIN)


def test_open_parcels_are_not_touched_by_zero():
    changed = _local(10, 9)
    parcel = _parcel(ParcelStatus.IN_TRANSIT, None, changed)
    assert not should_remove(parcel, _local(18, 9), 0, BERLIN)


def test_one_day_still_counts_from_the_time_of_delivery():
    delivered = _local(17, 15)
    parcel = _parcel(ParcelStatus.DELIVERED, delivered, delivered)
    assert not should_remove(parcel, delivered + timedelta(days=1), 1, BERLIN)
    assert should_remove(parcel, delivered + timedelta(days=1, minutes=1), 1, BERLIN)
    assert not should_remove(parcel, delivered + timedelta(days=1), 1)


# ----- review: nothing is lost or comes back with 0 -----

from unittest.mock import patch  # noqa: E402

from homeassistant.util import dt as dt_util  # noqa: E402

from custom_components.parcel_tracker.const import (  # noqa: E402
    CONF_KEEP_DELIVERED_DAYS,
    REMOVED_KEEP,
)
from custom_components.parcel_tracker.coordinator import _ParsedMail  # noqa: E402
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate  # noqa: E402
from custom_components.parcel_tracker.store import ParcelStore  # noqa: E402

from .test_coordinator_mail import _coordinator  # noqa: E402

NUMBER = "00340434161234567890"
JUST_AFTER_MIDNIGHT = _local(18, 0, 5)


async def _delivered_yesterday(hass):
    coord = await _coordinator(hass, None, {CONF_KEEP_DELIVERED_DAYS: 0})
    delivered = _local(17, 23, 40)
    coord.store.add(_parcel(ParcelStatus.DELIVERED, delivered, delivered))
    return coord


async def test_a_parcel_whose_push_still_waits_stays_past_midnight(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")
    coord = await _delivered_yesterday(hass)
    coord.store.parcels[NUMBER].unannounced_from = ParcelStatus.IN_TRANSIT
    coord._cleanup(JUST_AFTER_MIDNIGHT)
    assert NUMBER in coord.store.parcels
    coord.store.parcels[NUMBER].unannounced_from = None
    coord._cleanup(JUST_AFTER_MIDNIGHT)
    assert NUMBER not in coord.store.parcels
    assert coord.store.was_removed(NUMBER)


async def _import(coord, update, message_id):
    parsed = [_ParsedMail(message_id=message_id, result=MailResult([update]))]
    with patch("custom_components.parcel_tracker.coordinator._parse_mails", return_value=parsed):
        return await coord.async_import_raw_mail(b"synthetic")


async def test_a_late_mail_does_not_bring_a_removed_parcel_back(hass, freezer):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(JUST_AFTER_MIDNIGHT)
    coord = await _delivered_yesterday(hass)
    coord._cleanup(dt_util.utcnow())
    assert coord.store.parcels == {}
    late = MailUpdate(NUMBER, "dhl", ParcelStatus.DELIVERED, dt_util.now(), title="Beispiel")
    with patch.object(coord, "_fire") as fire:
        await _import(coord, late, "<late-1@synthetic.example>")
    await hass.async_block_till_done()
    assert coord.store.parcels == {}
    fire.assert_not_called()
    # Two days on, the number is free again.
    later = JUST_AFTER_MIDNIGHT + REMOVED_KEEP + timedelta(minutes=1)
    freezer.move_to(later)
    coord._cleanup(later)
    assert not coord.store.was_removed(NUMBER)
    again = MailUpdate(NUMBER, "dhl", ParcelStatus.IN_TRANSIT, dt_util.now(), title="Beispiel")
    await _import(coord, again, "<late-2@synthetic.example>")
    assert NUMBER in coord.store.parcels


async def test_the_removed_numbers_survive_a_restart(hass):
    store = ParcelStore(hass)
    await store.async_load()
    delivered = _local(17, 23, 40)
    parcel = _parcel(ParcelStatus.DELIVERED, delivered, delivered)
    parcel.tracking_ref = "JJD000390012345678901"
    store.mark_removed(parcel, JUST_AFTER_MIDNIGHT)
    await store.async_save()
    loaded = ParcelStore(hass)
    await loaded.async_load()
    assert loaded.removed == {NUMBER: JUST_AFTER_MIDNIGHT, parcel.tracking_ref: JUST_AFTER_MIDNIGHT}


ORDER = "AMZ99912345677654321"
DHL_1 = "00340434161234567890"
DHL_2 = "00340434161234567891"


async def _order_removed(hass):
    coord = await _coordinator(hass, None, {CONF_KEEP_DELIVERED_DAYS: 0})
    delivered = _local(17, 15)
    order = _parcel(ParcelStatus.DELIVERED, delivered, delivered)
    order.number, order.carrier, order.tracking_ref = ORDER, "amazon", DHL_1
    order.tracking_carrier = "dhl"
    coord.store.add(order)
    coord._cleanup(JUST_AFTER_MIDNIGHT)
    assert coord.store.parcels == {}
    return coord


async def test_the_order_number_of_a_removed_order_is_not_held_back(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")
    coord = await _order_removed(hass)
    assert coord.store.was_removed(DHL_1) and not coord.store.was_removed(ORDER)
    sent = dt_util.now()
    second = MailUpdate(
        ORDER, "amazon", ParcelStatus.IN_TRANSIT, sent, tracking_ref=DHL_2, tracking_carrier="dhl"
    )
    assert not coord._removed_lately(second)
    only_order = MailUpdate(ORDER, "amazon", ParcelStatus.DELIVERED, sent)
    assert not coord._removed_lately(only_order)


async def test_the_carrier_number_of_a_removed_order_is_held_back(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")
    coord = await _order_removed(hass)
    sent = dt_util.now()
    assert coord._removed_lately(MailUpdate(DHL_1, "dhl", ParcelStatus.DELIVERED, sent))
    late_shop = MailUpdate(
        ORDER, "amazon", ParcelStatus.DELIVERED, sent, tracking_ref=DHL_1, tracking_carrier="dhl"
    )
    assert coord._removed_lately(late_shop)


async def test_an_item_cancelled_from_a_removed_order_keeps_no_late_mail_coming(hass):
    # (it takes no mail: the late one would make a phantom "…P3" delivered)
    await hass.config.async_set_time_zone("Europe/Berlin")
    coord = await _order_removed(hass)
    cancelled = _parcel(ParcelStatus.CANCELLED, None, _local(17, 9))
    cancelled.number, cancelled.carrier = f"{ORDER}P2", "amazon"
    coord.store.add(cancelled)
    late_shop = MailUpdate(
        ORDER, "amazon", ParcelStatus.DELIVERED, dt_util.now(), tracking_ref=DHL_1,
        tracking_carrier="dhl",
    )
    assert coord._removed_lately(late_shop)


async def test_the_next_parcel_of_a_removed_order_comes_in(hass, freezer):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(JUST_AFTER_MIDNIGHT)
    coord = await _order_removed(hass)
    second = MailUpdate(
        ORDER, "amazon", ParcelStatus.IN_TRANSIT, dt_util.now(), title="Beispiel",
        tracking_ref=DHL_2, tracking_carrier="dhl",
    )
    await _import(coord, second, "<order-2@synthetic.example>")
    assert any(p.tracking_ref == DHL_2 or p.number == DHL_2 for p in coord.store.parcels.values())


async def test_an_open_order_in_the_same_box_still_takes_its_mail(hass):
    await hass.config.async_set_time_zone("Europe/Berlin")
    coord = await _order_removed(hass)
    other = "AMZ99912345677654322"
    open_order = _parcel(ParcelStatus.PRE_TRANSIT, None, _local(17, 9))
    open_order.number, open_order.carrier = other, "amazon"
    coord.store.add(open_order)
    mail = MailUpdate(
        other, "amazon", ParcelStatus.IN_TRANSIT, dt_util.now(), tracking_ref=DHL_1,
        tracking_carrier="dhl",
    )
    assert not coord._removed_lately(mail)

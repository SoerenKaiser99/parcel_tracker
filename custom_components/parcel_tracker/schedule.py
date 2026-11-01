"""Polling schedule and cleanup rules (no Home Assistant imports)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo

from .carriers.base import BERLIN
from .const import (
    ORDER_NO_ETA_DAYS,
    ORDER_OVERDUE_DAYS,
    SHIP_LATER_SHOPS,
    SHOP_CARRIERS,
    STALE_REMOVE_DAYS,
)
from .models import CLOSED_STATUSES, Parcel, ParcelStatus

_INTERVALS = {
    ParcelStatus.OUT_FOR_DELIVERY: timedelta(minutes=10),
    ParcelStatus.IN_TRANSIT: timedelta(minutes=30),
    ParcelStatus.AT_DELIVERY_DEPOT: timedelta(minutes=30),
    ParcelStatus.AWAITING_PICKUP: timedelta(minutes=30),
}
_DEFAULT = timedelta(minutes=60)
_NIGHT_MIN = timedelta(minutes=60)
# The UPS API counts against a monthly budget: ask rarely, more often only on the day.
_UPS_INTERVALS = {ParcelStatus.OUT_FOR_DELIVERY: timedelta(minutes=30)}
_UPS_DEFAULT = timedelta(hours=4)
# GLS has no official API: its open lookup is never asked more often than this.
GLS_MIN_INTERVAL = timedelta(minutes=30)


def poll_interval(
    status: ParcelStatus | None, now: datetime, carrier: str | None = None
) -> timedelta | None:
    """Return the time until the next poll, None if polling stops."""
    if status in CLOSED_STATUSES:
        return None
    if carrier == "ups":
        interval = _UPS_INTERVALS.get(status, _UPS_DEFAULT) if status else _UPS_DEFAULT
    else:
        interval = _INTERVALS.get(status, _DEFAULT) if status else _DEFAULT
    if carrier == "gls":
        interval = max(interval, GLS_MIN_INTERVAL)
    local_hour = now.astimezone(BERLIN).hour
    if local_hour >= 22 or local_hour < 6:
        interval = max(interval, _NIGHT_MIN)
    return interval


def backoff(streak: int) -> timedelta:
    """Exponential backoff 5, 10, 20 … capped at 120 minutes."""
    minutes = min(5 * 2 ** max(streak - 1, 0), 120)
    return timedelta(minutes=minutes)


def should_remove(parcel: Parcel, now: datetime, keep_delivered_days: int) -> bool:
    """Return True when a parcel should be dropped."""
    result = parcel.result
    if result and result.status in CLOSED_STATUSES:
        delivered = result.delivered_at or parcel.last_change_at
        return now - delivered > timedelta(days=keep_delivered_days)
    return now - parcel.last_change_at > timedelta(days=STALE_REMOVE_DAYS)


# Nothing more is expected for an order in one of these statuses.
_ORDER_FINAL = frozenset(
    {
        ParcelStatus.DELIVERED,
        ParcelStatus.AWAITING_PICKUP,
        ParcelStatus.EXCEPTION,
        ParcelStatus.CANCELLED,
    }
)


def order_overdue(
    parcel: Parcel, today: date, tz: tzinfo = BERLIN, askable: bool = True
) -> bool:
    """Tell whether a shop order waits in vain for its "delivered" mail.

    Only an order nobody can ask about (Amazon, eBay, AliExpress, Eventim) that is not
    delivered, ready for pickup, in trouble or cancelled. Nobody can ask about an order
    without a carrier number. An order with a number is overdue only if nobody can be asked about
    that number at all with the current settings (``askable`` False, the caller knows:
    no lookup for its carrier, e.g. UPS without its API or DHL without a key, and no
    17track). What a carrier that can be asked answered last says nothing here: a number
    it does not know yet, or one failed lookup, never closes an order - the carrier may
    tell the delivery tomorrow. Its last delivery day
    must lie more than ORDER_OVERDUE_DAYS full days before ``today`` (a day in ``tz``); a
    mail that changed the order after that day counts from the day it came. Without any
    delivery day: ORDER_NO_ETA_DAYS days after the last change. Never an Eventim order
    that is only "Bestellt": its tickets may be sent months later (SHIP_LATER_SHOPS).
    """
    if parcel.carrier not in SHOP_CARRIERS:
        return False
    if parcel.tracking_ref is not None and askable:
        return False
    result = parcel.result
    if result is not None and result.status in _ORDER_FINAL:
        return False
    if parcel.carrier in SHIP_LATER_SHOPS and (
        result is None or result.status is ParcelStatus.PRE_TRANSIT
    ):
        return False
    changed = parcel.last_change_at.astimezone(tz).date()
    last = (result.eta_latest or result.eta_date) if result else None
    if last is None:
        return (today - changed).days >= ORDER_NO_ETA_DAYS
    return (today - max(last, changed)).days > ORDER_OVERDUE_DAYS


def days_until(eta: date | None, today: date) -> int | None:
    """Days from today to the ETA (0 = today)."""
    return (eta - today).days if eta else None


# Groups of sensor.pakete_heute: counted ("sure") or only listed ("possible").
TODAY_SURE = "sure"
TODAY_POSSIBLE = "possible"


def today_group(parcel: Parcel, today: date, tz: tzinfo = BERLIN) -> str | None:
    """Tell whether a parcel comes today for sure, possibly, or not (None).

    Sure: in delivery, or a fixed delivery day today. Possible: today lies within
    a delivery window of several days ("2.–5. Okt."). Delivered and cancelled parcels are neither.

    "In delivery" does not hold forever: a parcel whose "delivered" never arrives
    leaves the group once its estimate is over, or, without any estimate, once the
    day of its last change (in ``tz``, the time zone ``today`` is meant in) is over.
    """
    result = parcel.result
    if result is None or result.status in CLOSED_STATUSES:
        return None
    first, last = result.eta_date, result.eta_latest
    if result.status is ParcelStatus.OUT_FOR_DELIVERY:
        end = last or first
        if end is None:
            return TODAY_SURE if _changed_on(parcel, tz) == today else None
        return TODAY_SURE if end >= today else None
    if first is None:
        return None
    if last is None or last <= first:  # one fixed day
        return TODAY_SURE if first == today else None
    return TODAY_POSSIBLE if first <= today <= last else None


def _changed_on(parcel: Parcel, tz: tzinfo) -> date:
    """The day of the parcel's last change, in ``tz``."""
    return parcel.last_change_at.astimezone(tz).date()


def parcel_days_until(parcel: Parcel, today: date, tz: tzinfo = BERLIN) -> int | None:
    """Days from today to the delivery day of a parcel (0 = today), None: no day known.

    A parcel in delivery without any date (Hermes names none) that ``today_group`` counts
    today is due today: 0. A stale one (last change on an earlier day) stays None.
    """
    result = parcel.result
    if result is None:
        return None
    if result.eta_date is not None:
        return days_until(result.eta_date, today)
    if (
        result.status is ParcelStatus.OUT_FOR_DELIVERY
        and today_group(parcel, today, tz) == TODAY_SURE
    ):
        return 0
    return None


def delivered_today(parcel: Parcel, today: date, tz: tzinfo = BERLIN) -> bool:
    """Tell whether a parcel was delivered today (``today`` is a day in ``tz``).

    The time of delivery decides; a carrier or mail that names none leaves the day the
    status changed. Such a parcel is in no group of ``today_group`` any more. An order
    closed without a delivery mail never counts: nobody knows when it came. Neither does
    such an order once the user confirmed it by hand ("Erhalten" sets a time of delivery
    for everything else, see ``mail.apply.mark_received``).
    """
    result = parcel.result
    if result is None or result.status is not ParcelStatus.DELIVERED:
        return False
    if parcel.assumed_delivered:
        return False
    if parcel.manual_delivered and result.delivered_at is None:
        return False
    delivered = result.delivered_at or parcel.last_change_at
    return delivered.astimezone(tz).date() == today


@dataclass
class ParcelSummary:
    """The parcels behind the summary sensors, each list in the order of the store."""

    active: list[Parcel] = field(default_factory=list)  # not delivered yet, not cancelled
    sure: list[Parcel] = field(default_factory=list)  # come today for sure
    possible: list[Parcel] = field(default_factory=list)  # delivery window includes today
    delivered_today: list[Parcel] = field(default_factory=list)
    awaiting_pickup: list[Parcel] = field(default_factory=list)  # wait at a pickup point


def summarize(parcels: Iterable[Parcel], today: date, tz: tzinfo = BERLIN) -> ParcelSummary:
    """Sort the parcels into the lists of the summary sensors (``today`` is a day in ``tz``).

    On the way is every parcel that is neither delivered nor cancelled, whatever else its
    status says (unknown, a problem, waiting at a pickup point, no answer from the carrier yet).
    Today's lists follow ``today_group`` and ``delivered_today``. Ready for pickup is
    every parcel with that status (Packstation, branch, parcel shop); it stays on the way.

    Today's lists count boxes: several shop orders that come in one box (they carry the
    same carrier number) are one entry there, the first of them. On the way and ready
    for pickup is every order.
    """
    summary = ParcelSummary()
    seen: set[tuple[str, str | None, str]] = set()
    for parcel in parcels:
        if parcel.status not in CLOSED_STATUSES:
            summary.active.append(parcel)
        if parcel.status is ParcelStatus.AWAITING_PICKUP:
            summary.awaiting_pickup.append(parcel)
        group = today_group(parcel, today, tz)
        if group is None and delivered_today(parcel, today, tz):
            group = "delivered"
        if group is None:
            continue
        if parcel.tracking_ref:
            box = (group, parcel.tracking_carrier, parcel.tracking_ref)
            if box in seen:
                continue
            seen.add(box)
        if group == TODAY_SURE:
            summary.sure.append(parcel)
        elif group == TODAY_POSSIBLE:
            summary.possible.append(parcel)
        else:
            summary.delivered_today.append(parcel)
    return summary

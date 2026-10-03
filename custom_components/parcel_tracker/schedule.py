"""Polling schedule and cleanup rules (no Home Assistant imports)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo

from .carriers.base import BERLIN
from .const import STALE_REMOVE_DAYS
from .models import Parcel, ParcelStatus

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
    if status is ParcelStatus.DELIVERED:
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
    if result and result.status is ParcelStatus.DELIVERED:
        delivered = result.delivered_at or parcel.last_change_at
        return now - delivered > timedelta(days=keep_delivered_days)
    return now - parcel.last_change_at > timedelta(days=STALE_REMOVE_DAYS)


def days_until(eta: date | None, today: date) -> int | None:
    """Days from today to the ETA (0 = today)."""
    return (eta - today).days if eta else None


# Groups of sensor.pakete_heute: counted ("sure") or only listed ("possible").
TODAY_SURE = "sure"
TODAY_POSSIBLE = "possible"


def today_group(parcel: Parcel, today: date, tz: tzinfo = BERLIN) -> str | None:
    """Tell whether a parcel comes today for sure, possibly, or not (None).

    Sure: in delivery, or a fixed delivery day today. Possible: today lies within
    a delivery window of several days ("2.–5. Okt."). Delivered parcels are neither.

    "In delivery" does not hold forever: a parcel whose "delivered" never arrives
    leaves the group once its estimate is over, or, without any estimate, once the
    day of its last change (in ``tz``, the time zone ``today`` is meant in) is over.
    """
    result = parcel.result
    if result is None or result.status is ParcelStatus.DELIVERED:
        return None
    first, last = result.eta_date, result.eta_latest
    if result.status is ParcelStatus.OUT_FOR_DELIVERY:
        end = last or first
        if end is None:
            end = parcel.last_change_at.astimezone(tz).date()
            return TODAY_SURE if end == today else None
        return TODAY_SURE if end >= today else None
    if first is None:
        return None
    if last is None or last <= first:  # one fixed day
        return TODAY_SURE if first == today else None
    return TODAY_POSSIBLE if first <= today <= last else None


def delivered_today(parcel: Parcel, today: date, tz: tzinfo = BERLIN) -> bool:
    """Tell whether a parcel was delivered today (``today`` is a day in ``tz``).

    The time of delivery decides; a carrier or mail that names none leaves the day the
    status changed. Such a parcel is in no group of ``today_group`` any more.
    """
    result = parcel.result
    if result is None or result.status is not ParcelStatus.DELIVERED:
        return False
    delivered = result.delivered_at or parcel.last_change_at
    return delivered.astimezone(tz).date() == today


@dataclass
class ParcelSummary:
    """The parcels behind the summary sensors, each list in the order of the store."""

    active: list[Parcel] = field(default_factory=list)  # not delivered yet
    sure: list[Parcel] = field(default_factory=list)  # come today for sure
    possible: list[Parcel] = field(default_factory=list)  # delivery window includes today
    delivered_today: list[Parcel] = field(default_factory=list)


def summarize(parcels: Iterable[Parcel], today: date, tz: tzinfo = BERLIN) -> ParcelSummary:
    """Sort the parcels into the lists of the summary sensors (``today`` is a day in ``tz``).

    On the way is every parcel that is not delivered, whatever else its status says
    (unknown, a problem, waiting at a pickup point, no answer from the carrier yet).
    Today's lists follow ``today_group`` and ``delivered_today``.
    """
    summary = ParcelSummary()
    for parcel in parcels:
        if parcel.status is not ParcelStatus.DELIVERED:
            summary.active.append(parcel)
        group = today_group(parcel, today, tz)
        if group == TODAY_SURE:
            summary.sure.append(parcel)
        elif group == TODAY_POSSIBLE:
            summary.possible.append(parcel)
        elif delivered_today(parcel, today, tz):
            summary.delivered_today.append(parcel)
    return summary

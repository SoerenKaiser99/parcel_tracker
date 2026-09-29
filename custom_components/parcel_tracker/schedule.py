"""Polling schedule and cleanup rules (no Home Assistant imports)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

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


def poll_interval(status: ParcelStatus | None, now: datetime) -> timedelta | None:
    """Return the time until the next poll, None if polling stops."""
    if status is ParcelStatus.DELIVERED:
        return None
    interval = _INTERVALS.get(status, _DEFAULT) if status else _DEFAULT
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

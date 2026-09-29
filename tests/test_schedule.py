from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.schedule import (
    backoff,
    days_until,
    poll_interval,
    should_remove,
)

NOON = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)   # 12:00 Berlin
NIGHT = datetime(2026, 9, 29, 22, 30, tzinfo=UTC)  # 00:30 Berlin


@pytest.mark.parametrize(
    ("status", "minutes"),
    [
        (ParcelStatus.OUT_FOR_DELIVERY, 10),
        (ParcelStatus.IN_TRANSIT, 30),
        (ParcelStatus.AT_DELIVERY_DEPOT, 30),
        (ParcelStatus.AWAITING_PICKUP, 30),
        (ParcelStatus.PRE_TRANSIT, 60),
        (ParcelStatus.UNKNOWN, 60),
        (None, 60),
    ],
)
def test_poll_interval_day(status, minutes):
    assert poll_interval(status, NOON) == timedelta(minutes=minutes)


def test_poll_interval_delivered_never():
    assert poll_interval(ParcelStatus.DELIVERED, NOON) is None


def test_poll_interval_night_at_least_hourly():
    assert poll_interval(ParcelStatus.OUT_FOR_DELIVERY, NIGHT) == timedelta(minutes=60)


@pytest.mark.parametrize(
    ("streak", "minutes"), [(1, 5), (2, 10), (3, 20), (5, 80), (6, 120), (10, 120)]
)
def test_backoff(streak, minutes):
    assert backoff(streak) == timedelta(minutes=minutes)


def _parcel(status, delivered_at=None, last_change=NOON):
    result = TrackingResult(status, None, None, None, None, None, None, None, delivered_at, [])
    return Parcel("1", "dpd", "auto", None, last_change, last_change, result=result)


def test_remove_delivered_after_keep_days():
    p = _parcel(ParcelStatus.DELIVERED, delivered_at=NOON)
    assert not should_remove(p, NOON + timedelta(days=2, hours=23), 3)
    assert should_remove(p, NOON + timedelta(days=3, minutes=1), 3)


def test_remove_stale_after_30_days():
    p = _parcel(ParcelStatus.IN_TRANSIT)
    assert not should_remove(p, NOON + timedelta(days=29), 3)
    assert should_remove(p, NOON + timedelta(days=30, minutes=1), 3)


def test_remove_never_polled_after_30_days():
    p = Parcel("1", None, "auto", None, NOON, NOON)
    assert should_remove(p, NOON + timedelta(days=31), 3)


def test_days_until():
    today = date(2026, 9, 29)
    assert days_until(date(2026, 9, 29), today) == 0
    assert days_until(date(2026, 10, 1), today) == 2
    assert days_until(None, today) is None

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.schedule import (
    TODAY_POSSIBLE,
    TODAY_SURE,
    backoff,
    days_until,
    delivered_today,
    poll_interval,
    should_remove,
    today_group,
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


@pytest.mark.parametrize(
    ("status", "minutes"),
    [
        (ParcelStatus.OUT_FOR_DELIVERY, 30),
        (ParcelStatus.IN_TRANSIT, 240),
        (ParcelStatus.AWAITING_PICKUP, 240),
        (ParcelStatus.PRE_TRANSIT, 240),
        (None, 240),
    ],
)
def test_ups_api_is_asked_sparingly(status, minutes):
    assert poll_interval(status, NOON, "ups") == timedelta(minutes=minutes)
    assert poll_interval(ParcelStatus.DELIVERED, NOON, "ups") is None


def test_ups_night_rule_still_applies():
    assert poll_interval(ParcelStatus.OUT_FOR_DELIVERY, NIGHT, "ups") == timedelta(minutes=60)
    assert poll_interval(ParcelStatus.IN_TRANSIT, NIGHT, "ups") == timedelta(hours=4)


def test_other_carriers_keep_their_intervals():
    assert poll_interval(ParcelStatus.IN_TRANSIT, NOON, "hermes") == timedelta(minutes=30)


@pytest.mark.parametrize(
    ("status", "minutes"),
    [
        (ParcelStatus.OUT_FOR_DELIVERY, 30),  # others: 10 min; GLS is asked at most every 30
        (ParcelStatus.IN_TRANSIT, 30),
        (ParcelStatus.AWAITING_PICKUP, 30),
        (ParcelStatus.PRE_TRANSIT, 60),
        (ParcelStatus.EXCEPTION, 60),
        (None, 60),
    ],
)
def test_gls_is_asked_at_most_every_30_minutes(status, minutes):
    assert poll_interval(status, NOON, "gls") == timedelta(minutes=minutes)
    assert poll_interval(ParcelStatus.DELIVERED, NOON, "gls") is None
    assert poll_interval(ParcelStatus.OUT_FOR_DELIVERY, NIGHT, "gls") == timedelta(minutes=60)


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


TODAY = date(2026, 10, 2)


TODAY_NOON = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)  # 12:00 Berlin on TODAY


def _eta_parcel(status, first=None, last=None, changed=0):
    """A parcel estimated from today+first to today+last, last changed today+changed (days)."""
    result = TrackingResult(
        status, None, TODAY + timedelta(days=first) if first is not None else None,
        None, None, None, None, None, None, [],
        eta_latest=TODAY + timedelta(days=last) if last is not None else None,
    )
    change = TODAY_NOON + timedelta(days=changed)
    return Parcel("1", "amazon", "mail", None, NOON, change, result=result)


@pytest.mark.parametrize(
    ("status", "first", "last", "group"),
    [
        # A fixed day today is sure, whatever the (not delivered) status.
        (ParcelStatus.IN_TRANSIT, 0, None, TODAY_SURE),
        (ParcelStatus.IN_TRANSIT, 0, 0, TODAY_SURE),
        (ParcelStatus.PRE_TRANSIT, 0, None, TODAY_SURE),
        (ParcelStatus.AWAITING_PICKUP, 0, None, TODAY_SURE),
        (ParcelStatus.EXCEPTION, 0, None, TODAY_SURE),
        # "In Zustellung" is sure, with or without a day, even inside a range.
        (ParcelStatus.OUT_FOR_DELIVERY, None, None, TODAY_SURE),
        (ParcelStatus.OUT_FOR_DELIVERY, 0, 3, TODAY_SURE),
        (ParcelStatus.OUT_FOR_DELIVERY, 1, None, TODAY_SURE),
        # A range that includes today is only possible.
        (ParcelStatus.IN_TRANSIT, 0, 3, TODAY_POSSIBLE),
        (ParcelStatus.IN_TRANSIT, -1, 2, TODAY_POSSIBLE),
        (ParcelStatus.PRE_TRANSIT, -2, 0, TODAY_POSSIBLE),
        # Neither.
        (ParcelStatus.IN_TRANSIT, 1, 3, None),
        (ParcelStatus.IN_TRANSIT, -3, -1, None),
        (ParcelStatus.IN_TRANSIT, 1, None, None),
        (ParcelStatus.IN_TRANSIT, -1, None, None),
        (ParcelStatus.IN_TRANSIT, None, None, None),
        (ParcelStatus.DELIVERED, 0, None, None),
        (ParcelStatus.DELIVERED, 0, 3, None),
    ],
)
def test_today_group(status, first, last, group):
    assert today_group(_eta_parcel(status, first, last), TODAY) == group


def test_today_group_without_result():
    assert today_group(Parcel("1", "dhl", "auto", None, NOON, NOON), TODAY) is None


@pytest.mark.parametrize(
    ("first", "last", "changed", "group"),
    [
        # an estimate decides: in delivery counts as long as its last day is not over
        (0, None, -5, TODAY_SURE),
        (1, None, -5, TODAY_SURE),
        (-2, 0, -5, TODAY_SURE),
        (0, 3, -5, TODAY_SURE),
        (-1, None, 0, None),  # day was yesterday, "zugestellt" never came
        (-3, -1, 0, None),  # range ended yesterday
        (-1, -1, 0, None),
        # an earliest day alone is no estimate that could be over
        (None, 0, -5, TODAY_SURE),
        (None, -1, 0, None),
        # no estimate at all: only on the day the parcel last changed
        (None, None, 0, TODAY_SURE),
        (None, None, -1, None),
        (None, None, -2, None),
    ],
)
def test_today_group_in_delivery_ends_with_its_estimate(first, last, changed, group):
    parcel = _eta_parcel(ParcelStatus.OUT_FOR_DELIVERY, first, last, changed)
    assert today_group(parcel, TODAY) == group


def test_today_group_in_delivery_reads_the_change_in_local_time():
    """00:30 in Berlin is "today" there while it is still yesterday in UTC."""
    parcel = _eta_parcel(ParcelStatus.OUT_FOR_DELIVERY)
    parcel.last_change_at = datetime(2026, 10, 1, 22, 30, tzinfo=UTC)
    assert today_group(parcel, TODAY) == TODAY_SURE
    assert today_group(parcel, TODAY, UTC) is None
    assert today_group(parcel, date(2026, 10, 1), UTC) == TODAY_SURE


def _delivered_parcel(delivered_at, changed, status=ParcelStatus.DELIVERED):
    result = TrackingResult(status, None, None, None, None, None, None, None, delivered_at, [])
    return Parcel("1", "amazon", "mail", None, NOON, changed, result=result)


YESTERDAY_NOON = TODAY_NOON - timedelta(days=1)


@pytest.mark.parametrize(
    ("delivered_at", "changed", "expected"),
    [
        (TODAY_NOON, TODAY_NOON, True),
        # the time of delivery decides, not the time the integration learned of it
        (TODAY_NOON, YESTERDAY_NOON, True),
        (YESTERDAY_NOON, TODAY_NOON, False),
        (TODAY_NOON + timedelta(days=1), TODAY_NOON, False),
        # no time of delivery: the day the status changed
        (None, TODAY_NOON, True),
        (None, YESTERDAY_NOON, False),
    ],
)
def test_delivered_today(delivered_at, changed, expected):
    assert delivered_today(_delivered_parcel(delivered_at, changed), TODAY) is expected


@pytest.mark.parametrize(
    "status", [s for s in ParcelStatus if s is not ParcelStatus.DELIVERED]
)
def test_delivered_today_needs_the_status_delivered(status):
    parcel = _delivered_parcel(TODAY_NOON, TODAY_NOON, status)
    assert delivered_today(parcel, TODAY) is False


def test_delivered_today_without_result():
    assert delivered_today(Parcel("1", "dhl", "auto", None, NOON, TODAY_NOON), TODAY) is False


def test_delivered_today_reads_the_time_in_the_given_time_zone():
    """00:30 in Berlin is "today" there while it is still yesterday in UTC."""
    late = datetime(2026, 10, 1, 22, 30, tzinfo=UTC)
    for parcel in (_delivered_parcel(late, NOON), _delivered_parcel(None, late)):
        assert delivered_today(parcel, TODAY) is True
        assert delivered_today(parcel, TODAY, UTC) is False
        assert delivered_today(parcel, date(2026, 10, 1), UTC) is True


def test_delivered_today_and_today_group_never_overlap():
    parcel = _delivered_parcel(TODAY_NOON, TODAY_NOON)
    parcel.result.eta_date = TODAY
    assert delivered_today(parcel, TODAY) is True
    assert today_group(parcel, TODAY) is None

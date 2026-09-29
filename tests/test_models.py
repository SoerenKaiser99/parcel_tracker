from datetime import UTC, date, datetime

from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)


def _result() -> TrackingResult:
    return TrackingResult(
        status=ParcelStatus.IN_TRANSIT,
        status_text="Paket unterwegs",
        eta_date=date(2026, 9, 30),
        eta_from=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        eta_to=datetime(2026, 9, 30, 13, 0, tzinfo=UTC),
        location="Erftstadt-Lechenich",
        pickup_point=None,
        pickup_until=None,
        delivered_at=None,
        events=[
            TrackingEvent(datetime(2026, 9, 29, 5, 11, tzinfo=UTC), "Paket unterwegs", "Erftstadt")
        ],
    )


def test_result_roundtrip():
    r = _result()
    assert TrackingResult.from_dict(r.to_dict()) == r


def test_parcel_roundtrip_and_status():
    now = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    p = Parcel(
        number="09999999999901",
        carrier="dpd",
        carrier_mode="auto",
        name="Testpaket",
        added_at=now,
        last_change_at=now,
        result=_result(),
    )
    assert p.status is ParcelStatus.IN_TRANSIT
    assert Parcel.from_dict(p.to_dict()) == p


def test_parcel_without_result_has_no_status():
    now = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    p = Parcel("123", None, "auto", None, now, now)
    assert p.status is None
    assert Parcel.from_dict(p.to_dict()) == p

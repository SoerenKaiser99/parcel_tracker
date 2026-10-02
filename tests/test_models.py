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


def _mail_parcel(**kwargs) -> Parcel:
    now = datetime(2026, 7, 30, 18, 0, tzinfo=UTC)
    return Parcel("AMZ99991565342587125", "amazon", "mail", "Metallplättchen", now, now, **kwargs)


def test_parcel_roundtrip_with_mail_fields():
    p = _mail_parcel(
        tracking_ref="JJD000012978217606560", tracking_carrier="dhl", mail_title="4 Ersatz"
    )
    assert Parcel.from_dict(p.to_dict()) == p


def test_old_stored_parcel_loads_with_defaults():
    now = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    old = Parcel("123", "dpd", "auto", None, now, now).to_dict()
    for key in ("tracking_ref", "tracking_carrier", "mail_title"):
        del old[key]
    p = Parcel.from_dict(old)
    assert p.tracking_ref is None
    assert p.tracking_carrier is None
    assert p.mail_title is None
    assert p.delivery_code is None


def test_delivery_code_is_never_serialised():
    p = _mail_parcel(delivery_code="123456", delivery_code_day=date(2026, 8, 20))
    data = p.to_dict()
    assert "delivery_code" not in data
    assert "delivery_code_day" not in data
    assert "123456" not in str(data)
    assert Parcel.from_dict(data).delivery_code is None


def test_active_code_expires_after_its_day():
    p = _mail_parcel(delivery_code="123456", delivery_code_day=date(2026, 8, 20))
    assert p.active_code(date(2026, 8, 20)) == "123456"
    assert p.active_code(date(2026, 8, 21)) is None
    assert _mail_parcel().active_code(date(2026, 8, 20)) is None


def test_poll_target():
    now = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    assert Parcel("123", None, "auto", None, now, now).poll_target == (None, "123")
    assert Parcel("123", "dpd", "manual", None, now, now).poll_target == ("dpd", "123")
    assert _mail_parcel().poll_target is None
    ups = Parcel("1Z999AA11026832876", "ups", "mail", None, now, now)
    assert ups.poll_target == ("ups", "1Z999AA11026832876")  # coordinator skips it without API
    ebay = Parcel("EBAY990000000001", "ebay", "mail", None, now, now)
    assert ebay.poll_target is None
    merged = _mail_parcel(tracking_ref="JJD000012978217606560", tracking_carrier="dhl")
    assert merged.poll_target == ("dhl", "JJD000012978217606560")


def test_eta_latest_roundtrip_and_backward_compat():
    r = _result()
    assert r.eta_latest is None
    assert TrackingResult.from_dict(r.to_dict()).eta_latest is None
    r.eta_latest = date(2026, 10, 5)
    assert r.to_dict()["eta_latest"] == "2026-10-05"
    assert TrackingResult.from_dict(r.to_dict()) == r
    old = r.to_dict()
    del old["eta_latest"]
    assert TrackingResult.from_dict(old).eta_latest is None


def test_shipping_carrier_hint_roundtrip_and_backward_compat():
    p = _mail_parcel(shipping_carrier_hint="hermes")
    assert p.to_dict()["shipping_carrier_hint"] == "hermes"
    assert Parcel.from_dict(p.to_dict()) == p
    old = _mail_parcel().to_dict()
    del old["shipping_carrier_hint"]
    assert Parcel.from_dict(old).shipping_carrier_hint is None


def test_unannounced_from_roundtrip():
    """The status a parcel had before a change that is still to be announced."""
    now = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    p = Parcel("123", "dpd", "auto", None, now, now, result=_result())
    assert p.unannounced_from is None
    assert p.to_dict()["unannounced_from"] is None
    p.unannounced_from = ParcelStatus.PRE_TRANSIT
    assert p.to_dict()["unannounced_from"] == "pre_transit"
    assert Parcel.from_dict(p.to_dict()) == p
    assert Parcel.from_dict(p.to_dict()).unannounced_from is ParcelStatus.PRE_TRANSIT


def test_old_stored_parcel_loads_without_unannounced_from():
    now = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    old = Parcel("123", "dpd", "auto", None, now, now, result=_result()).to_dict()
    del old["unannounced_from"]
    assert Parcel.from_dict(old).unannounced_from is None


def test_unreadable_unannounced_from_does_not_cost_the_parcel():
    now = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    stored = Parcel("123", "dpd", "auto", None, now, now, result=_result()).to_dict()
    for odd in ("no_status", "", 7, ["in_transit"], {"a": 1}):
        stored["unannounced_from"] = odd
        p = Parcel.from_dict(stored)
        assert p.unannounced_from is None
        assert p.status is ParcelStatus.IN_TRANSIT

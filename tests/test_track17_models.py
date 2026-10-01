"""17track fields on the data model: round trip, old stored data, poll and register targets."""

from datetime import UTC, date, datetime

from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.store import ParcelStore

NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
NUMBER = "99999999999901"


def _result(**kwargs) -> TrackingResult:
    return TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", date(2026, 10, 1), None, None, "Köln", None,
        None, None, [], **kwargs,
    )


def test_track17_fields_roundtrip():
    p = Parcel(
        NUMBER, "dpd", "manual", None, NOW, NOW,
        track17=True, track17_carrier=100007, track17_next_at=NOW,
        track17_result=_result(),
    )
    data = p.to_dict()
    assert (data["track17"], data["track17_carrier"]) == (True, 100007)
    assert data["track17_next_at"] == NOW.isoformat()
    assert data["track17_result"]["location"] == "Köln"
    assert Parcel.from_dict(data) == p


def test_parcel_saved_before_17track_loads_with_defaults():
    old = Parcel(NUMBER, "dpd", "manual", None, NOW, NOW).to_dict()
    for key in ("track17", "track17_carrier", "track17_next_at", "track17_result"):
        del old[key]
    p = Parcel.from_dict(old)
    assert (p.track17, p.track17_carrier, p.track17_next_at, p.track17_result) == (
        False, None, None, None,
    )


def test_enriched_roundtrip_and_backward_compat():
    r = _result(enriched=("location", "window"))
    assert r.to_dict()["enriched"] == ["location", "window"]
    assert TrackingResult.from_dict(r.to_dict()) == r
    old = _result().to_dict()
    del old["enriched"]
    assert TrackingResult.from_dict(old).enriched == ()


def test_other_is_never_polled_directly_but_registers_its_number():
    p = Parcel(NUMBER, "other", "manual", None, NOW, NOW)
    assert p.poll_target is None
    assert p.track17_target == ("other", NUMBER)


def test_track17_target():
    assert Parcel(NUMBER, "dpd", "manual", None, NOW, NOW).track17_target == ("dpd", NUMBER)
    assert Parcel(NUMBER, None, "auto", None, NOW, NOW).track17_target == (None, NUMBER)
    shop = Parcel("AMZ99990000000001", "amazon", "mail", None, NOW, NOW)
    assert shop.track17_target is None
    merged = Parcel(
        "AMZ99990000000001", "amazon", "mail", None, NOW, NOW,
        tracking_ref="H9999999999999999901", tracking_carrier="hermes",
    )
    assert merged.track17_target == ("hermes", "H9999999999999999901")


async def test_store_loads_parcels_saved_before_17track(hass, hass_storage):
    old = Parcel(NUMBER, "dpd", "manual", "Alt", NOW, NOW, result=_result()).to_dict()
    for key in ("track17", "track17_carrier", "track17_next_at", "track17_result"):
        del old[key]
    del old["result"]["enriched"]
    hass_storage["parcel_tracker"] = {
        "version": 1, "key": "parcel_tracker", "data": {"parcels": [old]},
    }
    store = ParcelStore(hass)
    await store.async_load()
    parcel = store.get(NUMBER)
    assert (parcel.name, parcel.track17, parcel.result.enriched) == ("Alt", False, ())

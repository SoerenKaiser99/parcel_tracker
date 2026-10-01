"""17track track_info parser and the gap-filling merge (no Home Assistant needed)."""

from datetime import date, datetime

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN, NotFound, ParseError
from custom_components.parcel_tracker.carriers.track17 import (
    Track17Info,
    enrich,
    parse_track17,
    standalone,
    strip_enrichment,
    with_track17,
)
from custom_components.parcel_tracker.models import ParcelStatus, TrackingEvent, TrackingResult

from .conftest import load_fixture


def _item() -> dict:
    return load_fixture("track17_synthetic_trackinfo.json")["response"]["data"]["accepted"][0]


def _with_status(status: str) -> dict:
    item = _item()
    item["track_info"]["latest_status"]["status"] = status
    return item


def test_fixture_is_marked_synthetic():
    data = load_fixture("track17_synthetic_trackinfo.json")
    assert data["_synthetic"].startswith("Synthetic: built from the 17track")


def test_parse_in_transit():
    info = parse_track17(_item())
    r = info.result
    assert isinstance(info, Track17Info)
    assert (info.expired, info.carrier) == (False, 100007)
    assert (r.status, r.status_text) == (
        ParcelStatus.IN_TRANSIT,
        "Das Paket ist im Zustelldepot eingetroffen.",
    )
    assert r.location == "Köln"
    assert (r.eta_date, r.eta_latest) == (date(2026, 10, 1), None)
    assert r.eta_from == datetime(2026, 10, 1, 10, 0, tzinfo=BERLIN)
    assert r.eta_to == datetime(2026, 10, 1, 14, 0, tzinfo=BERLIN)
    assert [e.text for e in r.events] == [
        "Das Paket ist im Zustelldepot eingetroffen.",
        "Das Paket ist im Paketzentrum eingetroffen.",
        "Die Sendungsdaten wurden übermittelt.",
    ]
    assert [e.location for e in r.events] == ["Köln", "Hamburg", None]
    assert r.events[0].timestamp == datetime(2026, 9, 30, 6, 12, tzinfo=BERLIN)
    assert (r.delivered_at, r.pickup_point, r.pickup_until, r.enriched) == (None, None, None, ())


def test_addresses_and_shipping_info_are_never_taken():
    text = str(parse_track17(_item()).result.to_dict())
    for secret in ("Absenderstadt", "Empfaengerstadt", "Synthetikweg", "00002", "SYNTH-0000"):
        assert secret not in text


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        ("InfoReceived", ParcelStatus.PRE_TRANSIT),
        ("InTransit", ParcelStatus.IN_TRANSIT),
        ("OutForDelivery", ParcelStatus.OUT_FOR_DELIVERY),
        ("AvailableForPickup", ParcelStatus.AWAITING_PICKUP),
        ("Delivered", ParcelStatus.DELIVERED),
        ("DeliveryFailure", ParcelStatus.EXCEPTION),
        ("Exception", ParcelStatus.EXCEPTION),
        ("NotFound", ParcelStatus.UNKNOWN),
        ("Expired", ParcelStatus.UNKNOWN),
        ("SomethingNew", ParcelStatus.UNKNOWN),
    ],
)
def test_status_mapping(raw, status):
    assert parse_track17(_with_status(raw)).result.status is status


def test_expired_ends_polling():
    assert parse_track17(_with_status("Expired")).expired is True


def test_delivered_takes_the_latest_event_time_and_no_eta():
    r = parse_track17(_with_status("Delivered")).result
    assert r.delivered_at == datetime(2026, 9, 30, 6, 12, tzinfo=BERLIN)
    assert (r.eta_date, r.eta_from, r.eta_to) == (None, None, None)


def _eta(start, end) -> TrackingResult:
    item = _item()
    item["track_info"]["time_metrics"]["estimated_delivery_date"] = {
        "source": "Official", "from": start, "to": end,
    }
    return parse_track17(item).result


def test_eta_over_several_days_is_a_range():
    r = _eta("2026-10-01T00:00:00+02:00", "2026-10-03T00:00:00+02:00")
    assert (r.eta_date, r.eta_latest, r.eta_from, r.eta_to) == (
        date(2026, 10, 1), date(2026, 10, 3), None, None,
    )


def test_whole_day_is_no_time_window():
    r = _eta("2026-10-01T00:00:00+02:00", "2026-10-01T23:59:59+02:00")
    assert (r.eta_date, r.eta_latest, r.eta_from, r.eta_to) == (
        date(2026, 10, 1), None, None, None,
    )


def test_only_an_end_date():
    r = _eta(None, "2026-10-02T00:00:00+02:00")
    assert (r.eta_date, r.eta_latest, r.eta_from) == (date(2026, 10, 2), None, None)


def test_no_estimate():
    item = _item()
    item["track_info"]["time_metrics"]["estimated_delivery_date"] = None
    r = parse_track17(item).result
    assert (r.eta_date, r.eta_latest, r.eta_from, r.eta_to) == (None, None, None, None)


def test_at_most_20_events_newest_first():
    item = _item()
    events = [
        {"time_iso": f"2026-09-{day:02d}T08:00:00+02:00", "description": f"Schritt {day}",
         "location": None}
        for day in range(1, 26)
    ]
    item["track_info"]["tracking"]["providers"][0]["events"] = events
    r = parse_track17(item).result
    assert len(r.events) == 20
    assert (r.events[0].text, r.events[-1].text) == ("Schritt 25", "Schritt 6")


def test_events_without_time_or_text_are_skipped():
    item = _item()
    item["track_info"]["tracking"]["providers"][0]["events"] = [
        {"time_iso": None, "description": "ohne Zeit", "location": None},
        {"time_iso": "2026-09-29T09:05:00+02:00", "description": "", "location": None},
        {"time_iso": "kaputt", "description": "kaputte Zeit", "location": None},
    ]
    assert parse_track17(item).result.events == []


def test_no_track_info_yet_is_not_found():
    item = _item()
    item["track_info"] = None
    with pytest.raises(NotFound):
        parse_track17(item)


def test_not_an_object():
    with pytest.raises(ParseError):
        parse_track17(["no"])


def _carrier(**kwargs) -> TrackingResult:
    values = {
        "status": ParcelStatus.IN_TRANSIT, "status_text": "Unterwegs", "eta_date": None,
        "eta_from": None, "eta_to": None, "location": None, "pickup_point": None,
        "pickup_until": None, "delivered_at": None, "events": [],
    }
    values.update(kwargs)
    return TrackingResult(**values)


def _extra() -> TrackingResult:
    return parse_track17(_with_status("OutForDelivery")).result


def test_enrich_fills_only_empty_fields_and_keeps_the_carrier_status():
    merged = enrich(_carrier(), _extra())
    assert (merged.status, merged.status_text, merged.delivered_at) == (
        ParcelStatus.IN_TRANSIT, "Unterwegs", None,
    )
    assert merged.location == "Köln"
    assert merged.eta_date == date(2026, 10, 1)
    assert merged.eta_from == datetime(2026, 10, 1, 10, 0, tzinfo=BERLIN)
    assert len(merged.events) == 3
    assert merged.enriched == ("location", "eta", "events")


def test_enrich_never_overrides_carrier_values():
    own_event = TrackingEvent(datetime(2026, 9, 29, 20, 0, tzinfo=BERLIN), "Im Paketzentrum", None)
    base = _carrier(location="Bonn", eta_date=date(2026, 10, 2), events=[own_event])
    assert enrich(base, _extra()) is base


def test_enrich_adds_a_window_only_on_the_same_day():
    same_day = enrich(_carrier(eta_date=date(2026, 10, 1), location="Bonn"), _extra())
    assert (same_day.eta_from, same_day.enriched[0]) == (
        datetime(2026, 10, 1, 10, 0, tzinfo=BERLIN), "window",
    )
    other_day = enrich(_carrier(eta_date=date(2026, 10, 2), location="Bonn"), _extra())
    assert other_day.eta_from is None


def test_enrich_adds_no_day_to_a_delivered_parcel():
    merged = enrich(_carrier(status=ParcelStatus.DELIVERED, location="Bonn"), _extra())
    assert (merged.eta_date, merged.eta_from) == (None, None)


def test_strip_enrichment_gives_back_the_carrier_answer():
    for base in (_carrier(), _carrier(eta_date=date(2026, 10, 1))):
        assert strip_enrichment(enrich(base, _extra())) == base
    plain = _carrier(location="Bonn")
    assert strip_enrichment(plain) is plain


def test_standalone_shows_the_whole_17track_answer_and_strips_to_nothing():
    alone = standalone(_extra())
    assert alone.status is _extra().status
    assert alone.enriched[0] == "status"
    assert {"location", "eta", "events"} <= set(alone.enriched)
    # No carrier answer is hidden in it: a later carrier answer starts from scratch.
    assert strip_enrichment(alone) is None
    assert strip_enrichment(None) is None
    assert TrackingResult.from_dict(alone.to_dict()) == alone


def test_with_track17_fills_gaps_or_stands_in_for_a_missing_carrier_answer():
    base = _carrier()
    assert with_track17(base, None) is base
    assert with_track17(None, None) is None
    assert with_track17(base, _extra()) == enrich(base, _extra())
    assert with_track17(None, _extra()) == standalone(_extra())

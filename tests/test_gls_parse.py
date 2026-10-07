"""GLS answers (synthetic, shaped after ha-gls, MIT): status, texts, events, ETA, dummies."""

import copy
import logging
from datetime import UTC, date, datetime

import pytest

from custom_components.parcel_tracker.carriers import gls as gls_module
from custom_components.parcel_tracker.carriers.base import BERLIN, NotFound, ParseError
from custom_components.parcel_tracker.carriers.gls import parse_gls
from custom_components.parcel_tracker.const import GLS_MAX_EVENTS
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_fixture

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
DAY = date(2026, 9, 30)
WINDOW = (datetime(2026, 9, 30, 10, 0, tzinfo=BERLIN), datetime(2026, 9, 30, 12, 30, tzinfo=BERLIN))
NO_ETA = (None, None, None)


def _detail() -> dict:
    """rstt028: flat object with history."""
    return copy.deepcopy(load_fixture("gls_synthetic_detail.json")["response"])


def _search() -> dict:
    """rstt029: {"tuStatus": [entry]} without history."""
    return copy.deepcopy(load_fixture("gls_synthetic_search.json")["response"])


def _with_status(code, retour=False) -> dict:
    data = _detail()
    data["progressBar"]["statusInfo"] = code
    data["progressBar"]["retourFlag"] = retour
    return data


def test_fixtures_are_synthetic_and_credit_their_source():
    for name in ("gls_synthetic_detail.json", "gls_synthetic_search.json"):
        source = load_fixture(name)["_source"]
        assert source.startswith("Synthetic, no real parcel")
        assert "github.com/ha-parcel-integrations/ha-gls (MIT License)" in source


def test_detail_delivered_with_history():
    r = parse_gls(_detail(), NOW)
    assert r.status is ParcelStatus.DELIVERED
    assert r.status_text == "Das Paket wurde zugestellt."
    assert r.delivered_at == datetime(2026, 9, 29, 11, 42, 10, tzinfo=BERLIN)
    assert len(r.events) == 6
    assert r.events[0].timestamp == datetime(2026, 9, 29, 11, 42, 10, tzinfo=BERLIN)
    assert r.events[4].text == "Das Paket wurde an GLS übergeben."  # entities decoded
    assert all(e.location is None for e in r.events)
    assert (r.eta_date, r.eta_from, r.eta_to, r.location, r.pickup_point) == (None,) * 5


def test_signature_references_and_weight_are_never_read():
    dump = str(parse_gls(_detail(), NOW).to_dict())
    for secret in ("MUSTERMANN", "REF-0001", "2.4 kg", "10115"):
        assert secret not in dump


def test_search_answer_out_for_delivery_with_day_and_window():
    r = parse_gls(_search(), NOW)
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY
    assert r.status_text == "Das Paket wird voraussichtlich im Laufe des Tages zugestellt."
    assert (r.eta_date, r.eta_from, r.eta_to) == (DAY, *WINDOW)
    assert (r.events, r.delivered_at) == ([], None)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("PREADVICE", ParcelStatus.PRE_TRANSIT),
        ("PROCESSING", ParcelStatus.IN_TRANSIT),
        ("INTRANSIT", ParcelStatus.IN_TRANSIT),
        ("MULTIPACK", ParcelStatus.IN_TRANSIT),
        ("INWAREHOUSE", ParcelStatus.AT_DELIVERY_DEPOT),
        ("INDELIVERY", ParcelStatus.OUT_FOR_DELIVERY),
        ("DELIVEREDPS", ParcelStatus.AWAITING_PICKUP),
        ("INPICKUP", ParcelStatus.AWAITING_PICKUP),
        ("DELIVERED", ParcelStatus.DELIVERED),
        ("NOTDELIVERED", ParcelStatus.EXCEPTION),
        ("NOTPICKEDUP", ParcelStatus.EXCEPTION),
        ("RETURNED", ParcelStatus.EXCEPTION),
        ("CANCELLED", ParcelStatus.EXCEPTION),
        ("UNAVAILABLE", ParcelStatus.UNKNOWN),
        (None, ParcelStatus.UNKNOWN),
    ],
)
def test_status_mapping_is_exact(code, status, caplog):
    with caplog.at_level(logging.WARNING):
        assert parse_gls(_with_status(code), NOW).status is status
    assert caplog.text == ""


def test_parcelshop_delivery_is_not_delivered():
    r = parse_gls(_with_status("DELIVEREDPS"), NOW)
    assert (r.status, r.delivered_at) == (ParcelStatus.AWAITING_PICKUP, None)


def test_retour_flag_is_an_exception_whatever_the_status():
    r = parse_gls(_with_status("INTRANSIT", retour=True), NOW)
    assert r.status is ParcelStatus.EXCEPTION


def test_unknown_status_is_unknown_and_warned_once_with_the_raw_value(caplog):
    gls_module._WARNED.clear()
    with caplog.at_level(logging.WARNING):
        assert parse_gls(_with_status("BRANDNEW"), NOW).status is ParcelStatus.UNKNOWN
        parse_gls(_with_status("BRANDNEW"), NOW)
    assert caplog.text.count("BRANDNEW") == 1


def test_status_text_falls_back_to_bar_heading_then_newest_event():
    data = _detail()
    for step in data["progressBar"]["statusBar"]:
        step["imageStatus"] = "COMPLETE"
    assert parse_gls(data, NOW).status_text == "Zugestellt"
    data["progressBar"]["statusBar"][-1].update(imageStatus="CURRENT", statusText="")
    assert parse_gls(data, NOW).status_text == "Zugestellt"
    data["progressBar"]["statusText"] = ""
    assert parse_gls(data, NOW).status_text == "Das Paket wurde zugestellt."
    data["history"] = []
    assert parse_gls(data, NOW).status_text is None


def test_events_are_capped_and_odd_entries_skipped():
    data = _detail()
    data["history"] = [
        {"date": "2026-09-29", "time": f"10:{minute:02d}:00", "evtNo": "2.0", "evtDscr": "Scan"}
        for minute in range(59, 29, -1)
    ]
    data["history"][1] = {"date": "29.09.", "time": "x", "evtNo": "2.0", "evtDscr": "Scan"}
    data["history"][2] = "odd"
    data["history"][3] = {"date": "2026-09-29", "time": "10:56", "evtNo": "2.0", "evtDscr": ""}
    r = parse_gls(data, NOW)
    assert len(r.events) == GLS_MAX_EVENTS == 20
    assert r.events[0].timestamp == datetime(2026, 9, 29, 10, 59, tzinfo=BERLIN)
    assert r.events[1].timestamp == datetime(2026, 9, 29, 10, 55, tzinfo=BERLIN)


def test_delivered_without_history_takes_the_poll_time():
    data = _search()
    data["tuStatus"][0]["progressBar"]["statusInfo"] = "DELIVERED"
    r = parse_gls(data, NOW)
    assert (r.status, r.delivered_at) == (ParcelStatus.DELIVERED, NOW)
    assert r.eta_date is None  # no ETA on a delivered parcel


@pytest.mark.parametrize(
    ("value", "eta"),
    [
        ("30.09.2026", (DAY, None, None)),
        ("Mi, 30.09.2026 zwischen 10:00–12:30 Uhr", (DAY, *WINDOW)),
        ("30.09.2026 10:00 bis 12:30", (DAY, *WINDOW)),
        ("30.09.2026 12:30 - 10:00", (DAY, None, None)),  # no window that ends before it starts
        ("30.09.2026 10:00 - 12:30 oder 13:00 - 15:00", (DAY, None, None)),  # two windows
        ("30.09.2026 - 02.10.2026", NO_ETA),  # two days: not unambiguous
        ("31.02.2026", NO_ETA),
        ("heute", NO_ETA),
        ("30.09. 10:00 - 12:30", NO_ETA),  # no year: not taken
        ("", NO_ETA),
        (None, NO_ETA),
    ],
)
def test_eta_only_when_unambiguous(value, eta):
    data = _search()
    data["tuStatus"][0]["arrivalTime"] = {"name": "Zustellung:", "value": value}
    r = parse_gls(data, NOW)
    assert (r.eta_date, r.eta_from, r.eta_to) == eta


def test_missing_arrival_time_gives_no_eta():
    data = _search()
    del data["tuStatus"][0]["arrivalTime"]
    assert parse_gls(data, NOW).eta_date is None


@pytest.mark.parametrize("owners", [[], [{"code": "", "type": "DELIVERY"}], None])
def test_real_parcel_without_owner_code_parses(owners):
    """v0.3.19 (issue 8): a real parcel may come with ``"owners": []`` and a few event codes."""
    data = _search()
    data["tuStatus"][0]["owners"] = owners
    data["tuStatus"][0]["progressBar"]["evtNos"] = ["11.0", "2.0", "0.0"]
    assert parse_gls(data, NOW).status is ParcelStatus.OUT_FOR_DELIVERY


def test_entry_with_owner_code_still_parses():
    data = _search()
    assert data["tuStatus"][0]["owners"] == [{"code": "DE03", "type": "DELIVERY"}]
    assert parse_gls(data, NOW).status is ParcelStatus.OUT_FOR_DELIVERY


def test_dummy_answer_with_every_event_code_is_not_found():
    """Seen live with an invented number: no owner and 1578 event codes."""
    data = _search()
    data["tuStatus"][0]["owners"] = []
    data["tuStatus"][0]["progressBar"]["evtNos"] = [f"{n}.0" for n in range(1578)]
    with pytest.raises(NotFound):
        parse_gls(data, NOW)


def test_dummy_answer_with_more_than_50_event_codes_is_not_found():
    data = _search()
    data["tuStatus"][0]["progressBar"]["evtNos"] = [f"{n}.0" for n in range(50)]
    assert parse_gls(data, NOW).status is ParcelStatus.OUT_FOR_DELIVERY  # exactly 50 is fine
    data["tuStatus"][0]["progressBar"]["evtNos"].append("50.0")
    with pytest.raises(NotFound):
        parse_gls(data, NOW)


def test_detail_answer_is_not_checked_for_dummies():
    data = _detail()
    data["owners"] = []
    assert parse_gls(data, NOW).status is ParcelStatus.DELIVERED


def test_empty_search_answer_is_not_found():
    with pytest.raises(NotFound):
        parse_gls({"tuStatus": []}, NOW)


@pytest.mark.parametrize(
    "data",
    [[], "text", None, {"tuStatus": {}}, {"tuStatus": ["x"]}, {"exceptionText": "x"},
     {"progressBar": []}],
)
def test_unexpected_shapes(data):
    with pytest.raises(ParseError):
        parse_gls(data, NOW)

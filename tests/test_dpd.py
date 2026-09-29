from datetime import date, datetime
from unittest import mock

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.parcel_tracker.carriers.base import (
    BERLIN,
    CarrierUnavailable,
    Match,
    NotFound,
    ParseError,
)
from custom_components.parcel_tracker.carriers.dpd import DPD_ENTRY_URL, DpdCarrier, parse_dpd
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import FIXTURES

TODAY = date(2026, 9, 29)
NUMBER = "09999999999901"
URL = f"{DPD_ENTRY_URL}?action=12&parcelno={NUMBER}"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _stage_html(status_text: str | None = "Paket unterwegs", **dates: str) -> str:
    parts = [
        '<span id="ContentPlaceHolder1_repParcelList_labParcelNo_0" '
        f'class="parcelNo">{NUMBER}</span>'
    ]
    if status_text is not None:
        parts.append(
            '<span id="ContentPlaceHolder1_repParcelList_labDeliveryStatus_0" '
            f'class="parcelDeliveryStatus">{status_text} </span>'
        )
    for stage in ("Start", "OnTheRoad", "DeliveryDepot", "CarLoad", "Delivered"):
        parts.append(
            f'<span id="ContentPlaceHolder1_labStatus{stage}Date" class="labSub13 lSBold">'
            f"{dates.get(stage, '')}</span>"
        )
    return "\n".join(parts)


def test_matches():
    assert DpdCarrier.matches(NUMBER) is Match.POSSIBLE
    assert DpdCarrier.matches("00340999999999999901") is Match.NO
    assert DpdCarrier.matches("0999999999990") is Match.NO


def test_parse_real_in_transit():
    r = parse_dpd(html("dpd_web_in_transit_no_plz.html"), TODAY)
    assert r.status is ParcelStatus.IN_TRANSIT
    assert r.status_text == "Paket unterwegs"
    assert [e.text for e in r.events] == ["Paket unterwegs", "Paketinfo an DPD übergeben"]
    assert r.events[0].timestamp == datetime(2026, 9, 29, tzinfo=BERLIN)
    assert r.eta_date is None
    assert r.location is None


def test_parse_real_pre_transit():
    r = parse_dpd(html("dpd_web_pre_transit.html"), TODAY)
    assert r.status is ParcelStatus.PRE_TRANSIT
    assert r.status_text == "Auftragsdaten übermittelt"


def test_parse_real_not_found():
    with pytest.raises(NotFound):
        parse_dpd(html("dpd_web_not_found.html"), TODAY)


def test_out_for_delivery_today_sets_eta():
    r = parse_dpd(
        _stage_html("Paket in Zustellung", Start="27.09.", OnTheRoad="28.09.",
                    DeliveryDepot="29.09.", CarLoad="29.09."),
        TODAY,
    )
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY
    assert r.eta_date == TODAY


def test_delivered():
    r = parse_dpd(
        _stage_html("Paket zugestellt", Start="27.09.", OnTheRoad="28.09.",
                    DeliveryDepot="29.09.", CarLoad="29.09.", Delivered="29.09."),
        TODAY,
    )
    assert r.status is ParcelStatus.DELIVERED
    assert r.delivered_at == datetime(2026, 9, 29, tzinfo=BERLIN)
    assert r.eta_date is None


def test_pickup_text_wins_over_stage():
    html = _stage_html("Paket im Paketshop abholbereit", Start="27.09.", OnTheRoad="28.09.")
    r = parse_dpd(html, TODAY)
    assert r.status is ParcelStatus.AWAITING_PICKUP


def test_year_rollover():
    r = parse_dpd(_stage_html("Paketinfo an DPD übergeben", Start="30.12."), date(2027, 1, 2))
    assert r.events[0].timestamp == datetime(2026, 12, 30, tzinfo=BERLIN)


def test_invalid_date_ignored():
    r = parse_dpd(_stage_html("Irgendwas", Start="31.02."), TODAY)
    assert r.status is ParcelStatus.UNKNOWN
    assert r.events == []


def test_no_status_and_no_dates_is_parse_error():
    with pytest.raises(ParseError):
        parse_dpd(_stage_html(None), TODAY)


async def test_fetch_ok():
    with aioresponses() as m:
        m.get(URL, status=200, body=html("dpd_web_in_transit_no_plz.html"))
        r = await DpdCarrier().fetch(NUMBER, None)
    assert r.status is ParcelStatus.IN_TRANSIT


async def test_fetch_errors():
    with aioresponses() as m:
        m.get(URL, status=503)
        with pytest.raises(CarrierUnavailable):
            await DpdCarrier().fetch(NUMBER, None)
    with aioresponses() as m:
        m.get(URL, exception=aiohttp.ClientConnectionError("boom"))
        with pytest.raises(CarrierUnavailable):
            await DpdCarrier().fetch(NUMBER, None)


async def test_fetch_undecodable_body():
    with aioresponses() as m:
        m.get(URL, status=200, body=b"\xff\xfe\xfa", content_type="text/html; charset=utf-8")
        with mock.patch(
            "aiohttp.ClientResponse.text",
            side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"),
        ):
            with pytest.raises(ParseError) as exc_info:
                await DpdCarrier().fetch(NUMBER, None)
            assert "undecodable" in str(exc_info.value).lower()

from datetime import date, datetime

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.parcel_tracker.carriers.base import (
    BERLIN,
    AuthError,
    CarrierUnavailable,
    Match,
    MissingCredentials,
    NotFound,
    ParseError,
    RateLimited,
)
from custom_components.parcel_tracker.carriers.dhl import DHL_URL, DhlCarrier, parse_dhl
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_fixture

NUMBER = "00340999999999999901"
URL = f"{DHL_URL}?language=de&recipientPostalCode=10115&trackingNumber={NUMBER}"


def test_matches():
    assert DhlCarrier.matches(NUMBER) is Match.SURE
    assert DhlCarrier.matches("JJD000390007777777777") is Match.POSSIBLE
    assert DhlCarrier.matches("123456789012") is Match.POSSIBLE
    assert DhlCarrier.matches("09999999999901") is Match.NO


def test_parse_out_for_delivery():
    r = parse_dhl(load_fixture("dhl_synthetic_out_for_delivery.json"))
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY
    assert r.location == "Bonn"
    assert r.eta_date == date(2026, 9, 29)
    assert r.eta_from == datetime(2026, 9, 29, 14, 0, tzinfo=BERLIN)
    assert r.eta_to == datetime(2026, 9, 29, 16, 0, tzinfo=BERLIN)
    assert len(r.events) == 3
    assert r.events[0].text.startswith("Die Sendung wurde in das Zustellfahrzeug")


def test_parse_delivered():
    r = parse_dhl(load_fixture("dhl_synthetic_delivered.json"))
    assert r.status is ParcelStatus.DELIVERED
    assert r.delivered_at == datetime(2026, 9, 29, 14, 37, tzinfo=BERLIN)


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Die Sendung ist in der Zustellbasis eingetroffen.", ParcelStatus.AT_DELIVERY_DEPOT),
        ("Die Sendung liegt in der Filiale zur Abholung bereit.", ParcelStatus.AWAITING_PICKUP),
        (
            "Die Sendung liegt in der Packstation 123 zur Abholung bereit.",
            ParcelStatus.AWAITING_PICKUP,
        ),
        ("Die Sendung wurde im Start-Paketzentrum bearbeitet.", ParcelStatus.IN_TRANSIT),
    ],
)
def test_text_refinement(text, status):
    data = {"shipments": [{"status": {"timestamp": "2026-09-29T08:00:00", "statusCode": "transit",
                                      "status": text, "description": text}}]}
    assert parse_dhl(data).status is status


async def _fetch(mock_status, body=None, headers=None, api_key="key"):
    with aioresponses() as m:
        m.get(URL, status=mock_status, payload=body or {}, headers=headers)
        async with aiohttp.ClientSession() as session:
            return await DhlCarrier(session, api_key).fetch(NUMBER, "10115")


async def test_fetch_ok():
    r = await _fetch(200, load_fixture("dhl_synthetic_out_for_delivery.json"))
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY


async def test_fetch_errors():
    with pytest.raises(NotFound):
        await _fetch(404)
    with pytest.raises(AuthError):
        await _fetch(401)
    with pytest.raises(RateLimited) as err:
        await _fetch(429, headers={"Retry-After": "120"})
    assert err.value.retry_after == 120
    with pytest.raises(CarrierUnavailable):
        await _fetch(503)


async def test_fetch_without_key():
    async with aiohttp.ClientSession() as session:
        with pytest.raises(MissingCredentials) as err:
            await DhlCarrier(session, None).fetch(NUMBER, "10115")
        assert isinstance(err.value, AuthError)


async def test_fetch_non_json_body():
    with aioresponses() as m:
        m.get(URL, status=200, body="<html>Wartung</html>")
        async with aiohttp.ClientSession() as session:
            with pytest.raises(ParseError):
                await DhlCarrier(session, "key").fetch(NUMBER, "10115")


async def test_validate_key():
    probe = f"{DHL_URL}?language=de&trackingNumber=00340000000000000000"
    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.get(probe, status=404)
            assert await DhlCarrier(session, "good").validate_key() is True
        with aioresponses() as m:
            m.get(probe, status=401)
            assert await DhlCarrier(session, "bad").validate_key() is False


def test_parse_real_delivered():
    r = parse_dhl(load_fixture("dhl_real_delivered.json"))
    assert r.status is ParcelStatus.DELIVERED
    assert r.delivered_at == datetime(2026, 9, 29, 15, 18, tzinfo=BERLIN)
    assert len(r.events) == 5
    assert r.events[0].text == "Die Sendung wurde zugestellt."
    assert r.events[0].location is None
    # Real fixture only carries the bare country ("Deutschland") -> no location.
    assert all(e.location is None for e in r.events)
    stamps = [e.timestamp for e in r.events]
    assert stamps == sorted(stamps, reverse=True)


def test_short_code_po_is_out_for_delivery():
    data = {"shipments": [{"status": {"timestamp": "2026-09-29T09:51:00", "statusCode": "transit",
                                      "status": "PO", "description": "Irgendein Text"}}]}
    assert parse_dhl(data).status is ParcelStatus.OUT_FOR_DELIVERY


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Neuwied, Deutschland", "Neuwied"), ("Deutschland", None), ("Germany", None),
     ("Bonn", "Bonn")],
)
def test_locality_cleanup(raw, expected):
    data = {"shipments": [{"status": {"timestamp": "2026-09-29T09:51:00", "statusCode": "transit",
            "description": "x", "location": {"address": {"addressLocality": raw}}}}]}
    assert parse_dhl(data).location == expected

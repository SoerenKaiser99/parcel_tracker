"""Österreichische Post (public GraphQL lookup)."""

from datetime import datetime

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.parcel_tracker.carriers import build_carriers
from custom_components.parcel_tracker.carriers.base import (
    CarrierUnavailable,
    Match,
    NotFound,
    ParseError,
)
from custom_components.parcel_tracker.carriers.post_at import (
    POST_AT_URL,
    VIENNA,
    PostAtCarrier,
    parse_post_at,
    state_key,
)
from custom_components.parcel_tracker.detect import candidates
from custom_components.parcel_tracker.links import tracking_url
from custom_components.parcel_tracker.models import Parcel, ParcelStatus

NUMBER = "1099999999999999012301"


def _event(key, stamp, text, place="Wien"):
    return {"trackingStateKey": key, "text": text, "timestamp": stamp, "eventPlaceName": place}


def _shipment(*events, status="Zugestellt", eta=None):
    return {"status": status, "estimatedDelivery": eta, "sendungsEvents": list(events)}


DELIVERED = _shipment(
    # oldest first, as Post sent them for real parcels
    _event("pendingInformation", "2026-11-12T23:03:58", "Sendung angekündigt", None),
    _event("inDistribution", "2026-11-13T07:30:00", "In Verteilung", "Allhaming"),
    _event("inDelivery", "2026-11-14T06:00:00", "In Zustellung", "Wien"),
    _event("delivered", "2026-11-14T13:12:42", "Zugestellt", "Wien"),
)


def test_matches():
    assert PostAtCarrier.matches(NUMBER) is Match.SURE
    assert PostAtCarrier.matches("158999999999999999901230") is Match.SURE
    assert PostAtCarrier.matches("RR123456789AT") is Match.SURE
    assert PostAtCarrier.matches("RR123456789DE") is Match.NO
    assert PostAtCarrier.matches("09999999999901") is Match.NO
    assert PostAtCarrier.matches("00340434161234567890") is Match.NO


def test_carrier_is_built_and_detected():
    async def run():
        async with aiohttp.ClientSession() as session:
            carriers = build_carriers(session, None, "at")
            assert isinstance(carriers["post_at"], PostAtCarrier)
            assert candidates(NUMBER, carriers) == ["post_at"]
            # a German S10 stays DHL's
            assert candidates("RR123456789DE", carriers) == ["dhl"]

    import asyncio

    asyncio.run(run())


def test_state_key():
    assert state_key("readyForPickUpStation") == "READY_FOR_PICK_UP_STATION"
    assert state_key("delivered") == "DELIVERED"
    assert state_key(None) is None


def test_delivered_by_newest_event_whatever_the_order():
    result = parse_post_at(DELIVERED)
    assert result.status is ParcelStatus.DELIVERED
    assert result.delivered_at == datetime(2026, 11, 14, 13, 12, 42, tzinfo=VIENNA)
    assert [e.text for e in result.events][:2] == ["Zugestellt", "In Zustellung"]
    assert result.location == "Wien"
    assert result.eta_date is None and result.eta_from is None


def test_out_for_delivery_with_window():
    shipment = _shipment(
        _event("inDistribution", "2026-11-13T07:30:00", "In Verteilung"),
        _event("inDelivery", "2026-11-14T06:00:00", "In Zustellung"),
        status="In Zustellung",
        eta={
            "startDate": "2026-11-14",
            "startTime": "13:00",
            "endDate": "2026-11-14",
            "endTime": "15:00",
        },
    )
    result = parse_post_at(shipment)
    assert result.status is ParcelStatus.OUT_FOR_DELIVERY
    assert result.status_text == "In Zustellung"  # the newest scan, not Post's code
    assert result.eta_date.isoformat() == "2026-11-14"
    assert result.eta_from == datetime(2026, 11, 14, 13, 0, tzinfo=VIENNA)
    assert result.eta_to == datetime(2026, 11, 14, 15, 0, tzinfo=VIENNA)
    assert result.delivered_at is None


def test_pickup_and_problems():
    pickup = parse_post_at(
        _shipment(_event("readyForPickUpStation", "2026-10-13T10:25:00", "Abholbereit"))
    )
    assert pickup.status is ParcelStatus.AWAITING_PICKUP
    returning = parse_post_at(
        _shipment(_event("deliveryInReturn", "2026-10-20T10:00:00", "Rücksendung"))
    )
    assert returning.status is ParcelStatus.EXCEPTION


def test_known_without_scans_is_announced_and_unknown_keys_are_skipped():
    assert parse_post_at(_shipment(status=None)).status is ParcelStatus.PRE_TRANSIT
    result = parse_post_at(
        _shipment(
            _event("inDistribution", "2026-11-13T07:30:00", "In Verteilung"),
            _event("somethingNew", "2026-11-13T09:00:00", "Neu"),
        )
    )
    assert result.status is ParcelStatus.IN_TRANSIT
    assert result.events[0].text == "Neu"
    with pytest.raises(ParseError):
        parse_post_at({"sendungsEvents": "nope"})


def test_tracking_page():
    now = datetime(2026, 11, 14, tzinfo=VIENNA)
    parcel = Parcel(NUMBER, "post_at", "manual", None, now, now)
    assert tracking_url(parcel) == f"https://www.post.at/s/sendungsdetails?snr={NUMBER}"


async def _fetch(status=200, payload=None, **kwargs):
    with aioresponses() as m:
        m.post(POST_AT_URL, status=status, payload=payload, **kwargs)
        async with aiohttp.ClientSession() as session:
            return await PostAtCarrier(session).fetch(NUMBER, "1230")


async def test_fetch_sends_only_the_number():
    with aioresponses() as m:
        m.post(POST_AT_URL, payload={"data": {"einzelsendung": DELIVERED}})
        async with aiohttp.ClientSession() as session:
            result = await PostAtCarrier(session).fetch(NUMBER, "1230")
        [call] = next(iter(m.requests.values()))
    assert result.status is ParcelStatus.DELIVERED
    assert call.kwargs["json"]["variables"] == {"id": NUMBER}
    assert set(call.kwargs["json"]["variables"]) == {"id"}  # no postcode


async def test_fetch_errors():
    with pytest.raises(NotFound):
        await _fetch(payload={"data": {"einzelsendung": None}})
    with pytest.raises(NotFound):
        await _fetch(
            400,
            {"errors": [{"extensions": {"code": "INVALID_ARGUMENT_IDENTITY_CODE"}}]},
        )
    with pytest.raises(CarrierUnavailable):
        await _fetch(payload={"errors": [{"message": "Cannot query field"}], "data": None})
    with pytest.raises(CarrierUnavailable):
        await _fetch(503, {})
    with pytest.raises(ParseError):
        await _fetch(200, body="<html>Wartung</html>")
    with aioresponses() as m:
        m.post(POST_AT_URL, exception=aiohttp.ClientConnectionError("down"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CarrierUnavailable):
                await PostAtCarrier(session).fetch(NUMBER, None)


def test_status_text_is_the_newest_scan_not_posts_code():
    shipment = _shipment(
        _event("delivered", "2026-11-14T13:27:00", "Sendung von Post-Empfangsbox abgeholt"),
        status="ZU",
    )
    assert parse_post_at(shipment).status_text == "Sendung von Post-Empfangsbox abgeholt"
    assert parse_post_at(_shipment(status="ZU")).status_text == "ZU"

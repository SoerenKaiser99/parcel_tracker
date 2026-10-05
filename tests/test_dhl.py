import re
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


@pytest.mark.parametrize("number", ["CQ999999901DE", "RR999999902DE", "LX000000001DE"])
def test_matches_international_s10_numbers_issued_in_germany(number):
    """v0.3.15: two letters, nine digits, "DE" (UPU S10), e.g. a parcel to Austria."""
    assert DhlCarrier.matches(number) is Match.SURE


@pytest.mark.parametrize(
    "number",
    [
        "CQ999999901AT",  # issued by another post
        "CQ99999990DE",  # eight digits
        "CQ9999999012DE",  # ten digits
        "C9999999901DE",  # one letter
        "cq999999901de",  # numbers arrive normalised (upper case)
        "1Z999AA10123456784",
        "H9999999999999999901",
        "999999999012",  # 12 digits stay "possible", see above
    ],
)
def test_s10_rule_takes_nothing_else(number):
    assert DhlCarrier.matches(number) is not Match.SURE


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


@pytest.mark.parametrize("postcode", ["1010", "8001", "10115"])
async def test_postcode_is_sent_as_stored_and_no_country_parameter(postcode):
    """Austria and Switzerland have 4 digits: nothing is padded, cut or added."""
    with aioresponses() as m:
        m.get(
            re.compile(rf"^{re.escape(DHL_URL)}\?"),
            payload=load_fixture("dhl_synthetic_out_for_delivery.json"),
        )
        async with aiohttp.ClientSession() as session:
            await DhlCarrier(session, "key").fetch(NUMBER, postcode)
        [call] = [c for calls in m.requests.values() for c in calls]
    assert call.kwargs["params"] == {
        "trackingNumber": NUMBER, "language": "de", "recipientPostalCode": postcode,
    }


# ----- v0.3.17: the delivery estimate as DHL's API team described it (invented values) -----


def _estimate(**fields) -> dict:
    status = {
        "timestamp": "2026-10-05T07:10:00+02:00",
        "statusCode": "transit",
        "status": "Die Sendung wurde in das Zustellfahrzeug geladen.",
    }
    return {"shipments": [{"id": "00340999999999999903", "status": status, **fields}]}


def _eta(result):
    return result.eta_date, result.eta_from, result.eta_to


def test_estimate_with_day_and_time_frame():
    """The real key is "estimatedDeliveryTimeFrame" (v0.3.16 read another one)."""
    r = parse_dhl(
        _estimate(
            estimatedTimeOfDelivery="2026-10-05",
            estimatedDeliveryTimeFrame={
                "estimatedFrom": "2026-10-05T10:35:00+02:00",
                "estimatedThrough": "2026-10-05T12:05:00+02:00",
            },
        )
    )
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY
    assert _eta(r) == (
        date(2026, 10, 5),
        datetime(2026, 10, 5, 10, 35, tzinfo=BERLIN),
        datetime(2026, 10, 5, 12, 5, tzinfo=BERLIN),
    )
    assert r.eta_from.utcoffset() == r.eta_to.utcoffset() == BERLIN.utcoffset(r.eta_from)


def test_estimate_with_the_day_only_has_no_window():
    assert _eta(parse_dhl(_estimate(estimatedTimeOfDelivery="2026-10-05"))) == (
        date(2026, 10, 5), None, None,
    )


@pytest.mark.parametrize(
    ("value", "day"),
    [
        ("2026-10-05T14:00:00+02:00", date(2026, 10, 5)),
        ("2026-10-05T14:00:00", date(2026, 10, 5)),  # no offset: German time
        ("2026-10-05T22:30:00Z", date(2026, 10, 6)),  # 00:30 in Berlin
        ("2026-10-05T23:30:00+00:00", date(2026, 10, 6)),
        ("2026-10-06T00:30:00+05:00", date(2026, 10, 5)),  # 21:30 in Berlin the day before
    ],
)
def test_estimate_as_a_timestamp_gives_the_day_in_berlin_and_no_window(value, day):
    assert _eta(parse_dhl(_estimate(estimatedTimeOfDelivery=value))) == (day, None, None)


def test_estimate_with_the_time_frame_only():
    frame = {
        "estimatedFrom": "2026-10-05T10:35:00+02:00",
        "estimatedThrough": "2026-10-05T12:05:00+02:00",
    }
    r = parse_dhl(_estimate(estimatedDeliveryTimeFrame=frame))
    assert _eta(r) == (
        date(2026, 10, 5),
        datetime(2026, 10, 5, 10, 35, tzinfo=BERLIN),
        datetime(2026, 10, 5, 12, 5, tzinfo=BERLIN),
    )


def test_time_frame_in_utc_is_shown_in_berlin():
    frame = {"estimatedFrom": "2026-10-05T22:30:00Z", "estimatedThrough": "2026-10-05T23:30:00Z"}
    r = parse_dhl(_estimate(estimatedTimeOfDelivery="2026-10-05", estimatedDeliveryTimeFrame=frame))
    assert r.eta_date == date(2026, 10, 6)
    assert (r.eta_from.hour, r.eta_from.minute, r.eta_to.hour) == (0, 30, 1)


def test_the_day_of_the_time_frame_wins_over_the_estimated_day():
    frame = {
        "estimatedFrom": "2026-10-06T09:00:00+02:00",
        "estimatedThrough": "2026-10-06T11:00:00+02:00",
    }
    r = parse_dhl(_estimate(estimatedTimeOfDelivery="2026-10-05", estimatedDeliveryTimeFrame=frame))
    assert r.eta_date == date(2026, 10, 6)
    assert r.eta_from == datetime(2026, 10, 6, 9, 0, tzinfo=BERLIN)


def test_without_estimate_there_is_no_day_and_no_window():
    assert _eta(parse_dhl(_estimate())) == (None, None, None)
    assert _eta(
        parse_dhl(_estimate(estimatedTimeOfDelivery=None, estimatedDeliveryTimeFrame=None))
    ) == (None, None, None)


def test_old_key_of_the_time_frame_is_still_read_and_the_real_one_wins():
    old = {"estimatedFrom": "2026-10-05T14:00:00", "estimatedThrough": "2026-10-05T16:00:00"}
    new = {"estimatedFrom": "2026-10-05T10:35:00+02:00"}
    r = parse_dhl(_estimate(estimatedTimeOfDeliveryTimeFrame=old))
    assert (r.eta_from.hour, r.eta_to.hour) == (14, 16)
    r = parse_dhl(_estimate(estimatedTimeOfDeliveryTimeFrame=old, estimatedDeliveryTimeFrame=new))
    assert (r.eta_from, r.eta_to) == (datetime(2026, 10, 5, 10, 35, tzinfo=BERLIN), None)


@pytest.mark.parametrize(
    "fields",
    [
        {"estimatedTimeOfDelivery": "bald"},
        {"estimatedTimeOfDelivery": ""},
        {"estimatedTimeOfDelivery": 20261005},
        {"estimatedTimeOfDelivery": {"day": "2026-10-05"}},
        {"estimatedTimeOfDelivery": "2026-13-45"},
        {"estimatedDeliveryTimeFrame": "10-12 Uhr"},
        {"estimatedDeliveryTimeFrame": ["2026-10-05T10:35:00+02:00"]},
        {"estimatedDeliveryTimeFrame": {"estimatedFrom": "vormittags", "estimatedThrough": 12}},
        {"estimatedDeliveryTimeFrame": {"estimatedFrom": None, "estimatedThrough": None}},
        {"estimatedDeliveryTimeFrame": {}},
    ],
)
def test_malformed_estimate_is_ignored(fields):
    r = parse_dhl(_estimate(**fields))
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY
    assert _eta(r) == (None, None, None)


def test_malformed_part_does_not_take_the_readable_part_along():
    frame = {"estimatedFrom": "vormittags", "estimatedThrough": "2026-10-05T12:05:00+02:00"}
    r = parse_dhl(_estimate(estimatedTimeOfDelivery="bald", estimatedDeliveryTimeFrame=frame))
    assert _eta(r) == (date(2026, 10, 5), None, datetime(2026, 10, 5, 12, 5, tzinfo=BERLIN))
    # A bare day inside the frame is no time: it only tells the day.
    frame = {"estimatedFrom": "2026-10-05", "estimatedThrough": "2026-10-05"}
    assert _eta(parse_dhl(_estimate(estimatedDeliveryTimeFrame=frame))) == (
        date(2026, 10, 5), None, None,
    )
    r = parse_dhl(_estimate(estimatedTimeOfDelivery="2026-10-05", estimatedDeliveryTimeFrame=7))
    assert _eta(r) == (date(2026, 10, 5), None, None)


async def test_fetch_never_sends_a_service_or_country_parameter():
    """DHL finds the service itself; a fixed one would turn Express into a 404."""
    with aioresponses() as m:
        m.get(re.compile(rf"^{re.escape(DHL_URL)}\?"), payload=_estimate(), repeat=True)
        async with aiohttp.ClientSession() as session:
            await DhlCarrier(session, "key").fetch("9999999901", "10115")
            await DhlCarrier(session, "key").fetch("9999999901", None)
        queries = [dict(url.query) for (_, url), calls in m.requests.items() for _ in calls]
    assert queries == [
        {"trackingNumber": "9999999901", "language": "de", "recipientPostalCode": "10115"},
        {"trackingNumber": "9999999901", "language": "de"},
    ]


async def test_configured_tells_whether_a_key_is_set():
    async with aiohttp.ClientSession() as session:
        assert DhlCarrier(session, "key").configured is True
        assert DhlCarrier(session, None).configured is False
        assert DhlCarrier(session, "").configured is False

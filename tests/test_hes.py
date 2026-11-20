"""Hermes Einrichtungs Service against an anonymised answer of myhes.de plus synthetic cases."""

import copy
from datetime import date, datetime

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.parcel_tracker.carriers import build_carriers
from custom_components.parcel_tracker.carriers.base import (
    BERLIN,
    CarrierUnavailable,
    Match,
    NotFound,
    ParseError,
    RateLimited,
)
from custom_components.parcel_tracker.carriers.hes import HES_URL, HesCarrier, parse_hes
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_fixture

NUMBER = "999999999999999999901"
# The day the depot planned the delivery of the answer (for the day it names).
PLANNED = date(2026, 10, 19)
URL = f"{HES_URL}?parcelNumber={NUMBER}"


def _answer() -> dict:
    return copy.deepcopy(load_fixture("hes_synthetic_delivered.json"))


def _at(journeycode: int, steps: int) -> dict:
    """The answer as it stood after the first ``steps`` steps, at ``journeycode``."""
    data = _answer()
    journey = data["body"]["auftragsdaten"]["statusjourneyDto"]
    journey["journeycode"] = journeycode
    journey["auftragstatusdaten"] = journey["auftragstatusdaten"][:steps]
    journey["statusdaten"] = journey["statusdaten"][:steps]
    return data


def test_matches():
    assert HesCarrier.matches(NUMBER) is Match.SURE
    assert HesCarrier.matches("12345678901234") is Match.NO
    assert HesCarrier.matches("H9999999999999999901") is Match.NO
    assert HesCarrier.matches("9999999999999999999012") is Match.NO


def test_carrier_is_built():
    carriers = build_carriers(None, None)
    assert isinstance(carriers["hes"], HesCarrier)
    assert carriers["hes"].name == "Hermes Einrichtungs Service"


def test_delivered():
    r = parse_hes(_answer())
    assert r.status is ParcelStatus.DELIVERED
    assert r.delivered_at == datetime(2026, 10, 20, 11, 28, tzinfo=BERLIN)
    assert r.status_text == "Deine Sendung wurde erfolgreich zugestellt."
    # newest first, the step without a text left out, only the first sentence
    assert [e.text for e in r.events][:2] == [
        "Deine Sendung wurde erfolgreich zugestellt.",
        "Deine Sendung befindet sich auf Tour.",
    ]
    assert r.events[0].timestamp == datetime(2026, 10, 20, 11, 28, tzinfo=BERLIN)
    assert r.eta_date is None and r.location is None


def test_steps_of_the_journey():
    assert parse_hes(_at(100, 1)).status is ParcelStatus.PRE_TRANSIT
    assert parse_hes(_at(110, 3)).status is ParcelStatus.IN_TRANSIT
    assert parse_hes(_at(140, 12)).status is ParcelStatus.OUT_FOR_DELIVERY
    # (a step nobody knows: see test_unknown_journeycode_takes_the_newest_known_step)


def test_day_and_window_from_the_depots_step():
    """The order's day is still empty: the depot's step names day and window."""
    r = parse_hes(_at(130, 11), today=PLANNED)
    assert r.status is ParcelStatus.AT_DELIVERY_DEPOT
    assert r.eta_date == date(2026, 10, 20)
    assert r.eta_from == datetime(2026, 10, 20, 10, 0, tzinfo=BERLIN)
    assert r.eta_to == datetime(2026, 10, 20, 14, 0, tzinfo=BERLIN)


def test_day_and_window_from_the_order():
    data = _at(140, 12)
    order = data["body"]["auftragsdaten"]
    order["lieferdatum"] = "2026-10-21"
    order["lieferzeitfensterVon"] = "08:30"
    order["lieferzeitfensterBis"] = "12:30:00"
    r = parse_hes(data, today=PLANNED)
    assert r.eta_date == date(2026, 10, 21)
    assert (r.eta_from.hour, r.eta_from.minute, r.eta_to.hour) == (8, 30, 12)


def test_a_past_order_day_falls_back_to_the_chosen_day_then_the_depots():
    """lieferdatum gone by: the day the recipient chose, else the depot's newest step."""
    data = _at(130, 11)
    order = data["body"]["auftragsdaten"]
    order["lieferdatum"] = "2026-10-17"
    order["lieferzeitfensterVon"] = "08:00"
    order["wunschLieferdatum"] = "2026-10-22"
    order["wunschLieferzeitfensterVon"] = "12:00"
    order["wunschLieferzeitfensterBis"] = "16:00"
    r = parse_hes(data, today=PLANNED)
    assert r.eta_date == date(2026, 10, 22)
    assert (r.eta_from.hour, r.eta_to.hour) == (12, 16)
    order["wunschLieferdatum"] = None
    r = parse_hes(data, today=PLANNED)
    # the depot's step: "am 20.10.2026 zwischen 10 - 14 Uhr"
    assert r.eta_date == date(2026, 10, 20)
    assert (r.eta_from.hour, r.eta_to.hour) == (10, 14)


def test_an_older_depot_day_is_never_taken_for_the_newest():
    """Only the depot's newest step that names a day counts, even if it is gone by."""
    data = _at(130, 11)
    depot = data["body"]["auftragsdaten"]["statusjourneyDto"]["statusdaten"]
    depot.insert(0, {"sendungsstatus": "Ihre Sendung wird am 30.10.2026 zwischen 8 - 9 Uhr "
                     "zugestellt.", "sendungsstatusBuchungszeitpunkt": "2026-10-18 10:00",
                     "sendungsstatusId": 10200})
    r = parse_hes(data, today=date(2026, 10, 21))
    assert r.eta_date is None


def test_a_day_gone_by_is_no_day():
    """Planned anew without a new day yet: the old day no longer holds."""
    r = parse_hes(_at(130, 11), today=date(2026, 10, 21))
    assert (r.eta_date, r.eta_from, r.eta_to) == (None, None, None)


def test_journeycode_as_text():
    data = _at(140, 12)
    data["body"]["auftragsdaten"]["statusjourneyDto"]["journeycode"] = "140"
    assert parse_hes(data).status is ParcelStatus.OUT_FOR_DELIVERY


def test_unknown_journeycode_takes_the_newest_known_step(caplog):
    """A step the page adds: the history's newest step it knows tells, and a warning."""
    data = _at(135, 11)
    with caplog.at_level("WARNING"):
        assert parse_hes(data).status is ParcelStatus.AT_DELIVERY_DEPOT
    assert "Unknown HES journeycode 135" in caplog.text


def test_unknown_journeycode_and_steps_is_unknown():
    data = _at(136, 1)
    data["body"]["auftragsdaten"]["statusjourneyDto"]["auftragstatusdaten"][0][
        "sendungsstatusId"
    ] = 1
    assert parse_hes(data).status is ParcelStatus.UNKNOWN


def test_no_day_before_the_depot_plans():
    r = parse_hes(_at(110, 3))
    assert (r.eta_date, r.eta_from, r.eta_to) == (None, None, None)


def test_answer_names_no_recipient():
    """The answer the adapter reads holds no name or address of the recipient."""
    r = parse_hes(_answer())
    texts = " ".join([r.status_text or "", *(e.text for e in r.events)])
    assert "Beispiel" not in texts and "@" not in texts


def test_unknown_number_and_broken_answers():
    with pytest.raises(NotFound):
        parse_hes({"body": {"exceptionKey": "validation.constraintViolation"}})
    with pytest.raises(ParseError):
        parse_hes([])
    with pytest.raises(ParseError):
        parse_hes({"body": {}})


async def _fetch(status, body=None, raw=None, headers=None):
    with aioresponses() as m:
        if raw is not None:
            m.get(URL, status=status, body=raw)
        else:
            m.get(URL, status=status, payload=body, headers=headers)
        async with aiohttp.ClientSession() as session:
            return await HesCarrier(session).fetch(NUMBER, None)


async def test_fetch_ok():
    r = await _fetch(200, _answer())
    assert r.status is ParcelStatus.DELIVERED


async def test_fetch_errors():
    for status in (400, 404, 409):
        with pytest.raises(NotFound):
            await _fetch(status, {})
    with pytest.raises(RateLimited) as err:
        await _fetch(429, {}, headers={"Retry-After": "90"})
    assert err.value.retry_after == 90
    with pytest.raises(CarrierUnavailable):
        await _fetch(503, {})
    with pytest.raises(ParseError):
        await _fetch(200, raw="<html>Wartung</html>")


async def test_fetch_network_error():
    with aioresponses() as m:
        m.get(URL, exception=aiohttp.ClientConnectionError("down"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CarrierUnavailable):
                await HesCarrier(session).fetch(NUMBER, None)

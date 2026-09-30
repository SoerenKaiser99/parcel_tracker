"""UPS Track API client: token reuse, retries, errors and the monthly budget."""

import logging
from datetime import date, datetime, timedelta

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

from custom_components.parcel_tracker.carriers import ups as ups_module
from custom_components.parcel_tracker.carriers.base import (
    BERLIN,
    AuthError,
    CarrierUnavailable,
    Match,
    MissingCredentials,
    NotFound,
    RateLimited,
)
from custom_components.parcel_tracker.carriers.ups import (
    UPS_TOKEN_URL,
    UPS_TRACK_URL,
    ApiBudget,
    BudgetExhausted,
    UpsCarrier,
    month_key,
    next_month_start,
    parse_ups,
)
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_fixture

NUMBER = "1Z999AA10123456784"
TRACK = f"{UPS_TRACK_URL}/{NUMBER}?locale=de_DE"
NOON = "2026-09-30 10:00:00+00:00"


def _body(name: str) -> dict:
    return load_fixture(name)["response"]


def _token(value: str = "synthetic-token-1", expires: str = "14399") -> dict:
    return {**_body("ups_synthetic_token.json"), "access_token": value, "expires_in": expires}


def _carrier(session, budget=None, limit=100, client_id="id", secret="secret"):
    return UpsCarrier(session, client_id, secret, budget or ApiBudget(), limit)


def _calls(m, method: str, url: str) -> list:
    return m.requests.get((method, URL(url)), [])


def test_fixtures_are_marked_synthetic():
    for name in ("ups_synthetic_in_transit.json", "ups_synthetic_out_for_delivery.json",
                 "ups_synthetic_delivered.json", "ups_synthetic_access_point.json",
                 "ups_synthetic_not_found.json", "ups_synthetic_token.json"):
        assert load_fixture(name)["_synthetic"].startswith("Synthetic: built from the official")


def test_matches():
    assert UpsCarrier.matches(NUMBER) is Match.SURE
    assert UpsCarrier.matches("1Z999AA1012345678") is Match.NO
    assert UpsCarrier.matches("H9999999999999999901") is Match.NO


def test_parse_in_transit():
    r = parse_ups(_body("ups_synthetic_in_transit.json"))
    assert (r.status, r.status_text) == (ParcelStatus.IN_TRANSIT, "Unterwegs")
    assert (r.eta_date, r.eta_from, r.eta_to) == (date(2026, 10, 2), None, None)
    assert r.location == "Köln"
    assert [e.text for e in r.events] == [
        "Im Zielpaketzentrum eingetroffen",
        "Versandinformationen an UPS übermittelt",
    ]
    assert r.events[0].timestamp == datetime(2026, 9, 30, 3, 15, tzinfo=BERLIN)


def test_parse_out_for_delivery_uses_rescheduled_day_and_window():
    r = parse_ups(_body("ups_synthetic_out_for_delivery.json"))
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY
    assert r.eta_date == date(2026, 9, 30)
    assert r.eta_from == datetime(2026, 9, 30, 14, 0, tzinfo=BERLIN)
    assert r.eta_to == datetime(2026, 9, 30, 16, 30, tzinfo=BERLIN)


def test_parse_delivered_never_takes_the_drop_place():
    r = parse_ups(_body("ups_synthetic_delivered.json"))
    assert r.status is ParcelStatus.DELIVERED
    assert r.delivered_at == datetime(2026, 9, 30, 14, 37, tzinfo=BERLIN)
    assert "Haustür" not in str(r.to_dict())


def test_parse_access_point():
    r = parse_ups(_body("ups_synthetic_access_point.json"))
    assert (r.status, r.pickup_until) == (ParcelStatus.AWAITING_PICKUP, date(2026, 10, 7))


def test_parse_warning_without_package_is_not_found():
    with pytest.raises(NotFound):
        parse_ups(_body("ups_synthetic_not_found.json"))


def test_unknown_type_is_unknown_and_warned_once(caplog):
    ups_module._WARNED.clear()
    data = _body("ups_synthetic_in_transit.json")
    data["trackResponse"]["shipment"][0]["package"][0]["currentStatus"]["type"] = "ZZ"
    with caplog.at_level(logging.WARNING):
        assert parse_ups(data).status is ParcelStatus.UNKNOWN
        parse_ups(data)
    assert caplog.text.count("ZZ") == 1


def _package(data: dict) -> dict:
    return data["trackResponse"]["shipment"][0]["package"][0]


def test_missing_current_type_falls_back_to_the_newest_activity():
    data = _body("ups_synthetic_in_transit.json")
    package = _package(data)
    package["currentStatus"] = {"description": "Unterwegs"}
    package["activity"][0]["status"]["type"] = "D"
    assert parse_ups(data).status is ParcelStatus.DELIVERED


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("011", ParcelStatus.DELIVERED),
        ("021", ParcelStatus.OUT_FOR_DELIVERY),
        ("005", ParcelStatus.IN_TRANSIT),
        ("003", ParcelStatus.PRE_TRANSIT),
        ("999", ParcelStatus.UNKNOWN),
    ],
)
def test_without_any_type_the_status_code_decides(code, status):
    data = _body("ups_synthetic_in_transit.json")
    package = _package(data)
    package["currentStatus"] = {"statusCode": code}
    for activity in package["activity"]:
        activity["status"].pop("type", None)
    assert parse_ups(data).status is status


def test_status_code_of_the_newest_activity_when_current_has_none():
    data = _body("ups_synthetic_in_transit.json")
    package = _package(data)
    package.pop("currentStatus", None)
    package["activity"][0]["status"] = {"statusCode": "021", "description": "Zustellung"}
    result = parse_ups(data)
    assert (result.status, result.status_text) == (ParcelStatus.OUT_FOR_DELIVERY, "Zustellung")


def test_budget_counts_per_berlin_month():
    budget = ApiBudget()
    budget.spend(datetime(2026, 9, 30, 22, 30, tzinfo=BERLIN))
    assert (budget.month, budget.count) == ("2026-09", 1)
    later = datetime(2026, 10, 1, 0, 30, tzinfo=BERLIN)
    assert budget.used(later) == 0
    budget.spend(later)
    assert (budget.month, budget.count, budget.used(later)) == ("2026-10", 1, 1)
    assert ApiBudget.from_dict(budget.to_dict()) == budget
    assert ApiBudget.from_dict(None) == ApiBudget()
    assert ApiBudget.from_dict({"month": 3, "count": "x"}) == ApiBudget()
    assert month_key(datetime(2026, 9, 30, 23, 0, tzinfo=BERLIN)) == "2026-09"
    assert next_month_start(later) == datetime(2026, 11, 1, tzinfo=BERLIN)
    assert next_month_start(datetime(2026, 12, 5, tzinfo=BERLIN)) == datetime(
        2027, 1, 1, tzinfo=BERLIN
    )


async def test_fetch_sends_the_documented_headers_and_reuses_the_token(freezer):
    freezer.move_to(NOON)
    budget = ApiBudget()
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_token())
        m.get(TRACK, payload=_body("ups_synthetic_in_transit.json"), repeat=True)
        async with aiohttp.ClientSession() as session:
            carrier = _carrier(session, budget)
            r = await carrier.fetch(NUMBER, "10115")
            await carrier.fetch(NUMBER, None)
        [token_call] = _calls(m, "POST", UPS_TOKEN_URL)
        first, second = _calls(m, "GET", TRACK)
    assert r.status is ParcelStatus.IN_TRANSIT
    assert token_call.kwargs["data"] == {"grant_type": "client_credentials"}
    assert token_call.kwargs["headers"] == {"Authorization": "Basic aWQ6c2VjcmV0"}  # id:secret
    headers = first.kwargs["headers"]
    assert headers["Authorization"] == "Bearer synthetic-token-1"
    assert headers["transactionSrc"] == "parcel_tracker"
    assert len(headers["transId"]) == 32
    assert headers["transId"] != second.kwargs["headers"]["transId"]
    assert (budget.month, budget.count) == ("2026-09", 2)  # token calls don't count


async def test_token_is_renewed_60_seconds_before_it_expires(freezer):
    freezer.move_to(NOON)
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_token("t1", "3600"))
        m.post(UPS_TOKEN_URL, payload=_token("t2", "3600"))
        m.get(TRACK, payload=_body("ups_synthetic_in_transit.json"), repeat=True)
        async with aiohttp.ClientSession() as session:
            carrier = _carrier(session)
            await carrier.fetch(NUMBER, None)
            freezer.tick(timedelta(seconds=3539))
            await carrier.fetch(NUMBER, None)
            freezer.tick(timedelta(seconds=1))
            await carrier.fetch(NUMBER, None)
        tokens = [c.kwargs["headers"]["Authorization"] for c in _calls(m, "GET", TRACK)]
    assert tokens == ["Bearer t1", "Bearer t1", "Bearer t2"]


async def test_401_fetches_a_new_token_and_retries_once(freezer):
    freezer.move_to(NOON)
    budget = ApiBudget()
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_token("old"))
        m.post(UPS_TOKEN_URL, payload=_token("new"))
        m.get(TRACK, status=401, payload={"response": {"errors": [{"code": "250002"}]}})
        m.get(TRACK, payload=_body("ups_synthetic_delivered.json"))
        async with aiohttp.ClientSession() as session:
            r = await _carrier(session, budget).fetch(NUMBER, None)
    assert r.status is ParcelStatus.DELIVERED
    assert budget.count == 2


async def test_second_401_is_an_auth_error(freezer):
    freezer.move_to(NOON)
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_token(), repeat=True)
        m.get(TRACK, status=401, repeat=True)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(AuthError):
                await _carrier(session).fetch(NUMBER, None)


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_rejected_credentials_are_an_auth_error(status, freezer):
    freezer.move_to(NOON)
    budget = ApiBudget()
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, status=status, payload={"response": {"errors": []}})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(AuthError):
                await _carrier(session, budget).fetch(NUMBER, None)
    assert budget.count == 0


async def test_track_errors(freezer):
    freezer.move_to(NOON)
    cases = [
        (404, {}, NotFound),
        (400, {}, NotFound),
        (200, _body("ups_synthetic_not_found.json"), NotFound),
        (429, {"Retry-After": "120"}, RateLimited),
        (503, {}, CarrierUnavailable),
    ]
    for status, extra, error in cases:
        with aioresponses() as m:
            m.post(UPS_TOKEN_URL, payload=_token())
            if status == 429:
                m.get(TRACK, status=429, headers=extra)
            else:
                m.get(TRACK, status=status, payload=extra)
            async with aiohttp.ClientSession() as session:
                with pytest.raises(error) as err:
                    await _carrier(session).fetch(NUMBER, None)
        if error is RateLimited:
            assert err.value.retry_after == 120


@pytest.mark.parametrize("expires", [None, "", "abc", "0"])
async def test_token_without_usable_lifetime_lasts_an_hour(expires, freezer):
    freezer.move_to(NOON)
    token = _token()
    if expires is None:
        del token["expires_in"]
    else:
        token["expires_in"] = expires
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=token, repeat=True)
        m.get(TRACK, payload=_body("ups_synthetic_in_transit.json"), repeat=True)
        async with aiohttp.ClientSession() as session:
            carrier = _carrier(session)
            await carrier.fetch(NUMBER, None)
            freezer.tick(timedelta(minutes=58))
            await carrier.fetch(NUMBER, None)
            assert len(_calls(m, "POST", UPS_TOKEN_URL)) == 1
            freezer.tick(timedelta(minutes=2))
            await carrier.fetch(NUMBER, None)
            assert len(_calls(m, "POST", UPS_TOKEN_URL)) == 2


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_error_stops_all_further_calls(status, freezer):
    freezer.move_to(NOON)
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, status=status, payload={}, repeat=True)
        async with aiohttp.ClientSession() as session:
            carrier = _carrier(session)
            for _ in range(3):
                with pytest.raises(AuthError):
                    await carrier.fetch(NUMBER, None)
        assert carrier.auth_blocked
        assert len(_calls(m, "POST", UPS_TOKEN_URL)) == 1


async def test_network_error_is_unavailable(freezer):
    freezer.move_to(NOON)
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, exception=aiohttp.ClientConnectionError("down"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CarrierUnavailable):
                await _carrier(session).fetch(NUMBER, None)


async def test_budget_stops_calls_until_the_next_month(freezer):
    freezer.move_to("2026-09-30 21:00:00+00:00")  # 23:00 Berlin
    budget = ApiBudget()
    with aioresponses() as m:
        m.post(UPS_TOKEN_URL, payload=_token(), repeat=True)
        m.get(TRACK, payload=_body("ups_synthetic_in_transit.json"), repeat=True)
        async with aiohttp.ClientSession() as session:
            carrier = _carrier(session, budget, limit=2)
            await carrier.fetch(NUMBER, None)
            await carrier.fetch(NUMBER, None)
            assert carrier.exhausted(datetime.now(BERLIN))
            with pytest.raises(BudgetExhausted):
                await carrier.fetch(NUMBER, None)
            assert len(_calls(m, "GET", TRACK)) == 2
            freezer.tick(timedelta(hours=1, minutes=1))  # 00:01 Berlin, 1 October
            assert not carrier.exhausted(datetime.now(BERLIN))
            await carrier.fetch(NUMBER, None)
    assert (budget.month, budget.count) == ("2026-10", 1)


async def test_zero_budget_never_calls(freezer):
    freezer.move_to(NOON)
    with aioresponses():
        async with aiohttp.ClientSession() as session:
            with pytest.raises(BudgetExhausted):
                await _carrier(session, limit=0).fetch(NUMBER, None)


async def test_missing_credentials():
    async with aiohttp.ClientSession() as session:
        with pytest.raises(MissingCredentials):
            await _carrier(session, client_id="").fetch(NUMBER, None)


async def test_validate(freezer):
    freezer.move_to(NOON)
    async with aiohttp.ClientSession() as session:
        with aioresponses() as m:
            m.post(UPS_TOKEN_URL, payload=_token())
            assert await _carrier(session).validate() is True
        with aioresponses() as m:
            m.post(UPS_TOKEN_URL, status=401, payload={})
            assert await _carrier(session).validate() is False
        with aioresponses() as m:
            m.post(UPS_TOKEN_URL, status=500, payload={})
            with pytest.raises(CarrierUnavailable):
                await _carrier(session).validate()

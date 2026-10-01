"""17track client: request format, error codes, HTTP errors, batching (HA-free)."""

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses
from yarl import URL

from custom_components.parcel_tracker.carriers.base import (
    AuthError,
    CarrierUnavailable,
    NotFound,
    ParseError,
    RateLimited,
)
from custom_components.parcel_tracker.carriers.track17 import (
    TRACK17_URL,
    CarrierNotDetected,
    NotRegistered,
    Quota,
    QuotaExhausted,
    Registration,
    Track17Client,
    Track17Info,
)
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_fixture

KEY = "synthetic-17track-key"
NUMBER = "99999999999901"
OTHER = "99999999999902"
REGISTER = f"{TRACK17_URL}/register"
INFO = f"{TRACK17_URL}/gettrackinfo"
QUOTA = f"{TRACK17_URL}/getquota"


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


def _ok(accepted=(), rejected=()):
    return {"code": 0, "data": {"accepted": list(accepted), "rejected": list(rejected)}}


def _rej(number, code):
    return {"number": number, "error": {"code": code, "message": "synthetic"}}


def _calls(m, url):
    return m.requests.get(("POST", URL(url)), [])


def _item(number=NUMBER):
    item = load_fixture("track17_synthetic_trackinfo.json")["response"]["data"]["accepted"][0]
    item["number"] = number
    return item


async def test_register_sends_number_code_and_key(session):
    with aioresponses() as m:
        m.post(REGISTER, payload=_ok([{"origin": 1, "number": NUMBER, "carrier": 100007}]))
        reg = await Track17Client(session, KEY).register(NUMBER, 100007)
        call = _calls(m, REGISTER)[0]
    assert reg == Registration(NUMBER, 100007)
    assert call.kwargs["json"] == [{"number": NUMBER, "carrier": 100007}]
    assert call.kwargs["headers"]["17token"] == KEY


async def test_register_without_code_lets_17track_detect_the_carrier(session):
    with aioresponses() as m:
        m.post(REGISTER, payload=_ok([{"origin": 1, "number": NUMBER, "carrier": 101070}]))
        reg = await Track17Client(session, KEY).register(NUMBER, None)
        assert _calls(m, REGISTER)[0].kwargs["json"] == [{"number": NUMBER}]
    assert reg.carrier == 101070


async def test_already_registered_is_success(session):
    with aioresponses() as m:
        m.post(REGISTER, payload=_ok(rejected=[_rej(NUMBER, -18019901)]))
        assert await Track17Client(session, KEY).register(NUMBER, 100007) == Registration(
            NUMBER, None
        )


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (-18010001, AuthError),
        (-18010002, AuthError),
        (-18010005, AuthError),
        (-18019902, NotRegistered),
        (-18019903, CarrierNotDetected),
        (-18019907, RateLimited),
        (-18019908, QuotaExhausted),
        (-18019909, NotFound),
        (-18019910, CarrierNotDetected),
        (-18019911, CarrierUnavailable),
        (-1, CarrierUnavailable),
    ],
)
async def test_register_rejections(session, code, error):
    with aioresponses() as m:
        m.post(REGISTER, payload=_ok(rejected=[_rej(NUMBER, code)]))
        with pytest.raises(error):
            await Track17Client(session, KEY).register(NUMBER, None)


async def test_register_neither_accepted_nor_rejected(session):
    with aioresponses() as m:
        m.post(REGISTER, payload=_ok())
        with pytest.raises(ParseError):
            await Track17Client(session, KEY).register(NUMBER, None)


@pytest.mark.parametrize("code", [-18010002, -18010005])
async def test_top_level_error_code(session, code):
    with aioresponses() as m:
        m.post(QUOTA, payload={"code": code, "data": None})
        with pytest.raises(AuthError):
            await Track17Client(session, KEY).getquota()


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, AuthError),
        (403, AuthError),
        (429, RateLimited),
        (500, CarrierUnavailable),
        (503, CarrierUnavailable),
    ],
)
async def test_http_errors(session, status, error):
    with aioresponses() as m:
        m.post(QUOTA, status=status)
        with pytest.raises(error):
            await Track17Client(session, KEY).getquota()


async def test_rate_limit_passes_retry_after(session):
    with aioresponses() as m:
        m.post(QUOTA, status=429, headers={"Retry-After": "30"})
        with pytest.raises(RateLimited) as err:
            await Track17Client(session, KEY).getquota()
    assert err.value.retry_after == 30


async def test_network_error(session):
    with aioresponses() as m:
        m.post(QUOTA, exception=aiohttp.ClientConnectionError("down"))
        with pytest.raises(CarrierUnavailable):
            await Track17Client(session, KEY).getquota()


async def test_non_json_answer(session):
    with aioresponses() as m:
        m.post(QUOTA, status=200, body="<html>Wartung</html>")
        with pytest.raises(ParseError):
            await Track17Client(session, KEY).getquota()


async def test_getquota(session):
    with aioresponses() as m:
        m.post(QUOTA, payload={"code": 0, "data": {
            "quota_total": 200, "quota_used": 3, "quota_remain": 197,
            "today_used": 1, "max_track_daily": 100,
        }})
        assert await Track17Client(session, KEY).getquota() == Quota(200, 3, 197)
        assert _calls(m, QUOTA)[0].kwargs["json"] == []


async def test_getquota_incomplete(session):
    with aioresponses() as m:
        m.post(QUOTA, payload={"code": 0, "data": {"quota_total": 200}})
        with pytest.raises(ParseError):
            await Track17Client(session, KEY).getquota()


async def test_gettrackinfo_parses_and_maps_rejections(session):
    with aioresponses() as m:
        m.post(INFO, payload=_ok([_item()], [_rej(OTHER, -18019909)]))
        out = await Track17Client(session, KEY).gettrackinfo([(NUMBER, 100007), (OTHER, None)])
        assert _calls(m, INFO)[0].kwargs["json"] == [
            {"number": NUMBER, "carrier": 100007},
            {"number": OTHER},
        ]
    assert isinstance(out[NUMBER], Track17Info)
    assert out[NUMBER].result.status is ParcelStatus.IN_TRANSIT
    assert isinstance(out[OTHER], NotFound)


async def test_gettrackinfo_asks_at_most_40_numbers_per_call(session):
    def echo(url, **kwargs):
        accepted = [_item(entry["number"]) for entry in kwargs["json"]]
        return CallbackResult(payload=_ok(accepted))

    numbers = [f"999999999999{i:02d}" for i in range(1, 42)]
    with aioresponses() as m:
        m.post(INFO, callback=echo, repeat=True)
        out = await Track17Client(session, KEY).gettrackinfo([(n, None) for n in numbers])
        sizes = [len(call.kwargs["json"]) for call in _calls(m, INFO)]
    assert sizes == [40, 1]
    assert set(out) == set(numbers)

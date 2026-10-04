"""GLS carrier: detection, endpoint choice by postcode and error mapping (synthetic answers)."""

import re

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.parcel_tracker.carriers import build_carriers
from custom_components.parcel_tracker.carriers.base import (
    CarrierUnavailable,
    Match,
    NotFound,
    ParseError,
    RateLimited,
)
from custom_components.parcel_tracker.carriers.gls import GLS_URL, GlsCarrier, gls_url
from custom_components.parcel_tracker.detect import candidates
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_fixture

NUMBER = "99999999901"
DETAIL = re.compile(rf"^{re.escape(GLS_URL)}/rstt028/{NUMBER}\?")
SEARCH = re.compile(rf"^{re.escape(GLS_URL)}/rstt029\?")


def _detail() -> dict:
    return load_fixture("gls_synthetic_detail.json")["response"]


def _search() -> dict:
    return load_fixture("gls_synthetic_search.json")["response"]


def _urls(mock: aioresponses) -> list[str]:
    return [str(url) for _, url in mock.requests]


async def _fetch(postcode: str | None, number: str = NUMBER):
    async with aiohttp.ClientSession() as session:
        return await GlsCarrier(session).fetch(number, postcode)


def test_matches_only_eleven_digits():
    assert GlsCarrier.matches("99999999901") is Match.SURE
    assert GlsCarrier.matches("999999999012") is Match.NO  # 12 digits: eBay item numbers
    assert GlsCarrier.matches("9999999990") is Match.NO
    assert GlsCarrier.matches("ZABCD123") is Match.NO  # track IDs only with carrier "GLS"
    assert GlsCarrier.matches("9999999990A") is Match.NO


async def test_detection_with_the_real_carriers():
    async with aiohttp.ClientSession() as session:
        carriers = build_carriers(session, None)
    assert list(carriers) == ["dhl", "dpd", "hermes", "gls"]
    assert carriers["gls"].name == "GLS"
    assert candidates("99999999901", carriers) == ["gls"]
    assert candidates("999999999012", carriers) == ["dhl"]  # as before: never GLS
    assert candidates("99999999999901", carriers) == ["dpd", "hermes"]
    assert candidates("ZABCD123", carriers) == []


async def test_with_postcode_the_detail_endpoint_is_asked():
    with aioresponses() as m:
        m.get(DETAIL, payload=_detail())
        r = await _fetch("10 115")
        [url] = _urls(m)
    assert r.status is ParcelStatus.DELIVERED and len(r.events) == 6
    assert "/rstt028/99999999901?" in url
    for part in ("caller=witt002", "postalCode=10115", "tuOwnerCode=", "millis="):
        assert part in url


@pytest.mark.parametrize("postcode", [None, "", " "])
async def test_without_postcode_the_search_endpoint_is_asked(postcode):
    with aioresponses() as m:
        m.get(SEARCH, payload=_search())
        r = await _fetch(postcode, "99999999902")
        [url] = _urls(m)
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY and r.events == []
    assert "/rstt029?" in url and "rstt028" not in url
    for part in ("match=99999999902", "type=", "caller=witt002", "millis="):
        assert part in url
    assert "postalCode" not in url


async def test_postcode_mismatch_falls_back_to_the_search_endpoint_once():
    with aioresponses() as m:
        m.get(DETAIL, status=404, payload={"lastError": "E609", "exceptionText": "x"})
        m.get(SEARCH, payload=_search())
        r = await _fetch("10115")
        urls = _urls(m)
    assert r.status is ParcelStatus.OUT_FOR_DELIVERY
    assert len(urls) == 2 and "rstt028" in urls[0] and "rstt029" in urls[1]


async def test_postcode_mismatch_is_remembered_per_number():
    other = "99999999902"
    other_detail = re.compile(rf"^{re.escape(GLS_URL)}/rstt028/{other}\?")
    async with aiohttp.ClientSession() as session:
        carrier = GlsCarrier(session)
        with aioresponses() as m:
            m.get(DETAIL, status=404, payload={"lastError": "E609"})
            m.get(SEARCH, payload=_search(), repeat=True)
            m.get(other_detail, payload=_detail())
            for _ in range(3):
                r = await carrier.fetch(NUMBER, "10115")
                assert r.status is ParcelStatus.OUT_FOR_DELIVERY
            calls = [str(c.kwargs["params"]) for key in m.requests for c in m.requests[key]]
            urls = _urls(m)
            # One failed try with the postcode, afterwards the lookup by number at once.
            assert sum("rstt028" in url for url in urls) == 1
            assert len(calls) == 4
            # Another parcel is still asked with the postcode ...
            assert len((await carrier.fetch(other, "10115")).events) == 6
            # ... and so is this one once another postcode is set.
            m.get(DETAIL, payload=_detail())
            assert len((await carrier.fetch(NUMBER, "10117")).events) == 6


async def test_postcode_mismatch_then_dummy_answer_is_not_found():
    dummy = _search()
    dummy["tuStatus"][0]["owners"] = []
    with aioresponses() as m:
        m.get(DETAIL, status=404, payload={"lastError": "E609"})
        m.get(SEARCH, payload=dummy)
        with pytest.raises(NotFound):
            await _fetch("10115")


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, {"lastError": "E206", "exceptionText": "x"}),
        (404, {"lastError": "E800", "exceptionText": "x"}),
        (500, {"lastError": "E801", "exceptionText": "x"}),
        (400, {"lastError": "E801"}),
        (404, {}),
    ],
)
async def test_not_found_answers(status, body):
    with aioresponses() as m:
        m.get(DETAIL, status=status, payload=body)
        with pytest.raises(NotFound):
            await _fetch("10115")
    with aioresponses() as m:
        m.get(SEARCH, status=status, payload=body)
        with pytest.raises(NotFound):
            await _fetch(None)


async def test_too_short_input_is_not_asked_at_all():
    with aioresponses() as m:
        with pytest.raises(NotFound):
            await _fetch("10115", "1234567")
        assert _urls(m) == []


async def test_dummy_answer_for_an_invalid_number_is_not_found():
    dummy = _search()
    dummy["tuStatus"][0]["progressBar"]["evtNos"] = [f"{n}.0" for n in range(60)]
    with aioresponses() as m:
        m.get(SEARCH, payload=dummy)
        with pytest.raises(NotFound):
            await _fetch(None)


@pytest.mark.parametrize(
    ("status", "raw"),
    [
        (200, "<html><body>Maintenance</body></html>"),  # maintenance page instead of JSON
        (200, ""),
        (500, '{"exceptionText": "Systemfehler"}'),
        (503, "<html>down</html>"),
        (400, '{"fieldExceptions": [{"attribute": "zipcode"}], "exceptionText": "x"}'),
    ],
)
async def test_unusable_answers_are_unavailable(status, raw):
    with aioresponses() as m:
        m.get(SEARCH, status=status, body=raw)
        with pytest.raises(CarrierUnavailable):
            await _fetch(None)


async def test_redirect_means_the_lookup_was_closed_and_is_not_followed():
    with aioresponses() as m:
        m.get(DETAIL, status=303, headers={"Location": "https://example.org/register-api-access"})
        with pytest.raises(CarrierUnavailable, match="303"):
            await _fetch("10115")
        assert len(_urls(m)) == 1


@pytest.mark.parametrize(
    ("status", "headers", "retry_after"),
    [
        (429, {"Retry-After": "120"}, 120),
        (429, {}, None),
        (403, {}, None),
        (429, {"Retry-After": "86400"}, 86400),
        (429, {"Retry-After": "86401"}, 86400),  # never longer than a day
        (429, {"Retry-After": "9" * 400}, 86400),  # absurd values must not break polling
        (429, {"Retry-After": " 120 "}, 120),
        (429, {"Retry-After": "000000120"}, 120),  # leading zeros are no length
        (429, {"Retry-After": "0" * 400}, 0),
        (429, {"Retry-After": "-5"}, None),
        (429, {"Retry-After": "1e9"}, None),
        (429, {"Retry-After": "\u00b2"}, None),  # a digit for str.isdigit(), not for int()
        (403, {"Retry-After": "Wed, 30 Sep 2026 08:00:00 GMT"}, None),
    ],
)
async def test_rate_limit_and_block(status, headers, retry_after):
    with aioresponses() as m:
        m.get(SEARCH, status=status, headers=headers, body="<html>blocked</html>")
        with pytest.raises(RateLimited) as err:
            await _fetch(None)
    assert err.value.retry_after == retry_after


async def test_network_error_and_timeout_are_unavailable():
    for error in (aiohttp.ClientConnectionError("down"), TimeoutError()):
        with aioresponses() as m:
            m.get(SEARCH, exception=error)
            with pytest.raises(CarrierUnavailable):
                await _fetch(None)


async def test_json_of_an_unexpected_shape_is_a_parse_error():
    with aioresponses() as m:
        m.get(SEARCH, payload=["odd"])
        with pytest.raises(ParseError):
            await _fetch(None)


async def test_only_number_and_postcode_leave_the_house():
    with aioresponses() as m:
        m.get(DETAIL, payload=_detail())
        await _fetch("10115")
        [((_, url), calls)] = m.requests.items()
    assert set(url.query) == {"caller", "millis", "tuOwnerCode", "postalCode"}
    headers = calls[0].kwargs["headers"]
    assert headers == {"Accept": "application/json"}  # no fake browser, no cookies


def test_url_by_country():
    """Live check 2026-10-04 with an invalid number: AT/de answers exactly like DE/de;
    CH/de answers in the same shape but with English texts, so Switzerland stays on DE/de."""
    base = "https://gls-group.com/app/service/open/rest"
    assert GLS_URL == f"{base}/DE/de"
    assert gls_url("de") == f"{base}/DE/de"
    assert gls_url("at") == f"{base}/AT/de"
    assert gls_url("ch") == f"{base}/DE/de"
    assert gls_url("AT") == f"{base}/AT/de"  # tolerant of the case
    for other in ("fr", "FR", "", None):
        assert gls_url(other) == f"{base}/DE/de"


@pytest.mark.parametrize(
    ("country", "path"), [(None, "DE/de"), ("de", "DE/de"), ("at", "AT/de"), ("ch", "DE/de")]
)
@pytest.mark.parametrize("postcode", ["1010", None])
async def test_both_lookups_use_the_path_of_the_country(country, path, postcode):
    with aioresponses() as m:
        m.get(re.compile(r".*/rstt028/"), payload=_detail())
        m.get(re.compile(r".*/rstt029\?"), payload=_search())
        async with aiohttp.ClientSession() as session:
            carrier = GlsCarrier(session) if country is None else GlsCarrier(session, country)
            await carrier.fetch(NUMBER, postcode)
        [url] = _urls(m)
    lookup = f"rstt028/{NUMBER}?" if postcode else "rstt029?"
    assert url.startswith(f"https://gls-group.com/app/service/open/rest/{path}/{lookup}")
    if postcode:
        assert "postalCode=1010" in url


async def test_build_carriers_passes_the_country_to_gls_only():
    async with aiohttp.ClientSession() as session:
        default = build_carriers(session, None)
        austria = build_carriers(session, None, "at")
    assert default["gls"].url == GLS_URL
    assert austria["gls"].url.endswith("/AT/de")
    assert list(austria) == list(default)

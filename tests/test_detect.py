import pytest

from custom_components.parcel_tracker.carriers.base import Carrier, Match
from custom_components.parcel_tracker.detect import UnsupportedNumber, candidates, normalize


class FakeDhl(Carrier):
    key = "dhl"
    name = "DHL"

    @staticmethod
    def matches(number: str) -> Match:
        if len(number) == 20 and number.startswith("00340"):
            return Match.SURE
        if len(number) == 12 and number.isdigit():
            return Match.POSSIBLE
        return Match.NO

    async def fetch(self, number, postcode):  # pragma: no cover
        raise NotImplementedError


class FakeDpd(FakeDhl):
    key = "dpd"
    name = "DPD"

    @staticmethod
    def matches(number: str) -> Match:
        return Match.POSSIBLE if len(number) == 14 and number.isdigit() else Match.NO


CARRIERS = {"dhl": FakeDhl, "dpd": FakeDpd}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0 0 3 4 0 9 9 9 9 9 9 9 9 9 9 9 9 9 0 1", "00340999999999999901"),
        ("0999-9999-9999-01", "09999999999901"),
        (" jjd0123 ", "JJD0123"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_candidates_sure_first():
    assert candidates("00340999999999999901", CARRIERS) == ["dhl"]


def test_candidates_possible():
    assert candidates("09999999999901", CARRIERS) == ["dpd"]


def test_candidates_none():
    assert candidates("XYZ", CARRIERS) == []


def test_amazon_rejected():
    with pytest.raises(UnsupportedNumber) as err:
        candidates("TBA123456789000", CARRIERS)
    assert err.value.reason == "amazon"


def test_empty_rejected():
    with pytest.raises(UnsupportedNumber) as err:
        candidates("", CARRIERS)
    assert err.value.reason == "empty"

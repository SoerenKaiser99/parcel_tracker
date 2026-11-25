"""DHL mail with a "JJD" number of 24 digits (parcel from Poland, issue #98)."""

from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.base import carrier_for, find_numbers

from .conftest import load_mail


def test_dhl_mail_with_jjd_and_24_digits_is_recognised():
    result = parse_mail(load_mail("237_dhl_jjd_24_ziffern.eml"))
    assert [(u.carrier, u.number) for u in result.updates] == [
        ("dhl", "JJD000000000000000000009898")
    ]


def test_jjd_numbers_from_12_to_24_digits_count_but_not_longer():
    assert carrier_for("JJD" + "1" * 24) == "dhl"
    assert carrier_for("JJD" + "1" * 12) == "dhl"
    assert carrier_for("JJD" + "1" * 25) is None
    assert find_numbers("Sendung JJD" + "1" * 25 + " heute") == []

"""Shopify's shipping mail "Eine Sendung aus der Bestellung #… ist unterwegs" (issue #92)."""

import pytest

from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.base import find_numbers

from .conftest import load_mail


def test_shopify_mail_with_dpd_trackingnummer_is_a_dpd_parcel():
    result = parse_mail(load_mail("235_shopify_dpd_trackingnummer.eml"))
    assert [(u.carrier, u.number) for u in result.updates] == [("dpd", "09999999999292")]
    [update] = result.updates
    assert update.status is None


@pytest.mark.parametrize(
    "label",
    ["dpd Trackingnummer:", "DPD Tracking-Nummer", "Trackingnr.", "Tracking number:"],
)
def test_tracking_labels_name_a_dpd_number(label):
    assert find_numbers(f"Versand mit DPD\n{label} 09999999999901", "labelled") == [
        ("dpd", "09999999999901")
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Versand mit DPD\nRetouren-Trackingnummer: 09999999999901",
        "Versand mit DPD\nRücksendung Trackingnummer: 09999999999901",
        "Versand mit DPD\nTrackingnummer: 099999999999012",  # 15 digits
        "Versand mit DPD\nOrdertrackingnummer 09999999999901",  # not a word start
    ],
)
def test_returns_and_other_numbers_are_no_dpd_parcel(text):
    assert find_numbers(text, "labelled") == []


def test_without_dpd_in_the_mail_a_trackingnummer_is_no_dpd_parcel():
    assert find_numbers("Trackingnummer: 09999999999901", None) == []


def test_number_only_in_the_html_part_is_found():
    # Issue #92: the plain part names "dpd Trackingnummer:" without the number.
    result = parse_mail(load_mail("236_shopify_dpd_nur_im_html.eml"))
    assert [(u.carrier, u.number) for u in result.updates] == [("dpd", "09999999999292")]

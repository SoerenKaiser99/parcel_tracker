from datetime import date, datetime
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.ebay import EBAY_SENDER, order_number, parse_ebay
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail

SHIPPED = "104_ebay_ihre_sendung_ist_jetzt_beim_versand.eml"
DELIVERED = "106_ebay_bestellung_zugestellt.eml"


def _msg(subject: str, body: str) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"eBay <{EBAY_SENDER}>"
    msg["Subject"] = subject
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 -0700"
    msg.set_content(body)
    return msg


def test_order_number():
    assert order_number("99-00000-00001") == "EBAY990000000001"


def test_shipped_html_only_two_items_one_order():
    [u] = parse_ebay(load_mail(SHIPPED))
    assert (u.number, u.carrier) == ("EBAY992179315376", "ebay")
    assert u.status is ParcelStatus.IN_TRANSIT
    assert u.title == "Bambu Lab PLA Basic Filament Blue Bl… und 1 weiterer Artikel"
    assert len(u.title) <= 60
    assert (u.eta_date, u.eta_latest) == (date(2026, 1, 28), date(2026, 1, 29))
    assert u.shipping_carrier_hint == "hermes"
    assert u.delivered_at is None


def test_delivered_with_emoji_subject_and_drop_time():
    [u] = parse_ebay(load_mail(DELIVERED))
    assert (u.number, u.status) == ("EBAY990157856617", ParcelStatus.DELIVERED)
    assert u.title == "Crucial RAM XY00Z0ABC0000 16GB DDR4 2666MHz PC Desktop RAM…"
    assert u.delivered_at == datetime(2026, 5, 5, 15, 15, tzinfo=BERLIN)
    # The return notice mentions Hermes and DHL; only "Versanddienstleister:" counts.
    assert u.shipping_carrier_hint is None


def test_title_falls_back_to_subject_and_unknown_carrier_hint_is_kept():
    msg = _msg(
        "BESTELLUNG ZUGESTELLT: Kabel USB-C",
        "Bestellnummer:\n12-34567-89012\nVersanddienstleister:\nFedEx Express\n",
    )
    [u] = parse_ebay(msg)
    assert (u.number, u.title, u.shipping_carrier_hint) == (
        "EBAY123456789012",
        "Kabel USB-C",
        "FedEx Express",
    )
    assert u.delivered_at == datetime(2026, 9, 30, 17, 0, tzinfo=BERLIN)


def test_gls_as_shipping_carrier_becomes_the_carrier_key():
    msg = _msg(
        "BESTELLUNG ZUGESTELLT: Kabel USB-C",
        "Bestellnummer:\n12-34567-89012\nVersanddienstleister:\nGLS Paket\n",
    )
    [u] = parse_ebay(msg)
    assert u.shipping_carrier_hint == "gls"


@pytest.mark.parametrize(
    "subject", ["Sie haben einen Artikel gekauft", "Bewerten Sie Ihren Kauf", "Angebot"]
)
def test_other_subjects_are_unrecognised_and_never_generic(subject):
    msg = _msg(subject, "Artikelnr.: 999999999901\nBestellnummer: 99-00000-00001\n"
                        "Sendungsnummer JJD000012978217606560")
    assert parse_ebay(msg) == []
    result = parse_mail(msg)
    assert result.updates == [] and not result.amazon and not result.ignored


def test_item_numbers_never_become_tracking_numbers():
    for name in (SHIPPED, DELIVERED):
        assert all(u.number.startswith("EBAY") for u in parse_mail(load_mail(name)).updates)

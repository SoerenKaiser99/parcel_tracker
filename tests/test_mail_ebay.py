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


# ----- "Update zur Bestellung": shipped, with the carrier's number -----
UPDATE = "167_ebay_update_zur_bestellung.eml"


def _update(tracking: str, item: str = "Beispiel-Artikel\n") -> EmailMessage:
    return _msg(
        "🚚 Update zur Bestellung: Beispiel-Artikel",
        f"Sendungsnummer:{tracking}\nEinzelheiten zu Ihrem Kauf\n{item}"
        "Artikelnr.:\n999999999901\nBestellnummer:\n99-00000-00001\n",
    )


def test_update_mail_is_shipped_and_brings_the_dhl_number():
    [u] = parse_mail(load_mail(UPDATE)).updates
    assert (u.number, u.carrier, u.status) == ("EBAY990000000167", "ebay", ParcelStatus.IN_TRANSIT)
    # The price lines between title and item number are no title.
    assert u.title == "Beispiel Akku-LED-Baustrahler blau IP55"
    assert (u.eta_date, u.eta_latest) == (date(2025, 7, 1), date(2025, 7, 9))
    assert (u.tracking_ref, u.tracking_carrier) == ("00340999999999990167", "dhl")
    assert u.delivered_at is None


@pytest.mark.parametrize(
    ("tracking", "ref", "carrier"),
    [
        (" 00340999999999990901", "00340999999999990901", "dhl"),
        ("\n00340999999999990901", "00340999999999990901", "dhl"),  # on the line below
        (" H1000999999999990901", "H1000999999999990901", "hermes"),
        # 12 or 14 digits may be DHL, GLS, DPD or Hermes: the number is left alone
        (" 999999999902", None, None),
        (" 09999999999903", None, None),
    ],
)
def test_update_mail_takes_only_a_number_that_tells_its_carrier(tracking, ref, carrier):
    [u] = parse_mail(_update(tracking)).updates
    assert (u.number, u.status) == ("EBAY990000000001", ParcelStatus.IN_TRANSIT)
    assert (u.tracking_ref, u.tracking_carrier) == (ref, carrier)
    assert u.title == "Beispiel-Artikel"


def test_update_mail_title_falls_back_to_the_subject():
    msg = _msg("🚚 Update zur Bestellung: Beispiel-Artikel mit langem Na...",
               "Bestellnummer:\n99-00000-00001\n")
    [u] = parse_mail(msg).updates
    assert (u.title, u.tracking_ref) == ("Beispiel-Artikel mit langem Na", None)


def test_the_number_of_another_ebay_mail_is_never_taken():
    msg = _msg("Ihre Sendung ist jetzt beim Versanddienstleister!",
               "Sendungsnummer: 00340999999999990901\nBestellnummer:\n99-00000-00001\n")
    [u] = parse_mail(msg).updates
    assert (u.status, u.tracking_ref) == (ParcelStatus.IN_TRANSIT, None)


def test_item_numbers_never_become_tracking_numbers():
    for name in (SHIPPED, DELIVERED):
        assert all(u.number.startswith("EBAY") for u in parse_mail(load_mail(name)).updates)


def test_update_mail_about_two_orders_gives_neither_the_number():
    msg = _msg(
        "🚚 Update zur Bestellung: Beispiel-Artikel",
        "Sendungsnummer: 00340999999999990901\n"
        "Artikel A\nArtikelnr.:\n999999999901\nBestellnummer:\n99-00000-00001\n"
        "Artikel B\nArtikelnr.:\n999999999902\nBestellnummer:\n99-00000-00002\n",
    )
    first, second = parse_mail(msg).updates
    assert (first.number, second.number) == ("EBAY990000000001", "EBAY990000000002")
    assert (first.tracking_ref, second.tracking_ref) == (None, None)


# ----- "Zustellversuch": nobody was met -----
def test_delivery_attempt_takes_the_order_back_on_its_way_in_its_own_words():
    msg = _msg(
        "Zustellversuch: Beispiel-Artikel...",
        "Update zu Ihrer Bestellung.\nDHL Germany hat Sie leider nicht angetroffen.\n"
        "Sendungsnummer: 00340999999999990901\nBestellung nachverfolgen\n"
        "Beispiel-Artikel mit vollem Namen\nArtikelnr.:\n999999999901\n"
        "Bestellnummer:\n99-00000-00001\nZustellversuch:\nMo, 28. Sep 15:56 Ortszeit\n"
        "Versanddienstleister:\nDHL Germany\n",
    )
    [u] = parse_mail(msg).updates
    assert (u.number, u.status) == ("EBAY990000000001", ParcelStatus.IN_TRANSIT)
    assert (u.status_text, u.postponed) == ("Zustellung versucht", True)
    assert (u.title, u.shipping_carrier_hint) == ("Beispiel-Artikel mit vollem Namen", "dhl")
    assert (u.tracking_ref, u.tracking_carrier) == ("00340999999999990901", "dhl")
    assert (u.eta_date, u.delivered_at) == (None, None)


def test_other_ebay_mails_are_never_postponed():
    for name in (SHIPPED, DELIVERED, UPDATE):
        updates = parse_mail(load_mail(name)).updates
        assert all(not u.postponed and u.status_text is None for u in updates)


# ----- review: the carrier's mail came first -----
def test_update_takes_over_the_parcel_a_dhl_mail_made_before():
    from custom_components.parcel_tracker.mail.apply import apply_update
    from custom_components.parcel_tracker.mail.base import sent_at

    update = load_mail(UPDATE)
    [order] = parse_mail(update).updates
    assert order.tracking_carrier == "dhl"
    dhl = EmailMessage(policy=policy.default)
    dhl["From"] = "DHL Paket <noreply@dhl.de>"
    dhl["Subject"] = "Ihre Sendung ist unterwegs"
    dhl["Date"] = update["Date"]
    dhl.set_content(f"{order.tracking_ref}\n")
    [parcel] = parse_mail(dhl).updates
    parcels = {}
    now = sent_at(update)
    apply_update(parcels, parcel, now)
    assert list(parcels) == [order.tracking_ref]
    apply_update(parcels, order, now)
    # One entry is left: the order, asked about at DHL.
    assert list(parcels) == [order.number]
    assert parcels[order.number].tracking_ref == order.tracking_ref

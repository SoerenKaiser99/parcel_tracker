"""DHL eCommerce: 20-digit SSCC numbers ("00…", not only DHL's own "00340…") and the mails of
dhlecommerce.nl (shipments from the Netherlands).

The two fixtures derive from a tester's anonymised mails; their number is an invented SSCC
with a valid check digit.
"""

from datetime import date, datetime
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN, Match
from custom_components.parcel_tracker.carriers.dhl import DhlCarrier
from custom_components.parcel_tracker.mail import (
    forwarded_original,
    known_sender_domain,
    parse_mail,
)
from custom_components.parcel_tracker.mail.base import find_numbers, sent_at, sscc_valid
from custom_components.parcel_tracker.mail.shipping import (
    parse_dhl_ecommerce_mail,
    parse_generic,
)
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail

SSCC = "00099999999999999992"  # invented, valid check digit
WRONG = "00099999999999999993"  # the same digits with a wrong check digit
OTHER = "00012345678901234560"  # invented, valid check digit
DHL_MAIL = "195_dhl_sendung_ist_unterwegs_sscc.eml"
FORWARDED = "196_dhl_ecommerce_weitergeleitet_shipment_on_its_way.eml"
ECOMMERCE = "DHL eCommerce <noreply@dhlecommerce.nl>"


def _msg(subject: str, body: str, from_: str) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = from_
    msg["Subject"] = subject
    msg["Date"] = "Tue, 06 Oct 2026 17:54:00 +0000"
    msg.set_content(body)
    return msg


# ----- the check digit -----
@pytest.mark.parametrize(
    ("number", "valid"),
    [
        (SSCC, True),
        (OTHER, True),
        (WRONG, False),
        ("00340434161094012345", True),  # (DHL's own numbers are SSCCs too)
        ("00340999999999999917", False),
        ("10099999999999999992", False),  # no "00" in front
        ("0009999999999999999", False),  # 19 digits
        ("000999999999999999920", False),  # 21 digits
        ("0009999999999999999A", False),
        ("", False),
    ],
)
def test_sscc_valid(number, valid):
    assert sscc_valid(number) is valid


def test_sscc_check_digit_is_gs1_mod_10():
    # Every check digit but one is wrong.
    body = SSCC[:-1]
    assert [d for d in "0123456789" if sscc_valid(body + d)] == ["2"]


# ----- find_numbers: an SSCC only right behind a label, only with a valid check digit -----
@pytest.mark.parametrize(
    "label",
    [
        "Sendungsnummer",
        "Sendungsnummer:",
        "Ihre Sendungsnummer\n",
        "Sendungsnr.",
        "Sendungsnr.: ",
        "Trackingnummer:",
        "DHL Trackingnummer:",
        "DHL-Trackingnummer",
        "Tracking-Nummer:",
        "tracking-nummer",
        "Shipment number\n\n",
        "SHIPMENT NUMBER:",
        "Tracking number:",
        "Tracking number :\n  ",
    ],
)
def test_sscc_behind_a_label_is_a_dhl_number(label):
    assert find_numbers(f"Hallo,\n{label}{SSCC}\nGrüße") == [("dhl", SSCC)]


@pytest.mark.parametrize(
    "label",
    [
        "Rücksendungsnummer:",
        "Rücksendungsnummer\n",
        "Rück-Sendungsnummer:",
        "Retouren-Trackingnummer",
        "Retouren Trackingnummer:",
        "Retoure Sendungsnummer:",
        "Retourensendungsnummer:",
        "RETOUREN-SENDUNGSNR.",
        "Return tracking number:",
        "Return shipment number:",
        "Rücksendung Sendungsnummer:",
        "Rücksende-Sendungsnummer:",
        "Rückversand-Sendungsnummer:",
        "Return label – Tracking number:",
        "Return label: Tracking number ",
        "Retouren Sendungsnummer:",
        "Retourenschein Sendungsnummer:",
        "Paketsendungsnummer:",
        "XTrackingnummer:",
        "Tracking-Nummer2 ",
    ],
)
def test_sscc_behind_a_return_or_other_label_is_no_number(label):
    assert find_numbers(f"Hallo,\n{label}{SSCC}\n") == []


def test_sscc_with_a_wrong_check_digit_is_no_number():
    assert find_numbers(f"Sendungsnummer: {WRONG}") == []
    assert find_numbers(f"DHL Trackingnummer: {WRONG}") == []


@pytest.mark.parametrize(
    "text",
    [
        f"{SSCC}",
        f"Bestellnummer: {SSCC}",
        f"Rechnungsnummer {SSCC}",
        f"Kundennummer {SSCC}",
        f"Sendungsnummer folgt, Ihre Referenz {SSCC}",
        f"Sendungsnummer: 1{SSCC}",  # 21 digits
        f"Sendungsnummer: {SSCC}1",
    ],
)
def test_sscc_without_its_label_is_no_number(text):
    assert find_numbers(text) == []


def test_dhl_00340_numbers_are_found_as_before():
    # (anywhere, without a label and whatever their last digit)
    assert find_numbers("00340999999999999917") == [("dhl", "00340999999999999917")]
    assert find_numbers("Sendungsnummer: 00340434161094012345") == [
        ("dhl", "00340434161094012345")
    ]


def test_shop_mail_with_a_dhl_tracking_number():
    msg = _msg(
        "Deine Bestellung ist unterwegs",
        f"Hallo Max,\ndeine Bestellung ist unterwegs.\nDHL Trackingnummer: {SSCC}\n",
        "Beispiel Shop <shop@example.org>",
    )
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (SSCC, "dhl", None)
    [u] = parse_generic(msg)
    assert (u.number, u.carrier) == (SSCC, "dhl")


def test_shop_mail_with_a_wrong_check_digit_has_no_number():
    msg = _msg(
        "Deine Bestellung ist unterwegs",
        f"DHL Trackingnummer: {WRONG}\n",
        "Beispiel Shop <shop@example.org>",
    )
    assert parse_mail(msg).updates == []


# ----- DHL's own mail -----
def test_dhl_mail_with_an_sscc_below_its_label():
    msg = load_mail(DHL_MAIL)
    assert "Ihre Sendungsnummer\n" + SSCC in msg.get_body(("plain",)).get_content()
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (SSCC, "dhl", ParcelStatus.IN_TRANSIT)
    assert u.eta_date == date(2026, 10, 8)
    # "Harman Service Delivery" names no company: no name without the option ...
    assert (u.title, u.shop) == (None, None)
    # ... with "Absendernamen aus DHL-Mails übernehmen" it is the name
    [u] = parse_mail(msg, plain_names=True).updates
    assert u.title == "Harman Service Delivery"


def test_dhl_mail_reads_an_sscc_behind_its_label_whatever_its_check_digit():
    # In DHL's own mail DHL decides whether it knows the number (like a UPU S10 number).
    for body in (f"Ihre Sendungsnummer\n{WRONG}\n", f"Ihre Sendungsnummer: {WRONG}\n"):
        msg = _msg("Ihre Sendung ist unterwegs", body, "DHL <paketankuendigung@dhl.de>")
        [u] = parse_mail(msg).updates
        assert (u.number, u.carrier) == (WRONG, "dhl")


def test_dhl_mail_sscc_without_its_label_is_no_number():
    msg = _msg("Ihre Sendung ist unterwegs", f"Referenz {SSCC}\n", "DHL <noreply@dhl.de>")
    assert parse_mail(msg).updates == []


def test_dhl_html_part_shows_an_sscc_below_the_button():
    msg = _msg("Ihre Beispiel GmbH Sendung ist unterwegs", "[{PACKAGE_IDENTIFIER}]\n",
               "DHL Paket <noreply@dhl.de>")
    msg.add_alternative(
        f"<html><body><p>Sendungsstatus einsehen</p><p>{WRONG}</p></body></html>",
        subtype="html",
    )
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier) == (WRONG, "dhl")


# ----- dhlecommerce.nl -----
def test_dhlecommerce_is_a_known_sender():
    assert known_sender_domain("noreply@dhlecommerce.nl") == "dhlecommerce.nl"
    assert known_sender_domain("info@mail.dhlecommerce.nl") == "dhlecommerce.nl"


def test_forwarded_dhl_ecommerce_mail():
    msg = load_mail(FORWARDED)
    assert str(msg["Subject"]) == "WG: Shipment on its way"
    assert "dhlecommerce" not in str(msg["From"])
    original = forwarded_original(msg)
    assert original is not None and "noreply@dhlecommerce.nl" in str(original["From"])
    result = parse_mail(msg)
    assert result.amazon is False and not result.ignored
    [u] = result.updates
    assert (u.number, u.carrier, u.status) == (SSCC, "dhl", ParcelStatus.IN_TRANSIT)
    assert u.sent_at == datetime(2026, 10, 6, 15, 21, tzinfo=BERLIN) < sent_at(msg)
    # "Harman Service Delivery" passes no naming gate
    assert (u.title, u.shop, u.eta_date, u.delivered_at) == (None, None, None, None)
    # The option takes the name the mail gives, as from DHL's own mails.
    assert parse_mail(msg, plain_names=True).updates[0].title == "Harman Service Delivery"


def _ecommerce(subject: str, body: str) -> EmailMessage:
    return _msg(subject, body, ECOMMERCE)


def test_dhl_ecommerce_mail_names_a_company_through_the_gate():
    body = (
        "WE WILL DELIVER SOON\n\nSoon our courier will deliver shipment "
        f"{SSCC}<https://secure.dhlecommerce.nl/…> from Beispiel B.V. to you.\n"
    )
    [u] = parse_mail(_ecommerce("Shipment on its way", body)).updates
    assert (u.number, u.carrier, u.status, u.title) == (
        SSCC, "dhl", ParcelStatus.IN_TRANSIT, "Beispiel B.V."
    )
    assert u.sent_at == sent_at(_ecommerce("x", "x"))


def test_dhl_ecommerce_mail_never_names_a_person():
    body = f"Soon our courier will deliver shipment {SSCC} from Erika Beispiel to you.\n"
    [u] = parse_dhl_ecommerce_mail(_ecommerce("Shipment on its way", body))
    assert u.title is None
    [u] = parse_dhl_ecommerce_mail(_ecommerce("Shipment on its way", body), plain_names=True)
    assert u.title == "Erika Beispiel"  # (only with the option, like DHL's own mails)


def test_dhl_ecommerce_text_alone_tells_the_status():
    body = f"WE WILL DELIVER SOON\nShipment number\n\n{SSCC}\n"
    [u] = parse_dhl_ecommerce_mail(_ecommerce("Your parcel", body))
    assert (u.number, u.status) == (SSCC, ParcelStatus.IN_TRANSIT)


def test_dhl_ecommerce_shipment_number_label():
    [u] = parse_dhl_ecommerce_mail(
        _ecommerce("Shipment on its way", f"Shipment number\n\n{OTHER}\n")
    )
    assert (u.number, u.carrier, u.status) == (OTHER, "dhl", ParcelStatus.IN_TRANSIT)


def test_dhl_ecommerce_other_mail_names_the_number_without_a_status():
    body = f"Something about your shipment.\nShipment number: {SSCC}\n"
    [u] = parse_mail(_ecommerce("Your shipment", body)).updates
    assert (u.number, u.carrier, u.status) == (SSCC, "dhl", None)


def test_dhl_ecommerce_mail_without_a_number():
    msg = _ecommerce("Shipment on its way", "WE WILL DELIVER SOON\n")
    assert parse_dhl_ecommerce_mail(msg) == []
    # (a wrong check digit behind a label is no number; "deliver shipment" is DHL's own)
    body = f"Shipment number: {WRONG}\n"
    assert parse_dhl_ecommerce_mail(_ecommerce("Shipment on its way", body)) == []
    body = f"Soon our courier will deliver shipment {WRONG} from Beispiel B.V. to you."
    [u] = parse_dhl_ecommerce_mail(_ecommerce("Shipment on its way", body))
    assert u.number == WRONG


def test_dhl_ecommerce_html_only_mail():
    msg = EmailMessage(policy=policy.default)
    msg["From"] = ECOMMERCE
    msg["Subject"] = "Shipment on its way"
    msg["Date"] = "Tue, 06 Oct 2026 17:54:00 +0000"
    msg.set_content(
        "<html><body><p>WE WILL DELIVER SOON</p><p>Soon our courier will deliver shipment "
        f"{SSCC}</p><p>from</p><p>Beispiel GmbH to you.</p></body></html>",
        subtype="html",
    )
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.title) == (SSCC, ParcelStatus.IN_TRANSIT, "Beispiel GmbH")


# ----- typed in by hand: no rule of DHL's, the DHL fallback asks once (as before) -----
def test_hand_typed_sscc_is_left_to_the_dhl_fallback():
    assert DhlCarrier.matches(SSCC) is Match.NO
    assert DhlCarrier.matches("00340434161094012345") is Match.SURE

from datetime import date, datetime
from email import policy
from email.message import EmailMessage

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail.shipping import (
    AMAZON_DHL_NAME,
    parse_dhl_mail,
    parse_generic,
    parse_ups_mail,
)
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail


def _msg(subject: str, body: str, from_: str) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = from_
    msg["Subject"] = subject
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content(body)
    return msg


def test_dhl_amazon_shipment_with_day_and_month():
    [u] = parse_dhl_mail(load_mail("045_noreply_ihre_amazon_sendung_ist_unterweg.eml"))
    assert (u.number, u.carrier) == ("JJD000012978217606560", "dhl")
    assert u.status is ParcelStatus.IN_TRANSIT
    assert u.shop == "amazon"
    assert u.title == AMAZON_DHL_NAME == "Amazon-Sendung (DHL)"
    assert u.eta_date == date(2026, 7, 31)
    assert u.eta_from is None


def test_dhl_today_window():
    [u] = parse_dhl_mail(load_mail("049_noreply_ihre_amazon_sendung_kommt_heute_.eml"))
    assert u.status is ParcelStatus.OUT_FOR_DELIVERY
    assert u.shop == "amazon"
    assert u.eta_date == date(2026, 7, 31)
    assert u.eta_from == datetime(2026, 7, 31, 13, 10, tzinfo=BERLIN)
    assert u.eta_to == datetime(2026, 7, 31, 14, 40, tzinfo=BERLIN)


def test_dhl_day_without_month_and_not_amazon():
    msg = _msg(
        "Ihre Sendung ist unterwegs",
        "Ihre Sendung wird Ihnen voraussichtlich\nam Freitag, den 2.\nzugestellt.\n"
        "00340999999999999917",
        "DHL Paket <noreply@dhl.de>",
    )
    [u] = parse_dhl_mail(msg)
    assert u.number == "00340999999999999917"
    assert u.shop is None
    assert u.title is None
    assert u.eta_date == date(2026, 10, 2)


def test_dhl_without_number_gives_nothing():
    assert parse_dhl_mail(_msg("Hallo", "kein Paket", "DHL Paket <noreply@dhl.de>")) == []


def test_ups_announcement():
    [u] = parse_ups_mail(load_mail("070_pkginfo_ups_versandbenachrichtigung_kont.eml"))
    assert (u.number, u.carrier) == ("1Z999AA11026832876", "ups")
    assert u.status is ParcelStatus.PRE_TRANSIT
    assert u.eta_date == date(2019, 3, 6)
    assert u.title == "Beispiel Versand GmbH"


def test_ups_delivered_with_time():
    [u] = parse_ups_mail(load_mail("071_pkginfo_ups_zustellbenachrichtigung_kont.eml"))
    assert u.status is ParcelStatus.DELIVERED
    assert u.delivered_at == datetime(2019, 3, 5, 13, 43, tzinfo=BERLIN)
    assert u.title is None


def test_generic_takes_only_safe_numbers_and_no_unknown_sender_name():
    msg = _msg(
        "Deine Bestellung ist unterwegs",
        "Sendungsnummer 00340999999999999917, Kundennummer 09999999999901",
        "Kaffeerösterei Beispiel <shop@example.org>",
    )
    updates = parse_generic(msg)
    assert [(u.carrier, u.number, u.title, u.status) for u in updates] == [
        ("dhl", "00340999999999999917", None, None)
    ]


def test_generic_dpd_needs_dpd_in_text_and_a_label():
    msg = _msg("Versand mit DPD", "Paketnummer 09999999999901", "Shop <shop@example.org>")
    assert [(u.carrier, u.number) for u in parse_generic(msg)] == [("dpd", "09999999999901")]
    msg = _msg("Versand", "Paketnummer 09999999999901", "Shop <shop@example.org>")
    assert parse_generic(msg) == []


def test_generic_dpd_probe_yields_exactly_one_number():
    body = (
        "Vielen Dank für deine Bestellung.\n"
        "Bestellnummer 10105012345678\n"
        "Dein Paket ist mit DPD unterwegs.\n"
        "Paketnummer: 09999999999901\n"
        "Fragen? Hotline 08001234567890\n"
    )
    msg = _msg("Deine Bestellung ist unterwegs", body, "Shop <shop@example.org>")
    assert [(u.carrier, u.number) for u in parse_generic(msg)] == [("dpd", "09999999999901")]


def test_generic_mail_from_dpd_takes_unlabelled_numbers():
    msg = _msg(
        "Ihr Paket kommt heute",
        "Ihr Paket 09999999999901 kommt heute.",
        "DPD <noreply@service.dpd.de>",
    )
    assert [(u.carrier, u.number, u.title) for u in parse_generic(msg)] == [
        ("dpd", "09999999999901", "DPD")
    ]


def test_forwarded_mail_never_takes_the_sender_name():
    msg = _msg(
        "WG: Ihr Paket kommt heute",
        "Ihr Paket 09999999999901 kommt heute.\nDHL: 00340999999999999917",
        "Max Mustermann <noreply@service.dpd.de>",
    )
    updates = parse_generic(msg)
    assert {u.number for u in updates} == {"09999999999901", "00340999999999999917"}
    assert all(u.title is None for u in updates)


def test_forwarded_shop_mail_has_no_name():
    msg = _msg(
        "Fwd: Versandbestätigung",
        "---------- Forwarded message ---------\nVon: Shop <shop@example.org>\n"
        "Ihre DHL-Sendungsnummer: JJD000012978217606560",
        "Max Mustermann <max@example.org>",
    )
    assert [(u.carrier, u.number, u.title) for u in parse_generic(msg)] == [
        ("dhl", "JJD000012978217606560", None)
    ]


def test_ups_shipper_names_the_shop():
    msg = load_mail("070_pkginfo_ups_versandbenachrichtigung_kont.eml")
    [u] = parse_ups_mail(msg)
    assert u.shop is None
    text = msg.get_body(preferencelist=("plain",)).get_content()
    msg.set_content(text.replace("Beispiel Versand GmbH", "Amazon EU S.a.r.L."))
    [u] = parse_ups_mail(msg)
    assert (u.shop, u.title) == ("amazon", "Amazon EU S.a.r.L.")

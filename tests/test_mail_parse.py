from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.mail import is_ignored, parse_mail

from .conftest import load_mail


@pytest.mark.parametrize(
    "address",
    [
        "promotion4@amazon.de",
        "no-reply@primevideo.com",
        "rueckgabe@amazon.de",
        "account-update@amazon.de",
        "no-reply@amazon.de",
    ],
)
def test_ignored_senders(address):
    assert is_ignored(address)
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"Amazon <{address}>"
    msg["Subject"] = "Angebot"
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content("x")
    result = parse_mail(msg)
    assert result.ignored and not result.updates and not result.amazon


def test_not_ignored():
    assert not is_ignored("versandbestaetigung@amazon.de")
    assert not is_ignored("promotion@example.org")


@pytest.mark.parametrize(
    ("name", "carrier", "amazon"),
    [
        ("001_bestellbestaetigung_bestellt.eml", "amazon", True),
        ("046_versandbestaetigung_ihre_amazon_de_beste.eml", "ups", True),
        ("045_noreply_ihre_amazon_sendung_ist_unterweg.eml", "dhl", False),
        ("070_pkginfo_ups_versandbenachrichtigung_kont.eml", "ups", False),
    ],
)
def test_routing(name, carrier, amazon):
    result = parse_mail(load_mail(name))
    assert result.updates[0].carrier == carrier
    assert result.amazon is amazon
    assert not result.ignored


def test_read_otp_is_passed_through():
    name = "097_shipment_tracking_zustellung_heute_f_r_d.eml"
    assert parse_mail(load_mail(name)).updates[0].delivery_code is None
    assert parse_mail(load_mail(name), read_otp=True).updates[0].delivery_code == "123456"


def test_hand_forwarded_amazon_mail_is_recognised():
    msg = load_mail("074_versandbestaetigung_versendet.eml")
    msg.replace_header("From", "Max Mustermann <max@example.org>")
    msg.replace_header("Subject", "WG: " + str(msg["Subject"]))
    result = parse_mail(msg)
    assert result.amazon is False  # not from Amazon itself: never counts as unrecognised
    [update] = result.updates
    assert update.number == "AMZ99991565342587125"
    assert update.title == "4 Ersatz Metallplättchen…"


def test_forwarded_amazon_like_mail_without_order_falls_back_to_generic():
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "Max Mustermann <max@example.org>"
    msg["Subject"] = "WG: Versendet: „Bilderrahmen Holz 20x30...“"
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content(
        "Bestellnr. fehlt hier leider\nIhre DHL-Sendungsnummer: JJD000012978217606560"
    )
    result = parse_mail(msg)
    assert result.amazon is False
    assert [(u.carrier, u.number, u.title) for u in result.updates] == [
        ("dhl", "JJD000012978217606560", None)
    ]


def test_forwarded_unparsable_amazon_mail_does_not_count():
    msg = load_mail("023_order_update_geliefert.eml")
    msg.replace_header("From", "Max Mustermann <max@example.org>")
    msg.replace_header("Subject", "Fwd: Geliefert: kaputt")
    msg.set_content("Bestellnr. unlesbar")
    result = parse_mail(msg)
    assert result.amazon is False
    assert result.updates == []


def test_unknown_amazon_mail_counts_as_amazon_without_updates():
    msg = load_mail("023_order_update_geliefert.eml")
    msg.replace_header("Subject", "Deine Meinung ist gefragt")
    msg.set_content("Bewerte deinen Kauf")
    result = parse_mail(msg)
    assert result.amazon is True
    assert result.updates == []


def test_generic_fallback():
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "Shop <shop@example.org>"
    msg["Subject"] = "Versandbestätigung"
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content("Ihre DHL-Sendungsnummer: JJD000012978217606560")
    result = parse_mail(msg)
    assert [(u.carrier, u.number, u.title) for u in result.updates] == [
        ("dhl", "JJD000012978217606560", None)
    ]


def test_legacy_amazon_with_other_subject_form_is_routed():
    result = parse_mail(load_mail("102_versandbestaetigung_ihre_amazon_de_beste.eml"))
    assert [(u.number, u.tracking_carrier) for u in result.updates] == [
        ("AMZ99900779704106459", "hermes")
    ]
    assert result.amazon is True


def _swap(msg: EmailMessage, start: str, end: str) -> EmailMessage:
    """``msg`` with ``start`` and ``end`` swapped in the subject and every text part."""

    def swap(text: str) -> str:
        return text.replace(start, "\0").replace(end, start).replace("\0", end)

    msg.replace_header("Subject", swap(msg["Subject"]))
    for part in msg.walk():
        if part.get_content_maintype() == "text":
            part.set_content(swap(part.get_content()), subtype=part.get_content_subtype())
    return msg


@pytest.mark.parametrize(
    ("name", "start", "end"),
    [
        ("049_noreply_ihre_amazon_sendung_kommt_heute_.eml", "13:10", "14:40"),
        ("181_dhl_kommt_frueher_als_geplant.eml", "13:10", "14:40"),
        ("111_no_reply_dein_paket_wird_in_wenigen_tage.eml", "08:00", "09:30"),
        ("168_hermes_deine_sendung_kommt_heute.eml", "12:05", "13:35"),
        ("161_dpd_de_zwischen_uhr_kommt_ihr_dpd_paket.eml", "14:06", "15:06"),
        ("176_dpd_at_kommt_zwischen_uhr.eml", "13:00", "14:00"),
        ("050_shipment_tracking_in_zustellung.eml", "18h", "22h"),
    ],
)
def test_a_reversed_window_keeps_status_and_day_but_no_window(name, start, end):
    """Every parser builds its window with ``window_at`` (its cases: test_mail_base)."""
    [read] = parse_mail(load_mail(name)).updates
    assert read.eta_from and read.eta_to
    [swapped] = parse_mail(_swap(load_mail(name), start, end)).updates
    assert (swapped.number, swapped.status, swapped.eta_date) == (
        read.number, read.status, read.eta_date
    )
    assert (swapped.eta_from, swapped.eta_to) == (None, None)

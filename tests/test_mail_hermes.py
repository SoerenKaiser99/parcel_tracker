from dataclasses import asdict
from datetime import date, datetime
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.hermes import HERMES_SENDER, parse_hermes_mail
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail

ON_THE_WAY = "103_noreply_ihre_hermes_sendung_ist_auf_dem_.eml"
ANNOUNCED = "105_noreply_information_zur_zustellung_an_de.eml"
DELIVERED = "099_noreply_dein_hermes_paket_von_amazon_eu_.eml"


def _msg(subject: str, body: str) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"Hermes Paketankündigung <{HERMES_SENDER}>"
    msg["Subject"] = subject
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content(body)
    return msg


def test_on_the_way_html_only_with_day_and_window():
    [u] = parse_hermes_mail(load_mail(ON_THE_WAY))
    assert (u.number, u.carrier) == ("H9999978276078000836", "hermes")
    assert u.status is ParcelStatus.IN_TRANSIT
    assert u.eta_date == date(2020, 4, 2)
    assert u.eta_from == datetime(2020, 4, 2, 14, 0, tzinfo=BERLIN)
    assert u.eta_to == datetime(2020, 4, 2, 18, 0, tzinfo=BERLIN)
    assert (u.shop, u.title) == (None, None)


def test_drop_off_information_is_an_announcement():
    # "wurde uns gerade angekündigt": delivery came a day and a half later.
    [u] = parse_hermes_mail(load_mail(ANNOUNCED))
    assert u.number == "H9999767129584220767"
    assert u.status is ParcelStatus.PRE_TRANSIT
    assert u.eta_date is None
    assert (u.shop, u.title) == ("amazon", "Amazon EU SARL")


def test_delivered_takes_shop_as_title():
    msg = load_mail(DELIVERED)
    [u] = parse_hermes_mail(msg)
    assert u.number == "H9999767129584220767"
    assert u.status is ParcelStatus.DELIVERED
    assert u.delivered_at == datetime(2023, 7, 18, 10, 2, 46, tzinfo=BERLIN)
    assert (u.shop, u.title) == ("amazon", "Amazon EU SARL")


def test_drop_off_text_is_never_taken():
    for name in (ANNOUNCED, DELIVERED):
        for update in parse_hermes_mail(load_mail(name)):
            assert "Garage" not in str(asdict(update))


def test_weekday_date_on_the_label_line_and_labelled_14_digits():
    msg = _msg(
        "Ihre Hermes Sendung ist auf dem Weg",
        "Deine Sendung von eBay-Händler ist unterwegs.\n"
        "Voraussichtliche Zustellung: Freitag, 02.10.\nSendungsnummer: 12345678901234\n",
    )
    [u] = parse_hermes_mail(msg)
    assert (u.number, u.status, u.eta_date) == (
        "12345678901234",
        ParcelStatus.IN_TRANSIT,
        date(2026, 10, 2),
    )
    assert u.eta_from is None
    assert u.shop == "ebay"


@pytest.mark.parametrize(
    "subject",
    [
        "Dein Hermes Paket von Amazon EU SARL konnte nicht zugestellt werden",
        "Dein Hermes Paket wurde nicht zugestellt",
        "Zustellversuch: Dein Hermes Paket wurde leider nicht zugestellt",
    ],
)
def test_failed_delivery_is_never_delivered(subject):
    # Documented choice: no status from such a mail; the Hermes API tells what happened.
    [u] = parse_hermes_mail(_msg(subject, "Sendungsnummer H9999999999999999901"))
    assert (u.number, u.status, u.delivered_at) == ("H9999999999999999901", None, None)


def test_delivered_needs_wurde_before_zugestellt():
    [u] = parse_hermes_mail(_msg("Paket zugestellt?", "Sendungsnummer H9999999999999999901"))
    assert u.status is None
    [u] = parse_hermes_mail(
        _msg("Dein Hermes Paket wurde zugestellt.", "Sendungsnummer H9999999999999999901")
    )
    assert u.status is ParcelStatus.DELIVERED


@pytest.mark.parametrize(
    ("sender", "title"),
    [
        ("Erika Musterfrau", None),
        ("Otto Beispiel", None),
        ("OTTO GmbH & Co KG", "OTTO GmbH & Co KG"),
        ("Zalando SE", "Zalando SE"),
        # nothing behind the legal form or the shop is taken
        ("OTTO GmbH & Co KG Erika Musterfrau", "OTTO GmbH & Co KG"),
        ("Zalando Versand Max Mustermann", "Zalando Versand"),
        ("Beispiel GmbH Erika Musterfrau", None),  # Hermes: only a shop we know
    ],
)
def test_only_a_known_shop_becomes_the_name(sender, title):
    [u] = parse_hermes_mail(
        _msg(
            f"Dein Hermes Paket von {sender} wurde an deinen WunschAblageort zugestellt.",
            "Sendungsnummer H9999999999999999901",
        )
    )
    assert u.status is ParcelStatus.DELIVERED
    assert (u.title, u.shop) == (title, None)


# ----- today's window, the delivery at the door, a new day -----
def test_comes_today_is_in_delivery_with_its_window():
    msg = load_mail("168_hermes_deine_sendung_kommt_heute.eml")
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (
        "H1000999999999990168", "hermes", ParcelStatus.OUT_FOR_DELIVERY,
    )
    assert u.eta_date == date(2025, 7, 11)
    assert (u.eta_from, u.eta_to) == (
        datetime(2025, 7, 11, 12, 5, tzinfo=BERLIN), datetime(2025, 7, 11, 13, 35, tzinfo=BERLIN),
    )
    assert (u.shop, u.postponed) == ("amazon", False)


def test_delivery_at_the_door_is_delivered():
    msg = load_mail("169_hermes_erfolgreiche_haustuerzustellung.eml")
    [u] = parse_mail(msg).updates
    assert (u.number, u.status) == ("H1000999999999990168", ParcelStatus.DELIVERED)
    assert u.delivered_at == msg["Date"].datetime
    assert (u.eta_date, u.eta_from) == (None, None)


def test_new_attempt_puts_the_parcel_back_on_its_way_for_the_new_day():
    [u] = parse_mail(load_mail("170_hermes_erneuter_zustellversuch.eml")).updates
    assert (u.number, u.status, u.postponed) == (
        "H1000999999999990170", ParcelStatus.IN_TRANSIT, True,
    )
    assert u.eta_date == date(2025, 8, 28)
    assert (u.eta_from, u.eta_to) == (
        datetime(2025, 8, 28, 10, 50, tzinfo=BERLIN), datetime(2025, 8, 28, 13, 50, tzinfo=BERLIN),
    )
    assert u.delivered_at is None


def test_a_later_day_without_a_window_is_taken_too():
    body = (
        "wir schaffen es heute leider nicht. Deine Sendung wird voraussichtlich Mittwoch "
        "zugestellt.\nNeuer Zustelltermin am\nMittwoch, 07.10.2026\n"
        "Sendungsnummer H1000999999999990901\n"
    )
    msg = _msg("Wichtige Information zur Zustellung deiner Hermes Sendung von Zalando", body)
    [u] = parse_mail(msg).updates
    assert (u.status, u.postponed, u.eta_date) == (ParcelStatus.IN_TRANSIT, True, date(2026, 10, 7))
    assert (u.eta_from, u.eta_to) == (None, None)


def test_failed_attempt_without_a_new_day_still_tells_no_status():
    body = ("deine Sendung konnte leider nicht zugestellt werden.\n"
            "Sendungsnummer H1000999999999990901\n")
    [u] = parse_mail(_msg("Erneuter Zustellversuch deiner Hermes Sendung", body)).updates
    assert (u.status, u.postponed, u.eta_date) == (None, False, None)


def test_unknown_subject_keeps_number_without_status():
    [u] = parse_hermes_mail(_msg("Neuigkeiten", "Sendungsnummer H9999999999999999901"))
    assert (u.number, u.status) == ("H9999999999999999901", None)


def test_without_number_gives_nothing():
    assert parse_hermes_mail(_msg("Ihre Hermes Sendung ist auf dem Weg", "ohne Nummer")) == []


def test_routing():
    result = parse_mail(load_mail(DELIVERED))
    assert [(u.carrier, u.status) for u in result.updates] == [
        ("hermes", ParcelStatus.DELIVERED)
    ]
    assert not result.amazon and not result.ignored


def test_shop_of_the_new_attempt_subject_ends_before_the_question():
    body = "Neuer Zustellversuch am\nDonnerstag, 08.10.2026\nSendungsnummer H1000999999999990901\n"
    msg = _msg("Erneuter Zustellversuch deiner Hermes Sendung von Zalando. Wo möchtest du sie "
               "empfangen?", body)
    [u] = parse_mail(msg).updates
    assert (u.title, u.status) == ("Zalando", ParcelStatus.IN_TRANSIT)


# ----- review: "kommt heute … nicht", a delivery that is not one at the door -----
def test_not_today_after_all_is_not_in_delivery():
    body = "Sendungsnummer H1000999999999990901\n"
    [u] = parse_mail(_msg("Deine Sendung kommt heute leider nicht mehr.", body)).updates
    assert (u.status, u.eta_date) == (None, None)


def test_only_the_delivery_at_the_door_is_delivered():
    body = "Sendungsnummer H1000999999999990901\n"
    [u] = parse_mail(_msg("Erfolgreiche PaketShopzustellung", body)).updates
    assert (u.status, u.delivered_at) == (None, None)

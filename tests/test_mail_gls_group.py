"""GLS mails of noreply@gls-group.eu and noreply@gls-rtt.com (seen from GLS Austria).

The three fixtures derive from anonymised tester submissions; days and times are asserted
relative to each mail's own Date header.
"""

from dataclasses import asdict
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.mail import known_sender_domain, parse_mail
from custom_components.parcel_tracker.mail.base import at, sent_at
from custom_components.parcel_tracker.mail.gls import (
    GLS_GROUP_SENDER,
    GLS_RTT_SENDER,
    parse_gls_group_mail,
)
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail

RTT = "115_gls_rtt_auf_dem_weg.eml"
UNDERWAY = "116_gls_group_unterwegs.eml"
DROPPED = "117_gls_group_abgestellt.eml"
NUMBERS = ["99999999901", "99999999902", "99999999903"]
COMPANY = "Beispiel Handels OHG"  # the mail says "Beispiel Handels OHG (AT-B2C)"
BODY = (
    "IHR PAKET WURDE ZUGESTELLT\nPAKETNUMMER\n99999999901\nZUSTELLUNG\nHeute 9:05 Uhr\n"
    "ABSENDER\n{company}\nZUSTELLADRESSE\nMusterstraße 1\n12345\nMusterstadt\n"
)


def _msg(subject: str, body: str, sender: str = GLS_GROUP_SENDER) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"GLS <{sender}>"
    msg["Subject"] = subject
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content(body)
    return msg


def test_senders_are_the_ones_the_testers_saw():
    assert (GLS_GROUP_SENDER, GLS_RTT_SENDER) == ("noreply@gls-group.eu", "noreply@gls-rtt.com")
    assert known_sender_domain(GLS_GROUP_SENDER) == "gls-group.eu"
    assert known_sender_domain(GLS_RTT_SENDER) == "gls-rtt.com"


def test_underway_mail_updates_every_parcel_it_names():
    updates = parse_mail(load_mail(UNDERWAY)).updates
    assert [u.number for u in updates] == NUMBERS
    for u in updates:
        assert (u.carrier, u.status, u.title, u.shop) == (
            "gls", ParcelStatus.IN_TRANSIT, COMPANY, None,
        )
        assert (u.eta_date, u.eta_from, u.eta_to, u.delivered_at) == (None,) * 4


def test_dropped_off_mail_is_delivered_at_the_named_time_of_the_mail_day():
    msg = load_mail(DROPPED)
    updates = parse_mail(msg).updates
    assert [u.number for u in updates] == NUMBERS
    for u in updates:
        assert (u.carrier, u.status, u.title) == ("gls", ParcelStatus.DELIVERED, COMPANY)
        # "ZUSTELLUNG / Heute 12:33 Uhr": today is the day the mail was sent
        assert u.delivered_at == at(sent_at(msg).date(), 12, 33)
        assert u.delivered_at <= sent_at(msg)


def test_real_time_tracking_mail_means_out_for_delivery_today():
    msg = load_mail(RTT)
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (
        "99999999902", "gls", ParcelStatus.OUT_FOR_DELIVERY,
    )
    assert u.eta_date == sent_at(msg).date()
    assert (u.title, u.eta_from, u.delivered_at) == (None, None, None)


@pytest.mark.parametrize("name", [RTT, UNDERWAY, DROPPED])
def test_address_recipient_and_reference_are_never_taken(name):
    dump = repr([asdict(u) for u in parse_mail(load_mail(name)).updates])
    for secret in ("Musterstraße", "Musterstadt", "12345", "Mustermann", "Max", "AT000000"):
        assert secret not in dump, secret


@pytest.mark.parametrize(
    ("subject", "status"),
    [
        ("Ihr Paket von Beispiel GmbH ist unterwegs", ParcelStatus.IN_TRANSIT),
        ("Ihr Paket von Beispiel GmbH wurde durch GLS zugestellt", ParcelStatus.DELIVERED),
        ("Ihr Paket von Beispiel GmbH wurde durch GLS am gewünschten Ort abgestellt",
         ParcelStatus.DELIVERED),
        ("Ihr Paket von Beispiel GmbH wurde durch GLS im PaketShop zugestellt",
         ParcelStatus.AWAITING_PICKUP),
        ("Ihr Paket von Beispiel GmbH wurde nicht zugestellt", None),
        ("Ihr Paket von Beispiel GmbH konnte nicht zugestellt werden", None),
        ("Ihr Paket von Beispiel GmbH wurde leider nicht am gewünschten Ort abgestellt", None),
        ("Zustellversuch: Ihr Paket von Beispiel GmbH", None),
        ("Neuigkeiten von GLS", None),
    ],
)
def test_status_comes_from_the_subject_and_negations_give_none(subject, status):
    [u] = parse_gls_group_mail(_msg(subject, BODY.format(company="Beispiel GmbH")))
    assert (u.number, u.status) == ("99999999901", status)
    if status is ParcelStatus.DELIVERED:
        assert u.delivered_at == at(sent_at(_msg(subject, "")).date(), 9, 5)
    else:
        assert u.delivered_at is None


def test_delivery_without_a_time_counts_from_the_mail():
    body = BODY.format(company="Beispiel GmbH").replace("Heute 9:05 Uhr\n", "")
    msg = _msg("Ihr Paket von Beispiel GmbH wurde durch GLS zugestellt", body)
    [u] = parse_gls_group_mail(msg)
    assert u.delivered_at == sent_at(msg)


@pytest.mark.parametrize(
    ("company", "title", "shop"),
    [
        ("Beispiel GmbH", "Beispiel GmbH", None),
        ("Amazon EU S.a.r.l.", "Amazon EU S.a.r.l.", "amazon"),
        ("Erika Beispiel", None, None),  # a private sender never becomes the name
        # the line may go on with a branch code and contact persons: the name ends before them
        ("Beispiel Handels OHG (AT-B2C) Erika Musterfrau Max Mustermann",
         "Beispiel Handels OHG", None),
        ("GLS Austria GmbH", None, None),  # a carrier is no shop
    ],
)
def test_sender_name_only_through_the_naming_gate(company, title, shop):
    subject = f"Ihr Paket von {company} ist unterwegs"
    [u] = parse_gls_group_mail(_msg(subject, BODY.format(company=company)))
    assert (u.title, u.shop) == (title, shop)


def test_rtt_mail_with_another_subject_only_names_the_parcel():
    body = "Ihr Paket hat sich verspätet.\nSendungsnummer: 99999999902\n"
    [u] = parse_gls_group_mail(_msg("Information zu Ihrem Paket", body, GLS_RTT_SENDER))
    assert (u.number, u.status, u.eta_date) == ("99999999902", None, None)


def test_mail_without_a_number_gives_nothing():
    assert parse_gls_group_mail(_msg("Ihr Paket von Beispiel GmbH ist unterwegs", "Hallo")) == []


def test_other_numbers_are_not_parcels():
    body = BODY.format(company="Beispiel GmbH") + (
        "Ihr Paket 99999999901 (Referenz: 88888888801) ist da.\nKundennummer 77777777701\n"
    )
    updates = parse_gls_group_mail(_msg("Ihr Paket von Beispiel GmbH ist unterwegs", body))
    assert [u.number for u in updates] == ["99999999901"]


# ----- v0.3.19 (issue 8): 11 digits plus a check digit -----
def test_twelve_digits_are_stored_without_the_check_digit():
    body = (
        "IHR PAKET IST UNTERWEGS\nPAKETNUMMER\n999999999017\n"
        "Dies betrifft ebenso das Paket/die Pakete 999999999025, 99999999903 und 999999999017.\n"
    )
    updates = parse_gls_group_mail(_msg("Ihr Paket von Beispiel GmbH ist unterwegs", body))
    assert [u.number for u in updates] == NUMBERS
    assert {u.status for u in updates} == {ParcelStatus.IN_TRANSIT}


def test_number_of_the_tracking_link_counts_when_no_label_names_one():
    body = "Ihr Paket ist unterwegs.\nhttps://gls-group.eu/track/999999999017\n"
    [u] = parse_gls_group_mail(_msg("Ihr Paket von Beispiel GmbH ist unterwegs", body))
    assert (u.number, u.status) == ("99999999901", ParcelStatus.IN_TRANSIT)
    longer = "https://gls-group.eu/track/9999999990171\n"
    assert parse_gls_group_mail(_msg("Ihr Paket von Beispiel GmbH ist unterwegs", longer)) == []

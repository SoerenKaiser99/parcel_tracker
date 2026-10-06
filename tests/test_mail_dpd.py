"""DPD Austria mails (no_reply@dpd.at): the mail itself tells the status. DPD Germany's
announcement (noreply@service.dpd.de) names the shipper and an estimate in working days.

The fixtures derive from anonymised tester submissions; times and days are asserted relative
to the mail's own Date header.
"""

import re
from dataclasses import asdict
from datetime import date, datetime
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import known_sender_domain, parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import add_workdays, at, sent_at
from custom_components.parcel_tracker.mail.dpd import (
    DPD_AT_SENDER,
    parse_dpd_de_mail,
    parse_dpd_mail,
)
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail

NEW = "114_dpd_at_neues_paket.eml"
DROPPED = "119_dpd_at_abgestellt.eml"
NUMBER = "09999999999901"


def _msg(subject: str, body: str, sender: str = DPD_AT_SENDER) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"DPD Versandinfo <{sender}>"
    msg["Subject"] = subject
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content(body)
    return msg


def test_sender():
    assert DPD_AT_SENDER == "no_reply@dpd.at"
    assert known_sender_domain(DPD_AT_SENDER) == "dpd.at"


def test_new_parcel_mail_creates_the_parcel():
    [u] = parse_mail(load_mail(NEW)).updates
    assert (u.number, u.carrier, u.status) == (NUMBER, "dpd", ParcelStatus.PRE_TRANSIT)
    assert (u.title, u.shop, u.eta_date, u.delivered_at) == (None,) * 4


def test_dropped_off_mail_is_delivered_at_the_named_time_of_the_mail_day():
    msg = load_mail(DROPPED)
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (
        "09999999999902", "dpd", ParcelStatus.DELIVERED,
    )
    assert u.delivered_at == at(sent_at(msg).date(), 16, 52)
    assert u.title is None


@pytest.mark.parametrize("name", [NEW, DROPPED])
def test_drop_off_place_and_recipient_are_never_taken(name):
    dump = repr([asdict(u) for u in parse_mail(load_mail(name)).updates])
    for secret in ("Abstellort", "Mustermann", "Max", "Leopoldsdorf"):
        assert secret not in dump, secret


@pytest.mark.parametrize(
    ("sentence", "status", "time"),
    [
        ("wurde heute um 9:07 Uhr an deinem gewünschten Abstellort hinterlegt.",
         ParcelStatus.DELIVERED, (9, 7)),
        ("wurde heute um 14:30 Uhr zugestellt.", ParcelStatus.DELIVERED, (14, 30)),
        ("wurde zugestellt.", ParcelStatus.DELIVERED, None),
        ("wurde heute um 14:30 Uhr nicht zugestellt.", None, None),
        ("konnte heute um 14:30 Uhr nicht zugestellt werden.", None, None),
        ("ist auf dem Weg zu dir.", None, None),
    ],
)
def test_news_mail_reads_only_a_delivery(sentence, status, time):
    msg = _msg("Neuigkeiten zu deinem Paket", f"Hallo,\ndein Paket {NUMBER} {sentence}\n")
    [u] = parse_dpd_mail(msg)
    assert (u.number, u.carrier, u.status) == (NUMBER, "dpd", status)
    if status is ParcelStatus.DELIVERED:
        assert u.delivered_at == (at(sent_at(msg).date(), *time) if time else sent_at(msg))
    else:
        assert u.delivered_at is None


def test_mail_without_a_number_gives_nothing():
    assert parse_dpd_mail(_msg("Neuigkeiten zu deinem Paket", "Hallo")) == []
    assert parse_mail(_msg("Neuigkeiten zu deinem Paket", "Hallo")).updates == []


def test_german_dpd_mail_still_only_creates_the_parcel():
    """Germany keeps its way: the mail names the number, the live lookup tells the status."""
    msg = _msg(
        "Ihr Paket kommt heute",
        f"Ihr Paket {NUMBER} wurde heute um 10:00 Uhr zugestellt.",
        "noreply@service.dpd.de",
    )
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (NUMBER, "dpd", None)


def test_mail_status_is_applied_and_delivered_is_never_moved_back():
    parcels: dict = {}
    new, dropped = load_mail(NEW), load_mail(DROPPED)
    [created] = parse_mail(new).updates
    now = sent_at(new)
    change = apply_update(parcels, created, now)
    assert change.created and parcels[NUMBER].status is ParcelStatus.PRE_TRANSIT
    [delivered] = parse_mail(dropped).updates
    delivered.number = NUMBER  # the same parcel
    apply_update(parcels, delivered, sent_at(dropped))
    parcel = parcels[NUMBER]
    assert parcel.status is ParcelStatus.DELIVERED
    assert parcel.result.delivered_at == at(sent_at(dropped).date(), 16, 52)
    # the first mail again (a late copy): the parcel stays delivered
    assert apply_update(parcels, created, sent_at(dropped)) is None
    assert parcel.status is ParcelStatus.DELIVERED


# ----- v0.3.15 review: only a real delivery is "delivered" -----
@pytest.mark.parametrize(
    ("sentence", "status"),
    [
        # delivered: handed over, or left at the place the recipient chose
        ("wurde heute um 9:07 Uhr an deinem gewünschten Abstellort hinterlegt.",
         ParcelStatus.DELIVERED),
        ("wurde heute um 9:07 Uhr an deinem Wunschort hinterlegt.", ParcelStatus.DELIVERED),
        ("wurde heute um 9:07 Uhr am gewünschten Ort hinterlegt.", ParcelStatus.DELIVERED),
        ("wurde heute um 9:07 Uhr am Abstellort abgestellt.", ParcelStatus.DELIVERED),
        ("wurde heute um 9:07 Uhr zugestellt.", ParcelStatus.DELIVERED),
        # waiting in a shop
        ("wurde heute um 9:07 Uhr im Pickup Paketshop hinterlegt.",
         ParcelStatus.AWAITING_PICKUP),
        ("wurde heute um 9:07 Uhr in einem Paketshop zugestellt.", ParcelStatus.AWAITING_PICKUP),
        ("ist im Pickup Paketshop abholbereit.", ParcelStatus.AWAITING_PICKUP),
        ("liegt abholbereit in deinem Pickup Point.", ParcelStatus.AWAITING_PICKUP),
        ("liegt in der Abholstation zur Abholung bereit.", ParcelStatus.AWAITING_PICKUP),
        ("liegt im Pickup Paketshop für dich bereit.", ParcelStatus.AWAITING_PICKUP),
        # handed to a neighbour: delivered (who it is is never read)
        ("wurde heute um 9:07 Uhr beim Nachbarn abgegeben.", ParcelStatus.DELIVERED),
        ("wurde heute um 9:07 Uhr bei deiner Nachbarin Erika Musterfrau abgegeben.",
         ParcelStatus.DELIVERED),
        # a shop is named, but the parcel does not wait there (yet)
        ("ist auf dem Weg in den Pickup Paketshop.", None),
        ("wurde in einen Pickup Paketshop umgeleitet.", None),
        ("wurde heute zur Abholstation umgeleitet.", None),
        ("ist abholbereit.", None),
        ("wurde heute um 9:07 Uhr abgegeben.", None),
        # no delivery: the mail tells no status, the parcel is kept
        ("wurde heute an DPD übergeben.", None),
        ("wurde heute um 9:07 Uhr im Depot abgegeben und wird morgen zugestellt.", None),
        ("wurde heute um 9:07 Uhr im Depot hinterlegt.", None),
        ("wurde heute um 9:07 Uhr hinterlegt.", None),
        ("wird morgen zugestellt.", None),
        ("wird morgen an deinem gewünschten Abstellort hinterlegt.", None),
        ("wird morgen in einen Pickup Paketshop gebracht.", None),
        ("wurde heute nicht an deinem gewünschten Abstellort hinterlegt.", None),
        ("konnte nicht im Pickup Paketshop hinterlegt werden.", None),
        ("wurde heute um 9:07 Uhr an den Absender zurückgeschickt.", None),
    ],
)
def test_news_mail_phrases(sentence, status):
    msg = _msg("Neuigkeiten zu deinem Paket", f"Hallo,\ndein Paket {NUMBER} {sentence}\n")
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (NUMBER, "dpd", status)
    if status is ParcelStatus.DELIVERED:
        assert u.delivered_at == at(sent_at(msg).date(), 9, 7)
    else:
        assert u.delivered_at is None
    assert (u.title, u.eta_date) == (None, None)


def test_the_place_word_of_another_sentence_does_not_count():
    body = (
        f"Hallo,\ndein Paket {NUMBER} wurde heute um 9:07 Uhr hinterlegt. "
        "Du kannst jederzeit einen Abstellort festlegen.\n"
    )
    [u] = parse_dpd_mail(_msg("Neuigkeiten zu deinem Paket", body))
    assert u.status is None


@pytest.mark.parametrize("local", ["newsletter", "service", "noreply", "info"])
def test_other_senders_at_dpd_at_only_name_the_parcel(local):
    """Only no_reply@dpd.at is the notification sender whose sentences are read."""
    for subject, body in (
        ("Neuigkeiten zu deinem Paket", f"dein Paket {NUMBER} wurde heute um 9:07 Uhr zugestellt."),
        ("Ein DPD Paket für dich", f"Paketnummer {NUMBER}"),
    ):
        [u] = parse_mail(_msg(subject, body, f"{local}@dpd.at")).updates
        assert (u.number, u.carrier, u.status, u.delivered_at, u.title) == (
            NUMBER, "dpd", None, None, None,
        )


# ----- v0.3.18: the announcement of DPD Germany ("Bald ist Ihr DPD Paket da", issue 6) -----
DE_SENDER = "noreply@service.dpd.de"
ANNOUNCED = "122_dpd_de_weitergeleitet_bald_da.eml"
ANNOUNCED_ONE_LINE = "123_dpd_de_weitergeleitet_bald_da.eml"
SHIPPER = "Beispiel Autoteile GmbH"


def _announcement(shipper: str = SHIPPER, estimate: str = "in 1-2 Werktagen") -> EmailMessage:
    """The mail as DPD sends it (invented values); its Date is a Wednesday."""
    body = (
        "Guten Tag,\n\n"
        f"Ihre Sendung stellen wir {estimate} zu.\n\n"
        "Versender & Paketnummer:\n\n"
        f"{shipper}\n \n<https://my.dpd.de/…> {NUMBER}\n\n"
        "Empfänger:\n\nMax |\nMax | Max Mustermann\n\n"
        "Weitere Informationen zu Ihrem Paket erhalten Sie von uns am Tag der Zustellung.\n"
    )
    return _msg("Bald ist Ihr DPD Paket da", body, DE_SENDER)


@pytest.mark.parametrize(
    ("start", "count", "expected"),
    [
        (date(2026, 9, 30), 1, date(2026, 10, 1)),  # Wednesday -> Thursday
        (date(2026, 10, 2), 1, date(2026, 10, 3)),  # Friday -> Saturday: a working day
        (date(2026, 10, 2), 2, date(2026, 10, 5)),  # Friday -> Monday: Sunday is skipped
        (date(2026, 10, 3), 1, date(2026, 10, 5)),  # Saturday -> Monday
        (date(2026, 10, 4), 1, date(2026, 10, 5)),  # Sunday -> Monday
        (date(2026, 9, 28), 6, date(2026, 10, 5)),  # a whole week of working days
        (date(2026, 9, 30), 0, date(2026, 9, 30)),
    ],
)
def test_add_workdays_counts_monday_to_saturday(start, count, expected):
    assert add_workdays(start, count) == expected


@pytest.mark.parametrize(
    ("name", "number", "original", "first", "last"),
    [
        # sent on a Friday: Saturday counts, Sunday does not
        (ANNOUNCED, "09999999999903", "2026-08-14T16:29:00", date(2026, 8, 15),
         date(2026, 8, 17)),
        (ANNOUNCED_ONE_LINE, "09999999999904", "2026-09-21T14:33:00", date(2026, 9, 22),
         date(2026, 9, 23)),
    ],
)
def test_forwarded_announcement_gives_shipper_and_estimate(name, number, original, first, last):
    """Forwarded by hand: the days count from the original mail, never from the forward."""
    msg = load_mail(name)
    assert str(msg["Subject"]).startswith("WG: ") and "dpd.de" not in str(msg["From"])
    sent = datetime.fromisoformat(original).replace(tzinfo=BERLIN)
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (number, "dpd", ParcelStatus.PRE_TRANSIT)
    assert (u.title, u.shop) == (SHIPPER, None)
    assert u.sent_at == sent and sent < sent_at(msg)
    assert (u.eta_date, u.eta_latest) == (first, last)
    assert (u.eta_from, u.eta_to, u.delivered_at, u.delivery_code) == (None,) * 4


@pytest.mark.parametrize("name", [ANNOUNCED, ANNOUNCED_ONE_LINE])
def test_announcement_never_takes_the_recipient(name):
    dump = repr([asdict(u) for u in parse_mail(load_mail(name)).updates])
    for secret in ("Mustermann", "Max", "Musterstadt", "Musterstraße", "Empfänger", "example"):
        assert secret not in dump, secret


@pytest.mark.parametrize("name", [ANNOUNCED, ANNOUNCED_ONE_LINE])
def test_announcement_fixtures_hold_only_invented_values(name):
    raw = (load_mail(name).as_string()).lower()
    assert "x-fixture: derived from an anonymised tester submission" in raw
    for word in ("geschäftsführung", "aufsichtsrat", "registergericht", "hrb"):
        assert word not in raw, word
    assert set(re.findall(r"(?<!\d)\d{14}(?!\d)", raw)) <= {"09999999999903", "09999999999904"}
    assert set(re.findall(r"[\w.+-]+@[\w.-]+\w", raw)) <= {
        "max@example.org", "noreply@service.dpd.de", "fixture-122@example.org",
        "fixture-123@example.org",
    }


def test_announcement_sent_directly_reads_the_same():
    msg = _announcement()
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status, u.title) == (
        NUMBER, "dpd", ParcelStatus.PRE_TRANSIT, SHIPPER,
    )
    assert (u.eta_date, u.eta_latest) == (date(2026, 10, 1), date(2026, 10, 2))
    assert parse_dpd_de_mail(msg) == [u]


@pytest.mark.parametrize(
    ("estimate", "first", "last"),
    [
        ("in 1-2 Werktagen", date(2026, 10, 1), date(2026, 10, 2)),
        ("in 2-3 Werktagen", date(2026, 10, 2), date(2026, 10, 3)),
        ("in 2 – 4 Werktagen", date(2026, 10, 2), date(2026, 10, 5)),
        ("in 1 bis 2 Werktagen", date(2026, 10, 1), date(2026, 10, 2)),
        ("in 3 Werktagen", date(2026, 10, 3), None),
        ("in 1 Werktag", date(2026, 10, 1), None),
        ("in 2-2 Werktagen", date(2026, 10, 2), None),
        # nothing a day can be told from
        ("in 0 Werktagen", None, None),
        ("in 3-1 Werktagen", None, None),
        ("in 40 Werktagen", None, None),
        ("in den nächsten Tagen", None, None),
        ("in Kürze", None, None),
    ],
)
def test_estimate_in_working_days(estimate, first, last):
    [u] = parse_mail(_announcement(estimate=estimate)).updates
    assert (u.eta_date, u.eta_latest) == (first, last)
    # Only a mail with an estimate is an announcement; without one the lookup tells the status.
    assert u.status is (ParcelStatus.PRE_TRANSIT if first else None)
    assert (u.number, u.title) == (NUMBER, SHIPPER)


def test_a_sentence_that_is_no_delivery_estimate_gives_no_day():
    body = (
        f"Ihr Paket {NUMBER} konnte nicht zugestellt werden.\n"
        "Wir melden uns in 1-2 Werktagen bei Ihnen. Die Rücksendung wird nicht in 3 "
        "Werktagen zugestellt.\n"
    )
    [u] = parse_mail(_msg("Neuigkeiten zu Ihrem Paket", body, DE_SENDER)).updates
    assert (u.number, u.status, u.title) == (NUMBER, None, None)
    assert (u.eta_date, u.eta_latest) == (None, None)


@pytest.mark.parametrize(
    ("shipper", "title", "shop"),
    [
        ("Beispiel Autoteile GmbH", "Beispiel Autoteile GmbH", None),
        ("Beispiel Handels\nGmbH & Co. KG", "Beispiel Handels GmbH & Co. KG", None),
        ("Beispiel Handels OHG\nErika Musterfrau", "Beispiel Handels OHG", None),
        ("Zalando", "Zalando", None),
        ("Amazon EU S.a.r.l.", "Amazon EU S.a.r.l.", "amazon"),
        # a private sender, a carrier, nothing at all: no name
        ("Erika Musterfrau", None, None),
        ("Erika Musterfrau\nMusterstraße 1", None, None),
        ("DPD Deutschland GmbH", None, None),
        ("", None, None),
    ],
)
def test_shipper_names_the_parcel_only_through_the_naming_gate(shipper, title, shop):
    [u] = parse_mail(_announcement(shipper=shipper)).updates
    assert (u.number, u.title, u.shop) == (NUMBER, title, shop)
    assert u.eta_date == date(2026, 10, 1)
    assert "Musterfrau" not in repr(asdict(u))


def test_shipper_block_without_estimate_names_the_parcel_but_tells_no_status():
    body = f"Versender & Paketnummer:\n\n{SHIPPER}\n{NUMBER}\n\nEmpfänger:\nMax Mustermann\n"
    [u] = parse_mail(_msg("Ihr Paket kommt heute", body, DE_SENDER)).updates
    assert (u.number, u.carrier, u.status, u.title) == (NUMBER, "dpd", None, SHIPPER)
    assert (u.eta_date, u.eta_latest) == (None, None)


def test_estimate_with_several_numbers_belongs_to_the_labelled_one():
    other = "09999999999905"
    msg = _announcement()
    msg.set_content(f"Ihre frühere Sendung {other}.\n{msg.get_content()}")
    first, second = parse_mail(msg).updates
    assert (first.number, first.status, first.title, first.eta_date) == (other, None, None, None)
    assert (second.number, second.status, second.title) == (
        NUMBER, ParcelStatus.PRE_TRANSIT, SHIPPER,
    )
    assert second.eta_date == date(2026, 10, 1)


def test_announcement_text_from_another_sender_is_not_read():
    """Only DPD's own mails are read this way: any other sender just names the parcel."""
    msg = _announcement()
    del msg["From"]
    msg["From"] = "Beispielshop <info@beispielshop.example>"
    msg.set_content(f"{msg.get_content()}\nPaketnummer: {NUMBER}\n")
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.title, u.eta_date) == (NUMBER, None, None, None)


def test_announcement_creates_the_parcel_with_name_and_window():
    parcels: dict = {}
    msg = load_mail(ANNOUNCED)
    [update] = parse_mail(msg).updates
    change = apply_update(parcels, update, sent_at(msg))
    parcel = parcels["09999999999903"]
    assert change.created and parcel.name == SHIPPER
    assert parcel.status is ParcelStatus.PRE_TRANSIT
    assert (parcel.result.eta_date, parcel.result.eta_latest) == (
        date(2026, 8, 15), date(2026, 8, 17),
    )

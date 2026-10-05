"""DPD Austria mails (no_reply@dpd.at): the mail itself tells the status.

The two fixtures derive from anonymised tester submissions; the time is asserted relative
to the mail's own Date header.
"""

from dataclasses import asdict
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.mail import known_sender_domain, parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import at, sent_at
from custom_components.parcel_tracker.mail.dpd import DPD_AT_SENDER, parse_dpd_mail
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

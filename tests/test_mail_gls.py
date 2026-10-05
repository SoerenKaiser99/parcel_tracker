"""GLS mails: the five anonymised mails, a shop mail without number and synthetic variants."""

from dataclasses import asdict
from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.base import sent_at
from custom_components.parcel_tracker.mail.gls import GLS_SENDER, parse_gls_mail
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail

SHOP_MAIL = "107_shop_versand_ihrer_bestellung_beispiel_g.eml"
TODAY_FIRST = "108_no_reply_dein_gls_paket_kommt_heute.eml"
TODAY_SECOND = "109_no_reply_dein_gls_paket_kommt_heute.eml"
DROP_OFF = "110_no_reply_dein_paket_wird_an_dem_gew_nsch.eml"
SOON = "111_no_reply_dein_paket_wird_in_wenigen_tage.eml"
DELIVERED = "112_no_reply_dein_paket_wurde_an_deinem_wuns.eml"
GLS_MAILS = (TODAY_FIRST, TODAY_SECOND, DROP_OFF, SOON, DELIVERED)
FIRST, SECOND = "99999999901", "99999999902"


def _msg(subject: str, body: str, sender: str = f"GLS Paket <{GLS_SENDER}>") -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content(body)
    return msg


def _delivered(subject: str, body: str = "") -> ParcelStatus | None:
    [u] = parse_gls_mail(_msg(subject, f"{body}\n*Sendungsnummer*\n{FIRST}\n"))
    return u.status


def test_in_a_few_days_gives_day_and_window():
    msg = load_mail(SOON)
    [u] = parse_gls_mail(msg)
    assert (u.number, u.carrier, u.status) == (SECOND, "gls", ParcelStatus.IN_TRANSIT)
    # The mail announces the next day with a window of that day (year from the mail date).
    assert u.eta_date == sent_at(msg).date() + timedelta(days=1)
    assert (u.eta_from.date(), u.eta_to.date()) == (u.eta_date, u.eta_date)
    assert u.eta_from < u.eta_to and u.eta_from.tzinfo is BERLIN
    assert (u.title, u.shop) == ("Beispiel GmbH", None)


def test_day_and_window_are_read_exactly():
    body = (
        "dein Paket von\n\n*Beispiel GmbH*\n\nwurde GLS übergeben.\n\n"
        "----------------------------\n*Voraussichtliche Lieferung*\n\n"
        "----------------------------\n\n-------------------\nFreitag, 2. Oktober\n"
        "zwischen 10:15 und 11:45 Uhr\n-------------------\n\n"
        f"*Sendungsnummer*\n {FIRST} ( https://example.org/… )\n"
    )
    [u] = parse_gls_mail(_msg("📦 Dein Paket wird in wenigen Tagen zugestellt", body))
    assert u.eta_date == date(2026, 10, 2)
    assert u.eta_from == datetime(2026, 10, 2, 10, 15, tzinfo=BERLIN)
    assert u.eta_to == datetime(2026, 10, 2, 11, 45, tzinfo=BERLIN)
    no_window = body.replace("zwischen 10:15 und 11:45 Uhr\n", "")
    [u] = parse_gls_mail(_msg("Dein Paket wird in wenigen Tagen zugestellt", no_window))
    assert (u.eta_date, u.eta_from, u.eta_to) == (date(2026, 10, 2), None, None)
    no_day = body.replace("Freitag, 2. Oktober\n", "")
    [u] = parse_gls_mail(_msg("Dein Paket wird in wenigen Tagen zugestellt", no_day))
    assert (u.status, u.eta_date, u.eta_from) == (ParcelStatus.IN_TRANSIT, None, None)


def test_comes_today_is_out_for_delivery_on_the_mail_day():
    msg = load_mail(TODAY_FIRST)
    [first] = parse_gls_mail(msg)
    assert (first.number, first.status) == (FIRST, ParcelStatus.OUT_FOR_DELIVERY)
    assert (first.eta_date, first.eta_from, first.eta_to) == (sent_at(msg).date(), None, None)
    assert first.title == "Beispiel GmbH"
    msg = load_mail(TODAY_SECOND)
    [second] = parse_gls_mail(msg)
    assert (second.number, second.eta_date) == (SECOND, sent_at(msg).date())


def test_drop_off_notice_only_announces_the_parcel():
    [u] = parse_gls_mail(load_mail(DROP_OFF))
    assert (u.number, u.status) == (FIRST, ParcelStatus.PRE_TRANSIT)
    assert (u.eta_date, u.delivered_at, u.title) == (None, None, "Beispiel GmbH")


def test_delivered_at_the_drop_off_place_despite_the_parcelshop_sentence_in_the_text():
    msg = load_mail(DELIVERED)
    assert "PaketShop geliefert und liegt für dich zur Abholung bereit" in (
        msg.get_body(("plain",)).get_content()
    )
    [u] = parse_gls_mail(msg)
    assert (u.number, u.status) == (FIRST, ParcelStatus.DELIVERED)
    assert u.delivered_at == sent_at(msg)


def test_private_values_are_never_taken():
    for name in GLS_MAILS:
        for update in parse_gls_mail(load_mail(name)):
            dump = str(asdict(update))
            for secret in ("Garage", "Ablageort", "Musterstraße", "Musterstadt", "Mustermann",
                           "+49", "REF-0001", "Beispielweg"):
                assert secret not in dump, (name, secret)


def test_shop_mail_without_parcel_number_is_not_recognised():
    msg = load_mail(SHOP_MAIL)
    assert "GLS" in msg.get_body(("plain",)).get_content()
    assert parse_gls_mail(msg) == []
    result = parse_mail(msg)
    assert result.updates == [] and not result.ignored and not result.amazon


def test_routing_of_all_gls_mails():
    for name in GLS_MAILS:
        result = parse_mail(load_mail(name))
        assert [u.carrier for u in result.updates] == ["gls"], name
        assert not result.amazon and not result.ignored


@pytest.mark.parametrize(
    ("subject", "body", "status"),
    [
        ("Dein Paket wurde zugestellt", "", ParcelStatus.DELIVERED),
        ("📦 Dein Paket wurde an deinen Nachbarn übergeben", "", ParcelStatus.DELIVERED),
        ("Dein Paket wurde an einen PaketShop geliefert", "", ParcelStatus.AWAITING_PICKUP),
        ("Dein Paket liegt zur Abholung bereit", "", ParcelStatus.AWAITING_PICKUP),
        (
            "Dein Paket wurde zugestellt",
            "wurde an einen GLS PaketShop geliefert und liegt für dich zur Abholung bereit.",
            ParcelStatus.AWAITING_PICKUP,
        ),
        (
            "Dein Paket wurde zugestellt",
            "wurde an einen GLS PaketShop geliefert und liegt für dich zur Abholung bereit.\n"
            "wurde erfolgreich zugestellt. Bis zum nächsten Mal.",
            ParcelStatus.DELIVERED,
        ),
        ("Dein Paket konnte nicht zugestellt werden", "", None),
        ("Dein Paket wurde nicht zugestellt", "", None),
        ("Neuigkeiten zu deinem Paket", "", None),
        # "übergeben" alone is the shop handing the parcel to GLS: only a neighbour delivers.
        ("Dein Paket wurde GLS übergeben", "", None),
        ("Dein Paket wurde an GLS übergeben", "", None),
        ("Dein Paket wurde bei einem Nachbarn übergeben", "", ParcelStatus.DELIVERED),
        # The negation wins, also with words in between and before "kommt heute".
        ("Dein Paket wurde nicht wie geplant zugestellt", "", None),
        ("Dein Paket wurde heute leider nicht zugestellt", "", None),
        ("Dein GLS Paket kommt heute nicht: neuer Zustellversuch morgen", "", None),
        ("Dein GLS Paket kommt heute doch nicht, es konnte nicht zugestellt werden", "", None),
        ("Dein Paket wurde nicht geliefert", "", None),
        ("Dein Paket wurde leider nicht an den Nachbarn übergeben", "", None),
        # "nicht" far from the verb is no negation of it.
        (
            "Nicht verpassen: Dein Paket wird in wenigen Tagen zugestellt",
            "",
            ParcelStatus.IN_TRANSIT,
        ),
    ],
)
def test_delivery_variants(subject, body, status):
    assert _delivered(subject, body) is status


@pytest.mark.parametrize(
    ("sender", "title"),
    [
        ("Beispiel GmbH", "Beispiel GmbH"),
        ("Muster & Söhne KG", "Muster & Söhne KG"),
        ("Hofladen Muster e.K.", "Hofladen Muster e.K."),
        ("Voorbeeld B.V.", "Voorbeeld B.V."),
        ("Exemple S.à r.l.", "Exemple S.à r.l."),
        ("Sample Ltd", "Sample Ltd"),
        ("Zalando", "Zalando"),  # known shop without a legal form
        ("Erika Musterfrau", None),
        ("Otto Beispiel", None),
        ("Tag und Nacht Versand", None),  # "ag" inside a word is no legal form
        ("X" * 70 + " GmbH", "X" * 59 + "…"),
        # nothing behind the legal form is taken
        ("Beispiel Handels OHG (AT-B2C) Erika Musterfrau", "Beispiel Handels OHG"),
        ("Beispiel GmbH Max Mustermann", "Beispiel GmbH"),
    ],
)
def test_only_a_shop_or_company_becomes_the_name(sender, title):
    body = f"dein Paket von\n\n*{sender}*\n\nwurde GLS übergeben.\n*Sendungsnummer*\n {FIRST} ( x )"
    [u] = parse_gls_mail(_msg("Dein Paket wird in wenigen Tagen zugestellt", body))
    assert (u.title, u.shop, u.eta_date) == (title, None, None)


def test_sender_block_and_amazon_as_shop():
    body = f"*Paketnummer*\n{FIRST} ( x )\n\n** *Versender*\nAmazon EU SARL\nBeispielweg 2 ,\n"
    [u] = parse_gls_mail(_msg("📦 Dein GLS Paket kommt heute!", body))
    assert (u.title, u.shop) == ("Amazon EU SARL", "amazon")
    assert u.eta_date == date(2026, 9, 30)


def test_forwarded_gls_mail_is_recognised_but_never_named():
    original = load_mail(SOON)
    quoted = "\n".join(
        f"> {line}" for line in original.get_body(("plain",)).get_content().splitlines()
    )
    msg = _msg(
        "WG: 📦 Dein Paket wird in wenigen Tagen zugestellt",
        quoted,
        "Max Mustermann <max@example.org>",
    )
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (SECOND, "gls", ParcelStatus.IN_TRANSIT)
    # Day and month from the mail, the year from the forwarding date.
    announced = sent_at(original).date() + timedelta(days=1)
    assert u.eta_date == date(2026, announced.month, announced.day)
    assert u.title is None


def test_forwarded_mail_with_another_subject_is_not_a_gls_mail():
    body = f"GLS\n*Sendungsnummer*\n{FIRST}\n"
    msg = _msg("WG: Rechnung", body, "Max Mustermann <max@example.org>")
    assert parse_gls_mail(msg) == []
    assert parse_mail(msg).updates == []


def test_forwarded_mail_needs_the_word_gls_not_just_the_letters():
    subject = "WG: Dein Paket wurde zugestellt"
    sender = "Max Mustermann <max@example.org>"
    for body in ("Gruß aus Englschalking", "Ringlstetter Paketdienst, Abteilung Englschalking"):
        msg = _msg(subject, f"{body}\n*Sendungsnummer*\n{FIRST}\n", sender)
        assert parse_gls_mail(msg) == [], body
    for word in ("GLS", "gls", "Dein GLS-Paket", "(Gls)"):
        msg = _msg(subject, f"{word}\n*Sendungsnummer*\n{FIRST}\n", sender)
        [u] = parse_gls_mail(msg)
        assert (u.number, u.status) == (FIRST, ParcelStatus.DELIVERED), word


def test_eleven_digits_only_after_a_label():
    assert parse_gls_mail(_msg("📦 Dein GLS Paket kommt heute!", f"Nummer {FIRST}")) == []
    assert parse_gls_mail(
        _msg("📦 Dein GLS Paket kommt heute!", "Sendungsnummer\n999999999012")  # 12 digits
    ) == []
    [u] = parse_gls_mail(_msg("Neuigkeiten", f"Paketnummer: {FIRST}"))
    assert (u.number, u.status) == (FIRST, None)

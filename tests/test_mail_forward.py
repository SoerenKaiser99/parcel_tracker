"""v0.3.16: a mail forwarded by hand is read like its original (invented mails only)."""

import email
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from html import escape

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import forwarded_original, parse_mail
from custom_components.parcel_tracker.mail.base import body_text, sender, sent_at, subject
from custom_components.parcel_tracker.mail.forward import parse_quoted_date
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail

FORWARDER = "Erika Musterfrau <erika.musterfrau@example.org>"
MAILBOX = "pakete@example.org"
DHL_NAME, DHL_ADDRESS = "DHL Zustell-Update", "zustellung@dhl.de"
DHL_SUBJECT = "Ihre Beispielmarke GmbH Sendung kommt heute"
SHORT = "999999999901"
OTHER = "00340999999999999919"
DHL_BODY = (
    "Hallo,\n\n"
    "Ihre Beispielmarke GmbH Sendung wird Ihnen heute durch Ihre Brief- und "
    "Paketzustellkraft zugestellt.\n\n"
    f"Ihre Sendungsnummer\n{SHORT}\n\n"
    "Viele Grüße\nDHL Group\n"
)
ORIGINAL = datetime(2026, 9, 28, 11, 51, 34, tzinfo=BERLIN)  # a Monday
LATER = timedelta(days=2, hours=3)  # forwarded two days after the original came

AMAZON_MAIL = "074_versandbestaetigung_versendet.eml"
GLS_MAIL = "111_no_reply_dein_paket_wird_in_wenigen_tage.eml"
DHL_MAIL = "120_dhl_zustellung_kommt_heute.eml"

WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
WEEKDAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS_DE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
    "Oktober", "November", "Dezember",
)
MONTHS_EN = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)
GMAIL_DE = ("Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.",
            "Nov.", "Dez.")


def _clock12(when: datetime) -> tuple[str, str]:
    return f"{when.hour % 12 or 12}:{when:%M}", "AM" if when.hour < 12 else "PM"


def _zone(when: datetime) -> tuple[str, str, str]:
    hours = int(when.utcoffset().total_seconds() // 3600)
    return f"+{hours:02d}00", "MESZ" if hours == 2 else "MEZ", f"GMT+{hours}"


def outlook_de(name, address, subj, when):
    return (
        "________________________________\n"
        f"Von: {name} <{address}>\n"
        f"Gesendet: {WEEKDAYS_DE[when.weekday()]}, {when.day}. {MONTHS_DE[when.month - 1]} "
        f"{when.year} {when:%H:%M}\n"
        f"An: Max Mustermann <{MAILBOX}>\n"
        f"Betreff: {subj}\n\n"
    )


def outlook_en(name, address, subj, when):
    clock, half = _clock12(when)
    return (
        f"From: {name} <{address}>\n"
        f"Sent: {WEEKDAYS_EN[when.weekday()]}, {MONTHS_EN[when.month - 1]} {when.day}, "
        f"{when.year} {clock} {half}\n"
        f"To: Max Mustermann <{MAILBOX}>\n"
        f"Subject: {subj}\n\n"
    )


def outlook_mixed(name, address, subj, when):
    """German labels, English date (as the mail of fixture 121 has it)."""
    clock, half = _clock12(when)
    return (
        "________________________________\n"
        f"Von: {name}<{address}>\n"
        f"Gesendet: {WEEKDAYS_DE[when.weekday()]}, {MONTHS_EN[when.month - 1]} {when.day}, "
        f"{when.year} {clock} {half}\n"
        f"An: {MAILBOX}\n"
        f"Betreff: {subj}\n\n"
    )


def outlook_classic(name, address, subj, when):
    return (
        "-----Ursprüngliche Nachricht-----\n"
        f"Von: {name} [mailto:{address}]\n"
        f"Gesendet: {WEEKDAYS_DE[when.weekday()]}, {when.day}. {MONTHS_DE[when.month - 1]} "
        f"{when.year} {when:%H:%M}\n"
        f"An: '{MAILBOX}'\n"
        f"Betreff: {subj}\n\n"
    )


def outlook_bold(name, address, subj, when):
    """Bold labels as a text part keeps them, the address as a mailto link."""
    return (
        f"*Von:* {name} <mailto:{address}>\n"
        f"*Gesendet:* {WEEKDAYS_DE[when.weekday()]}, {when.day}. "
        f"{MONTHS_DE[when.month - 1]} {when.year} {when:%H:%M}\n"
        f"*An:* Max Mustermann <mailto:{MAILBOX}>\n"
        f"*Betreff:* {subj}\n\n"
    )


def apple_de(name, address, subj, when):
    return (
        "Anfang der weitergeleiteten Nachricht:\n\n"
        f"Von: {name} <{address}>\n"
        f"Betreff: {subj}\n"
        f"Datum: {when.day}. {MONTHS_DE[when.month - 1]} {when.year} um {when:%H:%M:%S} "
        f"{_zone(when)[1]}\n"
        f"An: {MAILBOX}\n\n"
    )


def apple_en(name, address, subj, when):
    clock, half = _clock12(when)
    return (
        "Begin forwarded message:\n\n"
        f"From: {name} <{address}>\n"
        f"Subject: {subj}\n"
        f"Date: {MONTHS_EN[when.month - 1]} {when.day}, {when.year} at "
        f"{clock}:{when:%S} {half} {_zone(when)[2]}\n"
        f"To: {MAILBOX}\n\n"
    )


def gmail_en(name, address, subj, when):
    clock, half = _clock12(when)
    return (
        "---------- Forwarded message ---------\n"
        f"From: {name} <{address}>\n"
        f"Date: {WEEKDAYS_EN[when.weekday()][:3]}, {MONTHS_EN[when.month - 1][:3]} {when.day}, "
        f"{when.year} at {clock} {half}\n"
        f"Subject: {subj}\n"
        f"To: <{MAILBOX}>\n\n"
    )


def gmail_de(name, address, subj, when):
    return (
        "---------- Weitergeleitete Nachricht ---------\n"
        f"Von: {name} <{address}>\n"
        f"Date: {WEEKDAYS_DE[when.weekday()][:2]}., {when.day}. {GMAIL_DE[when.month - 1]} "
        f"{when.year} um {when:%H:%M} Uhr\n"
        f"Subject: {subj}\n"
        f"To: <{MAILBOX}>\n\n"
    )


def thunderbird(name, address, subj, when):
    return (
        "-------- Weitergeleitete Nachricht --------\n"
        f"Betreff: \t{subj}\n"
        f"Datum: \t{WEEKDAYS_EN[when.weekday()][:3]}, {when.day} {MONTHS_EN[when.month - 1][:3]} "
        f"{when.year} {when:%H:%M:%S} {_zone(when)[0]}\n"
        f"Von: \t{name} <{address}>\n"
        f"An: \t{MAILBOX}\n\n"
    )


# (header block, the quoted date carries seconds)
STYLES = [
    (outlook_de, False),
    (outlook_en, False),
    (outlook_mixed, False),
    (outlook_classic, False),
    (outlook_bold, False),
    (apple_de, True),
    (apple_en, True),
    (gmail_en, False),
    (gmail_de, False),
    (thunderbird, True),
]
STYLE_IDS = [style.__name__ for style, _ in STYLES]


def _forward(
    text: str,
    subj: str,
    when: datetime,
    markup: str | None = None,
    prefix: str = "WG: ",
) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = FORWARDER
    msg["To"] = MAILBOX
    msg["Subject"] = prefix + subj
    msg["Date"] = when + LATER
    msg["Message-ID"] = "<weiterleitung-1@example.org>"
    if markup is None:
        msg.set_content(text)
    else:
        msg.set_content(markup, subtype="html")
    return msg


def _seen(when: datetime, seconds: bool) -> datetime:
    return when if seconds else when.replace(second=0)


def _dhl(style, note: str = "") -> EmailMessage:
    block = style(DHL_NAME, DHL_ADDRESS, DHL_SUBJECT, ORIGINAL)
    return _forward(note + block + DHL_BODY, DHL_SUBJECT, ORIGINAL)


# ----- every client style: DHL "kommt heute" with a 12-digit number -----
@pytest.mark.parametrize(("style", "seconds"), STYLES, ids=STYLE_IDS)
def test_forwarded_dhl_mail_is_read_by_the_dhl_parser(style, seconds):
    msg = _wire(_dhl(style))
    # the forwarder is no sender the importer knows, and the generic parser reads nothing
    assert sender(msg)[0].endswith("@example.org")
    result = parse_mail(msg)
    [u] = result.updates
    assert (u.number, u.carrier, u.status) == (SHORT, "dhl", ParcelStatus.OUT_FOR_DELIVERY)
    assert u.title == "Beispielmarke GmbH"
    # "heute" is the day of the original mail, not the day it was forwarded
    assert u.sent_at == _seen(ORIGINAL, seconds)
    assert u.eta_date == ORIGINAL.date() != sent_at(msg).date()
    assert result.amazon is False and result.ignored is False


@pytest.mark.parametrize(("style", "seconds"), STYLES, ids=STYLE_IDS)
def test_quoted_lines_with_quote_marks_are_read_too(style, seconds):
    block = style(DHL_NAME, DHL_ADDRESS, DHL_SUBJECT, ORIGINAL)
    quoted = "\n".join(f"> {line}".rstrip() for line in (block + DHL_BODY).splitlines())
    [u] = parse_mail(_forward(f"Zur Info\n\n{quoted}\n", DHL_SUBJECT, ORIGINAL)).updates
    assert (u.number, u.status, u.title) == (
        SHORT, ParcelStatus.OUT_FOR_DELIVERY, "Beispielmarke GmbH",
    )
    assert u.sent_at == _seen(ORIGINAL, seconds)


# ----- an Amazon "Versendet" mail and a GLS mail: the same result as the direct mail -----
@pytest.mark.parametrize("name", [AMAZON_MAIL, GLS_MAIL])
@pytest.mark.parametrize(("style", "seconds"), STYLES, ids=STYLE_IDS)
def test_forward_gives_what_the_direct_mail_gives(style, seconds, name):
    direct = load_mail(name)
    expected = parse_mail(direct).updates
    assert expected and all(update.status is not None for update in expected)
    address, display = sender(direct)
    when = sent_at(direct)
    text = direct.get_body(("plain",)).get_content()
    block = style(display, address, subject(direct), when)
    msg = _forward("Schau mal, Gruß Erika\n\n" + block + text, subject(direct), when)
    result = parse_mail(msg)
    assert result.amazon is False  # only a mail Amazon sent itself counts there
    assert result.updates == [
        replace(
            update,
            sent_at=_seen(update.sent_at, seconds),
            delivered_at=update.delivered_at and _seen(update.delivered_at, seconds),
        )
        for update in expected
    ]
    assert all(update.sent_at.date() != sent_at(msg).date() for update in result.updates)


# ----- HTML only: labels in bold, mailto links, headers as a table -----
def _paragraphs(text: str) -> str:
    return "".join(f"<p>{escape(line)}</p>" for line in text.splitlines() if line)


def test_html_only_forward_with_bold_labels_and_mailto_link():
    markup = (
        "<html><body><div>Zur Info, Gruß Erika</div><hr>"
        f"<div><b>Von:</b> {DHL_NAME} &lt;<a href=\"mailto:{DHL_ADDRESS}\">{DHL_ADDRESS}</a>&gt;"
        "<br><b>Gesendet:</b> Montag, 28. September 2026 11:51<br>"
        f"<b>An:</b> Max Mustermann &lt;{MAILBOX}&gt;<br>"
        f"<b>Betreff:</b> {DHL_SUBJECT}</div>{_paragraphs(DHL_BODY)}</body></html>"
    )
    [u] = parse_mail(_forward("", DHL_SUBJECT, ORIGINAL, markup)).updates
    assert (u.number, u.status, u.title) == (
        SHORT, ParcelStatus.OUT_FOR_DELIVERY, "Beispielmarke GmbH",
    )
    assert u.sent_at == ORIGINAL.replace(second=0)


def test_html_only_forward_with_the_headers_as_a_table():
    markup = (
        "<html><body><p>Zur Info</p><div>-------- Weitergeleitete Nachricht --------</div>"
        "<table>"
        f"<tr><th>Betreff: </th><td>{DHL_SUBJECT}</td></tr>"
        "<tr><th>Datum: </th><td>Mon, 28 Sep 2026 11:51:34 +0200</td></tr>"
        f"<tr><th>Von: </th><td>{DHL_NAME} &lt;{DHL_ADDRESS}&gt;</td></tr>"
        f"<tr><th>An: </th><td>{MAILBOX}</td></tr>"
        f"</table>{_paragraphs(DHL_BODY)}</body></html>"
    )
    [u] = parse_mail(_forward("", DHL_SUBJECT, ORIGINAL, markup, prefix="Fwd: ")).updates
    assert (u.number, u.status, u.title, u.sent_at) == (
        SHORT, ParcelStatus.OUT_FOR_DELIVERY, "Beispielmarke GmbH", ORIGINAL,
    )


def test_block_only_in_the_html_part_is_found_when_the_text_part_has_none():
    msg = _forward("Siehe unten.\n", DHL_SUBJECT, ORIGINAL)
    block = outlook_de(DHL_NAME, DHL_ADDRESS, DHL_SUBJECT, ORIGINAL)
    msg.add_alternative(f"<html><body>{_paragraphs(block + DHL_BODY)}</body></html>",
                        subtype="html")
    [u] = parse_mail(msg).updates
    assert (u.number, u.status) == (SHORT, ParcelStatus.OUT_FOR_DELIVERY)


# ----- the original as an attachment -----
def _with_attachment(
    inner: EmailMessage, note: str = "Im Anhang.\n", when: datetime | None = None
) -> EmailMessage:
    msg = _forward(note, str(inner["Subject"]), when or sent_at(inner), prefix="Fwd: ")
    msg.add_attachment(inner)
    return msg


def _wire(msg: EmailMessage) -> EmailMessage:
    """The mail as the importer gets it: parsed from its bytes."""
    return email.message_from_bytes(bytes(msg), policy=policy.default)


def test_forward_as_attachment_is_the_attached_mail():
    direct = load_mail(DHL_MAIL)
    msg = _with_attachment(load_mail(DHL_MAIL), f"Im Anhang. Alte Nummer: {OTHER}\n")
    assert [part.get_content_type() for part in msg.iter_parts()] == [
        "text/plain", "message/rfc822",
    ]
    expected = parse_mail(direct).updates
    assert expected and parse_mail(msg).updates == expected
    assert parse_mail(_wire(msg)).updates == expected
    assert sender(forwarded_original(msg))[0] == DHL_ADDRESS


def test_attached_mail_without_a_date_takes_the_forwards_date():
    inner = load_mail(DHL_MAIL)
    when = sent_at(inner)
    del inner["Date"]
    msg = _wire(_with_attachment(inner, when=when))
    [u] = parse_mail(msg).updates
    assert u.sent_at == when + LATER and u.eta_date == (when + LATER).date()


def test_attached_mail_of_an_unknown_sender_changes_nothing():
    inner = EmailMessage(policy=policy.default)
    inner["From"] = "Shop <versand@shop.example>"
    inner["Subject"] = "Versandbestätigung"
    inner["Date"] = ORIGINAL
    inner.set_content(f"Ihre Sendungsnummer\n{SHORT}\n")
    msg = _with_attachment(inner)
    assert forwarded_original(msg) is None
    assert parse_mail(msg).updates == []


# ----- nested forwards: only the innermost one counts -----
def test_nested_forward_takes_the_innermost_block():
    first = ORIGINAL + timedelta(days=1)
    inner = outlook_de(DHL_NAME, DHL_ADDRESS, DHL_SUBJECT, ORIGINAL) + DHL_BODY
    outer = (
        f"Für dich. Vergleich: {OTHER}\n\n"
        + gmail_de("Otto Beispiel", "otto.beispiel@example.net", "WG: " + DHL_SUBJECT, first)
        + f"Hallo Erika, das ist deins.\nOtto Beispiel, Musterbau GmbH\n{OTHER}\n\n"
        + inner
    )
    msg = _forward(outer, "Fwd: " + DHL_SUBJECT, first, prefix="WG: ")
    view = forwarded_original(msg)
    assert sender(view) == (DHL_ADDRESS, DHL_NAME)
    assert subject(view) == DHL_SUBJECT
    assert "Otto" not in body_text(view) and OTHER not in body_text(view)
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.title) == (
        SHORT, ParcelStatus.OUT_FOR_DELIVERY, "Beispielmarke GmbH",
    )
    assert u.sent_at == ORIGINAL.replace(second=0) and u.eta_date == ORIGINAL.date()


def test_known_block_wins_over_a_deeper_unknown_one():
    """The last block with a sender the importer knows; an unknown one below it is text."""
    deeper = outlook_en("Shop", "info@shop.example", "Your order", ORIGINAL - timedelta(days=3))
    text = outlook_de(DHL_NAME, DHL_ADDRESS, DHL_SUBJECT, ORIGINAL) + DHL_BODY + "\n" + deeper
    [u] = parse_mail(_forward(text, DHL_SUBJECT, ORIGINAL)).updates
    assert (u.number, u.sent_at) == (SHORT, ORIGINAL.replace(second=0))


def test_attached_forward_with_a_quoted_original_inside():
    inner = _dhl(apple_de)
    inner.replace_header("From", "Otto Beispiel <otto.beispiel@example.net>")
    msg = _with_attachment(inner)
    [u] = parse_mail(msg).updates
    assert (u.number, u.title, u.sent_at) == (SHORT, "Beispielmarke GmbH", ORIGINAL)


# ----- nothing from above the block, nothing of the forwarder -----
NOTE = (
    "Hallo,\n\ndas ist die Sendung, nicht die alte mit der Nummer\n"
    f"{OTHER}\nIhre Sendungsnummer\n999999999955\n\n"
    "Viele Grüße\nErika Musterfrau\nMusterfirma GmbH\nTel. 01234 567890\n\n"
)


@pytest.mark.parametrize(("style", "seconds"), STYLES, ids=STYLE_IDS)
def test_the_forwarders_note_and_signature_are_never_read(style, seconds):
    msg = _dhl(style, NOTE)
    view = forwarded_original(msg)
    assert body_text(view).startswith("Hallo,\n\nIhre Beispielmarke GmbH Sendung")
    for word in (OTHER, "999999999955", "Musterfirma", "Erika", "01234"):
        assert word not in body_text(view) + subject(view) + str(view["From"]), word
    [u] = parse_mail(msg).updates
    assert (u.number, u.title) == (SHORT, "Beispielmarke GmbH")


def test_the_forwarders_name_never_names_the_parcel():
    """The forwarder is a company: neither its display name nor its signature is taken."""
    block = outlook_de(DHL_NAME, DHL_ADDRESS, "Ihre Sendung kommt heute", ORIGINAL)
    msg = _forward("Gruß\nMusterfirma GmbH\n\n" + block + DHL_BODY, "Ihre Sendung kommt heute",
                   ORIGINAL)
    msg.replace_header("From", "Musterfirma GmbH <buero@musterfirma.example>")
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.title) == (SHORT, ParcelStatus.OUT_FOR_DELIVERY, None)


# ----- unknown or unreadable original sender: as before -----
def test_forward_of_an_unknown_shop_mail_goes_the_generic_way():
    block = outlook_de("Beispielshop GmbH", "versand@shop.example", "Ihre Bestellung", ORIGINAL)
    text = block + f"Ihre Sendungsnummer\n{SHORT}\nDHL-Sendungsnummer: JJD000012978217606560\n"
    msg = _forward(text, "Ihre Bestellung", ORIGINAL)
    assert forwarded_original(msg) is None
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status, u.title) == (
        "JJD000012978217606560", "dhl", None, None,
    )
    assert u.sent_at == sent_at(msg)


@pytest.mark.parametrize(
    "line",
    [
        f"Von: {DHL_NAME}",  # no address at all
        "Von: DHL Zustell-Update <zustellung at dhl.de>",
        "Von:",
    ],
)
def test_block_without_a_readable_sender_changes_nothing(line):
    text = f"{line}\nGesendet: Montag, 28. September 2026 11:51\nBetreff: {DHL_SUBJECT}\n\n"
    msg = _forward(text + DHL_BODY, DHL_SUBJECT, ORIGINAL)
    assert forwarded_original(msg) is None
    assert parse_mail(msg).updates == []


def test_a_sender_line_alone_is_no_header_block():
    """"Von: …" as a mail has it in its text (a shipper line) is no forward."""
    text = f"Paket\nVon: {DHL_NAME} <{DHL_ADDRESS}>\n\n" + DHL_BODY
    msg = _forward(text, DHL_SUBJECT, ORIGINAL)
    assert forwarded_original(msg) is None


def test_a_mail_of_a_known_sender_is_never_rerouted_by_its_text():
    """What a carrier's own mail quotes is its text: only a forward is looked into."""
    amazon = load_mail(AMAZON_MAIL)
    block = outlook_de("Amazon.de", sender(amazon)[0], subject(amazon), ORIGINAL)
    msg = _forward(
        DHL_BODY + "\n" + block + amazon.get_body(("plain",)).get_content(), DHL_SUBJECT, ORIGINAL
    )
    msg.replace_header("From", f"{DHL_NAME} <{DHL_ADDRESS}>")
    msg.replace_header("Subject", DHL_SUBJECT)
    assert forwarded_original(msg) is None
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier) == (SHORT, "dhl")


def test_a_mail_of_an_ignored_sender_stays_ignored():
    msg = _dhl(outlook_de)
    msg.replace_header("From", "Prime Video <no-reply@primevideo.com>")
    assert forwarded_original(msg) is None
    result = parse_mail(msg)
    assert result.ignored and not result.updates


def test_the_first_lines_of_the_original_are_never_taken_for_header_lines():
    """Text derived from HTML has no empty line behind the block, and the original may have
    a labelled line of its own ("Von: …" of a UPS mail) right at its start."""
    text = (
        outlook_de("UPS", "pkginfo@ups.com", "UPS Versandbenachrichtigung", ORIGINAL).rstrip("\n")
        + "\nVon: Beispielmarke GmbH\nSendungsnummer: 1Z999AA10123456784\n"
    )
    msg = _forward(text, "UPS Versandbenachrichtigung", ORIGINAL)
    assert body_text(forwarded_original(msg)).startswith("Von: Beispielmarke GmbH")
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.title) == ("1Z999AA10123456784", "ups", "Beispielmarke GmbH")


def test_a_forged_block_does_no_more_than_a_direct_mail():
    """A quoted DHL header above free text: only what the DHL parser reads in a DHL mail."""
    block = outlook_de(DHL_NAME, DHL_ADDRESS, "Rechnung", ORIGINAL)
    msg = _forward(block + "Bitte zahlen. Nummer 999999999955\n", "Rechnung", ORIGINAL)
    assert parse_mail(msg).updates == []


# ----- the original date -----
MONDAY = datetime(2026, 9, 28, 11, 51, tzinfo=BERLIN)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Montag, 28. September 2026 11:51", MONDAY),
        ("Monday, September 28, 2026 11:51 AM", MONDAY),
        ("Montag, September 28, 2026 11:51 AM", MONDAY),
        ("Monday, 28 September 2026 11:51", MONDAY),
        ("28. September 2026 um 11:51:34 MESZ", MONDAY.replace(second=34)),
        ("September 28, 2026 at 11:51:34 AM GMT+2", MONDAY.replace(second=34)),
        ("28 September 2026 at 11:51:34 CEST", MONDAY.replace(second=34)),
        ("Mon, Sep 28, 2026 at 11:51 AM", MONDAY),
        ("Mon, 28 Sept 2026 at 11:51", MONDAY),
        ("Mo., 28. Sept. 2026 um 11:51 Uhr", MONDAY),
        ("Mon, 28 Sep 2026 11:51:34 +0200", MONDAY.replace(second=34)),
        ("Mon, 28 Sep 2026 09:51:34 +0000", MONDAY.replace(second=34)),
        ("28.09.2026 11:51", MONDAY),
        ("28.09.26, 11:51", MONDAY),
        ("Montag, 28.09.2026 11:51 Uhr", MONDAY),
        ("2026-09-28 11:51", MONDAY),
        ("9/28/2026 11:51 AM", MONDAY),
        ("28/09/2026 11:51", MONDAY),
        ("Monday, 9/7/2026 3:05 PM", datetime(2026, 9, 7, 15, 5, tzinfo=BERLIN)),
        ("Montag, 7/9/2026 15:05", datetime(2026, 9, 7, 15, 5, tzinfo=BERLIN)),
        ("Monday, September 28, 2026 12:05 AM", MONDAY.replace(hour=0, minute=5)),
        ("Monday, September 28, 2026 12:05 PM", MONDAY.replace(hour=12, minute=5)),
        ("Monday, September 28, 2026 9:51 PM", MONDAY.replace(hour=21)),
        ("Montag, 28. September 2026 09:51 UTC", MONDAY),
        ("Montag, 14. Dezember 2026 11:51", datetime(2026, 12, 14, 11, 51, tzinfo=BERLIN)),
        ("Sonntag, 1. März 2026 08:00 MEZ", datetime(2026, 3, 1, 8, 0, tzinfo=BERLIN)),
        ("*Montag, 28. September 2026 11:51*", MONDAY),
    ],
)
def test_quoted_dates_that_are_certain(text, expected):
    found = parse_quoted_date(text)
    assert found is not None and found.tzinfo is not None, text
    assert found.astimezone(UTC) == expected.astimezone(UTC), text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "gestern Abend",
        "Montag, 28. September 2026",  # no time
        "Dienstag, 28. September 2026 11:51",  # the 28th is a Monday
        "Tuesday, September 28, 2026 11:51 AM",
        "7/9/2026 15:05",  # 7 September or 9 July
        "Montag, 28. Septembär 2026 11:51",
        "28. September 2026 11:51 PST",  # a zone we do not know
        "28. September 2026 25:51",
        "31. Februar 2026 11:51",
        "September 28, 2026 13:51 PM",
        "28. September 11:51",  # no year
        "Mon, 32 Sep 2026 11:51:34 +0200",
    ],
)
def test_quoted_dates_that_are_not_certain(text):
    assert parse_quoted_date(text) is None, text


@pytest.mark.parametrize(
    "line",
    [
        "Gesendet: gestern Abend",
        "Gesendet: Dienstag, 28. September 2026 11:51",
        "Gesendet: 7/9/2026 11:51",
        # later than the forward itself: not the date of the original
        "Gesendet: Montag, 5. Oktober 2026 11:51",
    ],
)
def test_uncertain_date_falls_back_to_the_date_of_the_forward(line):
    text = f"Von: {DHL_NAME} <{DHL_ADDRESS}>\n{line}\nBetreff: {DHL_SUBJECT}\n\n" + DHL_BODY
    msg = _forward(text, DHL_SUBJECT, ORIGINAL)
    [u] = parse_mail(msg).updates
    assert u.sent_at == sent_at(msg) and u.eta_date == sent_at(msg).date()
    assert (u.number, u.status) == (SHORT, ParcelStatus.OUT_FOR_DELIVERY)


def test_block_without_a_date_line_falls_back_too():
    text = f"Von: {DHL_NAME} <{DHL_ADDRESS}>\nBetreff: {DHL_SUBJECT}\n\n" + DHL_BODY
    msg = _forward(text, DHL_SUBJECT, ORIGINAL)
    [u] = parse_mail(msg).updates
    assert u.sent_at == sent_at(msg)


def test_quoted_date_without_a_zone_is_berlin_time_also_in_winter():
    when = datetime(2026, 12, 14, 9, 30, tzinfo=BERLIN)
    block = outlook_de(DHL_NAME, DHL_ADDRESS, DHL_SUBJECT, when)
    [u] = parse_mail(_forward(block + DHL_BODY, DHL_SUBJECT, when)).updates
    assert u.sent_at == when and u.sent_at.utcoffset() == timedelta(hours=1)


# ----- the subject of the original -----
@pytest.mark.parametrize("prefix", ["WG: ", "Fw: ", "FW: Fwd: ", "AW: WG: ", "Re: "])
def test_prefixes_of_the_quoted_subject_are_dropped(prefix):
    block = outlook_de(DHL_NAME, DHL_ADDRESS, prefix + DHL_SUBJECT, ORIGINAL)
    msg = _forward(block + DHL_BODY, "etwas ganz anderes", ORIGINAL)
    assert subject(forwarded_original(msg)) == DHL_SUBJECT
    [u] = parse_mail(msg).updates
    assert (u.status, u.title) == (ParcelStatus.OUT_FOR_DELIVERY, "Beispielmarke GmbH")


def test_forward_without_a_subject_prefix_is_read_too():
    msg = _forward(
        outlook_de(DHL_NAME, DHL_ADDRESS, DHL_SUBJECT, ORIGINAL) + DHL_BODY, "Paket", ORIGINAL,
        prefix="",
    )
    [u] = parse_mail(msg).updates
    assert (u.number, u.title) == (SHORT, "Beispielmarke GmbH")


def test_wrapped_recipient_line_inside_the_block():
    text = (
        f"Von: {DHL_NAME} <{DHL_ADDRESS}>\n"
        "Gesendet: Montag, 28. September 2026 11:51\n"
        "An: Max Mustermann <max@example.org>; Erika Musterfrau\n"
        "<erika.musterfrau@example.org>\n"
        f"Betreff: {DHL_SUBJECT}\n\n" + DHL_BODY
    )
    view = forwarded_original(_forward(text, DHL_SUBJECT, ORIGINAL))
    assert subject(view) == DHL_SUBJECT and "Musterfrau" not in body_text(view)

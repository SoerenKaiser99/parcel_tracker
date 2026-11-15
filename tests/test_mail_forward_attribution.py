"""v0.3.52: a forward with only an attribution line above the original (issues 71-73).

Some mail programs (mostly on phones) quote no "Von: / Gesendet: / Betreff:" block above a
forwarded mail, only one line "Am 14.11.26, 15:50 schrieb DHL <…@dhl.de>:". Invented mails
only: example.org addresses, invented numbers.
"""

import email
from datetime import date, datetime
from email import policy
from email.message import EmailMessage
from html import escape

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import forwarded_original, parse_mail
from custom_components.parcel_tracker.models import ParcelStatus

FORWARDER = "Erika Musterfrau <erika.musterfrau@example.org>"
MAILBOX = "pakete@example.org"
DHL_NUMBER = "00340999999999999919"
DPD_NUMBER = "09999999999901"
SHOP = "Beispielmarke GmbH"

ANNOUNCE_LINE = (
    'Am 14.11.26, 15:50 schrieb "📦 DHL Paketankündigung" <paketankuendigung@dhl.de>:'
)
ANNOUNCE_SENT = datetime(2026, 11, 14, 15, 50, tzinfo=BERLIN)  # a Saturday
ANNOUNCE_BODY = [
    "Zustelltag und Empfangsoptionen ansehen",
    "Hallo Max Mustermann,",
    f"Ihre {SHOP} Sendung ist unterwegs und wird Ihnen voraussichtlich",
    "—",
    "am Montag, den 16.11.",
    "—",
    "zugestellt.",
    "Ihre Sendungsnummer",
    DHL_NUMBER,
    "Viele Grüße",
    "Ihr DHL Team",
]
ANNOUNCE_SUBJECT = f"Ihre {SHOP} Sendung ist unterwegs"

TODAY_LINE = "Am 10.11.26, 09:14 schrieb DHL Live Tracking <noreply@dhl.de>:"
TODAY_SENT = datetime(2026, 11, 10, 9, 14, tzinfo=BERLIN)  # a Tuesday
TODAY_BODY = [
    f"Ihre {SHOP} Sendung wird Ihnen",
    "heute zwischen 12:45 - 14:15 Uhr",
    "durch Ihre Brief- und Paketzustellkraft zugestellt.",
    "Ihre Sendungsnummer",
    DHL_NUMBER,
]
TODAY_SUBJECT = f"Ihre {SHOP} Sendung kommt heute - Jetzt Live verfolgen"

DPD_LINE = "Am 13.11.26, 19:05 schrieb DPD <noreply@service.dpd.de>:"
DPD_SENT = datetime(2026, 11, 13, 19, 5, tzinfo=BERLIN)  # a Friday
DPD_BODY = [
    "Guten Tag,",
    "Ihre Sendung stellen wir in 1-2 Werktagen zu.",
    "Versender & Paketnummer:",
    "Beispiel Autoteile GmbH",
    DPD_NUMBER,
    "Weitere Informationen zu Ihrem Paket erhalten Sie von uns am Tag der Zustellung.",
]
DPD_SUBJECT = "Bald ist Ihr DPD Paket da"

FORWARD_DATE = datetime(2026, 11, 15, 10, 30, tzinfo=BERLIN)
NOTE = ["Schau mal bitte", "Gruß Erika", "Gesendet von meinem Telefon"]


def _paragraphs(lines: list[str]) -> str:
    return "".join(f"<p>{escape(line)}</p>" for line in lines)


def _forward(
    subject: str,
    lines: list[str],
    *,
    html: bool = True,
    sender: str = FORWARDER,
    when: datetime = FORWARD_DATE,
) -> EmailMessage:
    """A forward as the importer gets it (parsed from its bytes)."""
    msg = EmailMessage(policy=policy.default)
    msg["From"] = sender
    msg["To"] = MAILBOX
    msg["Subject"] = subject
    msg["Date"] = when
    msg["Message-ID"] = "<weiterleitung-71@example.org>"
    if html:
        msg.set_content(f"<html><body>{_paragraphs(lines)}</body></html>", subtype="html")
    else:
        msg.set_content("\n".join(lines) + "\n")
    return email.message_from_bytes(bytes(msg), policy=policy.default)


# ----- the three mails of the issues, end to end -----
def test_dhl_announcement_is_read_by_the_dhl_parser():
    msg = _forward(f"Wg: {ANNOUNCE_SUBJECT}", [*NOTE, ANNOUNCE_LINE, *ANNOUNCE_BODY])
    original = forwarded_original(msg)
    assert original is not None
    assert str(original["Subject"]) == ANNOUNCE_SUBJECT
    result = parse_mail(msg)
    [u] = result.updates
    assert (u.number, u.carrier, u.status) == (DHL_NUMBER, "dhl", ParcelStatus.IN_TRANSIT)
    assert u.title == SHOP
    assert u.sent_at == ANNOUNCE_SENT
    assert u.eta_date == date(2026, 11, 16)
    assert result.amazon is False and result.ignored is False


def test_dhl_today_with_window_is_on_the_quoted_day():
    msg = _forward(f"Wg: {TODAY_SUBJECT}", [TODAY_LINE, *TODAY_BODY])
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (
        DHL_NUMBER, "dhl", ParcelStatus.OUT_FOR_DELIVERY,
    )
    assert u.sent_at == TODAY_SENT
    assert u.eta_date == date(2026, 11, 10)
    assert u.eta_from == datetime(2026, 11, 10, 12, 45, tzinfo=BERLIN)
    assert u.eta_to == datetime(2026, 11, 10, 14, 15, tzinfo=BERLIN)


def test_dpd_announcement_is_recognised():
    msg = _forward(f"Wg: {DPD_SUBJECT}", [*NOTE, DPD_LINE, *DPD_BODY])
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier) == (DPD_NUMBER, "dpd")
    assert u.sent_at == DPD_SENT


# ----- other forms of the line -----
@pytest.mark.parametrize(
    "line",
    [
        ANNOUNCE_LINE,
        # escaped in the HTML part: html_text gives it back as it was
        "Am 14.11.26, 15:50 schrieb DHL Paketankündigung <mailto:paketankuendigung@dhl.de>:",
        "Am 14.11.2026 um 15:50 schrieb DHL Paketankündigung <paketankuendigung@dhl.de>:",
        "Am Sa., 14. Nov. 2026 um 15:50 Uhr schrieb DHL <paketankuendigung@dhl.de>:",
        "Am 14.11.26, 15:50 schrieb paketankuendigung@dhl.de:",
        "Am 14.11.26, 15:50 schrieb DHL [mailto:paketankuendigung@dhl.de]:",
        "On Sat, Nov 14, 2026 at 3:50 PM DHL <paketankuendigung@dhl.de> wrote:",
        "On Nov 14, 2026, at 15:50, DHL Paketankündigung <paketankuendigung@dhl.de> wrote:",
        'On 14.11.26, 15:50, "DHL" <paketankuendigung@dhl.de> wrote:',
    ],
)
def test_forms_of_the_attribution_line(line):
    msg = _forward(f"WG: {ANNOUNCE_SUBJECT}", [*NOTE, line, *ANNOUNCE_BODY])
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.sent_at) == (
        DHL_NUMBER, ParcelStatus.IN_TRANSIT, ANNOUNCE_SENT,
    )


@pytest.mark.parametrize(
    "wrapped",
    [
        [
            "Am Sa., 14. Nov. 2026 um 15:50 Uhr schrieb DHL Paketankündigung <",
            "paketankuendigung@dhl.de>:",
        ],
        [
            "On Sat, Nov 14, 2026 at 3:50 PM DHL Paketankündigung",
            "<paketankuendigung@dhl.de> wrote:",
        ],
    ],
)
def test_attribution_line_wrapped_over_two_lines(wrapped):
    msg = _forward(f"Fwd: {ANNOUNCE_SUBJECT}", [*NOTE, "", *wrapped, "", *ANNOUNCE_BODY],
                   html=False)
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.sent_at) == (
        DHL_NUMBER, ParcelStatus.IN_TRANSIT, ANNOUNCE_SENT,
    )


def test_plain_text_part_with_quote_marks():
    quoted = [f"> {line}" for line in ANNOUNCE_BODY]
    msg = _forward(f"FW: {ANNOUNCE_SUBJECT}", [*NOTE, "", ANNOUNCE_LINE, *quoted], html=False)
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.eta_date) == (
        DHL_NUMBER, ParcelStatus.IN_TRANSIT, date(2026, 11, 16),
    )


def test_uncertain_quoted_date_falls_back_to_the_forwards_date():
    msg = _forward(
        f"Wg: {ANNOUNCE_SUBJECT}",
        ["Am Freitag, 14.11.26, 15:50 schrieb DHL <paketankuendigung@dhl.de>:", *ANNOUNCE_BODY],
    )
    original = forwarded_original(msg)
    assert original is not None
    assert original["Date"].datetime == FORWARD_DATE  # 14.11.2026 is no Friday


def test_the_forwarders_note_is_never_part_of_the_original():
    note = ["Die alte Nummer war 00340999999999999927", "Gruß Erika"]
    msg = _forward(f"Wg: {ANNOUNCE_SUBJECT}", [*note, ANNOUNCE_LINE, *ANNOUNCE_BODY])
    original = forwarded_original(msg)
    text = original.get_body(("plain",)).get_content()
    assert "00340999999999999927" not in text and "Erika" not in text
    assert text.startswith("Zustelltag")
    assert [u.number for u in parse_mail(msg).updates] == [DHL_NUMBER]


# ----- what must stay as it is -----
@pytest.mark.parametrize("prefix", ["AW: ", "Re: ", "RE: ", "", "Re: WG: "])
def test_no_forward_prefix_no_attribution_line(prefix):
    """A reply quotes the same line: there the text above it is the answer, not a note."""
    msg = _forward(f"{prefix}{ANNOUNCE_SUBJECT}", [*NOTE, ANNOUNCE_LINE, *ANNOUNCE_BODY])
    assert forwarded_original(msg) is None


def test_attribution_line_of_an_unknown_sender_changes_nothing():
    line = "Am 14.11.26, 15:50 schrieb Max Beispiel <max.beispiel@example.org>:"
    msg = _forward(f"Wg: {ANNOUNCE_SUBJECT}", [*NOTE, line, *ANNOUNCE_BODY])
    assert forwarded_original(msg) is None


def test_a_line_without_an_address_changes_nothing():
    line = "Am 14.11.26, 15:50 schrieb DHL Paketankündigung:"
    msg = _forward(f"Wg: {ANNOUNCE_SUBJECT}", [*NOTE, line, *ANNOUNCE_BODY])
    assert forwarded_original(msg) is None


def test_a_known_outer_sender_is_never_rerouted():
    msg = _forward(
        f"Wg: {ANNOUNCE_SUBJECT}",
        [ANNOUNCE_LINE, *ANNOUNCE_BODY],
        sender="DHL Paketankündigung <paketankuendigung@dhl.de>",
    )
    assert forwarded_original(msg) is None


def test_a_header_block_wins_over_an_attribution_line():
    block = [
        "Von: DHL Live Tracking <noreply@dhl.de>",
        "Gesendet: Dienstag, 10. November 2026 09:14",
        f"An: {MAILBOX}",
        f"Betreff: {TODAY_SUBJECT}",
    ]
    lines = [ANNOUNCE_LINE, "Zur Info", *block, *TODAY_BODY]
    msg = _forward(f"WG: {TODAY_SUBJECT}", lines)
    original = forwarded_original(msg)
    assert str(original["From"]) == "DHL Live Tracking <noreply@dhl.de>"
    [u] = parse_mail(msg).updates
    assert (u.status, u.sent_at) == (ParcelStatus.OUT_FOR_DELIVERY, TODAY_SENT)


def test_a_mail_with_a_header_block_keeps_its_result():
    block = [
        "Von: DHL Live Tracking <noreply@dhl.de>",
        "Gesendet: Dienstag, 10. November 2026 09:14",
        f"An: {MAILBOX}",
        f"Betreff: {TODAY_SUBJECT}",
    ]
    msg = _forward(f"WG: {TODAY_SUBJECT}", [*NOTE, *block, *TODAY_BODY])
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.eta_from) == (
        DHL_NUMBER, ParcelStatus.OUT_FOR_DELIVERY, datetime(2026, 11, 10, 12, 45, tzinfo=BERLIN),
    )


def test_a_sentence_of_the_original_is_no_attribution_line():
    lines = [*NOTE, "Am Montag, den 16.11. schrieb der Bote uns: alles gut", *ANNOUNCE_BODY]
    assert forwarded_original(_forward(f"Wg: {ANNOUNCE_SUBJECT}", lines)) is None


def test_a_us_date_with_a_two_digit_year_falls_back_to_the_forwards_date():
    """11/10/26 can be read two ways and has no 4-digit year: not certain (documented)."""
    line = "On 11/10/26, 9:14 AM, DHL Live Tracking <noreply@dhl.de> wrote:"
    msg = _forward(f"Fwd: {TODAY_SUBJECT}", [line, *TODAY_BODY])
    original = forwarded_original(msg)
    assert original is not None
    assert str(original["From"]) == "DHL Live Tracking <noreply@dhl.de>"
    assert original["Date"].datetime == FORWARD_DATE

"""Eventim ticket orders that come by post (no Home Assistant imports).

Eventim writes two mails about an order whose tickets are sent as a letter: the order
confirmation ("Deine EVENTIM-Bestellung: <event> - Bestellnummer <number>") and, on the day
the tickets leave, a shipping notice ("eventim.de - Versandbenachrichtigung - Deine Bestellung
Nr. <number>"). Neither names a carrier or a tracking number, and no mail tells the delivery.
Read: the order number, the event's name as the title, the delivery method and, from the
shipping notice only, the estimate in working days. Buyer, addresses, venue, organiser,
seats and prices are never taken, and no link is followed.

Only postal delivery makes an order: tickets to print or for the phone (ticketdirect,
print@home, mobile ticket) never arrive in a letter box. Every other sender at Eventim
(newsletters, ticket alarm, customer service, the clubs' own ticket shops) is ignored.
"""

from __future__ import annotations

import re
from datetime import date
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    TITLE_MAX,
    MailResult,
    MailUpdate,
    add_workdays,
    body_text,
    sender,
    sent_at,
    shorten,
    subject,
)

EVENTIM_SENDER = "bestellstatus@eventim.de"
EVENTIM_DOMAIN = "eventim.de"  # every sender there is Eventim
# The promoter's newsletters ("eventimpresents"): never about an order.
EVENTIM_PRESENTS_DOMAIN = "eventimpresents.com"

_ORDER_SUBJECT = re.compile(
    r"Deine EVENTIM-Bestellung:\s*(?P<title>\S.*?)\s+-\s+Bestellnummer\s+(?P<order>\d{6,12})\b",
    re.IGNORECASE,
)
_SHIPPED_SUBJECT = re.compile(
    r"Versandbenachrichtigung\s+-\s+Deine Bestellung Nr\.?\s*(?P<order>\d{6,12})\b",
    re.IGNORECASE,
)
# "<event> und 2 mehr": an order with tickets for several events.
_MORE = re.compile(r"(?P<name>\S.*?)\s+und\s+(?P<more>\d+)\s+mehr")
_METHOD_LABEL = "Liefermethode:"
# Delivery methods that put something into the letter box: "Standardversand (Deutschland)"
# (the only one seen so far), registered or insured mail ("Wertbrief"), express and
# courier. Anything else ("ticketdirect", "Mobile Ticket (für Apple & Google Wallet)",
# print@home, pickup at the box office) does not, and neither does a method that only
# uses one of those words for something else: sent by e-mail, a download, a PDF, a
# digital ticket, "kein Versand", pickup or deposit at the box office.
_POSTAL = re.compile(r"versand|einschreiben|express|kurier|\bpost\b|brief", re.IGNORECASE)
_DIGITAL = re.compile(
    r"ticketdirect|print\s*@\s*home|mobile|wallet|e-?ticket|pass\b"
    r"|e-?mail|download|pdf|digital|\bkein\w*\s+\S*versand"
    r"|abholung|abendkasse|hinterlegung",
    re.IGNORECASE,
)
_ARRIVAL_LABEL = "Voraussichtliche Ankunft:"
_WORKDAYS = re.compile(r"innerhalb von (\d{1,2})(?:\s*(?:bis|-|–)\s*(\d{1,2}))? Werktagen")
# More working days than this are no estimate anybody can plan with.
_MAX_WORKDAYS = 30
_DETAILS = "EINZELHEITEN DEINER BESTELLUNG"
_EVENT_DAY = "Datum:"
# What ends an event's block below its name: the labelled lines, a price, a ruler.
_EVENT_FIELD = re.compile(r"(?:Datum|Ort|Veranstalter):|.*€|[-=_]{5,}$")
# An event's name takes one line, sometimes two (a subtitle); more lines above "Datum:"
# are not a name.
_MAX_NAME_LINES = 3
# Lines that are no event's name for sure: a greeting ("Hallo …", "Liebe …," with its
# comma), a label, a link, a street with its house number, a postcode with its town. (A
# year is neither: "… am Ring 2026".)
_NO_EVENT = re.compile(
    r"(?:hallo|hi|hey)(?=[\s,!]|$)"
    r"|(?:liebe[rs]?|guten\s+(?:tag|morgen|abend)|sehr\s+geehrte\w*)\b.*[,!]$"
    r"|.*:$|.*https?://|.*www\."
    r"|.*(?:stra(?:ß|ss)e|str\.|weg|platz|allee|gasse|ring|ufer|damm)\s+\d{1,3}\s?[a-z]?$"
    r"|\d{5}\s+\S",
    re.IGNORECASE,
)


def order_number(order: str) -> str:
    """Parcel number for an Eventim order: 'EVT' + digits."""
    return "EVT" + order


def _event_title(names: list[str], more: int = 0) -> str | None:
    """Title of an order: the (first) event's name, with Eventim's "und N mehr"."""
    if not names:
        return None
    more = more or len(names) - 1
    if not more:
        return shorten(names[0])
    suffix = f" und {more} mehr"
    return shorten(names[0], TITLE_MAX - len(suffix)) + suffix


def _subject_title(raw: str) -> str | None:
    found = _MORE.fullmatch(raw)
    if found:
        return _event_title([found.group("name")], int(found.group("more")))
    return _event_title([raw])


def _lines(msg: EmailMessage) -> list[str]:
    return [line for line in body_text(msg).splitlines() if line]


def _delivery_method(lines: list[str]) -> str | None:
    """What stands behind "Liefermethode:" (older mails: on the next line); None if the
    mail does not tell."""
    for index, line in enumerate(lines):
        if not line.startswith(_METHOD_LABEL):
            continue
        value = line[len(_METHOD_LABEL) :].strip()
        if not value and index + 1 < len(lines):
            value = lines[index + 1].strip()
        return value or None
    return None


def is_postal(method: str | None) -> bool:
    """True if a delivery method sends the tickets by post (see ``_POSTAL``)."""
    return bool(method) and not _DIGITAL.search(method) and _POSTAL.search(method) is not None


def _details_title(lines: list[str]) -> str | None:
    """The event names below "EINZELHEITEN DEINER BESTELLUNG" as a title.

    Each event is a block: its name, sometimes a second line with a subtitle, then its
    day ("Datum: …") and further labelled lines. The name is the first line of the block,
    found from the day upwards to the heading or to the block before.

    Fails closed, for the mail as a whole: no title if a block is longer than a name can
    be or holds a line that may be a greeting, a label, a link or an address (the buyer's
    name and address stand in the same mail, and they must never name an order).
    """
    if _DETAILS not in lines:
        return None
    section = lines[lines.index(_DETAILS) + 1 :]
    names = []
    for index, line in enumerate(section):
        if not line.startswith(_EVENT_DAY):
            continue
        start = index
        while start > 0 and not _EVENT_FIELD.match(section[start - 1]):
            start -= 1
        block = [row.strip() for row in section[start:index]]
        if not 0 < len(block) <= _MAX_NAME_LINES or any(_NO_EVENT.match(row) for row in block):
            return None
        names.append(block[0])
    return _event_title(list(dict.fromkeys(names)))


def _estimate(lines: list[str], sent: date) -> tuple[date | None, date | None]:
    """(first, last) day of "innerhalb von 2 bis 4 Werktagen", counted from the day the
    shipping notice was sent."""
    line = next((row for row in lines if row.startswith(_ARRIVAL_LABEL)), None)
    found = _WORKDAYS.search(line) if line else None
    if not found:
        return None, None
    first = int(found.group(1))
    last = int(found.group(2)) if found.group(2) else first
    if not 0 < first <= last <= _MAX_WORKDAYS:
        return None, None
    return add_workdays(sent, first), (add_workdays(sent, last) if last > first else None)


def parse_eventim(msg: EmailMessage) -> MailResult:
    """Any mail of Eventim: updates, ignored, or (no updates) unrecognised.

    Order confirmation with postal delivery: "Bestellt", without a day. Its sentence
    about the delivery ("spätestens innerhalb von 2 bis 4 Werktagen …") counts from the
    order, but tickets often leave weeks later ("Der Versand der Tickets erfolgt zwischen
    dem …"), so only the shipping notice gives an estimate. Shipping notice: "Versendet"
    with that estimate; it also makes the order if its confirmation was never seen.
    Ignored: an order whose delivery method is none by post or cannot be read, and every
    other sender. A subject of the order sender nobody knows yet is unrecognised, so it
    gets noticed.
    """
    if sender(msg)[0] != EVENTIM_SENDER:
        return MailResult(ignored=True)
    subj = subject(msg)
    if found := _ORDER_SUBJECT.search(subj):
        if not is_postal(_delivery_method(_lines(msg))):
            return MailResult(ignored=True)
        return MailResult(
            updates=[
                MailUpdate(
                    number=order_number(found.group("order")),
                    carrier="eventim",
                    status=ParcelStatus.PRE_TRANSIT,
                    sent_at=sent_at(msg),
                    title=_subject_title(found.group("title")),
                )
            ]
        )
    if found := _SHIPPED_SUBJECT.search(subj):
        lines = _lines(msg)
        method = _delivery_method(lines)
        if method is not None and not is_postal(method):
            return MailResult(ignored=True)
        sent = sent_at(msg)
        first, last = _estimate(lines, sent.date())
        return MailResult(
            updates=[
                MailUpdate(
                    number=order_number(found.group("order")),
                    carrier="eventim",
                    status=ParcelStatus.IN_TRANSIT,
                    sent_at=sent,
                    title=_details_title(lines),
                    eta_date=first,
                    eta_latest=last,
                )
            ]
        )
    return MailResult()

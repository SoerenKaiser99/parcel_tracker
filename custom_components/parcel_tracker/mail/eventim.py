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
# (the only one seen so far), registered mail, express and courier. Anything else
# ("ticketdirect", "Mobile Ticket (für Apple & Google Wallet)", print@home, pickup at the
# box office) does not.
_POSTAL = re.compile(r"versand|einschreiben|express|kurier|\bpost\b|\bbrief", re.IGNORECASE)
_DIGITAL = re.compile(r"ticketdirect|print\s*@\s*home|mobile|wallet|e-?ticket|pass\b", re.I)
_ARRIVAL_LABEL = "Voraussichtliche Ankunft:"
_WORKDAYS = re.compile(r"innerhalb von (\d{1,2})(?:\s*(?:bis|-|–)\s*(\d{1,2}))? Werktagen")
# More working days than this are no estimate anybody can plan with.
_MAX_WORKDAYS = 30
_DETAILS = "EINZELHEITEN DEINER BESTELLUNG"
_EVENT_DAY = "Datum:"


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
    """The event names below "EINZELHEITEN DEINER BESTELLUNG" as a title: each event is
    its name and, on the next line, its day ("Datum: …")."""
    if _DETAILS not in lines:
        return None
    section = lines[lines.index(_DETAILS) + 1 :]
    names = [
        line
        for line, below in zip(section, section[1:], strict=False)
        if below.startswith(_EVENT_DAY) and not line.startswith(_EVENT_DAY)
    ]
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

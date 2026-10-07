"""GLS notification mails (no Home Assistant imports).

Only number, status, day, window, the time of a delivery and the sender company's name
are taken. The drop-off place, the delivery address, the recipient's name, the phone number
and references are never read into an update.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    MailUpdate,
    at,
    body_text,
    company_name,
    is_forwarded,
    resolve_dates,
    sender,
    sent_at,
    shop_of,
    subject,
)

GLS_SENDER = "no-reply@gls-pakete.de"

# 11 digits right after the label (the text part puts them on the next line). GLS's own
# mails may add a check digit as the 12th: it is read apart and never stored, so the
# parcel is the one known by its 11 digits.
_NUMBER = re.compile(r"(?:Paketnummer|Sendungsnummer)\s*:?\s*(\d{11})(\d?)(?!\d)")
# The tracking link of GLS's own mails ("gls-group.eu/track/<number>"), with or without
# the check digit: only looked at when no label names a number.
_TRACK_LINK = re.compile(r"\bgls-group\.(?:eu|com)/track/(\d{11})\d?(?!\d)", re.IGNORECASE)
_DELIVERED = re.compile(r"\bwurde\b.*\b(?:zugestellt|geliefert)\b")
# "wurde GLS übergeben" is the shop handing the parcel over: only a neighbour delivers.
_HANDED_OVER = re.compile(r"\bwurde\b.*\bübergeben\b")
# "nicht" only negates a verb a few words away: "Nicht verpassen: ... wird zugestellt" is none.
_NOT_DELIVERED = re.compile(
    r"\bnicht\b(?:\s+\S+){0,4}?\s+(?:zugestellt|geliefert|übergeben)\b|konnte nicht|zustellversuch"
)
_GLS_WORD = re.compile(r"\bgls\b", re.IGNORECASE)
_PICKUP_TEXT = re.compile(r"paketshop\b[^\n]*zur abholung bereit")
# The text part of the "zugestellt" mail holds the sentences of every variant at once
# (ParcelShop, neighbour, drop-off place, plain delivery): the ParcelShop sentence only
# counts when no home-delivery sentence stands next to it.
_HOME_TEXT = re.compile(r"wunschort zugestellt|erfolgreich zugestellt")
_ETA_LABEL = "voraussichtliche lieferung"
_WINDOW = re.compile(r"zwischen\s+(\d{1,2}):(\d{2})\s+und\s+(\d{1,2}):(\d{2})\s*Uhr")
_SENDER_LABELS = frozenset(
    {"versender", "absender", "dein paket von", "dein paket von dem absender"}
)

# noreply@gls-group.eu and noreply@gls-rtt.com (seen from GLS Austria, read whatever the
# country): the label in capitals on its own line, the value on the next one.
GLS_GROUP_SENDER = "noreply@gls-group.eu"
GLS_RTT_SENDER = "noreply@gls-rtt.com"
GLS_GROUP_SENDERS = frozenset({GLS_GROUP_SENDER, GLS_RTT_SENDER})
_GROUP_NUMBER = re.compile(
    r"(?:Paketnummer|Sendungsnummer)\s*:?\s*(\d{11})\d?(?!\d)", re.IGNORECASE
)
# "Dies betrifft ebenso das Paket/die Pakete A, B." and "(Wir wurden ebenfalls) beauftragt
# mit der Zustellung des Paketes/der Pakete A, B.": the same news for every number listed.
_GROUP_MORE = re.compile(
    r"(?:betrifft\s+ebenso\s+das\s+Paket/die\s+Pakete"
    r"|beauftragt\s+mit\s+der\s+Zustellung\s+des\s+Paketes/der\s+Pakete)"
    r"\s+((?:\d{11,12}\b[\s,]*(?:und\s+)?)+)"
)
_GROUP_DELIVERED = re.compile(r"\bwurde\b.*\b(?:zugestellt|geliefert|abgestellt)\b")
_GROUP_NOT = re.compile(
    r"\bnicht\b(?:\s+\S+){0,5}?\s+(?:zugestellt|geliefert|abgestellt|übergeben)\b"
    r"|konnte nicht|zustellversuch"
)
_GROUP_TIME = re.compile(r"Zustellung\s*\n\s*Heute\s+(\d{1,2})[:.](\d{2})\s*Uhr", re.IGNORECASE)


def _lines(text: str) -> list[str]:
    """Text lines without GLS' markup ('*bold*', rules of dashes, '>' of a forwarded mail)."""
    lines = (line.strip(" \t*>") for line in text.splitlines())
    return [line for line in lines if line and set(line) != {"-"}]


def _status(subj: str, text: str) -> ParcelStatus | None:
    lower = subj.lower()
    if _NOT_DELIVERED.search(lower):
        return None  # the GLS lookup tells what happened
    if "in wenigen tagen" in lower:
        return ParcelStatus.IN_TRANSIT
    if "kommt heute" in lower:
        return ParcelStatus.OUT_FOR_DELIVERY
    if "abgestellt" in lower and "wird" in lower:
        # Only announces the drop-off place: creates the parcel, never moves one back.
        return ParcelStatus.PRE_TRANSIT
    body = text.lower()
    if "paketshop" in lower or "abhol" in lower:
        return ParcelStatus.AWAITING_PICKUP
    if _PICKUP_TEXT.search(body) and not _HOME_TEXT.search(body):
        return ParcelStatus.AWAITING_PICKUP
    if _DELIVERED.search(lower) or (_HANDED_OVER.search(lower) and "nachbar" in lower):
        return ParcelStatus.DELIVERED
    return None


def _company(lines: list[str]) -> str | None:
    """The line after 'Versender' or 'dein Paket von [dem Absender]' as the mail has it.

    It may go on behind the company ("… OHG (AT-B2C) Erika Musterfrau"): only
    ``company_name`` makes a parcel name of it.
    """
    for label, value in zip(lines, lines[1:], strict=False):
        if label.lower() in _SENDER_LABELS:
            return value
    return None


def _eta(lines: list[str], ref: date) -> tuple[date, datetime | None, datetime | None] | None:
    """'Voraussichtliche Lieferung' / 'Freitag, 2. Oktober' / 'zwischen 10:15 und 11:45 Uhr'."""
    for index, line in enumerate(lines):
        if not line.lower().startswith(_ETA_LABEL):
            continue
        for offset, candidate in enumerate(lines[index + 1 : index + 3], start=index + 1):
            if resolved := resolve_dates(candidate.strip(" ,"), ref):
                day = resolved[0]
                window = _WINDOW.search("\n".join(lines[offset + 1 : offset + 3]))
                if not window:
                    return day, None, None
                hours = [int(part) for part in window.groups()]
                return day, at(day, hours[0], hours[1]), at(day, hours[2], hours[3])
    return None


def parse_gls_mail(msg: EmailMessage) -> list[MailUpdate]:
    """Announcement (day + window), 'kommt heute', drop-off notice or delivery."""
    subj = subject(msg)
    lines = _lines(body_text(msg))
    text = "\n".join(lines)
    status = _status(subj, text)
    direct = sender(msg)[0] == GLS_SENDER
    if not direct and (status is None or not _GLS_WORD.search(f"{subj}\n{text}")):
        return []  # a forwarded mail only counts with a GLS subject we know and the word GLS
    number = _NUMBER.search(text)
    if number and number.group(2) and not direct:
        return []  # 12 digits in a mail of anybody else say nothing (eBay item numbers)
    if not number and direct:
        number = _TRACK_LINK.search(text)
    if not number:
        return []
    sent = sent_at(msg)
    company = _company(lines)
    title = company_name(company) if company and not is_forwarded(msg) else None
    update = MailUpdate(
        number=number.group(1),
        carrier="gls",
        status=status,
        sent_at=sent,
        title=title,
        shop=shop_of(company) if company else None,
    )
    if status is ParcelStatus.DELIVERED:
        update.delivered_at = sent
    elif status is ParcelStatus.OUT_FOR_DELIVERY:
        update.eta_date = sent.date()
    elif status is ParcelStatus.IN_TRANSIT and (eta := _eta(lines, sent.date())):
        update.eta_date, update.eta_from, update.eta_to = eta
    return [update]


def _group_status(address: str, subj: str, text: str) -> ParcelStatus | None:
    lower = subj.lower()
    if _GROUP_NOT.search(lower):
        return None  # the GLS lookup tells what happened
    if address == GLS_RTT_SENDER:
        # Real-time tracking only starts once the parcel is on the delivery vehicle.
        if "auf dem weg" in lower or "ihr paket ist fast da" in text.lower():
            return ParcelStatus.OUT_FOR_DELIVERY
        return None
    if _GROUP_DELIVERED.search(lower):
        # Handed to a ParcelShop it still waits for its recipient (the lookup goes on).
        shop = "paketshop" in lower or "parcelshop" in lower
        return ParcelStatus.AWAITING_PICKUP if shop else ParcelStatus.DELIVERED
    if "ist unterwegs" in lower:
        return ParcelStatus.IN_TRANSIT
    return None


def parse_gls_group_mail(msg: EmailMessage) -> list[MailUpdate]:
    """'ist unterwegs', 'abgestellt'/'zugestellt' (with the time) and real-time tracking.

    One mail may speak for several parcels: each number it lists gets the same update.
    """
    address = sender(msg)[0]
    subj = subject(msg)
    lines = _lines(body_text(msg))
    text = "\n".join(lines)
    first = _GROUP_NUMBER.search(text) or _TRACK_LINK.search(text)
    if not first:
        return []
    numbers = [first.group(1)]
    for listed in _GROUP_MORE.finditer(text):
        for found in re.findall(r"\d{11,12}", listed.group(1)):
            if found[:11] not in numbers:  # without the check digit
                numbers.append(found[:11])
    sent = sent_at(msg)
    status = _group_status(address, subj, text)
    company = _company(lines)
    title = company_name(company) if company and not is_forwarded(msg) else None
    delivered_at = eta_date = None
    if status is ParcelStatus.DELIVERED:
        delivered_at = sent
        if time := _GROUP_TIME.search(text):
            hour, minute = int(time.group(1)), int(time.group(2))
            if hour < 24 and minute < 60:
                delivered_at = at(sent.date(), hour, minute)
    elif status is ParcelStatus.OUT_FOR_DELIVERY:
        eta_date = sent.date()
    return [
        MailUpdate(
            number=number,
            carrier="gls",
            status=status,
            sent_at=sent,
            title=title,
            eta_date=eta_date,
            delivered_at=delivered_at,
            shop=shop_of(company) if company else None,
        )
        for number in numbers
    ]

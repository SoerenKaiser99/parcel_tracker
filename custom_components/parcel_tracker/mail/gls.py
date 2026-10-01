"""GLS notification mails (no Home Assistant imports).

Only number, status, day, window and the sender company's name are taken. The drop-off
place, the delivery address, the recipient's name, the phone number and references are
never read into an update.
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
    is_forwarded,
    known_shop,
    resolve_dates,
    sender,
    sent_at,
    shop_of,
    shorten,
    subject,
)

GLS_SENDER = "no-reply@gls-pakete.de"

# 11 digits right after the label (the text part puts them on the next line).
_NUMBER = re.compile(r"(?:Paketnummer|Sendungsnummer)\s*:?\s*(\d{11})(?!\d)")
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
_SENDER_LABELS = frozenset({"versender", "dein paket von", "dein paket von dem absender"})
# A company, never a private sender: only such a name may become the parcel's name.
_LEGAL_FORM = re.compile(
    r"(?<![\w.])(?:GmbH|GMBH|AG|KG|UG|SE|OHG|GbR|Ltd\.?|e\.\s?K\.|B\.\s?V\.|S\.\s?à\s?r\.\s?l\.)"
    r"(?!\w)"
)


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
    """The line after 'Versender' or 'dein Paket von [dem Absender]'."""
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
    if not number:
        return []
    sent = sent_at(msg)
    company = _company(lines)
    named = (
        company is not None
        and not is_forwarded(msg)
        and (known_shop(company) or _LEGAL_FORM.search(company) is not None)
    )
    update = MailUpdate(
        number=number.group(1),
        carrier="gls",
        status=status,
        sent_at=sent,
        title=shorten(company) if named else None,
        shop=shop_of(company) if company else None,
    )
    if status is ParcelStatus.DELIVERED:
        update.delivered_at = sent
    elif status is ParcelStatus.OUT_FOR_DELIVERY:
        update.eta_date = sent.date()
    elif status is ParcelStatus.IN_TRANSIT and (eta := _eta(lines, sent.date())):
        update.eta_date, update.eta_from, update.eta_to = eta
    return [update]

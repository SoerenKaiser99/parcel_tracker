"""Hermes notification mails (no Home Assistant imports).

The drop-off place ("WunschAblageort …") is never read: only number, status, day,
window and the shop's name are taken.
"""

from __future__ import annotations

import re
from datetime import date
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    MailUpdate,
    at,
    body_text,
    find_numbers,
    known_shop,
    resolve_dates,
    sent_at,
    shop_of,
    shorten,
    subject,
    upcoming_date,
)

HERMES_SENDER = "noreply@paketankuendigung.myhermes.de"

_LABELLED = re.compile(r"Sendungsnummer\s*:?\s*(\d{14})\b")
_SHOP = re.compile(r"(?:Sendung|Paket) von (?P<shop>[^\n]+?)(?: wurde| kommt| ist|\.?$)", re.M)
_ETA_LABEL = re.compile(r"Voraussichtliche Zustellung:?")
_FULL_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(?!\d)")
_WINDOW = re.compile(r"zwischen\s+(\d{1,2}):(\d{2})\s+und\s+(\d{1,2}):(\d{2})\s*Uhr")


_DELIVERED = re.compile(r"\bwurde\b.*\bzugestellt\b")
_NOT_DELIVERED = re.compile(r"nicht zugestellt|konnte nicht|zustellversuch")


def _status(subj: str, text: str) -> ParcelStatus | None:
    lower = subj.lower()
    if _NOT_DELIVERED.search(lower):
        # A failed attempt says nothing reliable (a second attempt or the shop may
        # follow): no status from the mail, the Hermes API tells what happened.
        return None
    if _DELIVERED.search(lower):
        return ParcelStatus.DELIVERED
    if "auf dem weg" in lower:
        return ParcelStatus.IN_TRANSIT
    if "angekündigt" in text or "information zur zustellung" in lower:
        return ParcelStatus.PRE_TRANSIT
    return None


def _eta(text: str, ref: date) -> date | None:
    label = _ETA_LABEL.search(text)
    if not label:
        return None
    segment = text[label.end() : label.end() + 200]
    if full := _FULL_DATE.search(segment):
        try:
            return date(int(full.group(3)), int(full.group(2)), int(full.group(1)))
        except ValueError:
            return None
    if short := _DAY_MONTH.search(segment):
        return upcoming_date(int(short.group(1)), int(short.group(2)), ref)
    for line in segment.splitlines()[:3]:
        if line.strip() and (resolved := resolve_dates(line.strip(" ,"), ref)):
            return resolved[0]
    return None


def parse_hermes_mail(msg: EmailMessage) -> list[MailUpdate]:
    """Announcement, 'auf dem Weg' (day + window) or 'zugestellt'."""
    subj = subject(msg)
    text = body_text(msg)
    sent = sent_at(msg)
    both = f"{subj}\n{text}"
    numbers = [n for carrier, n in find_numbers(both) if carrier == "hermes"]
    numbers += [m.group(1) for m in _LABELLED.finditer(both)]
    if not numbers:
        return []
    status = _status(subj, text)
    shop_match = _SHOP.search(both)
    shop = shop_match.group("shop").strip() if shop_match else None
    update = MailUpdate(
        number=numbers[0],
        carrier="hermes",
        status=status,
        sent_at=sent,
        # Only a known shop becomes the name, never a private sender.
        title=shorten(shop) if shop and known_shop(shop) else None,
        shop=shop_of(shop) if shop else None,
    )
    if status is ParcelStatus.DELIVERED:
        update.delivered_at = sent
    elif status is ParcelStatus.IN_TRANSIT and (day := _eta(text, sent.date())):
        update.eta_date = day
        if window := _WINDOW.search(text):
            update.eta_from = at(day, int(window.group(1)), int(window.group(2)))
            update.eta_to = at(day, int(window.group(3)), int(window.group(4)))
    return [update]

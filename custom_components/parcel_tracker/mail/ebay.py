"""eBay order mails (no Home Assistant imports).

eBay mails carry no tracking number; 12-digit numbers are item numbers and are never
read as one. Buyer, seller and address are never taken.
"""

from __future__ import annotations

import re
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    MailUpdate,
    at,
    body_text,
    carrier_key,
    resolve_dates,
    sent_at,
    shorten,
    subject,
)

EBAY_SENDER = "ebay@ebay.com"

_DELIVERED = re.compile(r"BESTELLUNG ZUGESTELLT:\s*(?P<title>.+)$")
_ITEM = re.compile(r"^(?P<title>[^\n]+)\nArtikelnr\.:[ \t]*\n?[ \t]*\d{6,}", re.M)
_ORDER = re.compile(r"Bestellnummer:\s*(\d{2}-\d{5}-\d{5})\b")
_ETA = re.compile(r"Lieferung ca\.:[ \t]*\n?[ \t]*(?P<rest>[^\n]+)")
_HINT = re.compile(r"Versanddienstleister:[ \t]*\n?[ \t]*(?P<name>[^\n]+)")
_DROPPED = re.compile(
    r"Abgegeben am (?P<day>(?:\w+\.?,\s*)?\d{1,2}\.\s*\w+)\.?,\s*(?P<h>\d{1,2}):(?P<m>\d{2})"
)


def order_number(order: str) -> str:
    """Parcel number for an eBay order: 'EBAY' + digits."""
    return "EBAY" + order.replace("-", "")


def _status(subj: str) -> ParcelStatus | None:
    if "beim Versanddienstleister" in subj:
        return ParcelStatus.IN_TRANSIT
    if _DELIVERED.search(subj):
        return ParcelStatus.DELIVERED
    return None


def _orders(text: str) -> dict[str, list[str]]:
    """Order number -> item titles in mail order (eBay repeats every value twice)."""
    orders: dict[str, list[str]] = {}
    for item in _ITEM.finditer(text):
        order = _ORDER.search(text, item.end())
        if order:
            titles = orders.setdefault(order.group(1), [])
            if item.group("title") not in titles:
                titles.append(item.group("title"))
    for order in _ORDER.finditer(text):
        orders.setdefault(order.group(1), [])
    return orders


def _title(titles: list[str]) -> str | None:
    if not titles:
        return None
    more = len(titles) - 1
    if not more:
        return shorten(titles[0])
    suffix = f" und {more} {'weiterer' if more == 1 else 'weitere'} Artikel"
    return shorten(titles[0], 60 - len(suffix)) + suffix


def _hint(text: str) -> str | None:
    match = _HINT.search(text)
    if not match:
        return None
    name = match.group("name").strip()
    return carrier_key(name) or shorten(name, 30)


def parse_ebay(msg: EmailMessage) -> list[MailUpdate]:
    """'beim Versanddienstleister' (in transit) or 'BESTELLUNG ZUGESTELLT' (delivered)."""
    subj = subject(msg)
    status = _status(subj)
    if status is None:
        return []
    text = body_text(msg)
    sent = sent_at(msg)
    eta_date = eta_latest = None
    if (eta := _ETA.search(text)) and (resolved := resolve_dates(eta.group("rest"), sent.date())):
        eta_date, eta_latest = resolved
    delivered_at = None
    if status is ParcelStatus.DELIVERED:
        delivered_at = sent
        dropped = _DROPPED.search(text)
        if dropped and (day := resolve_dates(dropped.group("day"), sent.date())):
            delivered_at = at(day[0], int(dropped.group("h")), int(dropped.group("m")))
    subject_title = _DELIVERED.search(subj)
    fallback = shorten(subject_title.group("title").rstrip(".… ")) if subject_title else None
    return [
        MailUpdate(
            number=order_number(order),
            carrier="ebay",
            status=status,
            sent_at=sent,
            title=_title(titles) or fallback,
            eta_date=eta_date,
            eta_latest=eta_latest,
            delivered_at=delivered_at,
            shipping_carrier_hint=_hint(text),
        )
        for order, titles in _orders(text).items()
    ]

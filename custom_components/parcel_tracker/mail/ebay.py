"""eBay order mails (no Home Assistant imports).

An order begins with eBay's purchase confirmation ("Bestellt"), or with the first mail
about its shipping if that one is not read. Only "Update zur Bestellung" and
"Zustellversuch" carry the carrier's number
("Sendungsnummer: …"); it is taken when it tells its carrier on its own. 12-digit numbers
are item numbers and are never read as one. Buyer, seller and address are never taken.
"""

from __future__ import annotations

import re
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    ATTEMPT_TEXT,
    MailUpdate,
    at,
    body_text,
    carrier_for,
    carrier_key,
    resolve_dates,
    sent_at,
    shorten,
    subject,
)

EBAY_SENDER = "ebay@ebay.com"

# "📦BESTELLUNG ZUGESTELLT: …" and "📦PAKET ZUGESTELLT: …": anywhere in the subject (an emoji,
# "[EXTERN]" or "*** SPAM ***" of a mail gateway may stand in front), but only in upper case
# and with the colon, as eBay writes it ("Ihr Paket zugestellt: …" is no eBay subject)
_DELIVERED = re.compile(r"(?<![^\W\d_])(?:BESTELLUNG|PAKET) ZUGESTELLT:\s*(?P<title>.+)$")
# "Kauf … wurde abgebrochen" (the seller agreed to the buyer's request): closed if nothing
# of it left yet and it is the item the mail names above the order number (see
# ``apply._cancel_order``). The request itself ("OK - Sie möchten den Kauf abbrechen")
# tells nothing yet: the seller may say no.
_CANCELLED = re.compile(r"Kauf (?P<order>\d{2}-\d{5}-\d{5}) wurde abgebrochen")
# (eBay names the item twice, like every value: any other line above the number is none)
_CANCELLED_ITEM = re.compile(r"^(?P<title>[^\n]+)\n(?P=title)\nBestellnummer:", re.M)
_CANCEL_REQUEST = re.compile(r"Sie möchten den Kauf abbrechen")
# "Update zur Bestellung: …": the seller shipped (or is about to) and names the number.
_UPDATE = re.compile(r"Update zur Bestellung:\s*(?P<title>.+)$")
_TRACKING = re.compile(r"Sendungsnummer:[ \t]*\n?[ \t]*(?P<number>[0-9A-Z]{8,30})(?![0-9A-Z])")
# "Zustellversuch: …": the carrier met nobody ("DHL Germany hat Sie leider nicht
# angetroffen."). On its way again, no longer today; it names the number as well.
_ATTEMPT = re.compile(r"Zustellversuch:\s*(?P<title>.+)$")
# The purchase confirmation: "Bestellung bestätigt: <item>", "<buyer>, Ihre Bestellung wurde
# bestätigt." and "Ihre Bestellung wurde bestätigt"; until 2023 also "Ihre Bestellung ist
# eingegangen!" and "Kauf bestätigt: …". Only as whole words ("Verkauf bestätigt" is the
# seller's mail). The layout of the items is the one below since autumn 2023; the mails
# before it name the order and its days the same way, but list their items in lines of
# their own: only the subject's item is taken.
_CONFIRMED = re.compile(
    r"(?<![^\W\d_])(?:Bestellung|Kauf) bestätigt:\s*(?P<title>.+)$"
    r"|(?<![^\W\d_])Ihre Bestellung (?:wurde bestätigt|ist eingegangen)",
    re.IGNORECASE,
)
# Lines above an item's number that never are its title: "Einzelheiten zum Kauf ansehen" (a
# link: the "PAKET ZUGESTELLT" mail may have no title), "eBay-Käuferschutz", "Preis:", a price
# ("EUR 7,95", "2 x EUR 7,95") and the labels of the older purchase confirmations.
_NO_TITLE = (
    r"(?:Einzelheiten zum Kauf ansehen|eBay-Käuferschutz|Preis:)\n"
    r"|(?:Artikelpreis|Bestellnummer|SKU|Gesamt|Insgesamt):"
    r"|(?:\d+\s*x\s*)?EUR\s"
)
# (one layout puts "eBay-Käuferschutz", "Preis:" and the price between title and number; the
# purchase confirmation since 2026 "Preis:" and the price twice, or the total and its parts)
_ITEM = re.compile(
    rf"^(?!{_NO_TITLE})(?P<title>[^\n]+)\n"
    r"(?:(?:eBay-Käuferschutz\n)?Preis:\n(?P<price>[^\n]+)\n"
    r"(?:(?P=price)\n|(?:\d+\s*x\s*)?EUR\s[^\n]*\n)?)?"
    r"Artikelnr\.:[ \t]*\n?[ \t]*\d{6,}",
    re.M,
)
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
    # (the confirmation last: its words may stand in the item's title of a later mail)
    if "beim Versanddienstleister" in subj or _UPDATE.search(subj) or _ATTEMPT.search(subj):
        return ParcelStatus.IN_TRANSIT
    if _DELIVERED.search(subj):
        return ParcelStatus.DELIVERED
    if _CONFIRMED.search(subj):
        return ParcelStatus.PRE_TRANSIT
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


def is_cancel_request(msg: EmailMessage) -> bool:
    """The buyer asked to break off the purchase: only read, nothing changes yet."""
    return bool(_CANCEL_REQUEST.search(subject(msg)))


def parse_ebay(msg: EmailMessage) -> list[MailUpdate]:
    """'Bestellung bestätigt' and its other wordings (ordered, with the days the seller
    names), 'beim Versanddienstleister' / 'Update zur Bestellung' (in transit),
    'Zustellversuch' (in transit again, in its own words), 'BESTELLUNG ZUGESTELLT' /
    'PAKET ZUGESTELLT' (delivered) or 'Kauf … wurde abgebrochen' (cancelled). Without a
    title in the body the subject's is taken.

    The update and the attempt name the carrier's number. It goes with the order only if
    the number tells its carrier on its own (DHL "00340…"/"JJD…", UPS, Hermes "H…"): then
    the order is asked about there. 12 or 14 digits may belong to several carriers and are
    left alone.
    """
    subj = subject(msg)
    if cancelled := _CANCELLED.search(subj):
        number = order_number(cancelled.group("order"))
        # (an order of more items stays: the rest of it still comes; without the item in
        # the text it is the whole order)
        item = _CANCELLED_ITEM.search(body_text(msg))
        title = shorten(item.group("title")) if item else None
        return [MailUpdate(number, "ebay", ParcelStatus.CANCELLED, sent_at(msg), title=title)]
    status = _status(subj)
    if status is None:
        return []
    text = body_text(msg)
    sent = sent_at(msg)
    eta_date = eta_latest = None
    # (the purchase confirmation names the days twice, at its head with a sentence behind them)
    for eta in _ETA.finditer(text):
        if resolved := resolve_dates(eta.group("rest"), sent.date()):
            eta_date, eta_latest = resolved
            break
    delivered_at = None
    if status is ParcelStatus.DELIVERED:
        delivered_at = sent
        dropped = _DROPPED.search(text)
        if dropped and (day := resolve_dates(dropped.group("day"), sent.date())):
            delivered_at = at(day[0], int(dropped.group("h")), int(dropped.group("m")))
    attempt = _ATTEMPT.search(subj)
    update = _UPDATE.search(subj) or attempt
    subject_title = _DELIVERED.search(subj) or update or _CONFIRMED.search(subj)
    named = (subject_title.group("title") or "").rstrip(".… ") if subject_title else ""
    fallback = shorten(named) if named else None
    orders = _orders(text)
    tracking_ref = tracking_carrier = None
    # (a mail about several orders does not tell whose number it is)
    if update and len(orders) == 1 and (tracking := _TRACKING.search(text)):
        tracking_carrier = carrier_for(tracking.group("number"))
        tracking_ref = tracking.group("number") if tracking_carrier else None
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
            tracking_ref=tracking_ref,
            tracking_carrier=tracking_carrier,
            postponed=attempt is not None,
            status_text=ATTEMPT_TEXT if attempt else None,
        )
        for order, titles in orders.items()
    ]

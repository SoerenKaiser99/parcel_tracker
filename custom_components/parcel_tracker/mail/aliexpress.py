"""AliExpress order mails (no Home Assistant imports).

AliExpress writes one mail per step of an order ("Bestellung <number>: <step>") and, once
the parcel is with a carrier, mails about the parcel ("Packstück <carrier's number>: <step>").
The subject tells the step. Read from the body: the item name, the estimated day of
delivery, the order numbers of a mail about several orders and the carrier's number. A
parcel mail names its orders only in its links (never followed, only read); the text of
such a mail names none. Buyer, address, shop and price are never taken.
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    MailResult,
    MailUpdate,
    body_text,
    carrier_for,
    sent_at,
    shorten,
    subject,
)

ALIEXPRESS_SENDER = "transaction@notice.aliexpress.com"
ALIEXPRESS_DOMAIN = "aliexpress.com"  # every sender there is AliExpress
# Offers only ("Ihre Bestellung hat einen lokalen Boost erhalten!").
ALIEXPRESS_MARKETING_DOMAIN = "deals.aliexpress.com"
# Name of a carrier's parcel a "Packstück" mail creates when it fits no order (like
# "Amazon-Sendung (DHL)"): it names the shop, so ``fold_delivered`` finds the order later.
PARCEL_NAME = "AliExpress-Sendung"

_PRE = ParcelStatus.PRE_TRANSIT
_ON_WAY = ParcelStatus.IN_TRANSIT
# The step behind "Bestellung <number>": (status, AliExpress's own words or None for the
# usual text of the status).
_ORDER_STEPS: dict[str, tuple[ParcelStatus, str | None]] = {
    "bestellauftrag bestätigt": (_PRE, None),
    "bestellbestätigung": (_PRE, None),
    "versandfertig": (_PRE, "Versandbereit"),
    "versandbereit": (_PRE, "Versandbereit"),
    "bestellung versandt": (_ON_WAY, None),
    "wurde versandt": (_ON_WAY, None),
    "teilweise versandt": (_ON_WAY, "Teilweise versandt"),
    "paket im transit": (_ON_WAY, "Paket im Transit"),
    # (the step of a parcel mail, told for the order instead of the parcel)
    "vom kurier abgeholt": (_ON_WAY, "Vom Kurier abgeholt"),
    "in ihrem land / ihrer region angekommen": (_ON_WAY, "Im Zielland angekommen"),
    # (the body only says that there is news)
    "neuer lieferstatus": (_ON_WAY, None),
}
# "Wird zugestellt" comes hours after the shipping mail and its body says "dem
# Versandunternehmen übergeben": handed to the carrier, not on the last mile.
_HANDED_OVER = "wird zugestellt"
_HANDED_OVER_BODY = re.compile(r"dem\s+Versandunternehmen\s+übergeben")
HANDED_OVER_TEXT = "Dem Versandunternehmen übergeben"
# A reminder ("wird in Kürze als abgeschlossen markiert") and the request for a rating
# tell nothing about the parcel.
_NO_NEWS = frozenset({"auf bestätigung wird gewartet", "wie war ihr einkaufserlebnis?"})
# "wie ist es gelaufen?": a survey, but its body confirms the delivery.
_SURVEY = "wie ist es gelaufen?"
_CONFIRMED = re.compile(r"Wir haben die Lieferung Ihrer Bestellung\s+\d+\s+bestätigt")
CONFIRMED_TEXT = "Lieferung bestätigt"
# The step of a parcel mail, all on the way: AliExpress's words for the history (None
# for a mail that tells no step of its own).
_PARCEL_STEPS: dict[str, str | None] = {
    "hat die abflugregion verlassen": "Abflugregion verlassen",
    "vom kurier abgeholt": "Vom Kurier abgeholt",
    "in ihrem land / ihrer region": "Im Zielland angekommen",
    # (the body only says that there is news from the country of departure)
    "hat eine aktualisierung": None,
}
CUSTOMS_TEXT = "Zollabfertigung beendet"

_ORDER_SUBJECT = re.compile(r"Bestellung (?P<order>\d{12,20})\s*:?\s*(?P<step>\S.*)")
_ORDERS_SUBJECT = re.compile(r"\d+ Bestellungen wurden bestätigt: (?P<order>\d{12,20})\b")
_PARCEL_SUBJECT = re.compile(r"Packstück (?P<number>[0-9A-Z]{8,30})\s*:?\s*(?P<step>\S.*)")
_CUSTOMS_SUBJECT = re.compile(r"Zollabfertigung für (?P<number>[0-9A-Z]{8,30}) wurde beendet")
# English, whatever the language of the account; its body tells no reason (cancelled,
# refunded or done), so nothing is taken from it.
_CLOSED_SUBJECT = re.compile(r"Your order \d+ is closed")

_URL = re.compile(r"[\[<(]*https?://\S+")
# "x2" below an item, "€ 3,99x2" in the layout with prices; "<variant> x2" on one line.
_QUANTITY = re.compile(r"(?:€ ?[\d.,]+ ?)?x\d+")
_VARIANT_QUANTITY = re.compile(r"\S.* x\d+")
_PLACED = "Aufgegeben am"
_ORDER_LINE = re.compile(r"Bestellung (\d{13,22})")  # running number + order number
_ORDER_LABEL = "Bestell-Nr."
_DIGITS = re.compile(r"\d{12,20}")
# Lines that stand right above the first item of a mail (never an item's name).
_ABOVE_ITEMS = frozenset(
    {
        "paketinfos",
        "bestellung verfolgen",
        "sendungsverfolgung",
        "lieferung verfolgen",
        "empfang bestätigen",
        "bewertung schreiben",
        "bestellung prüfen",
        "bestelldetails",
        "bestelldetails anzeigen",
        "details anzeigen",
        "aktualisierung anzeigen",
        "bestätigt",
        "verpackt",
        "versandt",
        "im transit",
        "zugestellt",
    }
)
_ETA = re.compile(r"^Voraussichtliche Zustellzeit\n(\d{1,2})/(\d{1,2})/(\d{4})$", re.MULTILINE)
_TRACKING = re.compile(r"Sendungsverfolgungsnummer lautet ([0-9A-Z]{8,30})\b")
# The orders of a parcel stand only in its links (several in one: "o_ids=1,2").
_LINK_ORDERS = re.compile(r"[?&](?:tradeOrderId|o_ids|orderId)=(\d+(?:(?:,|%2C)\d+)*)", re.I)


def order_number(order: str) -> str:
    """Parcel number for an AliExpress order: 'ALI' + digits."""
    return "ALI" + order


def _lines(text: str) -> list[str]:
    """The lines of a body that say something: no links, no empty lines, no lone dots."""
    lines = (_URL.sub("", line).strip() for line in text.splitlines())
    return [line for line in lines if line and line != "."]


def _name(raw: str) -> str | None:
    """An item's name as a title; AliExpress cuts it with "..." (None if nothing is left)."""
    core = raw.rstrip(" .…")
    if not core:
        return None
    return shorten(f"{core}…" if core != raw.strip() else core)


def _title(names: list[str]) -> str | None:
    """Title of an order from its item names (each name once)."""
    names = list(dict.fromkeys(names))
    if not names:
        return None
    more = len(names) - 1
    if not more:
        return names[0]
    suffix = f" und {more} {'weiterer' if more == 1 else 'weitere'} Artikel"
    return shorten(names[0], 60 - len(suffix)) + suffix


def _above_items(lines: list[str], index: int) -> bool:
    """True if this line is none of an item: a quantity, a label, an order or a shop line."""
    line = lines[index]
    return (
        _QUANTITY.fullmatch(line) is not None
        or _VARIANT_QUANTITY.fullmatch(line) is not None
        or line.lower() in _ABOVE_ITEMS
        or _ORDER_LINE.fullmatch(line) is not None
        # the shop's name stands below the day of the order
        or (index > 0 and lines[index - 1].startswith(_PLACED))
    )


def _item_names(lines: list[str]) -> list[str]:
    """The names of the items in ``lines``.

    An item is its name, mostly a variant and then the quantity ("x2"); the name is found
    from the quantity upwards. The shop's line is never a name.
    """
    names = []
    for index, line in enumerate(lines):
        if _QUANTITY.fullmatch(line):
            # name, variant, quantity; without a variant the name stands right above
            rows = (index - 2, index - 1)
        elif _VARIANT_QUANTITY.fullmatch(line):
            rows = (index - 1,)
        else:
            continue
        if rows[0] < 0 or _above_items(lines, rows[-1]):
            continue  # a quantity without an item above it
        row = rows[0] if not _above_items(lines, rows[0]) else rows[-1]
        if name := _name(lines[row]):
            names.append(name)
    return names


def _orders(lines: list[str], subject_order: str) -> dict[str, str | None]:
    """Order number -> title for every order of a mail, in mail order.

    A mail about several orders lists each with its items: below "Bestellung <running
    number><order number>" (the confirmation of several orders) or above "Bestell-Nr."
    (also a combined delivery). Any other mail is about the order its subject names.
    """
    orders: dict[str, str | None] = {}
    starts = [index for index, line in enumerate(lines) if _ORDER_LINE.fullmatch(line)]
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        # (the running number stands right in front of the order number)
        order = lines[start].split()[-1][-len(subject_order) :]
        orders.setdefault(order, _title(_item_names(lines[start:end])))
    if orders:
        return orders
    above = 0
    for index, line in enumerate(lines[:-1]):
        if line == _ORDER_LABEL and _DIGITS.fullmatch(lines[index + 1]):
            block = lines[above:index]
            placed = [row for row, text in enumerate(block) if text.startswith(_PLACED)]
            items = block[placed[-1] :] if placed else block
            orders.setdefault(lines[index + 1], _title(_item_names(items)))
            above = index + 2
    if not orders:
        return {subject_order: _title(_item_names(lines))}
    return orders if subject_order in orders else {subject_order: None, **orders}


def _eta(text: str, sent: date) -> date | None:
    """The day below "Voraussichtliche Zustellzeit" (day/month/year)."""
    found = _ETA.search(text)
    if not found:
        return None
    try:
        day = date(int(found.group(3)), int(found.group(2)), int(found.group(1)))
    except ValueError:
        return None
    # A day long gone is no estimate (an old mail, or the other order of day and month).
    return day if day >= sent - timedelta(days=7) else None


def _order_step(step: str, text: str) -> tuple[ParcelStatus, str | None] | None:
    """(status, own words) of the step an order mail names; None for one we do not know."""
    key = " ".join(step.lower().split())
    if key == _HANDED_OVER:
        if _HANDED_OVER_BODY.search(text):
            return _ON_WAY, HANDED_OVER_TEXT
        return ParcelStatus.OUT_FOR_DELIVERY, None
    return _ORDER_STEPS.get(key)


def _order_mail(msg: EmailMessage, order: str, step: str) -> MailResult:
    text = "\n".join(_lines(body_text(msg)))
    key = " ".join(step.lower().split())
    if key in _NO_NEWS:
        return MailResult(ignored=True)
    sent = sent_at(msg)
    if key == _SURVEY:
        if not _CONFIRMED.search(text):
            return MailResult(ignored=True)
        status, words, confirmation = ParcelStatus.DELIVERED, CONFIRMED_TEXT, True
    elif found := _order_step(step, text):
        (status, words), confirmation = found, False
    else:
        return MailResult()
    tracking_ref = tracking_carrier = None
    # (a combined delivery names the carrier's number in its text)
    if (named := _TRACKING.search(text)) and (carrier := carrier_for(named.group(1))):
        tracking_ref, tracking_carrier = named.group(1), carrier
    eta = _eta(text, sent.date()) if status is not ParcelStatus.DELIVERED else None
    return MailResult(
        updates=[
            MailUpdate(
                number=order_number(number),
                carrier="aliexpress",
                status=status,
                sent_at=sent,
                title=title,
                eta_date=eta,
                delivered_at=sent if status is ParcelStatus.DELIVERED else None,
                tracking_ref=tracking_ref,
                tracking_carrier=tracking_carrier,
                status_text=words,
                confirmation=confirmation,
            )
            for number, title in _orders(text.splitlines(), order).items()
        ]
    )


def _link_orders(msg: EmailMessage) -> list[str]:
    """The order numbers the links of a mail name, first occurrence first."""
    orders: list[str] = []
    for part in msg.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):
            content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        for listed in _LINK_ORDERS.findall(html.unescape(content)):
            for order in _DIGITS.findall(listed):
                if order not in orders:
                    orders.append(order)
    return orders


def _parcel_mail(msg: EmailMessage, number: str, words: str | None) -> MailResult:
    """A mail about the parcel at the carrier ("Packstück …", "Zollabfertigung für …").

    Its orders (the links name them) get the status and, if the number is one of a
    carrier we know, that number: the order is followed at the carrier then. A number in
    an unknown format (AliExpress's own, Cainiao) is dropped: no order may wait for a
    carrier nobody can ask. Without an order in the links the mail is a carrier's mail
    about an AliExpress shipment: merged into the one order that fits, else a parcel of
    its own; with an unknown number only the status is left, for the one order that fits.
    """
    sent = sent_at(msg)
    carrier = carrier_for(number)
    orders = _link_orders(msg)
    names = _item_names(_lines(body_text(msg)))
    if not orders:
        return MailResult(
            updates=[
                MailUpdate(
                    number=number if carrier else "",
                    carrier=carrier or "aliexpress",
                    status=_ON_WAY,
                    sent_at=sent,
                    title=PARCEL_NAME if carrier else None,
                    shop="aliexpress",
                    status_text=words,
                )
            ]
        )
    return MailResult(
        updates=[
            MailUpdate(
                number=order_number(order),
                carrier="aliexpress",
                status=_ON_WAY,
                sent_at=sent,
                # (which item belongs to which order is not told)
                title=_title(names) if len(orders) == 1 else None,
                tracking_ref=number if carrier else None,
                tracking_carrier=carrier,
                status_text=words,
            )
            for order in orders
        ]
    )


def parse_aliexpress(msg: EmailMessage) -> MailResult:
    """Any mail of AliExpress: updates, ignored, or (no updates) unrecognised.

    Order mails: confirmed and ready to ship ("Bestellt"), shipped and on its way
    ("Versendet", with AliExpress's words for the step), delivery confirmed. Parcel mails:
    see ``_parcel_mail``. Ignored: reminders, requests for a rating and "Your order … is
    closed". A subject nobody knows yet is unrecognised, so it gets noticed.
    """
    subj = subject(msg)
    if _CLOSED_SUBJECT.match(subj):
        return MailResult(ignored=True)
    if found := _CUSTOMS_SUBJECT.match(subj):
        return _parcel_mail(msg, found.group("number"), CUSTOMS_TEXT)
    if found := _PARCEL_SUBJECT.match(subj):
        step = " ".join(found.group("step").lower().split())
        if step not in _PARCEL_STEPS:
            return MailResult()
        return _parcel_mail(msg, found.group("number"), _PARCEL_STEPS[step])
    if found := _ORDERS_SUBJECT.match(subj):
        return _order_mail(msg, found.group("order"), "Bestellauftrag bestätigt")
    if found := _ORDER_SUBJECT.match(subj):
        return _order_mail(msg, found.group("order"), found.group("step"))
    return MailResult()

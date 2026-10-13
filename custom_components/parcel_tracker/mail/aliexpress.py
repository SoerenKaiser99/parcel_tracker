"""AliExpress order mails (no Home Assistant imports).

AliExpress writes one mail per step of an order ("Bestellung <number>: <step>") and, once
the parcel is with a carrier, mails about the parcel ("Packstück <carrier's number>: <step>").
The subject tells the step. Read from the body: the item name, the estimated day of
delivery, the order numbers of a mail about several orders and the carrier's number. A
parcel mail names its orders only in its links (never followed, only read); the text of
such a mail names none. Buyer, address, shop and price are never taken.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlsplit

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
    # (the steps of the mails of autumn 2024)
    "verzollt": (_ON_WAY, "Verzollt"),
    "im lieferzentrum": (_ON_WAY, "Im Lieferzentrum"),
    # ("wird in Kürze ausgeliefert": soon, no day)
    "zur auslieferung bereit": (_ON_WAY, "Zur Auslieferung bereit"),
    "zugestellt": (ParcelStatus.DELIVERED, None),
}
# "Bestellung <number>: Wird zugestellt" comes hours after the shipping mail and its body
# says "dem Versandunternehmen übergeben": handed to the carrier, not on the last mile. No
# mail seen so far tells the last mile under this subject, so it is never "in Zustellung":
# without that sentence the order is simply on its way. (The mail about a parcel, "Paket
# <number> wird zugestellt", is another one: see _PACKAGE_STEPS.)
_HANDED_OVER = "wird zugestellt"
_HANDED_OVER_BODY = re.compile(r"dem\s+Versandunternehmen\s+übergeben")
HANDED_OVER_TEXT = "Dem Versandunternehmen übergeben"
# A reminder ("wird in Kürze als abgeschlossen markiert") and the request for a rating
# tell nothing about the parcel.
_NO_NEWS = frozenset({"auf bestätigung wird gewartet", "wie war ihr einkaufserlebnis?"})
# "wie ist es gelaufen?": a survey, but its body confirms the delivery of the order it
# names. That is AliExpress's word, not an arrival anybody saw (the same mail goes on "Wenn
# Sie den Artikel immer noch nicht erhalten haben …"): see ``MailUpdate.confirmation``.
_SURVEY = "wie ist es gelaufen?"
_CONFIRMED = re.compile(r"Wir haben die Lieferung Ihrer Bestellung\s+(\d+)\s+bestätigt")
CONFIRMED_TEXT = "Lieferung bestätigt (laut AliExpress)"
# The step of a parcel mail, all on the way: AliExpress's words for the history (None
# for a mail that tells no step of its own).
_PARCEL_STEPS: dict[str, str | None] = {
    "hat die abflugregion verlassen": "Abflugregion verlassen",
    "vom kurier abgeholt": "Vom Kurier abgeholt",
    "in ihrem land / ihrer region": "Im Zielland angekommen",
    "im zielland / in der zielregion": "Im Zielland angekommen",
    "mit lokalem kurier": "Dem lokalen Kurier übergeben",
    # (the body only says that there is news from the country of departure)
    "hat eine aktualisierung": None,
}
CUSTOMS_TEXT = "Zollabfertigung beendet"
# "Paket <number> ist versandbereit" / "… wird zugestellt" (on the last mile: in nine of
# ten mails seen "… wurde zugestellt" followed two to five hours later, once the day
# after) / "… wurde zugestellt": (status, own words).
_PACKAGE_STEPS: dict[str, tuple[ParcelStatus, str | None]] = {
    "ist versandbereit": (_PRE, "Versandbereit"),
    "wird zugestellt": (ParcelStatus.OUT_FOR_DELIVERY, None),
    "wurde zugestellt": (ParcelStatus.DELIVERED, None),
}
# "Lieferprobleme für Packstück <number>": it could not be delivered; what follows is told
# by the next mail.
PROBLEM_TEXT = "Lieferprobleme"
# Mails that tell nothing about a parcel on its way: a note that there is news (the links
# name the parcels), a coupon for a late delivery, returns and refunds.
_NO_NEWS_SUBJECT = re.compile(
    r"\d+ Packstück\(e\) haben Lieferneuigkeiten|Ihr Verspätete-Lieferung-Coupon-Code"
    r"|Your delayed delivery coupon code|Warte auf Ihr Feedback"
    r"|Order \d+: Waiting for your return|Überprüfen Sie den Rückerstattungsantragsprozess",
    re.IGNORECASE,
)

_ORDER_SUBJECT = re.compile(r"Bestellung (?P<order>\d{12,20})\s*:?\s*(?P<step>\S.*)")
_ORDERS_SUBJECT = re.compile(r"\d+ Bestellungen wurden bestätigt: (?P<order>\d{12,20})\b")
_PARCEL_SUBJECT = re.compile(r"Packstück (?P<number>[0-9A-Z]{8,30})\s*:?\s*(?P<step>\S.*)")
_CUSTOMS_SUBJECT = re.compile(r"Zollabfertigung für (?P<number>[0-9A-Z]{8,30}) wurde beendet")
_PACKAGE_SUBJECT = re.compile(r"Paket (?P<number>[0-9A-Z]{8,30})\s+(?P<step>\S.*)")
_PROBLEM_SUBJECT = re.compile(r"Lieferprobleme für Packstück (?P<number>[0-9A-Z]{8,30})\b")
# English, whatever the language of the account; its body tells no reason (cancelled,
# refunded or done), so nothing is taken from it.
_CLOSED_SUBJECT = re.compile(r"Your order \d+ is closed")

# (the brackets in front of a link go with it; looked for from the first bracket of a run
# only, so a long run of brackets without a link is read once, not once per bracket)
_URL = re.compile(r"(?<![\[<(])[\[<(]*https?://\S+")
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
# Lines that are no item's name wherever they stand: a greeting, a line with a phone
# number (the recipient), a day, the labels around the address.
_NO_ITEM = re.compile(
    r"^(?:hallo|hi|hey|dear|liebe[rs]?|guten\s+tag)(?=[\s,!]|$)"
    r"|\(\+\d+\)|\+\d{2}[\d ]{6,}"
    r"|\b\d{1,2}/\d{1,2}/\d{4}\b"
    r"|^(?:aufgegeben am|voraussichtliche zustellzeit|versand nach|bestell-nr\.|bestellsumme"
    r"|gesamtbetrag|zahlungsmethode)",
    re.IGNORECASE,
)
_ETA = re.compile(r"^Voraussichtliche Zustellzeit\n(\d{1,2})/(\d{1,2})/(\d{4})$", re.MULTILINE)
_TRACKING = re.compile(r"Sendungsverfolgungsnummer lautet ([0-9A-Z]{8,30})\b")
# The orders of a parcel stand only in its links (several in one: "o_ids=1,2"): in these
# parameters of a link to AliExpress itself.
_LINK_HOST = "aliexpress.com"
_LINK_PARAMS = frozenset({"tradeorderid", "o_ids", "orderid"})
_PLAIN_LINK = re.compile(r"https?://[^\s<>\"'\[\]()]+")
# More orders than this in one mail are no parcel's orders: the mail is told like one
# that names none.
MAX_LINK_ORDERS = 20


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

    An item is its name, mostly a variant and then the quantity ("x2"). The name is found
    from the quantity upwards, and only where a layout puts it: right below a line that is
    none of an item (a label, the shop's line, an order line, the quantity of the item
    before). Anything else has no name: no title is better than a wrong one, and a
    greeting, the recipient's line or a day never is one.
    """
    names = []
    for index, line in enumerate(lines):
        if _QUANTITY.fullmatch(line):
            # the name stands right above, or above the variant
            rows = (index - 1, index - 2)
        elif _VARIANT_QUANTITY.fullmatch(line):
            rows = (index - 1,)
        else:
            continue
        row = next((r for r in rows if r >= 1 and _above_items(lines, r - 1)), None)
        if row is None or _above_items(lines, row) or _NO_ITEM.search(lines[row]):
            continue
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
        return _ON_WAY, HANDED_OVER_TEXT if _HANDED_OVER_BODY.search(text) else None
    return _ORDER_STEPS.get(key)


def _order_mail(msg: EmailMessage, order: str, step: str) -> MailResult:
    text = "\n".join(_lines(body_text(msg)))
    key = " ".join(step.lower().split())
    if key in _NO_NEWS:
        return MailResult(ignored=True)
    sent = sent_at(msg)
    if key == _SURVEY:
        confirmed = _CONFIRMED.search(text)
        # (only the order of this mail: a sentence about another one confirms nothing)
        if not confirmed or confirmed.group(1) != order:
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
    orders = _orders(text.splitlines(), order)
    if confirmation:
        orders = {order: orders.get(order)}
    return MailResult(
        updates=[
            MailUpdate(
                number=order_number(number),
                carrier="aliexpress",
                status=status,
                sent_at=sent,
                title=title,
                eta_date=eta,
                # (the step "zugestellt" tells when; a confirmation proves no arrival)
                delivered_at=(
                    sent if status is ParcelStatus.DELIVERED and not confirmation else None
                ),
                tracking_ref=tracking_ref,
                tracking_carrier=tracking_carrier,
                status_text=words,
                confirmation=confirmation,
            )
            for number, title in orders.items()
        ]
    )


class _Hrefs(HTMLParser):
    """The targets of the links (``<a href>``) of an HTML text."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.found += [value for name, value in attrs if name == "href" and value]


def _links(part: EmailMessage) -> list[str]:
    """The links of one text part: ``href`` of an HTML part, the addresses in a text."""
    try:
        content = part.get_content()
    except (LookupError, ValueError):
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if part.get_content_type() == "text/plain":
        return _PLAIN_LINK.findall(content)
    parser = _Hrefs()
    try:
        parser.feed(content)
        parser.close()
    except (AssertionError, ValueError):  # broken markup: what was read so far
        pass
    return parser.found


def _link_orders(msg: EmailMessage) -> list[str]:
    """The order numbers the links of a mail name, first occurrence first.

    Read only from links to AliExpress itself (aliexpress.com and its sub-domains), from
    the parameters that name orders; a list is split at its commas and every value must
    be an order number as a whole. Nothing else counts: no other host, no text or other
    attribute that looks like a link, no link inside a link (it stays encoded), no part
    of a longer run of digits. More than MAX_LINK_ORDERS orders are none at all.
    """
    orders: list[str] = []
    for part in msg.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        for link in _links(part):
            try:
                url = urlsplit(link.strip())
                host = (url.hostname or "").lower()
            except ValueError:
                continue
            if url.scheme not in ("http", "https"):
                continue
            if host != _LINK_HOST and not host.endswith("." + _LINK_HOST):
                continue
            for name, listed in parse_qsl(url.query):
                if name.lower() not in _LINK_PARAMS:
                    continue
                for order in listed.split(","):
                    if _DIGITS.fullmatch(order) and order not in orders:
                        orders.append(order)
    return orders if len(orders) <= MAX_LINK_ORDERS else []


def _parcel_mail(
    msg: EmailMessage,
    number: str,
    words: str | None,
    status: ParcelStatus = _ON_WAY,
    postponed: bool = False,
) -> MailResult:
    """A mail about the parcel at the carrier ("Packstück …", "Paket …", "Zollabfertigung …").

    Its orders (the links name them) get the status and, if the number is one of a
    carrier we know, that number: the order is followed at the carrier then. A number in
    an unknown format (AliExpress's own, Cainiao) is dropped: no order may wait for a
    carrier nobody can ask. Without an order in the links the mail is a carrier's mail
    about an AliExpress shipment: merged into the one order that fits, else a parcel of
    its own; with an unknown number only the status is left, for the one order that fits.
    "In delivery" is the day of the mail, "delivered" the time it was sent. A mail without
    an order names no day: it has to find its order by the status alone. ``postponed``: the
    mail may take its order back from "in Zustellung" (a failed delivery).
    """
    sent = sent_at(msg)
    when: dict[str, date | datetime] = {}
    if status is ParcelStatus.OUT_FOR_DELIVERY:
        when = {"eta_date": sent.date()}
    elif status is ParcelStatus.DELIVERED:
        when = {"delivered_at": sent}
    carrier = carrier_for(number)
    orders = _link_orders(msg)
    names = _item_names(_lines(body_text(msg)))
    if not orders:
        when.pop("eta_date", None)
        return MailResult(
            updates=[
                MailUpdate(
                    number=number if carrier else "",
                    carrier=carrier or "aliexpress",
                    status=status,
                    **when,
                    sent_at=sent,
                    title=PARCEL_NAME if carrier else None,
                    shop="aliexpress",
                    status_text=words,
                    postponed=postponed,
                )
            ]
        )
    return MailResult(
        updates=[
            MailUpdate(
                number=order_number(order),
                carrier="aliexpress",
                status=status,
                **when,
                sent_at=sent,
                # (which item belongs to which order is not told)
                title=_title(names) if len(orders) == 1 else None,
                tracking_ref=number if carrier else None,
                tracking_carrier=carrier,
                status_text=words,
                postponed=postponed,
            )
            for order in orders
        ]
    )


def parse_aliexpress(msg: EmailMessage) -> MailResult:
    """Any mail of AliExpress: updates, ignored, or (no updates) unrecognised.

    Order mails: confirmed and ready to ship ("Bestellt"), shipped and on its way
    ("Versendet", with AliExpress's words for the step), delivered, delivery confirmed.
    Parcel mails: see ``_parcel_mail``. Ignored: reminders, requests for a rating, "Your
    order … is closed" and the mails that tell nothing about a parcel on its way (news
    without a number, a coupon, returns and refunds). A subject nobody knows yet is
    unrecognised, so it gets noticed.
    """
    subj = subject(msg)
    if _CLOSED_SUBJECT.match(subj):
        return MailResult(ignored=True)
    if _NO_NEWS_SUBJECT.match(subj):
        return MailResult(ignored=True)
    if found := _CUSTOMS_SUBJECT.match(subj):
        return _parcel_mail(msg, found.group("number"), CUSTOMS_TEXT)
    if found := _PROBLEM_SUBJECT.match(subj):
        return _parcel_mail(msg, found.group("number"), PROBLEM_TEXT, postponed=True)
    if found := _PACKAGE_SUBJECT.match(subj):
        step = _PACKAGE_STEPS.get(" ".join(found.group("step").lower().split()))
        if step is None:
            return MailResult()
        return _parcel_mail(msg, found.group("number"), step[1], step[0])
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

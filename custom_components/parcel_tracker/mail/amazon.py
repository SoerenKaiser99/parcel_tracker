"""Amazon order mails (no Home Assistant imports)."""

from __future__ import annotations

import re
from datetime import date, datetime
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    ATTEMPT_TEXT,
    DELAY_TEXT,
    MONTHS,
    MailUpdate,
    at,
    body_text,
    carrier_for,
    relative_day,
    resolve_dates,
    sent_at,
    shorten,
    subject,
    title_key,
    upcoming_date,
)

SHIPPING_SENDER = "versandbestaetigung@amazon.de"
AMAZON_SENDERS = frozenset(
    {
        "bestellbestaetigung@amazon.de",
        SHIPPING_SENDER,
        "shipment-tracking@amazon.de",
        "order-update@amazon.de",
    }
)
# Old "… wurde versandt!" subjects (before ~2021), in two wordings.
LEGACY_PREFIXES = ("Ihre Amazon.de Bestellung von", "Ihre Amazon.de-Bestellung mit")
# The same layout came back later ("Deine Amazon.de-Bestellung mit … wurde versandt!", up
# to 2025; "Versendet: Für diese Amazon Lieferung ist ein Einmalpasswort erforderlich"):
# a mail of SHIPPING_SENDER the current parser finds no order in is read this way.
# "Versuchte Zustellung: …": nobody was met. The order is on its way again and no longer
# comes today; a later mail tells the next attempt or where the parcel waits. ("Zustellversuch:
# …" is the same mail in the wording of 2026.)
_ATTEMPT = "versuchte zustellung"
_ATTEMPTS = (f"{_ATTEMPT}:", "zustellversuch:")
# "Lieferungsaktualisierung: …": on its way, with a new day ("Jetzt erwartet bis zum 26.
# April."). Only a mail that says so is a delay ("… verspätet sich aber. Bitte entschuldigen
# Sie die Verzögerung."): the subject and a new day alone would also fit an earlier arrival.
# ("… ist nicht verspätet" is none.)
_DELAY = "lieferungsaktualisierung"
_DELAYED = re.compile(r"(?<!nicht )\b(?:verspät|verzöger)\w*", re.IGNORECASE)

_PREFIXES = {
    "bestellt": ParcelStatus.PRE_TRANSIT,
    "versendet": ParcelStatus.IN_TRANSIT,
    "versandt": ParcelStatus.IN_TRANSIT,
    _ATTEMPT: ParcelStatus.IN_TRANSIT,
    "zustellversuch": ParcelStatus.IN_TRANSIT,
    _DELAY: ParcelStatus.IN_TRANSIT,
    "in zustellung": ParcelStatus.OUT_FOR_DELIVERY,
    "unterwegs zur zustellung": ParcelStatus.OUT_FOR_DELIVERY,
    "zur auslieferung": ParcelStatus.OUT_FOR_DELIVERY,
    "zustellung heute": ParcelStatus.OUT_FOR_DELIVERY,
    "geliefert": ParcelStatus.DELIVERED,
    "zugestellt": ParcelStatus.DELIVERED,
}
_STAGES = {
    1: ParcelStatus.PRE_TRANSIT,
    2: ParcelStatus.IN_TRANSIT,
    3: ParcelStatus.OUT_FOR_DELIVERY,
    4: ParcelStatus.DELIVERED,
}
# An ASCII '"' inside the title (27" monitor) is kept as long as a typographic
# closing quote still follows; otherwise it closes the title.
_QUOTED = re.compile(
    r"^[^:]+:\s*(?:\d+\s*)?[„\"“](?P<title>(?:[^“\"”]|\"(?=[^“”]*[“”]))+)[“\"”]"
    r"(?:\s*und\s+(?P<more>\d+)\s+(?:weitere[r]?|mehr)\s+Artikel)?"
)
# ("Bestellung #…" in the plain layout of the delivery, delay and password mails)
_ORDER = re.compile(
    r"^(?:Bestellnr\.\s*|(?P<plain>Bestellung #))(\d{3}-\d{7}-\d{7})\s*$", re.MULTILINE
)
# The plain layout: "Ihr Paket mit <item> wird zugestellt." / "Ihr Amazon Paket wird
# zugestellt." tells the status (the subject is the item's name, or "Zustellung heute: …").
_ON_THE_ROUTE = re.compile(
    r"^Ihr (?:Amazon )?Paket(?: mit \S.*)? wird zugestellt\.?$", re.MULTILINE
)
_LATER = re.compile(r"Jetzt erwartet bis zum (\d{1,2}\.\s*[A-Za-zä]+)")
# The plain layout names an item with its quantity before it ("2 x …", "2-mal …"), below
# the number and, without quotes, in the subject ("2 x Beispiel... und 2 weiteren
# Artikeln"). The other mails of the order name it without the quantity.
_QUANTITY = re.compile(r"^\d+\s*(?:x|-mal)\s+", re.IGNORECASE)
_PLAIN_MORE = re.compile(r"\s+und\s+\d+\s+weiteren?\s+Artikeln?\s*$")
# An item below its order number: "[title]<link>" in a mail whose text was made from the
# HTML, "* title" in the text part Amazon writes itself.
_ITEM = re.compile(r"^(?:\[(?P<title>[^\]]+)\]<https?://|\* (?P<listed>\S.*)$)", re.MULTILINE)
_ETA = re.compile(
    r"^(?:Ankunft|Zustellung)\s+(?P<day>heute|morgen)"
    r"(?:\s+(?P<h1>\d{1,2})(?:[:.](?P<m1>\d{2}))?\s*h?\s*[–-]\s*"
    r"(?P<h2>\d{1,2})(?:[:.](?P<m2>\d{2}))?\s*h?(?:\s*Uhr)?)?$",
    re.MULTILINE,
)
_ETA_DATES = re.compile(r"^(?:Zustellung:|Ankunft:?)\s+(?P<rest>\S.*)$", re.MULTILINE)
_OTP = re.compile(r"Einmalpasswort lautet\s*(\d{4,8})\b")
_LEGACY_ORDER = re.compile(r"Bestellnummer:\s*#?(\d{3}-\d{7}-\d{7})")
_LEGACY_NUMBER = re.compile(r"Paketverfolgungsnummern?:\s*([0-9A-Z]{10,30})")
_LEGACY_ETA = re.compile(r"^Zustellung:\s*\n\w+,\s*(\d{1,2})\.?\s*([A-Za-zä]+)", re.MULTILINE)
_LEGACY_MORE = re.compile(r"\"\s*und\s+(\d+)\s+weiteren\s+Artikel")
_LEGACY_HERMES = re.compile(r"mit Hermes versandt")
# The sentence of the old layout: "… dass wir deine Bestellung versandt haben." / "… dass
# <seller> deine Bestellung verschickt hat." / "… einen Teil deiner Bestellung verschicken
# konnten." / "… die letzte Lieferung aus deiner Bestellung nun versandt haben."
_LEGACY_SHIPPED = re.compile(
    r"\b(?:deiner?|Ihrer?) Bestellung\b[^.\n]{0,20}?"
    r"\b(?:versandt haben|verschickt hat|verschicken konnten)\b"
)
_HERMES_14 = re.compile(r"\d{14}")


def order_number(order: str) -> str:
    """Parcel number for an Amazon order: 'AMZ' + digits."""
    return "AMZ" + order.replace("-", "")


def subject_title(subj: str) -> str | None:
    """Item title from the subject, incl. 'und N weitere Artikel'."""
    match = _QUOTED.match(subj)
    if not match:
        return None
    raw = match.group("title").strip()
    core = raw.rstrip(".…").strip()
    title = f"{core}…" if core != raw else core
    if more := match.group("more"):
        title += f" und {more} {'weiterer' if more == '1' else 'weitere'} Artikel"
    return shorten(title)


def subject_status(subj: str) -> ParcelStatus | None:
    """Status from the subject prefix before ':'."""
    if ":" not in subj:
        return None
    return _PREFIXES.get(subj.split(":", 1)[0].strip().lower())


def stage_status(text: str) -> ParcelStatus | None:
    """Status from the '[Abgeschlossen]' stage lines."""
    done = len(re.findall(r"^\[Abgeschlossen\]$", text, re.MULTILINE))
    if done:
        return _STAGES.get(done)
    if "Dein Paket wurde zugestellt" in text:
        return ParcelStatus.DELIVERED
    if _ON_THE_ROUTE.search(text):
        return ParcelStatus.OUT_FOR_DELIVERY
    return None


def _eta(text: str, sent: datetime) -> dict[str, date | datetime | None]:
    """The delivery day ``text`` names, as the eta fields of a MailUpdate ({} without one)."""
    if eta := _ETA.search(text):
        day = relative_day(eta.group("day"), sent)
        if not eta.group("h1"):
            return {"eta_date": day}
        return {
            "eta_date": day,
            "eta_from": at(day, int(eta.group("h1")), int(eta.group("m1") or 0)),
            "eta_to": at(day, int(eta.group("h2")), int(eta.group("m2") or 0)),
        }
    for line in _ETA_DATES.finditer(text):
        if resolved := resolve_dates(line.group("rest"), sent.date()):
            return {"eta_date": resolved[0], "eta_latest": resolved[1]}
    return {}


def _plain_title(subj: str, below: str) -> str | None:
    """Name of an order in the plain layout: the line below its number the subject names.

    The subject names the item (often cut: "Beispiel-Maßband 5..."), the other mails of the
    order name the same one; it is taken without its quantity, so the name fits theirs
    (``title_key``). Only a line that begins like the subject is taken: a person's name or
    an address never names a parcel. None if the subject names no item of the list
    ("Zustellung heute: Ihr Amazon Paket wird zugestellt").
    """
    named = subj.split(":", 1)[1] if subject_status(subj) is not None else subj
    wanted = title_key(_QUANTITY.sub("", _PLAIN_MORE.sub("", named.strip())))
    if not wanted:
        return None
    for line in below.strip().splitlines()[:20]:
        line = _QUANTITY.sub("", line.strip())
        if line.startswith("---"):
            break
        # (the subject's start may be shorter than the key: "WAGO 2773...")
        if line and title_key(line).startswith(wanted):
            return line
    return None


def parse_amazon(msg: EmailMessage, read_otp: bool) -> list[MailUpdate]:
    """Parse a current-format Amazon mail; one update per order number."""
    subj = subject(msg)
    text = body_text(msg)
    sent = sent_at(msg)
    status = subject_status(subj) or stage_status(text)
    # In the plain layout an order named again is the same one (in the head and again above
    # the items): its last mention counts. In the usual layout a number that comes again is
    # a further shipment with its own day and items.
    mentions = list(_ORDER.finditer(text))
    last = {match.group(2): match for match in mentions if match.group("plain")}
    orders = [m for m in mentions if not m.group("plain") or last[m.group(2)] is m]
    if status is None or not orders:
        return []

    attempt = subj.strip().lower().startswith(_ATTEMPTS)
    news = subj.strip().lower().startswith(f"{_DELAY}:")
    delay = news and bool(_DELAYED.search(text))
    eta = _eta(text, sent)
    if not eta and status is ParcelStatus.OUT_FOR_DELIVERY and _ON_THE_ROUTE.search(text):
        eta = {"eta_date": sent.date()}  # (the plain mail names no day: it is today)
    if news and (later := _LATER.search(text)):
        if resolved := resolve_dates(later.group(1), sent.date()):
            eta = {"eta_date": resolved[0]}
    code = None
    if read_otp and (otp := _OTP.search(text)):
        code = otp.group(1)

    from_subject = subject_title(subj) if len(orders) == 1 else None
    updates = []
    above = 0
    for index, match in enumerate(orders):
        if len(orders) > 1:
            # Each order's day stands above its number; an order without one keeps the day
            # of the order before it (the first one: the first day of the mail).
            eta = _eta(text[above : match.start()], sent) or eta
            above = match.end()
        end = orders[index + 1].start() if index + 1 < len(orders) else len(text)
        item = _ITEM.search(text, match.end(), end)
        listed = item.group("title") or item.group("listed") if item else None
        if listed is None and match.group("plain"):
            # (the plain layout names the items on the lines below the number)
            listed = _plain_title(subj, text[match.end() : end])
        title = from_subject or (shorten(listed) if listed else None)
        updates.append(
            MailUpdate(
                number=order_number(match.group(2)),
                carrier="amazon",
                status=status,
                sent_at=sent,
                title=title,
                delivered_at=sent if status is ParcelStatus.DELIVERED else None,
                delivery_code=code,
                postponed=attempt or delay,
                status_text=ATTEMPT_TEXT if attempt else DELAY_TEXT if delay else None,
                **eta,
            )
        )
    return updates


def old_shipping_layout(msg: EmailMessage) -> bool:
    """Tell whether a mail is a shipping mail in the old layout (see SHIPPING_SENDER)."""
    text = body_text(msg)
    return bool(_LEGACY_ORDER.search(text) and _LEGACY_SHIPPED.search(text))


def _legacy_title(subj: str) -> str | None:
    quoted = re.search(r"\"(.+)\"", subj)  # greedy: keeps a 27" inside the title
    if not quoted:
        return None
    raw = quoted.group(1).strip()
    core = raw.rstrip(".…").strip()
    title = f"{core}…" if core != raw else core
    if more := _LEGACY_MORE.search(subj):
        count = more.group(1)
        suffix = f" und {count} {'weiterer' if count == '1' else 'weitere'} Artikel"
        return shorten(title, 60 - len(suffix)) + suffix
    return shorten(title)


def parse_amazon_legacy(msg: EmailMessage, with_order: bool = False) -> list[MailUpdate]:
    """Old '… wurde versandt!' mails (carrier number inside).

    UPS/DHL numbers become their own parcel (as before); a Hermes number stays with the
    Amazon order as ``tracking_ref`` so the order is followed via Hermes. ``with_order``
    (the later mails in this layout: their order has its own "Bestellt" mail) keeps every
    carrier's number with the order, so no second parcel appears.
    """
    subj = subject(msg)
    text = body_text(msg)
    sent = sent_at(msg)
    title = _legacy_title(subj)
    eta_date = None
    if eta := _LEGACY_ETA.search(text):
        month = MONTHS.get(eta.group(2).lower())
        if month:
            eta_date = upcoming_date(int(eta.group(1)), month, sent.date())
    number_match = _LEGACY_NUMBER.search(text)
    raw_number = number_match.group(1) if number_match else None
    carrier = carrier_for(raw_number) if raw_number else None
    if raw_number and carrier is None and _LEGACY_HERMES.search(text):
        if _HERMES_14.fullmatch(raw_number):
            carrier = "hermes"
    order = _LEGACY_ORDER.search(text)
    tracking_ref = tracking_carrier = None
    if raw_number and carrier and order and (carrier == "hermes" or with_order):
        number, tracking_ref, tracking_carrier = order_number(order.group(1)), raw_number, carrier
        carrier = "amazon"
    elif raw_number and carrier:
        number = raw_number
    elif order:
        number, carrier = order_number(order.group(1)), "amazon"
    else:
        return []
    return [
        MailUpdate(
            number=number,
            carrier=carrier,
            status=ParcelStatus.IN_TRANSIT,
            sent_at=sent,
            title=title,
            eta_date=eta_date,
            tracking_ref=tracking_ref,
            tracking_carrier=tracking_carrier,
        )
    ]

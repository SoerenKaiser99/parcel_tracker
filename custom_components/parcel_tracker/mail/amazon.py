"""Amazon order mails (no Home Assistant imports)."""

from __future__ import annotations

import re
from datetime import date, datetime
from email.message import EmailMessage
from urllib.parse import parse_qsl, urlsplit

from ..models import ParcelStatus
from .base import (
    ATTEMPT_TEXT,
    DELAY_TEXT,
    MONTHS,
    MailUpdate,
    at,
    body_text,
    carrier_for,
    names_more_items,
    part_links,
    relative_day,
    resolve_dates,
    sent_at,
    shorten,
    subject,
    title_key,
    upcoming_date,
)

SHIPPING_SENDER = "versandbestaetigung@amazon.de"
# "Paket zur Abholung bereit: …": the order waits at a pickup point (a Hermes PaketShop, an
# Amazon Locker or Counter, another partner shop). See ``parse_amazon_pickup``.
PICKUP_SENDER = "pickup-point@amazon.de"
AMAZON_SENDERS = frozenset(
    {
        "bestellbestaetigung@amazon.de",
        SHIPPING_SENDER,
        "shipment-tracking@amazon.de",
        "order-update@amazon.de",
        PICKUP_SENDER,
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
_PICKUP = "paket zur abholung bereit"
# Cancellations. "Ihre Bestellung wurde storniert.": the whole order. "Artikel erfolgreich
# storniert: …" (the item in the subject) and "Erfolgreiche Stornierung von Artikeln aus
# Ihrer …-Bestellung" (the item below "Aufgegeben am …"): items of it, maybe not all.
# The order number stands as "Bestellnr.", "Bestellung #…" or "Bestell-Nr.…", in the
# head of the mail and again above its items.
_CANCELLED = "artikel erfolgreich storniert"
_ORDER_CANCELLED = "ihre bestellung wurde storniert"
_ITEMS_CANCELLED = "erfolgreiche stornierung von artikeln"
_CANCELLED_ORDER = re.compile(
    r"^(?:Bestellnr\.|Bestellung #|Bestell-Nr\.)\s*(\d{3}-\d{7}-\d{7})\s*$", re.MULTILINE
)
_CANCELLED_ITEM = re.compile(
    r"^Aufgegeben am [^\n]+\n(?:[ \t]*\n)*[ \t]*(?P<title>\S[^\n]*)", re.MULTILINE
)

_PREFIXES = {
    "bestellt": ParcelStatus.PRE_TRANSIT,
    "versendet": ParcelStatus.IN_TRANSIT,
    "versandt": ParcelStatus.IN_TRANSIT,
    _ATTEMPT: ParcelStatus.IN_TRANSIT,
    "zustellversuch": ParcelStatus.IN_TRANSIT,
    _DELAY: ParcelStatus.IN_TRANSIT,
    _CANCELLED: ParcelStatus.CANCELLED,
    "in zustellung": ParcelStatus.OUT_FOR_DELIVERY,
    "unterwegs zur zustellung": ParcelStatus.OUT_FOR_DELIVERY,
    "zur auslieferung": ParcelStatus.OUT_FOR_DELIVERY,
    "zustellung heute": ParcelStatus.OUT_FOR_DELIVERY,
    _PICKUP: ParcelStatus.AWAITING_PICKUP,
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
# The pickup mail: "Abholung am 24. Oktober", on the next line the pickup point ("Hermes
# PaketShop - Beispielkiosk Musterweg 1 HPS#909090 , 99999"). The subject names the same
# place behind "Paket zur Abholung bereit:", with the town and the day at its end.
_PICKUP_DAY = re.compile(
    r"^Abholung am\s+(?P<day>\d{1,2}\.\s*[A-Za-zä]+)\.?[ \t]*\n(?P<place>.*)$", re.MULTILINE
)
_DAY_TEXT = r"\d{1,2}\.\s*[A-Za-zä]+\.?"
# (a subject without a place is nothing but the day)
_SUBJECT_DAY = re.compile(rf"(?:^|\s+)(?P<day>{_DAY_TEXT})\s*$")
# What follows the place's own name and street, and everything after it: the shop's
# internal id ("HPS#909090"), the postcode (behind a comma, or before the town or at the
# end of the line), or a day ("24. Oktober").
_PLACE_END = re.compile(
    r"(?:\s+[A-Za-z]{2,6}#|\s*,\s*\d{4,5}\b|\s+\d{4,5}(?:\s+[^\W\d_]|\s*$)"
    rf"|\s+{_DAY_TEXT}\s*$).*$"
)
_QUANTITY_LINE = re.compile(r"^Menge:\s*\d+\s*$", re.MULTILINE)
# The link to a shipment's tracking page, in every mail from "Versendet" on (since autumn
# 2025): https://www.amazon.de/progress-tracker/package?orderId=…&shipmentId=…, behind
# Amazon's own redirect (https://www.amazon.de/gp/r.html?…&U=<the page>).
_LINK_HOSTS = frozenset({"www.amazon.de", "amazon.de"})
_REDIRECT_PATH = "/gp/r.html"
_TRACKER_PATH = "/progress-tracker/package"
_ORDER_ID = re.compile(r"\d{3}-\d{7}-\d{7}")
_SHIPMENT_ID = re.compile(r"[A-Za-z0-9]{5,20}")


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
    """Status from the subject prefix before ':', or from a subject that tells a cancellation."""
    if subj.strip().lower().startswith((_ORDER_CANCELLED, _ITEMS_CANCELLED)):
        return ParcelStatus.CANCELLED
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


def _tracker_params(link: str, redirect: bool = True) -> dict[str, str] | None:
    """The parameters of a link to Amazon's tracking page, None for any other link.

    Only https links to amazon.de count; Amazon's redirect counts for the page it names,
    which must be the page itself (no redirect inside a redirect).
    """
    try:
        url = urlsplit(link.strip())
    except ValueError:
        return None
    if url.scheme != "https" or (url.hostname or "").lower() not in _LINK_HOSTS:
        return None
    params = dict(parse_qsl(url.query))
    if url.path == _TRACKER_PATH or url.path.startswith(f"{_TRACKER_PATH}/"):
        return params
    if redirect and url.path == _REDIRECT_PATH and params.get("U"):
        return _tracker_params(params["U"], redirect=False)
    return None


def _shipments(msg: EmailMessage) -> dict[str, str]:
    """Amazon's shipment id per order number, as the mail's links name them.

    Read from the links to the tracking page only (never followed); an order and an id
    count only as a whole. The first id of an order counts.
    """
    found: dict[str, str] = {}
    for part in msg.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        for link in part_links(part):
            params = _tracker_params(link)
            if params is None:
                continue
            order, shipment = params.get("orderId", ""), params.get("shipmentId", "")
            if _ORDER_ID.fullmatch(order) and _SHIPMENT_ID.fullmatch(shipment):
                found.setdefault(order, shipment)
    return found


def _place(text: str) -> str | None:
    """A pickup point's name and street: without the shop's id, postcode and town."""
    place = _PLACE_END.sub("", text.strip()).strip(" ,;-")
    if re.fullmatch(_DAY_TEXT, place):
        return None  # only a day: no place
    if not place or "@" in place or not re.search(r"[^\W\d_]{2}", place):
        return None
    return shorten(place)


def _pickup_item(text: str, start: int, end: int) -> str | None:
    """The first item of the order: a listed one ("* …"), else the line above its quantity
    ("Menge: 1"). Never the price, which stands below the quantity."""
    if item := _ITEM.search(text, start, end):
        return item.group("title") or item.group("listed")
    if quantity := _QUANTITY_LINE.search(text, start, end):
        above = text[start : quantity.start()].strip().splitlines()
        line = above[-1].strip() if above else ""
        if line and not line.startswith(("Paket nachverfolgen", "http")):
            return line
    return None


def parse_amazon_pickup(msg: EmailMessage) -> list[MailUpdate]:
    """"Paket zur Abholung bereit: <place> <day>": the order waits at a pickup point.

    The place is taken from the line below "Abholung am …" (else from the subject): its
    name and street, without the shop's id, the postcode and the town. Nothing else of
    the mail's text becomes the place, so a greeting with a name never does. The day is
    the last day for the pickup; a day that is not after the mail's own only tells when
    the parcel got there and is no last day. Its year is found like every Amazon day.
    """
    subj = subject(msg)
    text = body_text(msg)
    sent = sent_at(msg)
    orders = list(_ORDER.finditer(text))
    if not orders:
        return []
    named = subj.split(":", 1)[1].strip() if ":" in subj else ""
    subject_day = _SUBJECT_DAY.search(named)
    if subject_day:
        named = named[: subject_day.start()]
    line = _PICKUP_DAY.search(text)
    in_subject = _place(named)
    below = line.group("place") if line else ""
    in_body = None if below.startswith(("Bestellnr", "Bestellung")) else _place(below)
    # (the line below the day counts if the subject names no place, or the same one)
    place = in_subject
    if in_body and (
        in_subject is None
        or in_body.startswith(in_subject.rstrip("…"))
        or in_subject.startswith(in_body)
    ):
        place = in_body
    day = line.group("day") if line else subject_day.group("day") if subject_day else None
    until = None
    if day and (resolved := resolve_dates(day, sent.date())):
        until = resolved[0] if resolved[0] > sent.date() else None
    updates = []
    for index, match in enumerate(orders):
        end = orders[index + 1].start() if index + 1 < len(orders) else len(text)
        item = _pickup_item(text, match.end(), end)
        updates.append(
            MailUpdate(
                number=order_number(match.group(2)),
                carrier="amazon",
                status=ParcelStatus.AWAITING_PICKUP,
                sent_at=sent,
                title=shorten(item) if item else None,
                pickup_point=place,
                pickup_until=until,
            )
        )
    return updates


def _cancellation(subj: str, text: str, sent: datetime) -> list[MailUpdate]:
    """A cancellation: one update per order, however often the mail names it.

    The mail about the whole order names no item (``title`` None). The mails about items
    name the first one they cancel, so only an order of that one item is closed (see
    ``apply._cancel_order``); without an item they tell nothing.
    """
    numbers = dict.fromkeys(_CANCELLED_ORDER.findall(text))
    title = None
    if not subj.strip().lower().startswith(_ORDER_CANCELLED):
        title = subject_title(subj)
        if title is None and (item := _CANCELLED_ITEM.search(text)):
            title = shorten(item.group("title"))
        if title is None:
            return []
    return [
        MailUpdate(order_number(n), "amazon", ParcelStatus.CANCELLED, sent, title=title)
        for n in numbers
    ]


def parse_amazon(msg: EmailMessage, read_otp: bool) -> list[MailUpdate]:
    """Parse a current-format Amazon mail; one update per order number."""
    subj = subject(msg)
    if subj.lower().startswith(f"{_PICKUP}:"):
        return parse_amazon_pickup(msg)
    text = body_text(msg)
    sent = sent_at(msg)
    status = subject_status(subj) or stage_status(text)
    if status is ParcelStatus.CANCELLED:
        return _cancellation(subj, text, sent)
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
    # An order the mail names as several shipments has several ids, and which link is
    # whose is not told: none of them gets one (the item tells them apart, as without).
    numbers = [match.group(2) for match in orders]
    # The order's mail names the items of each day under the number again: still one
    # order, named as the subject names it ("… und 3 weitere Artikel"), so that cancelling
    # one item does not close all of it (``apply._cancels_all``).
    if status is ParcelStatus.PRE_TRANSIT and len(set(numbers)) == 1 and len(numbers) > 1:
        whole = subject_title(subj)
        from_subject = whole if whole and names_more_items(whole) else None
    shipments = {o: s for o, s in _shipments(msg).items() if numbers.count(o) == 1}
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
                shipment_id=shipments.get(match.group(2)),
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

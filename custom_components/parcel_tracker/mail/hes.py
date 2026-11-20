"""Mails of the Hermes Einrichtungs Service (no Home Assistant imports).

Furniture and large appliances ("HES"). Its 21-digit numbers are tracked on its own page
(myhes.de, see ``carriers.hes``); HES sends few mails, the first ("Auftragseingang")
names the number and the shipper. The recipient's name and address are never read: only
number, status, day, window and the shipper ("Deine Sendung von: …").
"""

from __future__ import annotations

import re
from datetime import date
from email.message import EmailMessage
from urllib.parse import urlsplit

from ..models import ParcelStatus
from .base import (
    MailUpdate,
    at,
    body_text,
    company_name,
    html_body_text,
    html_text,
    names_carrier,
    part_links,
    sent_at,
    shop_of,
    shorten,
    subject,
)

HES_SENDER = "hermes.serviceteam@hes.de"
HES_DOMAINS = ("hes.de", "myhes.de")

# The number as the mails show it: "9999999999999 99999901" (13 + 8 digits).
_NUMBER = r"\d(?:\d| (?=\d))*\d"
_LABELLED = re.compile(rf"Sendungsnummer\s*:?\s*({_NUMBER})")
# "Auftragseingang deiner Sendung 9999999999999 99999901"
_SUBJECT = re.compile(rf"\bSendung\s+({_NUMBER})")
_FORM = re.compile(r"\d{18,24}")
# The tracking page the mails link to: "https://myhes.de/de/tracking/<number>?utm_…"
_TRACKING_PATH = re.compile(r"/tracking/(\d{18,24})/?")
# HTML markup in a text/plain part.
_MARKUP = re.compile(r"<(?:html|table|tr|td|p|div|br|span)\b", re.IGNORECASE)
# The next field's label: "Deine Sendung von:" was left empty, the line is no shipper.
_LABEL_LINE = re.compile(
    r"^(?:Sendungsnummer|Sendung|Liefertermin|Lieferdatum|Zeitfenster)\b|:$", re.IGNORECASE
)
_SHIPPER = re.compile(r"Deine Sendung von\s*:?\s*\n?\s*(?P<shipper>[^\n]+)")

# "Auftragseingang": the shop handed the order to HES, no day yet.
_RECEIVED = re.compile(r"\bauftragseingang\b|\bauftrag\b.*\bübernommen\b")
_HANDED = r"(?:zugestellt|geliefert|ausgeliefert)"
# Only what happened: "wurde … zugestellt", the participle belonging to that "wurde" (no
# "und", colon or comma between: "wurde umgeplant und soll … geliefert werden", "wurde
# vereinbart: … kann … zugestellt werden"), not followed by "werden".
_DELIVERED = re.compile(rf"\bwurde\b(?:(?!\b(?:und|oder)\b)[^:;,!?])*?\b{_HANDED}\b(?!\s+werden)")
# What announces a delivery instead: any of these words in the subject (also for the
# participle "wurde … zugestellt" as a whole: "… wurde vereinbart, sie kann … zugestellt
# werden").
_ANNOUNCED = re.compile(
    r"\b(?:wird|werden|soll|sollen|sollte|kann|können|könnte|darf|wollen|möchten|würde"
    r"|voraussichtlich|geplant|umgeplant)\b"
)
# "heute" only together with a word for the delivery itself: "kommt heute", "heute in
# Zustellung", "wird heute geliefert", "heute auf Tour". "ist heute im Depot eingetroffen"
# tells a step on the way.
_DELIVERY_TODAY = (
    rf"{_HANDED}|kommt|kommen|bringen|bringt|liefern|liefert|zustellung|auslieferung"
    r"|lieferung|tour|unterwegs\s+zu\s+dir"
)
_TODAY = re.compile(
    rf"\bheute\b.*\b(?:{_DELIVERY_TODAY})\b|\b(?:{_DELIVERY_TODAY})\b.*\bheute\b"
    # (the step "Deine Sendung befindet sich auf Tour" of myhes.de: out for delivery)
    r"|\bauf\s+tour\b"
)
_DAY_WORDS = re.compile(
    r"\blieferter?min\b|\blieferdatum\b|\bzeitfenster\b|\bunterwegs\b"
    rf"|\b(?:wird|werden|soll|sollen|kann|können)\b.*\b{_HANDED}\b"
    r"|\b(?:um|ein)?geplant\b|\b(?:eingetroffen|angekommen|übergeben)\b"
    r"|\btermin\w*|\bmorgen\b"
)
_NOT = re.compile(r"\bnicht\b|\bverschoben\b|\babgesagt\b")
# ("am" as a word: not in "Hamburg" or "Team"; "Bestellt am …" is the day of the order)
_DAY_LABEL = re.compile(r"\b(?:Lieferter?min|Lieferdatum|Liefertag|am)\b", re.IGNORECASE)
# "am <date>" is the delivery day only in a sentence about the delivery ("Wir liefern am
# …", "wird am … zugestellt"), never in one about being called ("Wir melden uns am …") or
# about something else ("Du hast am … deinen Termin bestätigt. Wir liefern am …").
_DELIVERY_LINE = re.compile(
    rf"\b(?:{_HANDED}|liefer\w*|zustell\w*|auslieferung|kommt|kommen|bringen|bringt)\b",
    re.IGNORECASE,
)
_CONTACT_LINE = re.compile(
    r"\b(?:melden|meldet|anrufen|rufen|ruft|kontaktieren|kontaktiert|informieren"
    r"|benachrichtigen|erreichen|anruf)\b",
    re.IGNORECASE,
)
# What tells the day of the order, not of the delivery: right before "am" ("Bestellt am",
# "Auftrag erteilt am", "aufgegeben  am", also across a line break) or between a word for
# the delivery day and the date ("Liefertermin: folgt. Bestellt am 01.10.2026").
_ORDER_WORDS = (
    r"bestellt|bestellung|bestelldatum|erteilt|aufgegeben|eingegangen|gekauft|bezahlt"
    r"|auftragsdatum|rechnungsdatum|kaufdatum"
)
_ORDER_BEFORE = re.compile(rf"\b(?:{_ORDER_WORDS})\s*:?\s*$", re.IGNORECASE)
_ORDER_BETWEEN = re.compile(rf"\b(?:{_ORDER_WORDS})\b", re.IGNORECASE)
_FULL_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_WINDOW = re.compile(
    r"(?:zwischen\s+)?(\d{1,2}):(\d{2})\s*(?:Uhr\s*)?(?:und|bis|[–-])\s*(\d{1,2}):(\d{2})"
)
# Without a date in front of it only "zwischen … und …" is the window: a bare "08:00 -
# 17:00 Uhr" may be the depot's service hours.
_TODAY_WINDOW = re.compile(
    r"zwischen\s+(\d{1,2}):(\d{2})\s*(?:Uhr\s*)?(?:und|bis|[–-])\s*(\d{1,2}):(\d{2})"
)


def _link_number(link: str) -> str | None:
    """The number of a link to HES's tracking page, None for any other link."""
    try:
        url = urlsplit(link.strip())
    except ValueError:
        return None
    host = (url.hostname or "").lower()
    if url.scheme not in ("http", "https") or not (
        host in HES_DOMAINS or host.endswith(tuple(f".{d}" for d in HES_DOMAINS))
    ):
        return None
    found = _TRACKING_PATH.search(url.path)
    return found.group(1) if found else None


def _number(msg: EmailMessage, text: str) -> str | None:
    for part in msg.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        for link in part_links(part):
            if number := _link_number(link):
                return number
    for pattern, where in ((_LABELLED, text), (_SUBJECT, subject(msg))):
        if found := pattern.search(where):
            number = found.group(1).replace(" ", "")
            if _FORM.fullmatch(number):
                return number
    return None


def _status(subj: str) -> ParcelStatus | None:
    lower = subj.lower()
    if _NOT.search(lower):
        return None  # a day taken back or a failed attempt: the next mail tells more
    delivered = _DELIVERED.search(lower) is not None
    if delivered and not _ANNOUNCED.search(lower):
        return ParcelStatus.DELIVERED
    if _TODAY.search(lower):
        return ParcelStatus.OUT_FOR_DELIVERY
    if delivered or _DAY_WORDS.search(lower):
        # (also "wurde voraussichtlich … zugestellt": announced, so on its way)
        return ParcelStatus.IN_TRANSIT
    if _RECEIVED.search(lower):
        return ParcelStatus.PRE_TRANSIT
    return None


# Where a sentence ends: a line break, or a full stop (also "!", "?") before the next word
# that starts with a capital letter. The dots of a date ("22.10.2026") end none.
_SENTENCE_END = re.compile(r"\n|[.!?](?=\s+[A-ZÄÖÜ])")


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence of ``text`` that holds ``text[start:end]``."""
    begin = 0
    for stop in _SENTENCE_END.finditer(text, 0, start):
        begin = stop.end()
    stop = _SENTENCE_END.search(text, end)
    return text[begin : stop.start() if stop else len(text)]


def _day(text: str) -> tuple[date, int] | None:
    """The first full date behind a word for the delivery day, with the position in
    ``text`` where the date ends (the window follows it); never a
    date the mail gives as the day of the order (``_ORDER_BEFORE``, ``_ORDER_BETWEEN``)."""
    for label in _DAY_LABEL.finditer(text):
        if _ORDER_BEFORE.search(text[max(label.start() - 40, 0) : label.start()]):
            continue
        if label.group(0).lower() == "am":
            sentence = _sentence(text, label.start(), label.end())
            if not _DELIVERY_LINE.search(sentence) or _CONTACT_LINE.search(sentence):
                continue
        segment = text[label.end() : label.end() + 80]
        if (full := _FULL_DATE.search(segment)) and not _ORDER_BETWEEN.search(
            segment[: full.start()]
        ):
            try:
                day = date(int(full.group(3)), int(full.group(2)), int(full.group(1)))
            except ValueError:
                continue
            return day, label.end() + full.end()
    return None


def parse_hes_mail(msg: EmailMessage) -> list[MailUpdate]:
    """A mail of the Hermes Einrichtungs Service: number, status, day, window and shipper.

    "Auftragseingang" (the shop handed the order over) sets "Angekündigt". A subject about
    the delivery day or a step on the way ("Liefertermin", "Zeitfenster", "wird/soll/kann
    am … zugestellt werden", "umgeplant", "im Depot eingetroffen") sets "Unterwegs" with
    the first delivery day the text names and a window ("zwischen 10:00 und 14:00 Uhr").
    "heute" with a word for the delivery ("kommt heute", "heute in Zustellung") sets "In
    Zustellung". Only "wurde … zugestellt/geliefert" without any word of an announcement
    (``_ANNOUNCED``) sets "Zugestellt". A subject with "nicht" tells no status. The
    shipper names the parcel: a company name through the naming gate, else the line as
    it is (HES delivers for shops, not for private senders); never a carrier.
    """
    subj = subject(msg)
    text = body_text(msg)
    if _MARKUP.search(text):
        # (HES puts the HTML source into its text/plain part as well)
        text = html_text(text)
    if not _SHIPPER.search(text) and not _LABELLED.search(text):
        text = html_body_text(msg) or text
    number = _number(msg, text)
    if number is None:
        return []
    sent = sent_at(msg)
    title = shop = None
    if shipper := _SHIPPER.search(text):
        line = " ".join(shipper.group("shipper").split())
        # (a line left over from markup, one without a letter or the next field's label
        # names nobody)
        if (
            line
            and "<" not in line
            and re.search(r"[^\W\d_]", line)
            and not _LABEL_LINE.search(line)
            and not names_carrier(line)
        ):
            title = company_name(line) or shorten(line)
            shop = shop_of(line)
    status = _status(subj)
    update = MailUpdate(number, "hes", status, sent, title=title, shop=shop)
    if status is ParcelStatus.DELIVERED:
        update.delivered_at = sent
        return [update]
    day = sent.date() if status is ParcelStatus.OUT_FOR_DELIVERY else None
    window_text, window_form = text, _TODAY_WINDOW
    if status is ParcelStatus.IN_TRANSIT and (found := _day(text)):
        day, end = found
        window_text, window_form = text[end : end + 120], _WINDOW
    if day:
        update.eta_date = day
        if window := window_form.search(window_text):
            hours = [int(window.group(i)) for i in range(1, 5)]
            if hours[0] < 24 and hours[2] < 24 and hours[1] < 60 and hours[3] < 60:
                update.eta_from = at(day, hours[0], hours[1])
                update.eta_to = at(day, hours[2], hours[3])
    return [update]

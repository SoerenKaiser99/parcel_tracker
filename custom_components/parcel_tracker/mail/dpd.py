"""DPD notification mails (no Home Assistant imports).

Austria: only the parcel number, a delivery and its time or "waits in a shop" are taken. The
drop-off place and the recipient's name are never read into an update.

Germany: the announcement ("Bald ist Ihr DPD Paket da") names the shipper and an estimate in
working days; both are taken, the shipper only through the naming gate. Every other German
mail only names the number, the German lookup tells the status.
"""

from __future__ import annotations

import re
from datetime import date
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    DPD_DOMAINS,
    MailUpdate,
    add_workdays,
    at,
    body_text,
    company_name,
    domain_of,
    find_numbers,
    sender,
    sent_at,
    shop_of,
    subject,
)

DPD_AT_SENDER = "no_reply@dpd.at"
DPD_AT_DOMAIN = "dpd.at"

# "Paketnummer 0999…" / "dein Paket 0999… wurde …"
_NUMBER = re.compile(r"\bPaket(?:nummer)?\s*:?\s*(\d{14})(?!\d)", re.IGNORECASE)
_NEW = "ein dpd paket für dich"
_NOT = re.compile(r"\bnicht\b|\bkein\w*\b|\bkonnte\b|zustellversuch", re.IGNORECASE)
# What is still to happen ("… und wird morgen zugestellt") is no news about a delivery.
_FUTURE = re.compile(r"\bwird\b|\bwerden\b|\bsoll\b", re.IGNORECASE)
# Waiting in a shop: the shop and that the parcel lies there. "auf dem Weg in den Pickup
# Paketshop" or "in einen Paketshop umgeleitet" is not there yet.
_SHOP = re.compile(r"paketshop|pickup|abholstation", re.IGNORECASE)
_THERE = re.compile(r"\bhinterlegt\b|\bzugestellt\b|abholbereit|\bbereit\b", re.IGNORECASE)
_HANDED = re.compile(r"\b(?:zugestellt|abgestellt)\b", re.IGNORECASE)
# "beim Nachbarn abgegeben" is a delivery ("im Depot abgegeben" is none); who it is, is not read.
_NEIGHBOUR = re.compile(r"\bnachbar\w*\b.*\babgegeben\b", re.IGNORECASE)
# "hinterlegt" alone may be a depot: only together with the place the recipient chose.
_LEFT = re.compile(r"\bhinterlegt\b", re.IGNORECASE)
_PLACE = re.compile(r"abstellort|wunschort|gewünschten\s+ort", re.IGNORECASE)
_TIME = re.compile(r"\bheute\s+um\s+(\d{1,2})[:.](\d{2})\s*Uhr", re.IGNORECASE)


def _status(sentence: str) -> ParcelStatus | None:
    """The status the sentence about the parcel tells, None for anything that is no delivery
    and no waiting in a shop (handed over to DPD, in the depot, announced, failed)."""
    if _NOT.search(sentence) or _FUTURE.search(sentence):
        return None
    if _SHOP.search(sentence):
        return ParcelStatus.AWAITING_PICKUP if _THERE.search(sentence) else None
    if (
        _HANDED.search(sentence)
        or _NEIGHBOUR.search(sentence)
        or (_LEFT.search(sentence) and _PLACE.search(sentence))
    ):
        return ParcelStatus.DELIVERED
    return None


def parse_dpd_mail(msg: EmailMessage) -> list[MailUpdate]:
    """'Ein DPD Paket für dich' (announced) and 'Neuigkeiten zu deinem Paket' (delivered or
    waiting in a shop); every other sentence only names the parcel and the lookup decides.

    Only the notification sender's sentences are read: a mail of another sender at dpd.at
    just names the parcel.
    """
    subj = subject(msg)
    text = " ".join(body_text(msg).split())
    number = _NUMBER.search(text)
    if not number:
        return []
    sent = sent_at(msg)
    update = MailUpdate(number=number.group(1), carrier="dpd", status=None, sent_at=sent)
    if sender(msg)[0] != DPD_AT_SENDER:
        return [update]
    sentence = text[number.end() :]
    sentence = re.split(r"[.!?](?:\s|$)", sentence, maxsplit=1)[0]
    if _NEW in subj.lower():
        update.status = ParcelStatus.PRE_TRANSIT
        return [update]
    update.status = _status(sentence)
    if update.status is ParcelStatus.DELIVERED:
        update.delivered_at = sent
        if time := _TIME.search(sentence):
            hour, minute = int(time.group(1)), int(time.group(2))
            if hour < 24 and minute < 60:
                update.delivered_at = at(sent.date(), hour, minute)
    return [update]


# ----- DPD Germany -----
# "Versender & Paketnummer:" – the shipper on the line(s) below, then the number. The
# recipient's block ("Empfänger:") follows and is never read.
_DE_SHIPPER = re.compile(
    r"Versender\s*(?:&|und)\s*Paketnummer\s*:(?P<block>.{0,1500}?)(?=Empfänger\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_LINK = re.compile(r"<[^<>]*>")
_DE_NUMBER = re.compile(r"(?<!\d)\d{14}(?!\d)")
# "Ihre Sendung stellen wir in 1-2 Werktagen zu.", "… wird in 3 Werktagen zugestellt."
_DE_ESTIMATE = re.compile(
    r"\bin\s+(\d{1,2})(?:\s*(?:-|–|bis)\s*(\d{1,2}))?\s+Werktag(?:en)?\b", re.IGNORECASE
)
_DE_DELIVERY = re.compile(r"stell", re.IGNORECASE)  # stellen … zu, zugestellt, Zustellung
_DE_MAX_WORKDAYS = 14


def _de_shipper(text: str) -> tuple[str | None, str | None]:
    """(shipper lines as one line, parcel number) of the shipper block, None for what is
    not there. Links are dropped first: a link may carry the number or break the lines."""
    block = _DE_SHIPPER.search(text)
    if not block:
        return None, None
    lines = _LINK.sub(" ", block.group("block"))
    number = _DE_NUMBER.search(lines)
    if number:
        lines = lines[: number.start()]
    return " ".join(lines.split()) or None, number.group(0) if number else None


def _de_estimate(text: str, sent: date) -> tuple[date | None, date | None]:
    """(first, last) day of "in N-M Werktagen" counted from the day the mail was sent;
    ``last`` is None for a single number. Only a sentence about the delivery counts, and
    none that says what will not happen."""
    for sentence in re.split(r"[.!?](?:\s|$)", " ".join(text.split())):
        found = _DE_ESTIMATE.search(sentence)
        if not found or not _DE_DELIVERY.search(sentence) or _NOT.search(sentence):
            continue
        first = int(found.group(1))
        last = int(found.group(2)) if found.group(2) else first
        if not 1 <= first <= last <= _DE_MAX_WORKDAYS:
            continue
        return add_workdays(sent, first), add_workdays(sent, last) if last > first else None
    return None, None


def parse_dpd_de_mail(msg: EmailMessage) -> list[MailUpdate]:
    """DPD Germany's own mails: every number like the generic parser, plus what the
    announcement tells about one parcel.

    The shipper below "Versender & Paketnummer:" names the parcel if it passes the naming
    gate (a company or a shop we know, never a person). "Ihre Sendung stellen wir in 1-2
    Werktagen zu." gives the first and the last day, counted from the day the mail was sent
    (for a forwarded mail the day of the original); only such a mail is an announcement and
    tells "announced", like DPD Austria's. Both belong to the number of the shipper block,
    without that block to the only number of the mail. A mail of any other sender is not
    read here.
    """
    if domain_of(sender(msg)[0]) not in DPD_DOMAINS:
        return []
    text = body_text(msg)
    sent = sent_at(msg)
    updates = [
        MailUpdate(number=number, carrier=carrier, status=None, sent_at=sent)
        for carrier, number in find_numbers(f"{subject(msg)}\n{text}", "any")
    ]
    shipper, labelled = _de_shipper(text)
    target = next((u for u in updates if u.number == labelled), None)
    if target is None and labelled is None and len(updates) == 1:
        target = updates[0]
    if target is None:
        return updates
    if shipper:
        target.title = company_name(shipper)
        target.shop = shop_of(shipper)
    target.eta_date, target.eta_latest = _de_estimate(text, sent.date())
    if target.eta_date:
        target.status = ParcelStatus.PRE_TRANSIT
    return updates

"""DPD Austria notification mails (no Home Assistant imports).

Only the parcel number, a delivery and its time or "waits in a shop" are taken. The drop-off
place and the recipient's name are never read into an update. Mails of DPD Germany stay with
the generic parser: they only name the number, the German lookup tells the status.
"""

from __future__ import annotations

import re
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import MailUpdate, at, body_text, sender, sent_at, subject

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

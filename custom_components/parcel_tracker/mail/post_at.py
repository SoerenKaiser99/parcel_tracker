"""Österreichische Post notification mails (no Home Assistant imports).

meinesendung@post.at (older: meinepost@post.at) writes:

- "Ihre [AMAZON-]Sendung ist in Verteilung": received for transport, with the expected day
- "Ihre [AMAZON-]Sendung ist in Zustellung": "wird voraussichtlich heute zugestellt"
- "So stellen wir Ihre Sendung (<number>) zu": redirected to a pickup station, only names it
- "[Erinnerung: ]Ihr Paket ist da! (<number>)": waiting in a station or branch

Only the number, the status, the day, the pickup place (its name and street) and the last
day to pick it up are taken; the pickup code only when reading delivery codes is switched
on. The recipient's name, the customer number, the weight and the postcode with the town
of the pickup place are never read into an update. "AMAZON-Sendung" names Amazon as the
shop, so the mail joins the Amazon order it belongs to (``apply._merge_candidate``).

Every other mail of post.at (receipts, invoices, labels bought, orders in the shop, a
claim) is no parcel coming in: it is ignored.
"""

from __future__ import annotations

import re
from datetime import date
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import MailUpdate, body_text, sent_at, subject

POST_AT_DOMAIN = "post.at"
POST_AT_SENDER = "meinesendung@post.at"
POST_AT_SENDERS = frozenset({POST_AT_SENDER, "meinepost@post.at"})

# Domestic parcels: 22 or 24 digits; international: UPU S10 ending "AT".
_NUMBER = re.compile(r"(?<![\dA-Z])(\d{24}|\d{22}|[A-Z]{2}\d{9}AT)(?![\dA-Z])")
_SUBJ_DISTRIBUTION = re.compile(r"^Ihre\s+(AMAZON-)?Sendung\s+ist\s+in\s+Verteilung", re.I)
_SUBJ_DELIVERY = re.compile(r"^Ihre\s+(AMAZON-)?Sendung\s+ist\s+in\s+Zustellung", re.I)
_SUBJ_REDIRECT = re.compile(r"^So\s+stellen\s+wir\s+Ihre\s+Sendung\b", re.I)
_SUBJ_PICKUP = re.compile(r"^(?:Erinnerung:\s*)?Ihr\s+Paket\s+ist\s+da!", re.I)
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_EXPECTED = re.compile(r"Voraussichtliche\s+Zustellung\s+am\s+\w+,\s*(\d{1,2}\.\d{1,2}\.\d{4})")
_UNTIL = re.compile(r"Abholfrist:\s*\w+,\s*(\d{1,2}\.\d{1,2}\.\d{4})")
# "ist in der Abholstation 1230, Musterstraße 1, 1230 Wien mit dem Code ABC123 abholbereit"
_PLACE = re.compile(
    r"\bist\s+in\s+der\s+(?P<place>.{3,120}?)\s+(?:mit\s+dem\s+Code|abholbereit)", re.S
)
_POSTCODE_TOWN = re.compile(r",\s*\d{4}\s+[^,]+$")
_CODE = re.compile(r"\bmit\s+dem\s+Code\s+([A-Z0-9]{4,10})\b")


def is_post_at_parcel_mail(subj: str) -> bool:
    """One of the four subjects about a parcel coming in."""
    return any(
        p.match(subj) for p in (_SUBJ_DISTRIBUTION, _SUBJ_DELIVERY, _SUBJ_REDIRECT, _SUBJ_PICKUP)
    )


def _date(text: str | None) -> date | None:
    match = _DATE.fullmatch(text or "")
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_post_at_mail(msg: EmailMessage, read_otp: bool = False) -> list[MailUpdate]:
    """The parcel the mail is about, with what the subject tells."""
    subj = subject(msg)
    if not is_post_at_parcel_mail(subj):
        return []
    text = " ".join(body_text(msg).split())
    number = _NUMBER.search(subj) or _NUMBER.search(text)
    if not number:
        return []
    sent = sent_at(msg)
    update = MailUpdate(number=number.group(1), carrier="post_at", status=None, sent_at=sent)
    amazon = _SUBJ_DISTRIBUTION.match(subj) or _SUBJ_DELIVERY.match(subj)
    if amazon and amazon.group(1):
        update.shop = "amazon"
    if _SUBJ_DISTRIBUTION.match(subj):
        update.status = ParcelStatus.IN_TRANSIT
        if expected := _EXPECTED.search(text):
            update.eta_date = _date(expected.group(1))
    elif _SUBJ_DELIVERY.match(subj):
        update.status = ParcelStatus.OUT_FOR_DELIVERY
        update.eta_date = sent.date()
    elif _SUBJ_PICKUP.match(subj):
        update.status = ParcelStatus.AWAITING_PICKUP
        if place := _PLACE.search(text):
            update.pickup_point = _POSTCODE_TOWN.sub("", place.group("place").strip(" ,"))
        if until := _UNTIL.search(text):
            update.pickup_until = _date(until.group(1))
        if read_otp and (code := _CODE.search(text)):
            update.delivery_code = code.group(1)
    # ("So stellen wir … zu" only names the parcel; the lookup tells its status.)
    return [update]

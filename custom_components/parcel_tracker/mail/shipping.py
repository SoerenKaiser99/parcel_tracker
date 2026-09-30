"""DHL, UPS and generic shipping mails (no Home Assistant imports)."""

from __future__ import annotations

import re
from datetime import date
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    DPD_DOMAINS,
    MailUpdate,
    at,
    body_text,
    domain_of,
    find_numbers,
    is_forwarded,
    sender,
    sent_at,
    shorten,
    subject,
    upcoming_date,
)

DHL_SENDER = "noreply@dhl.de"
UPS_SENDER = "pkginfo@ups.com"
AMAZON_DHL_NAME = "Amazon-Sendung (DHL)"
# Senders whose display name is a sensible parcel name (shops and carriers we know).
KNOWN_SENDER_DOMAINS = frozenset({"amazon.de", "dhl.de", "ups.com", *DPD_DOMAINS})

_DHL_WINDOW = re.compile(r"heute\s+zwischen\s+(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})")
_DHL_DAY = re.compile(r"voraussichtlich\s+am\s+\w+,\s+den\s+(\d{1,2})\.(?:(\d{1,2})\.)?")
_UPS_DELIVERED = re.compile(
    r"Lieferdatum:\s*(?:\w+,\s*)?(\d{2})/(\d{2})/(\d{4})\s*Zustellzeit:\s*(\d{1,2}):(\d{2})"
)
_UPS_PLANNED = re.compile(r"Geplantes Zustelldatum:\s*(?:\w+,\s*)?(\d{2})/(\d{2})/(\d{4})")
_UPS_SHIPPER = re.compile(r"^Von:\s*(.+)$", re.MULTILINE)


def parse_dhl_mail(msg: EmailMessage) -> list[MailUpdate]:
    """DHL notification: number, day or today's window, Amazon flag."""
    subj = subject(msg)
    text = body_text(msg)
    sent = sent_at(msg)
    numbers = [n for carrier, n in find_numbers(text) if carrier == "dhl"]
    if not numbers:
        return []
    amazon = "amazon sendung" in f"{subj}\n{text}".lower()
    status = ParcelStatus.IN_TRANSIT
    eta_date = eta_from = eta_to = None
    if window := _DHL_WINDOW.search(text):
        status = ParcelStatus.OUT_FOR_DELIVERY
        eta_date = sent.date()
        eta_from = at(eta_date, int(window.group(1)), int(window.group(2)))
        eta_to = at(eta_date, int(window.group(3)), int(window.group(4)))
    elif "kommt heute" in subj.lower():
        status = ParcelStatus.OUT_FOR_DELIVERY
        eta_date = sent.date()
    elif day := _DHL_DAY.search(text):
        month = int(day.group(2)) if day.group(2) else None
        eta_date = upcoming_date(int(day.group(1)), month, sent.date())
    return [
        MailUpdate(
            number=numbers[0],
            carrier="dhl",
            status=status,
            sent_at=sent,
            title=AMAZON_DHL_NAME if amazon else None,
            eta_date=eta_date,
            eta_from=eta_from,
            eta_to=eta_to,
            amazon_shipment=amazon,
        )
    ]


def parse_ups_mail(msg: EmailMessage) -> list[MailUpdate]:
    """UPS Quantum View: announcement (planned day) or delivery (day + time)."""
    subj = subject(msg)
    text = body_text(msg)
    sent = sent_at(msg)
    numbers = [n for carrier, n in find_numbers(f"{subj}\n{text}") if carrier == "ups"]
    if not numbers:
        return []
    shipper = _UPS_SHIPPER.search(text)
    update = MailUpdate(
        number=numbers[0],
        carrier="ups",
        status=ParcelStatus.PRE_TRANSIT,
        sent_at=sent,
        title=shorten(shipper.group(1)) if shipper else None,
    )
    if "zustellbenachrichtigung" in subj.lower():
        update.status = ParcelStatus.DELIVERED
        update.delivered_at = sent
        if done := _UPS_DELIVERED.search(text):
            day = date(int(done.group(3)), int(done.group(2)), int(done.group(1)))
            update.delivered_at = at(day, int(done.group(4)), int(done.group(5)))
    elif planned := _UPS_PLANNED.search(text):
        update.eta_date = date(int(planned.group(3)), int(planned.group(2)), int(planned.group(1)))
    return [update]


def parse_generic(msg: EmailMessage) -> list[MailUpdate]:
    """Any other mail: only numbers that are safe on their own.

    The sender's display name becomes the parcel name only for known shop/carrier
    senders and never for forwarded mails (it would be the forwarding person's name).
    Unnamed parcels show as "<Carrier> <number>".
    """
    text = f"{subject(msg)}\n{body_text(msg)}"
    address, display = sender(msg)
    sent = sent_at(msg)
    domain = domain_of(address)
    if domain in DPD_DOMAINS:
        dpd = "any"
    elif "dpd" in text.lower():
        dpd = "labelled"
    else:
        dpd = None
    named = domain in KNOWN_SENDER_DOMAINS and not is_forwarded(msg)
    title = shorten(display) if named and display else None
    return [
        MailUpdate(number=number, carrier=carrier, status=None, sent_at=sent, title=title)
        for carrier, number in find_numbers(text, dpd)
    ]

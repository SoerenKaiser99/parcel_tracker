"""Amazon order mails (no Home Assistant imports)."""

from __future__ import annotations

import re
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
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
    upcoming_date,
)

AMAZON_SENDERS = frozenset(
    {
        "bestellbestaetigung@amazon.de",
        "versandbestaetigung@amazon.de",
        "shipment-tracking@amazon.de",
        "order-update@amazon.de",
    }
)
LEGACY_PREFIX = "Ihre Amazon.de Bestellung von"

_PREFIXES = {
    "bestellt": ParcelStatus.PRE_TRANSIT,
    "versendet": ParcelStatus.IN_TRANSIT,
    "versandt": ParcelStatus.IN_TRANSIT,
    "in zustellung": ParcelStatus.OUT_FOR_DELIVERY,
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
    r"(?:\s*und\s+(?P<more>\d+)\s+weitere[r]?\s+Artikel)?"
)
_ORDER = re.compile(r"^Bestellnr\.\s*(\d{3}-\d{7}-\d{7})\s*$", re.MULTILINE)
_ITEM = re.compile(r"^\[(?P<title>[^\]]+)\]<https?://", re.MULTILINE)
_ETA = re.compile(
    r"^(?:Ankunft|Zustellung)\s+(?P<day>heute|morgen)"
    r"(?:\s+(?P<h1>\d{1,2})(?:[:.](?P<m1>\d{2}))?\s*h?\s*[–-]\s*"
    r"(?P<h2>\d{1,2})(?:[:.](?P<m2>\d{2}))?\s*h?(?:\s*Uhr)?)?$",
    re.MULTILINE,
)
_ETA_DATES = re.compile(r"^(?:Zustellung:|Ankunft:?)\s+(?P<rest>\S.*)$", re.MULTILINE)
_OTP = re.compile(r"Einmalpasswort lautet\s*(\d{4,8})\b")
_LEGACY_ORDER = re.compile(r"Bestellnummer:\s*#?(\d{3}-\d{7}-\d{7})")
_LEGACY_NUMBER = re.compile(r"Paketverfolgungsnummer:\s*([0-9A-Z]{10,30})")
_LEGACY_ETA = re.compile(r"^Zustellung:\s*\n\w+,\s*(\d{1,2})\.\s*([A-Za-zä]+)", re.MULTILINE)


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
    return None


def parse_amazon(msg: EmailMessage, read_otp: bool) -> list[MailUpdate]:
    """Parse a current-format Amazon mail; one update per order number."""
    subj = subject(msg)
    text = body_text(msg)
    sent = sent_at(msg)
    status = subject_status(subj) or stage_status(text)
    orders = list(_ORDER.finditer(text))
    if status is None or not orders:
        return []

    eta_date = eta_from = eta_to = eta_latest = None
    if eta := _ETA.search(text):
        eta_date = relative_day(eta.group("day"), sent)
        if eta.group("h1"):
            eta_from = at(eta_date, int(eta.group("h1")), int(eta.group("m1") or 0))
            eta_to = at(eta_date, int(eta.group("h2")), int(eta.group("m2") or 0))
    else:
        for line in _ETA_DATES.finditer(text):
            if resolved := resolve_dates(line.group("rest"), sent.date()):
                eta_date, eta_latest = resolved
                break
    code = None
    if read_otp and (otp := _OTP.search(text)):
        code = otp.group(1)

    from_subject = subject_title(subj) if len(orders) == 1 else None
    updates = []
    for index, match in enumerate(orders):
        end = orders[index + 1].start() if index + 1 < len(orders) else len(text)
        item = _ITEM.search(text, match.end(), end)
        title = from_subject or (shorten(item.group("title")) if item else None)
        updates.append(
            MailUpdate(
                number=order_number(match.group(1)),
                carrier="amazon",
                status=status,
                sent_at=sent,
                title=title,
                eta_date=eta_date,
                eta_latest=eta_latest,
                eta_from=eta_from,
                eta_to=eta_to,
                delivered_at=sent if status is ParcelStatus.DELIVERED else None,
                delivery_code=code,
            )
        )
    return updates


def parse_amazon_legacy(msg: EmailMessage) -> list[MailUpdate]:
    """Old 'Ihre Amazon.de Bestellung von "…" wurde versandt!' mails (carrier number inside)."""
    subj = subject(msg)
    text = body_text(msg)
    sent = sent_at(msg)
    quoted = re.search(r"\"(.+)\"", subj)  # greedy: keeps a 27" inside the title
    title = None
    if quoted:
        raw = quoted.group(1).strip()
        core = raw.rstrip(".…").strip()
        title = shorten(f"{core}…" if core != raw else core)
    eta_date = None
    if eta := _LEGACY_ETA.search(text):
        month = MONTHS.get(eta.group(2).lower())
        if month:
            eta_date = upcoming_date(int(eta.group(1)), month, sent.date())
    number_match = _LEGACY_NUMBER.search(text)
    carrier = carrier_for(number_match.group(1)) if number_match else None
    if number_match and carrier:
        number = number_match.group(1)
    else:
        order = _LEGACY_ORDER.search(text)
        if not order:
            return []
        number, carrier = order_number(order.group(1)), "amazon"
    return [
        MailUpdate(
            number=number,
            carrier=carrier,
            status=ParcelStatus.IN_TRANSIT,
            sent_at=sent,
            title=title,
            eta_date=eta_date,
        )
    ]

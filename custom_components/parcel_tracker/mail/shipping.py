"""DHL, UPS and generic shipping mails (no Home Assistant imports)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from email.message import EmailMessage

from ..models import ParcelStatus
from .base import (
    DPD_DOMAINS,
    MailUpdate,
    at,
    body_text,
    company_name,
    domain_of,
    find_numbers,
    html_body_text,
    html_text,
    is_forwarded,
    sender,
    sent_at,
    shop_of,
    subject,
    upcoming_date,
)

DHL_SENDER = "noreply@dhl.de"
DHL_DOMAIN = "dhl.de"  # every sender there (also paketankuendigung@dhl.de) is DHL
DHL_COM_DOMAIN = "dhl.com"  # DHL Express and the online postage shop
UPS_SENDER = "pkginfo@ups.com"
AMAZON_DHL_NAME = "Amazon-Sendung (DHL)"
# Shops and carriers we know: only the display name of such a sender is looked at as a
# parcel name, and only a shop's passes (``company_name``), never a carrier's.
KNOWN_SENDER_DOMAINS = frozenset({"amazon.de", "dhl.de", "ups.com", *DPD_DOMAINS})

_DHL_WINDOW = re.compile(r"heute\s+zwischen\s+(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})")
# (the newer layout puts "**—" between "voraussichtlich" and "am" in its text part)
_DHL_DAY = re.compile(
    r"voraussichtlich[\s*_–—-]*am\s+\w+,\s+den\s+(\d{1,2})\.(?:(\d{1,2})\.)?"
)
# "Ihr neuer voraussichtlicher Zustelltag ist — Donnerstag, der 08.10. —" (the mail
# "DHL Sendungs-Update" after a delay)
_DHL_NEW_DAY = re.compile(
    r"neuer\s+voraussichtlicher\s+Zustelltag\s+ist[\s*_–—-]*\w+,\s+de[rn]\s+"
    r"(\d{1,2})\.(?:(\d{1,2})\.)?"
)
# International shipments carry a UPU S10 number issued in Germany ("CQ…DE"). Read only
# in DHL's own mails: two letters, nine digits and "DE" say too little anywhere else.
_DHL_S10 = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2}\d{9}DE)(?![A-Za-z0-9])")
# Some shipments carry a 12-digit number. 12 digits alone say nothing (eBay item numbers
# look like that): read only in DHL's own mails and only right behind its label, which may
# stand in the table cell or on the line before the number.
_DHL_SHORT = re.compile(r"\bSendungsnummer\s*:?\s*(\d{12})(?!\d)")
# The text part of some mails is empty, or names the number only in a link (the text of the
# link is a placeholder nobody filled in). The HTML part shows the number on a line of its
# own below the button, in whatever form the sending post office gave it: 12 digits, a UPU
# S10 number of any country ("LR…NL"), "JJATA…" from Austria.
_DHL_SHOWN = re.compile(
    r"^(?:Sendungs(?:status|verlauf) einsehen|Ihre Sendung)\n"
    r"((?=[A-Z0-9]*\d{8})[A-Z0-9]{12,30})$",
    re.MULTILINE,
)
# One's own shipment: the receipt of a Packstation ("Einlieferungsbeleg: Ihr Versand an der
# Packstation", "Digitaler Einlieferungsbeleg für Ihr DHL Paket") says it was handed in.
_DHL_RECEIPT = re.compile(r"\bEinlieferungsbeleg\b", re.IGNORECASE)
OWN_SHIPMENT_NAME = "Versand (DHL)"
HANDED_IN_TEXT = "Eingeliefert"
# DHL's newer layout leaves HTML table markup in its text/plain part.
_MARKUP = re.compile(r"<(?:table|tr|td|p|div|br|span)\b", re.IGNORECASE)
# "Ihre <Shop> Sendung ist unterwegs" / "… kommt heute …" / "… wurde zugestellt" / "… wird
# heute zugestellt" / "… liegt zur Abholung bereit"
_DHL_SHOP = re.compile(
    r"^Ihre\s+(?P<shop>\S.*?)\s+Sendung\s+"
    r"(?:ist\s+unterwegs|kommt\s+(?:heute|morgen)|wurde\b|wird\b|liegt\b)"
)
# The subject alone tells the status: the body of a delivery photo, Packstation or survey
# mail speaks of days and deliveries too.
# "wurde zugestellt", "wurde an den gewünschten Ablageort zugestellt"
_DHL_DELIVERED = re.compile(r"\bwurde\b(?:\s+\S+){0,6}?\s+zugestellt\b")
# "liegt am gewünschten Ablageort", "wurde am vereinbarten Ablageort hinterlegt", "liegt im
# Briefkasten", "liegt nebenan" (handed to a neighbour): delivered too, told without the word.
_DHL_DROPPED = re.compile(
    r"\bliegt\b(?:\s+\S+){0,3}?\s+ablageort\b|\bablageort\s+hinterlegt\b"
    r"|\bliegt\s+im\s+briefkasten\b|\bliegt\s+nebenan\b"
)
# ... but "an Packstation 123 zugestellt" waits for the recipient.
_DHL_PICKUP_PLACE = re.compile(r"packstation|filiale|paketshop|poststation|postfiliale")
_DHL_READY = re.compile(r"\bzur\s+abholung\s+bereit\b|\babholbereit\b")
_DHL_TODAY = re.compile(r"\bkommt\s+heute\b|\bwird\s+(?:heute|gleich)\b.*\bzugestellt\b")
# "wird gleich zugestellt": the courier is close. Still "in Zustellung", with a line of
# its own in the history.
_DHL_SOON = re.compile(r"\bwird\s+gleich\b.*\bzugestellt\b")
SOON_TEXT = "Wird gleich zugestellt"
_DHL_TOMORROW = re.compile(r"\bkommt\s+morgen\b|\bwird\s+morgen\b.*\bzugestellt\b")
_DHL_NOT = re.compile(r"\bnicht\b|\bkonnte\b|zustellversuch")
_UPS_DELIVERED = re.compile(
    r"Lieferdatum:\s*(?:\w+,\s*)?(\d{2})/(\d{2})/(\d{4})\s*Zustellzeit:\s*(\d{1,2}):(\d{2})"
)
_UPS_PLANNED = re.compile(r"Geplantes Zustelldatum:\s*(?:\w+,\s*)?(\d{2})/(\d{2})/(\d{4})")
_UPS_SHIPPER = re.compile(r"^Von:\s*(.+)$", re.MULTILINE)


def _dhl_status(subj: str) -> tuple[ParcelStatus | None, int | None]:
    """(status, days from the mail's day to the delivery day) a DHL subject tells."""
    lower = subj.lower()
    if "?" in lower:
        return None, None  # a survey asks, it tells nothing
    if not _DHL_NOT.search(lower):
        if _DHL_READY.search(lower):
            return ParcelStatus.AWAITING_PICKUP, None
        if done := _DHL_DELIVERED.search(lower):
            if _DHL_PICKUP_PLACE.search(done.group(0)):
                return ParcelStatus.AWAITING_PICKUP, None
            return ParcelStatus.DELIVERED, None
        if _DHL_DROPPED.search(lower):
            return ParcelStatus.DELIVERED, None
        if _DHL_TODAY.search(lower):
            return ParcelStatus.OUT_FOR_DELIVERY, 0
        if _DHL_TOMORROW.search(lower):
            return ParcelStatus.IN_TRANSIT, 1
    # Any other mail about a "Sendung" (also a failed delivery): it is on its way.
    return (ParcelStatus.IN_TRANSIT if "sendung" in lower else None), None


def _dhl_numbers(text: str) -> list[str]:
    numbers = [n for carrier, n in find_numbers(text) if carrier == "dhl"]
    return numbers or _DHL_S10.findall(text) or _DHL_SHORT.findall(text)


def parse_dhl_mail(msg: EmailMessage) -> list[MailUpdate]:
    """DHL notification: number, status, day or today's window, the shop the subject names.

    Every sender at dhl.de comes here, so the status is read from the subject only: "ist
    unterwegs", "kommt morgen" (the day after the mail), "kommt heute" / "wird heute
    zugestellt" / "wird gleich zugestellt" (told in its own words), "wurde … zugestellt",
    "liegt am gewünschten Ablageort" / "liegt im Briefkasten" / "liegt nebenan" and, for a
    Packstation or branch, "liegt zur Abholung
    bereit" / "wurde an Packstation … zugestellt". Any other subject that speaks of a
    "Sendung" means "on its way" without a day; a question (survey) and
    a subject without "Sendung" tell no status. A pick-up code is never read. An Amazon shipment
    keeps its fixed name (and is merged into the open Amazon order when unambiguous); any other
    shop only names the parcel if it passes the naming gate and the mail was not forwarded. The
    international variant ("in den nächsten 2 Werktagen von der Österreichischen Post
    zugestellt") names no day, so none is set.
    """
    subj = subject(msg)
    text = body_text(msg)
    if _MARKUP.search(text):
        text = html_text(text)
    sent = sent_at(msg)
    numbers = _dhl_numbers(text)
    if not numbers:
        # Nothing in the text part: the HTML part is read instead, for the day as well.
        text = html_body_text(msg)
        numbers = _dhl_numbers(text) or _DHL_SHOWN.findall(text)
    if not numbers:
        return []
    amazon = "amazon sendung" in f"{subj}\n{text}".lower()
    named = _DHL_SHOP.match(subj)
    shop = named.group("shop") if named else None
    title = shop_name = None
    if amazon:
        title, shop_name = AMAZON_DHL_NAME, "amazon"
    elif shop:
        shop_name = shop_of(shop)
        if not is_forwarded(msg):
            title = company_name(shop)
    status, ahead = _dhl_status(subj)
    receipt = _DHL_RECEIPT.search(subj) is not None
    if receipt:
        title, shop_name, status = OWN_SHIPMENT_NAME, None, ParcelStatus.IN_TRANSIT
    eta_date = eta_from = eta_to = delivered_at = None
    postponed = False
    soon = status is ParcelStatus.OUT_FOR_DELIVERY and _DHL_SOON.search(subj.lower())
    if status is ParcelStatus.OUT_FOR_DELIVERY:
        eta_date = sent.date()
        if window := _DHL_WINDOW.search(text):
            eta_from = at(eta_date, int(window.group(1)), int(window.group(2)))
            eta_to = at(eta_date, int(window.group(3)), int(window.group(4)))
    elif ahead:
        eta_date = sent.date() + timedelta(days=ahead)
    elif "ist unterwegs" in subj.lower() and (day := _DHL_DAY.search(text)):
        month = int(day.group(2)) if day.group(2) else None
        eta_date = upcoming_date(int(day.group(1)), month, sent.date())
    elif status is ParcelStatus.IN_TRANSIT and (day := _DHL_NEW_DAY.search(text)):
        month = int(day.group(2)) if day.group(2) else None
        eta_date = upcoming_date(int(day.group(1)), month, sent.date())
        postponed = eta_date is not None
    elif status is ParcelStatus.DELIVERED:
        delivered_at = sent
    return [
        MailUpdate(
            number=numbers[0],
            carrier="dhl",
            status=status,
            sent_at=sent,
            title=title,
            eta_date=eta_date,
            eta_from=eta_from,
            eta_to=eta_to,
            delivered_at=delivered_at,
            shop=shop_name,
            postponed=postponed,
            status_text=SOON_TEXT if soon else HANDED_IN_TEXT if receipt else None,
        )
    ]


# ----- dhl.com: DHL Express and the online postage shop -----
# "Ihre DHL Express Sendung mit Sendungsnr. 9999990166 von AMAZON ist unterwegs." / "… wird
# voraussichtlich HEUTE bis Tagesende ausgeliefert." / "Ihre DHL Express Sendung mit der
# Sendungsnummer 9999990166 von AMAZON wurde wie gewünscht am 11 Jun 2025 um 15:45
# zugestellt." The subject is always "DHL On Demand Delivery".
_EXPRESS = re.compile(
    r"Ihre DHL Express Sendung mit (?:der )?Sendungsn(?:r\.|ummer) (?P<number>\d{10})(?!\d)"
    r"(?: von (?P<shipper>\S.*?))? (?P<told>ist unterwegs|wird\b.*?\bausgeliefert"
    r"|wurde\b.*?\bzugestellt)\b"
)
_EXPRESS_DAY = re.compile(r"voraussichtliche Zustelldatum (\d{1,2}) ([A-Za-zä]{3})\w* (\d{4})")
_EXPRESS_TIME = re.compile(r"\bam (\d{1,2}) ([A-Za-zä]{3})\w* (\d{4}) um (\d{1,2}):(\d{2})\b")
# (the month stands in English or German, three letters)
_EXPRESS_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "mär": 3, "apr": 4, "may": 5, "mai": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dez": 12,
}
_POSTAGE = re.compile(r"\bOnline\s+Frankierung\b", re.IGNORECASE)


def _express_day(day: str, month: str, year: str) -> date | None:
    try:
        return date(int(year), _EXPRESS_MONTHS[month.lower()], int(day))
    except (KeyError, ValueError):
        return None


def parse_dhl_com_mail(msg: EmailMessage) -> list[MailUpdate]:
    """Mails from dhl.com: DHL Express ("On Demand Delivery") and the online postage shop.

    Express: the sentence about the shipment tells the status ("ist unterwegs", today
    "wird … ausgeliefert", "wurde … zugestellt" with day and time), the shipper names the
    parcel through the naming gate. Postage ("Auftragsbestätigung Ihrer Online Frankierung"):
    one's own shipments, one per "Sendungsnummer:" of a label, announced; a stamp for a
    letter has no number and gives nothing. The recipients of the labels are never read.
    """
    # (the text part of the postage mail names no number, its HTML part does)
    text = f"{body_text(msg)}\n{html_body_text(msg)}"
    sent = sent_at(msg)
    if _POSTAGE.search(subject(msg)):
        return [
            MailUpdate(number, "dhl", ParcelStatus.PRE_TRANSIT, sent, title=OWN_SHIPMENT_NAME)
            for number in dict.fromkeys(_dhl_numbers(text))
        ]
    told = _EXPRESS.search(text)
    if not told:
        return []
    shipper = told.group("shipper") or ""
    shop_name = shop_of(shipper)
    update = MailUpdate(
        told.group("number"), "dhl", ParcelStatus.IN_TRANSIT, sent,
        title=AMAZON_DHL_NAME if shop_name == "amazon" else company_name(shipper),
        shop=shop_name,
    )
    words = told.group("told")
    if words.startswith("wurde"):
        update.status, update.delivered_at = ParcelStatus.DELIVERED, sent
        when = _EXPRESS_TIME.search(words)
        day = _express_day(*when.groups()[:3]) if when else None
        if day and int(when.group(4)) < 24 and int(when.group(5)) < 60:
            update.delivered_at = at(day, int(when.group(4)), int(when.group(5)))
    elif words.startswith("wird"):
        update.status, update.eta_date = ParcelStatus.OUT_FOR_DELIVERY, sent.date()
    elif day := _EXPRESS_DAY.search(text):
        update.eta_date = _express_day(*day.groups())
    return [update]


def parse_ups_mail(msg: EmailMessage) -> list[MailUpdate]:
    """UPS Quantum View: announcement (planned day) or delivery (day + time).

    The shipper line ("Von: …") names the parcel only through the naming gate: a company
    or a shop we know, never a person.
    """
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
        title=company_name(shipper.group(1)) if shipper else None,
        shop=shop_of(shipper.group(1)) if shipper else None,
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

    The sender's display name becomes the parcel name only for a known shop sender, cut
    like every company name. A carrier's display name ("DHL Paketankündigung") is never a
    name, nor is the one of a forwarded mail (it would be the forwarding person's name).
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
    title = company_name(display) if named and display else None
    return [
        MailUpdate(number=number, carrier=carrier, status=None, sent_at=sent, title=title)
        for carrier, number in find_numbers(text, dpd)
    ]

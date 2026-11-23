"""Mails of the Hermes Einrichtungs Service (no Home Assistant imports).

Furniture and large appliances ("HES"). Its 21-digit numbers are tracked on its own page
(myhes.de, see ``carriers.hes``), and that lookup tells status, day and window. A mail
only adds what the lookup does not know: the number, so the parcel exists and is asked
about at once, and the shipper ("Deine Sendung von: …") as its name. HES sends few mails
and we know only one of them ("Auftragseingang"): no other subject is read for a status,
a day or a window. A guess there could only be wrong, and a wrong "delivered" would end
the lookup for good. The recipient's name and address are never read.
"""

from __future__ import annotations

import re
from email.message import EmailMessage
from urllib.parse import urlsplit

from ..models import ParcelStatus
from .base import (
    MailUpdate,
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

# "Auftragseingang": the shop handed the order to HES. The one mail of HES we know; it
# tells "announced", no day.
_RECEIVED = re.compile(r"\bauftragseingang\b|\bauftrag\b.*\bübernommen\b")


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
    """"Angekündigt" for "Auftragseingang"; any other subject tells no status."""
    return ParcelStatus.PRE_TRANSIT if _RECEIVED.search(subj.lower()) else None


def parse_hes_mail(msg: EmailMessage) -> list[MailUpdate]:
    """A mail of the Hermes Einrichtungs Service: number, shipper and, for
    "Auftragseingang", "Angekündigt".

    Any other subject sets no status, day or window: the mail makes the parcel (or makes
    it be asked about again, see ``apply._apply_tracking``), and the lookup at myhes.de
    tells the rest. The shipper names the parcel: a company name through the naming
    gate, else the line as it is (HES delivers for shops, not for private senders); never
    a carrier.
    """
    text = body_text(msg)
    if _MARKUP.search(text):
        # (HES puts the HTML source into its text/plain part as well)
        text = html_text(text)
    if not _SHIPPER.search(text) and not _LABELLED.search(text):
        text = html_body_text(msg) or text
    number = _number(msg, text)
    if number is None:
        return []
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
    return [MailUpdate(number, "hes", _status(subject(msg)), sent_at(msg), title=title, shop=shop)]

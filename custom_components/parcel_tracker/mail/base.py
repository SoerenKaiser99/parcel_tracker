"""Mail parsing primitives (no Home Assistant imports)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Literal

from ..carriers.base import BERLIN
from ..models import ParcelStatus

TITLE_MAX = 60

MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}

# Invisible marks Amazon/DHL put into mails: combining grapheme joiner, zero-width
# chars, direction marks/embeddings (U+202B before the order number), soft hyphen.
_INVISIBLE = re.compile("[͏​-‏‪-‮⁠﻿­]")
_SPACES = re.compile("[ \t   ]+")
_FORWARD = re.compile(r"^(?:(?:wg|fwd?|aw|re)\s*:\s*)+", re.IGNORECASE)
_MORE = re.compile(r"\s*und\s+\d+\s+weitere[r]?\s+Artikel\s*$")


@dataclass
class MailUpdate:
    """One parcel fact taken from a mail."""

    number: str  # "AMZ"/"EBAY" + order digits for shop orders, else the tracking number
    carrier: str  # "amazon" | "ebay" | "dhl" | "dpd" | "gls" | "hermes" | "ups"
    status: ParcelStatus | None
    sent_at: datetime  # Date header in Europe/Berlin
    title: str | None = None
    eta_date: date | None = None
    eta_latest: date | None = None
    eta_from: datetime | None = None
    eta_to: datetime | None = None
    delivered_at: datetime | None = None
    delivery_code: str | None = None
    shop: str | None = None  # "amazon" | "ebay": carrier mail names the shop (for merging)
    shipping_carrier_hint: str | None = None  # shop mail names the carrier (display, merging)
    tracking_ref: str | None = None  # shop mail carries the carrier's number
    tracking_carrier: str | None = None


@dataclass
class MailResult:
    """Outcome of parsing one mail."""

    updates: list[MailUpdate] = field(default_factory=list)
    ignored: bool = False  # sender on the ignore list: no folder move, no counting
    amazon: bool = False  # came from an Amazon shipping sender (for the unrecognised counter)


_NUMBERS = (
    ("dhl", re.compile(r"\b(00340\d{15})\b")),
    ("dhl", re.compile(r"\b(JJD\d{12,22})\b")),
    ("ups", re.compile(r"\b(1Z[0-9A-Z]{16})\b")),
    ("hermes", re.compile(r"\b(H\d{19})\b")),
)
_DPD = re.compile(r"\b(\d{14})\b")
# 14 digits are ambiguous (order numbers, phone numbers): outside DPD's own mails
# only a number right after a parcel-number label counts.
_DPD_LABELLED = re.compile(
    r"(?:Paketnummer|Sendungsnummer|Paket-Nr\.?|Paketscheinnummer|Sendungs-Nr\.?)"
    r"\s*:?\s*(\d{14})\b",
    re.IGNORECASE,
)
DPD_DOMAINS = ("dpd.de", "service.dpd.de")

DpdMode = Literal["labelled", "any"] | None


def carrier_for(number: str) -> str | None:
    """Carrier of a number that is unambiguous on its own (DPD needs context)."""
    for carrier, pattern in _NUMBERS:
        if pattern.fullmatch(number):
            return carrier
    return None


def find_numbers(text: str, dpd: DpdMode = None) -> list[tuple[str, str]]:
    """Safe tracking numbers in ``text`` as (carrier, number), first occurrence first.

    ``dpd``: None = no DPD numbers, "labelled" = only 14 digits after a parcel-number
    label, "any" = every 14-digit number (mails from DPD itself).
    """
    found: list[tuple[int, str, str]] = []
    for carrier, pattern in _NUMBERS:
        found += [(m.start(), carrier, m.group(1)) for m in pattern.finditer(text)]
    if dpd is not None:
        pattern = _DPD if dpd == "any" else _DPD_LABELLED
        found += [(m.start(1), "dpd", m.group(1)) for m in pattern.finditer(text)]
    result: list[tuple[str, str]] = []
    for _, carrier, number in sorted(found):
        if all(number != known for _, known in result):
            result.append((carrier, number))
    return result


def clean(text: str) -> str:
    """Drop invisible marks, fold exotic spaces, strip every line."""
    text = _INVISIBLE.sub("", text)
    return "\n".join(_SPACES.sub(" ", line).strip() for line in text.splitlines())


_BLOCK_TAGS = frozenset({"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table", "td", "th"})
_SKIP_TAGS = frozenset({"style", "script", "head", "title"})


class _HtmlText(HTMLParser):
    """Collects visible text; block elements become line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(self._skip - 1, 0)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_text(markup: str) -> str:
    """Visible text of an HTML body: one line per block, cleaned, no empty lines."""
    parser = _HtmlText()
    parser.feed(markup)
    parser.close()
    return "\n".join(line for line in clean("".join(parser.parts)).splitlines() if line)


def _content(part: EmailMessage) -> str:
    try:
        return part.get_content()
    except (LookupError, ValueError):
        return (part.get_payload(decode=True) or b"").decode("utf-8", "replace")


def body_text(msg: EmailMessage) -> str:
    """Cleaned text/plain body, else the text of the HTML body ('' if there is neither)."""
    part = msg.get_body(preferencelist=("plain",))
    if part is not None:
        return clean(_content(part))
    part = msg.get_body(preferencelist=("html",))
    return html_text(_content(part)) if part is not None else ""


_CARRIER_WORDS = (
    ("hermes", "hermes"),
    ("dhl", "dhl"),
    ("deutsche post", "dhl"),
    ("dpd", "dpd"),
    ("gls", "gls"),
    ("ups", "ups"),
)


def carrier_key(text: str) -> str | None:
    """Our carrier key for a carrier name in a mail ('Hermes Germany' -> 'hermes')."""
    lower = text.lower()
    for word, key in _CARRIER_WORDS:
        if re.search(rf"\b{word}\b", lower):
            return key
    return None


def shop_of(text: str) -> str | None:
    """'amazon' / 'ebay' when a shop we track orders for is named in ``text``."""
    lower = text.lower()
    if "amazon" in lower:
        return "amazon"
    if "ebay" in lower:
        return "ebay"
    return None


# Well-known shops besides Amazon/eBay, only as the whole name (optionally with a legal
# form or domain): "Otto" alone is a shop, "Otto Beispiel" is a person.
_KNOWN_SHOP = re.compile(
    r"(?:otto|zalando|about you|media ?markt|saturn|ikea|lidl|tchibo|bonprix|thomann"
    r"|notebooksbilliger|alternate|cyberport|galaxus|decathlon|conrad|kaufland|shein|temu"
    r"|aliexpress)(?:\.(?:de|com))?(?:\s+(?:gmbh|ag|se|kg|sarl|&|co\b|versand|online|shop"
    r"|deutschland|germany|electronic)\b.*)?",
    re.IGNORECASE,
)


def known_shop(text: str) -> bool:
    """True if ``text`` names a shop or company we know (never a private person)."""
    text = text.strip()
    return shop_of(text) is not None or _KNOWN_SHOP.fullmatch(text) is not None


# A company, never a private sender: only such a name may become the parcel's name.
LEGAL_FORM = re.compile(
    r"(?<![\w.])(?:GmbH|GMBH|AG|KG|UG|SE|OHG|GbR|Ltd\.?|e\.\s?K\.|B\.\s?V\.|SARL"
    r"|S\.\s?[aà]\.?\s?r\.\s?[lL]\.)(?!\w)"
)
# "GmbH & Co KG", "AG & Co. KGaA": still the legal form.
_FORM_TAIL = re.compile(r"\s*(?:&|\+|und|u\.)\s*Co\.?(?:\s*(?:KGaA|KG|OHG))?(?!\w)")
_KNOWN_SHOP_NAME = re.compile(
    r"(?:otto|zalando|about you|media ?markt|saturn|ikea|lidl|tchibo|bonprix|thomann"
    r"|notebooksbilliger|alternate|cyberport|galaxus|decathlon|conrad|kaufland|shein|temu"
    r"|aliexpress)(?:\.(?:de|com))?(?:\s+(?:versand|online|shop|deutschland|germany"
    r"|electronic)\b)*",
    re.IGNORECASE,
)
_SHOP_WORD = re.compile(r"[^\s,;:()]*(?:amazon|ebay)[^\s,;:()]*", re.IGNORECASE)

# Carriers as they sign their mails ("DHL Paket", "myDPD", "UPS Quantum View") ...
_CARRIER_NAME = re.compile(
    r"(?<![^\W\d_])(?:(?:my)?(?:dhl|dpd|gls|hermes|ups)|fedex|tnt|deutsche\s+post"
    r"|österreichische\s+post|amazon\s+logistics)(?![^\W\d_])",
    re.IGNORECASE,
)
# ... and the words such a display name is made of besides the carrier.
_NOTICE_WORDS = frozenset(
    {
        "paket", "pakete", "paketankündigung", "paketankuendigung", "paketinfo",
        "paketbenachrichtigung", "sendung", "sendungen", "sendungsverfolgung",
        "sendungsinfo", "sendungsinformation", "sendungsbenachrichtigung", "versandinfo",
        "versandinformation", "versandbenachrichtigung", "zustellung", "zustell", "zustellupdate",
        "zustellbenachrichtigung", "zustellinformation", "update", "info", "information",
        "benachrichtigung", "service", "kundenservice", "team", "tracking", "real", "time",
        "quantum", "view", "express", "germany", "deutschland", "austria", "österreich",
        "de", "at", "noreply",
    }
)


def _display_words(text: str) -> tuple[bool, list[str]]:
    """(a carrier is named, the other words) of a display name; emoji and marks dropped."""
    rest, carriers = _CARRIER_NAME.subn(" ", text)
    return carriers > 0, re.findall(r"[^\W_]+", rest.lower())


def names_carrier(text: str) -> bool:
    """True if ``text`` names a carrier or is the title of a notification ("📦 DHL
    Paketankündigung", "Zustell-Update"): such a text is never taken as a parcel name."""
    carrier, words = _display_words(text)
    return carrier or (bool(words) and all(word in _NOTICE_WORDS for word in words))


def is_carrier_title(text: str) -> bool:
    """True if ``text`` is nothing but a carrier's display name or a notification title:
    no name a mail may give a parcel. A text with any other word ("DHL Schuhe",
    "Amazon-Sendung (DHL)") is a name.
    """
    carrier, words = _display_words(text)
    return (carrier or bool(words)) and all(word in _NOTICE_WORDS for word in words)


# What older versions stored as the name of a parcel: a carrier ...
_LEGACY_CARRIER = re.compile(
    r"(?<![^\W\d_])(?:(?:my)?(?:dhl|dpd|gls|hermes|ups)|deutsche\s+post)(?![^\W\d_])",
    re.IGNORECASE,
)
# ... together with the words of a notification, and nothing else.
_LEGACY_NOTICE = frozenset(
    {
        "paket", "pakete", "paketankündigung", "paketankuendigung", "paketinfo",
        "paketbenachrichtigung", "sendungsinfo", "sendungsinformation",
        "sendungsbenachrichtigung", "sendungsverfolgung", "versandinfo", "versandinformation",
        "versandbenachrichtigung", "zustellung", "zustell", "update", "zustellupdate",
        "zustellbenachrichtigung", "zustellinformation", "benachrichtigung", "tracking",
        "real", "time", "quantum", "view",
    }
)


def is_carrier_display(text: str) -> bool:
    """True if a stored name is a carrier's display name of an older version and may be
    replaced: a carrier and at least one notification word, nothing else but emoji and
    punctuation ("📦 DHL Paketankündigung", "DHL Zustell-Update", "DPD Versandinfo").

    Anything else may be a name somebody gave ("Hermes", "DHL Express", "Paket",
    "Österreich") and stays.
    """
    rest, carriers = _LEGACY_CARRIER.subn(" ", text)
    words = re.findall(r"[^\W_]+", rest.lower())
    return carriers > 0 and bool(words) and all(word in _LEGACY_NOTICE for word in words)


def is_company(text: str) -> bool:
    """The naming gate: a known shop or a name with a legal form (never a person)."""
    return known_shop(text) or LEGAL_FORM.search(text) is not None


def company_name(text: str) -> str | None:
    """The parcel name a sender line of a mail gives, None if it passes no naming gate.

    A name with a legal form ends at that form ("Beispiel Handels OHG (AT-B2C) Erika
    Musterfrau" -> "Beispiel Handels OHG"): what follows may be a contact person, and so may
    what stands in front of a comma ("Erika Musterfrau, Beispiel GmbH" -> "Beispiel GmbH"). A
    shop we know is taken alone ("Zalando Versand"); a word with "amazon" or "ebay" in it is
    just "Amazon" or "eBay", never a seller's handle. A name that names a carrier ("DHL Paket
    (Austria) GmbH") is no shop. Every name a parser takes from a mail goes through here.
    """
    text = " ".join(text.split())
    name = None
    if form := LEGAL_FORM.search(text):
        head = text[: form.start()]
        start = max(head.rfind(","), head.rfind(";")) + 1
        if not head[start:].strip(" ,;:-"):
            return None  # nothing in front of the form: where the name ends is unknown
        tail = _FORM_TAIL.match(text, form.end())
        name = text[start : (tail or form).end()].strip()
    elif (shop := _KNOWN_SHOP_NAME.match(text)) and _KNOWN_SHOP.fullmatch(text):
        name = shop.group(0)
    elif word := _SHOP_WORD.search(text):
        name = "Amazon" if "amazon" in word.group(0).lower() else "eBay"
    # "DHL Paket (Austria) GmbH c/o …" is the carrier's own company, not a shop.
    # (what stands behind a legal form is cut anyway: "… GmbH c/o DHL Lager" is fine)
    if not name or names_carrier(name if form else text):
        return None
    return shorten(name)


# Words too many companies carry in their name: a brand made only of them tells no order.
_NO_BRAND = frozenset(
    {
        "der", "die", "das", "the", "und", "and", "für", "von", "dein", "deine", "mein",
        "meine", "ihr", "ihre", "shop", "store", "online", "versand", "handel", "handels",
        "markt", "deutschland", "germany", "europe", "europa", "international", "global",
        "group", "gruppe", "service", "services", "logistik", "logistics", "express", "post",
        "paket", "pakete", "home", "haus", "best", "new", "neu", "top", "mini", "maxi", "auto",
        "bio", "baby", "sport", "sports", "black", "smart", "premium", "plus", "pro", "max",
        "super", "direkt", "direct", "original", "set", "trade", "trading", "vertrieb",
        "vertriebs", "company", "solutions",
    }
)


def brand_of(title: str | None) -> str | None:
    """The brand in a company name a carrier mail gives: the name without its legal form
    ("Beispielmarke GmbH" -> "Beispielmarke"), its words joined by single spaces.

    None for anything that says too little to tell a shop order by: no company name, a shop
    we know (it sells other makers' articles), a single word of fewer than five letters, and
    a name without a word of its own ("Neu GmbH", "Smart Home GmbH"). A common word next to
    a word of its own stays part of the brand ("Beispielmarke Premium").
    """
    name = company_name(title) if title else None
    if not name or name.endswith("…") or known_shop(name):
        return None
    form = LEGAL_FORM.search(name)
    words = (name[: form.start()] if form else name).strip(" ,;:&+-").split()
    brand = " ".join(words)
    if not brand or known_shop(brand):
        return None
    letters = [re.sub(r"[\W\d_]", "", word) for word in words]
    own = [word for word in letters if len(word) >= 3 and word.lower() not in _NO_BRAND]
    if not own or (len(words) == 1 and len(letters[0]) < 5):
        return None
    return brand


def _raw_subject(msg: EmailMessage) -> str:
    return clean(str(msg.get("Subject", ""))).replace("\n", " ").strip()


def subject(msg: EmailMessage) -> str:
    """Cleaned one-line subject without forward/reply prefixes."""
    return _FORWARD.sub("", _raw_subject(msg))


def is_forwarded(msg: EmailMessage) -> bool:
    """Subject starts with WG:/Fwd:/FW:/AW:/Re: (someone passed the mail on by hand)."""
    return _FORWARD.match(_raw_subject(msg)) is not None


def domain_of(address: str) -> str:
    """Domain part of an e-mail address ('' if there is none)."""
    return address.rpartition("@")[2] if "@" in address else ""


def sender(msg: EmailMessage) -> tuple[str, str]:
    """(lower-case address, display name) of the From header."""
    header = msg.get("From")
    addresses = getattr(header, "addresses", None)
    if not addresses:
        return "", ""
    return addresses[0].addr_spec.lower(), addresses[0].display_name


def sent_at(msg: EmailMessage) -> datetime:
    """Date header as an aware datetime in Europe/Berlin; ValueError if missing."""
    raw = msg.get("Date")
    if raw is None:
        raise ValueError("mail has no Date header")
    value = getattr(raw, "datetime", None) or parsedate_to_datetime(str(raw))
    if value.tzinfo is None:
        value = value.replace(tzinfo=BERLIN)
    return value.astimezone(BERLIN)


def relative_day(word: str, ref: datetime) -> date:
    """'heute'/'morgen' relative to the mail's local date."""
    return ref.date() + timedelta(days=1 if word.lower() == "morgen" else 0)


def at(day: date, hour: int, minute: int) -> datetime:
    """Local Europe/Berlin time on a day."""
    return datetime.combine(day, time(hour, minute), tzinfo=BERLIN)


def upcoming_date(day: int, month: int | None, ref: date) -> date | None:
    """First date with this day (and month) not more than a week before ``ref``."""
    for offset in range(13):
        year, month0 = divmod(ref.month - 1 + offset, 12)
        year += ref.year
        if month is not None and month0 + 1 != month:
            continue
        try:
            candidate = date(year, month0 + 1, day)
        except ValueError:
            continue
        if candidate >= ref - timedelta(days=7):
            return candidate
    return None


def shorten(text: str, limit: int = TITLE_MAX) -> str:
    """Trim to ``limit`` characters, marking a cut with '…'."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def title_key(title: str) -> str:
    """Comparable start of an item title (subject and body titles differ in length)."""
    core = _MORE.sub("", title.replace("…", "").replace("...", ""))
    core = re.sub(r"\s+", " ", core.replace("‑", "-")).strip().lower()
    return core[:15]


_WEEKDAYS = {"mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6}
_MONTHS_SHORT = {
    "jan": 1, "feb": 2, "mär": 3, "apr": 4, "mai": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12,
}
_WEEKDAY = (
    r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|Mo|Di|Mi|Do|Fr|Sa|So)"
)
_MONTH = (
    r"(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
    r"|Jan|Feb|Mär|Apr|Jun|Jul|Aug|Sep|Okt|Nov|Dez)"
)
_DAY_MONTH = re.compile(
    rf"(?:{_WEEKDAY}\.?,?\s*)?(?P<day>\d{{1,2}})\.\s*(?P<month>{_MONTH})\.?", re.IGNORECASE
)
_DAY_NAME = re.compile(rf"(?P<wd>{_WEEKDAY})\.?", re.IGNORECASE)
_RANGE_SPLIT = re.compile(r"\s*[–-]\s*")


def _on(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _dated(day: int, month: int, ref: date) -> date | None:
    """Day/month in the mail's year; more than 60 days before ``ref`` means next year."""
    try:
        found = date(ref.year, month, day)
        if found < ref - timedelta(days=60):
            found = date(ref.year + 1, month, day)
    except ValueError:
        return None
    return found


def resolve_dates(text: str, ref: date) -> tuple[date, date | None] | None:
    """(first, last) of a German date or range ('2. Oktober - 5. Oktober', 'Freitag').

    ``last`` is None for a single day. Weekday-only forms mean the next such day after ``ref``.
    """
    parts = _RANGE_SPLIT.split(text.strip())
    if len(parts) > 2:
        return None
    days: list[date] = []
    for part in parts:
        base = days[0] if days else ref
        if m := _DAY_MONTH.fullmatch(part):
            day, month = int(m.group("day")), _MONTHS_SHORT[m.group("month").lower()[:3]]
            if days:  # end of a range: same year as the start, or the one after
                found = _on(days[0].year, month, day)
                if found is not None and found < days[0]:
                    found = _on(days[0].year + 1, month, day)
            else:
                found = _dated(day, month, ref)
        elif m := _DAY_NAME.fullmatch(part):
            weekday = _WEEKDAYS[m.group("wd").lower()[:2]]
            shift = (weekday - base.weekday()) % 7
            found = base + timedelta(days=shift or (0 if days else 7))
        else:
            return None
        if found is None:
            return None
        days.append(found)
    if len(days) == 2 and days[1] != days[0]:
        return days[0], days[1]
    return days[0], None

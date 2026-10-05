"""The original message inside a mail someone forwarded by hand (no Home Assistant imports).

Two forms are read: the original as a ``message/rfc822`` attachment, and the header block
mail programs quote above a forwarded text (Outlook, Apple Mail, Gmail, Thunderbird; German
and English). What stands above that block (the forwarder's note, a signature) is never part
of the original.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from ..carriers.base import BERLIN
from .base import _FORWARD, _content, clean, html_text, sent_at

MAX_DEPTH = 5  # forwards inside forwards that are still followed
# The original cannot be younger than its forward; a little slack for clocks that differ.
_DATE_SLACK = timedelta(hours=1)

_QUOTE = re.compile(r"^(?:>[ \t]?)+")
_LABELS = {
    "von": "from", "from": "from",
    "betreff": "subject", "subject": "subject",
    "gesendet": "date", "sent": "date", "datum": "date", "date": "date",
    "an": "to", "to": "to", "cc": "to", "kopie": "to", "bcc": "to",
    "antwort an": "to", "reply-to": "to",
}
# "Von: …", "*Von:* …", "**From**: …" (bold as mail programs write it into a text part)
_LABEL = re.compile(
    r"^[*_]*\s*(?P<label>" + "|".join(re.escape(label) for label in _LABELS) + r")"
    r"\s*[*_]*\s*:\s*[*_]*\s*(?P<value>.*)$",
    re.IGNORECASE,
)
_ADDR = r"[\w.+%=&~-]+@[\w-]+(?:\.[\w-]+)+"
# "Name <addr>", "Name [mailto:addr]", "<mailto:addr>", else a bare address
_BRACKETED = re.compile(rf"[<\[]\s*(?:mailto:)?\s*({_ADDR})\s*[>\]]", re.IGNORECASE)
_BARE = re.compile(_ADDR)

_RFC_DATE = re.compile(
    r"(?:[A-Za-z]{3},\s*)?\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?"
    r"(?:\s*(?:[+-]\d{4}|GMT|UTC))?(?:\s*\([A-Za-z]+\))?"
)
_WEEKDAYS = {
    name: day
    for day, names in enumerate(
        (
            ("montag", "mo", "monday", "mon"),
            ("dienstag", "di", "tuesday", "tue", "tues"),
            ("mittwoch", "mi", "wednesday", "wed"),
            ("donnerstag", "do", "thursday", "thu", "thur", "thurs"),
            ("freitag", "fr", "friday", "fri"),
            ("samstag", "sonnabend", "sa", "saturday", "sat"),
            ("sonntag", "so", "sunday", "sun"),
        )
    )
    for name in names
}
_MONTHS = {
    "jan": 1, "feb": 2, "mär": 3, "mar": 3, "mrz": 3, "apr": 4, "mai": 5, "may": 5,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12,
    "dec": 12,
}
_MONTH_NAMES = frozenset(
    {
        "januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september",
        "oktober", "november", "dezember", "january", "february", "march", "may", "june",
        "july", "october", "december", "sept", "mrz", *_MONTHS,
    }
)
_ZONES = {"mesz": 2, "cest": 2, "mez": 1, "cet": 1, "utc": 0, "gmt": 0, "z": 0}
_TIME = re.compile(
    r"(?<![\d:])(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?(?![\d:])"
    r"\s*(?:Uhr\b)?\s*(?P<half>[AaPp])?(?(half)\.?[Mm]\b\.?)"
)
_OFFSET = re.compile(r"(?:\b(?:GMT|UTC))?\s*(?P<sign>[+-])(?P<h>\d{1,2})(?::?(?P<m>\d{2}))?(?!\d)")
_WORD = re.compile(r"[^\W\d_]+")
_DATES = (
    ("dmy", re.compile(r"(?<!\d)(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4}|\d{2})(?!\d)")),
    ("ymd", re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")),
    ("slash", re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")),
    ("dMy", re.compile(r"(?<!\d)(\d{1,2})\.?\s+([^\W\d_]+)\.?,?\s+(\d{4})(?!\d)")),
    ("Mdy", re.compile(r"([^\W\d_]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)")),
)


@dataclass
class _Block:
    """One quoted header block: lines ``start``..``end`` (exclusive) of a text."""

    start: int
    end: int
    fields: dict[str, str]


def _unquote(line: str) -> str:
    return _QUOTE.sub("", line.strip()).strip()


def header_blocks(lines: list[str]) -> list[_Block]:
    """The quoted header blocks in the (unquoted) lines of a text, first one first.

    A block is a run of header lines that names a sender and a subject or a date. A value
    may stand on the line below its label (headers set as a table), and a list of recipients
    may go on for two lines when another header follows. The block ends at the first other
    line: there the original text starts.
    """
    blocks: list[_Block] = []
    index = 0
    while index < len(lines):
        if not _LABEL.match(lines[index]):
            index += 1
            continue
        start, fields, key = index, {}, ""
        while index < len(lines):
            if match := _LABEL.match(lines[index]):
                if (kind := _LABELS[match.group("label").lower()]) != "to" and kind in fields:
                    break  # a second sender, subject or date: a line of the original
                key = kind
                value = match.group("value").strip()
                index += 1
                if (
                    not value
                    and index < len(lines)
                    and lines[index]
                    and not _LABEL.match(lines[index])
                ):
                    value = lines[index]
                    index += 1
                fields.setdefault(key, value)
                continue
            ahead = lines[index : index + 3]
            more = next((n for n, line in enumerate(ahead) if _LABEL.match(line)), 0)
            if key == "to" and more and all(ahead[:more]):
                index += more  # a wrapped list of recipients
                continue
            break
        if "from" in fields and ("subject" in fields or "date" in fields):
            blocks.append(_Block(start, index, fields))
    return blocks


def quoted_sender(value: str) -> tuple[str, str]:
    """(lower-case address, display name) of a quoted sender line ('' if it has none)."""
    match = _BRACKETED.search(value) or _BARE.search(value)
    if not match:
        return "", ""
    address = match.group(match.lastindex or 0).lower()
    name = value[: match.start()].strip(" \t\"'*_<[")
    return address, "" if "@" in name else name


def _numeric(kind: str, parts: tuple[str, ...], weekday: int | None) -> list[tuple[int, int, int]]:
    """The (year, month, day) readings a date in digits allows."""
    a, b, c = (int(part) for part in parts)
    if kind == "dmy":
        return [(c + 2000 if c < 100 else c, b, a)]
    if kind == "ymd":
        return [(a, b, c)]
    # 9/28/2026 or 28/09/2026: the weekday or a number above 12 has to tell which
    readings = {(c, a, b), (c, b, a)}
    valid = []
    for year, month, day in readings:
        try:
            found = datetime(year, month, day)
        except ValueError:
            continue
        if weekday is None or found.weekday() == weekday:
            valid.append((year, month, day))
    return valid


def parse_quoted_date(text: str) -> datetime | None:
    """The date of a quoted header line as an aware datetime, None if it is not certain.

    Read are the forms of the common mail programs in German and English: weekday and month
    as names or numbers, 24-hour times and AM/PM, a zone as offset or as MEZ/MESZ/CET/CEST/
    UTC. Without a zone the time is taken as Europe/Berlin. A weekday that does not match
    the date, a date in digits that can be read two ways, a missing time or any word left
    over means "not certain".
    """
    text = " ".join(clean(text).split()).strip(" *_")
    if _RFC_DATE.fullmatch(text):
        try:
            value = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        return value if value.tzinfo else value.replace(tzinfo=BERLIN)
    clock = _TIME.search(text)
    if not clock:
        return None
    hour, minute = int(clock.group("hour")), int(clock.group("minute"))
    second = int(clock.group("second") or 0)
    if half := clock.group("half"):
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if half.lower() == "p" else 0)
    head, tail = text[: clock.start()], text[clock.end() :]
    zone = None
    if offset := _OFFSET.match(tail.strip()):
        delta = timedelta(hours=int(offset.group("h")), minutes=int(offset.group("m") or 0))
        zone = timezone(delta if offset.group("sign") == "+" else -delta)
        tail = tail.strip()[offset.end() :]
    rest = f"{head} {tail}"
    weekday = None
    found: list[tuple[int, int, int]] = []
    for kind, pattern in _DATES:
        match = pattern.search(rest)
        if not match:
            continue
        if kind in ("dMy", "Mdy"):
            name = match.group(2 if kind == "dMy" else 1).lower()
            day = int(match.group(1 if kind == "dMy" else 2))
            if name not in _MONTH_NAMES:
                continue
            found = [(int(match.group(3)), _MONTHS[name[:3]], day)]
        rest = f"{rest[: match.start()]} {rest[match.end() :]}"
        for word in _WORD.findall(rest):
            lower = word.lower()
            if lower in _WEEKDAYS and weekday is None:
                weekday = _WEEKDAYS[lower]
            elif lower in _ZONES and zone is None:
                zone = timezone(timedelta(hours=_ZONES[lower]))
            elif lower not in ("um", "at", "uhr"):
                return None
        if kind not in ("dMy", "Mdy"):
            found = _numeric(kind, match.groups(), weekday)
        break
    if len(found) != 1:
        return None
    year, month, day = found[0]
    try:
        value = datetime(year, month, day, hour, minute, second, tzinfo=zone or BERLIN)
    except ValueError:
        return None
    if weekday is not None and value.weekday() != weekday:
        return None
    return value


def _texts(msg: EmailMessage) -> list[str]:
    """The cleaned text part and the text of the HTML part (those there are)."""
    texts = []
    part = msg.get_body(preferencelist=("plain",))
    if part is not None:
        texts.append(clean(_content(part)))
    part = msg.get_body(preferencelist=("html",))
    if part is not None:
        texts.append(html_text(_content(part)))
    return texts


def _fallback_date(msg: EmailMessage) -> datetime | None:
    try:
        return sent_at(msg)
    except (TypeError, ValueError):
        return None


def _view(msg: EmailMessage, block: _Block, lines: list[str]) -> EmailMessage | None:
    """A message made of a quoted header block and the text below it."""
    address, name = quoted_sender(block.fields["from"])
    outer = _fallback_date(msg)
    date = parse_quoted_date(block.fields.get("date", ""))
    if date is None or (outer is not None and date > outer + _DATE_SLACK):
        date = outer
    subject = block.fields.get("subject")
    if subject is None:
        subject = str(msg.get("Subject", ""))
    subject = _FORWARD.sub("", " ".join(subject.split()).strip(" *_"))
    body = "\n".join(lines[block.end :]).strip("\n")
    view = EmailMessage(policy=policy.default)
    try:
        local, _, domain = address.rpartition("@")
        view["From"] = Address(display_name=name, username=local, domain=domain)
        view["Subject"] = subject
        if date is not None:
            view["Date"] = date
        view.set_content(body.encode("utf-8", "replace").decode("utf-8") + "\n")
    except (ValueError, TypeError, LookupError):
        return None
    return view


def _inline(msg: EmailMessage, known) -> EmailMessage | None:
    for text in _texts(msg):
        lines = [_unquote(line) for line in text.splitlines()]
        # Innermost first: the last block is the oldest mail of a chain of forwards.
        for block in reversed(header_blocks(lines)):
            if known(quoted_sender(block.fields["from"])[0]) and (
                view := _view(msg, block, lines)
            ):
                return view
    return None


def _attached(msg: EmailMessage) -> list[EmailMessage]:
    """The messages attached to ``msg`` as message/rfc822 (not those inside them)."""
    found: list[EmailMessage] = []
    if not msg.is_multipart():
        return found
    for part in msg.iter_parts():
        if part.get_content_type() == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list) and payload and isinstance(payload[0], EmailMessage):
                found.append(payload[0])
        elif part.is_multipart():
            found += _attached(part)
    return found


def _address(msg: EmailMessage) -> str:
    header = msg.get("From")
    addresses = getattr(header, "addresses", None)
    return addresses[0].addr_spec.lower() if addresses else ""


def original_message(msg: EmailMessage, known, depth: int = 0) -> EmailMessage | None:
    """The innermost forwarded message whose sender ``known`` accepts, None if there is none.

    ``known`` is asked with the lower-case address. An attached message is taken as it is
    (with the forward's Date if it has none); a quoted one is rebuilt from its header block:
    sender, subject without forward prefixes, the quoted date if it is certain (else the
    forward's) and the text below the block without quote marks.
    """
    if depth >= MAX_DEPTH:
        return None
    for inner in _attached(msg):
        if deeper := original_message(inner, known, depth + 1):
            return deeper
        if known(_address(inner)):
            if inner.get("Date") is None and (date := _fallback_date(msg)) is not None:
                inner["Date"] = date
            return inner
    return _inline(msg, known)

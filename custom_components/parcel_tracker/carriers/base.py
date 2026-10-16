"""Carrier base class and errors."""

from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from enum import IntEnum
from zoneinfo import ZoneInfo

from ..models import TrackingResult

BERLIN = ZoneInfo("Europe/Berlin")

# A tag: "<" and a letter, "/" or "!", up to the first ">" outside quotes. A tag (or a
# quoted value) that is never closed runs to the end, so nothing of it is left over.
_TAG = re.compile(r"""<[A-Za-z/!](?:[^>"']|"[^"]*(?:"|$)|'[^']*(?:'|$))*(?:>|$)""")
# Tags that part words; every other tag (a link, a span) joins what stands around it.
_BREAK = re.compile(r"</?(?:br|p|div|li|tr|td|th|h\d|ul|ol|table)\b", re.IGNORECASE)


def _drop_tags(text: str) -> str:
    return _TAG.sub(lambda m: " " if _BREAK.match(m.group()) else "", text)


def plain_text(value: str) -> str:
    """A carrier's text as plain text: tags dropped, entities unescaped, whitespace
    collapsed (issue #18: DHL sent a link to a Packstation, its URL naming the place).

    A link keeps its visible text; nothing of a URL or an attribute is kept. Escaped
    HTML ("&lt;a …&gt;") is dropped as well. Plain text stays as it is.
    """
    return " ".join(_drop_tags(html.unescape(_drop_tags(value))).split())


def has_markup(value: str) -> bool:
    """True if the text holds a tag, also an escaped one (what ``plain_text`` drops)."""
    return bool(_TAG.search(value) or ("&" in value and _TAG.search(html.unescape(value))))


class Match(IntEnum):
    """How well a number matches a carrier."""

    NO = 0
    POSSIBLE = 1
    SURE = 2


class CarrierError(Exception):
    """Base error."""


class CarrierUnavailable(CarrierError):
    """Timeout, 5xx, network."""


class NotFound(CarrierError):
    """Carrier does not know this number (yet)."""


class AuthError(CarrierError):
    """Credentials missing or rejected."""


class MissingCredentials(AuthError):
    """Credentials not configured."""


class RateLimited(CarrierError):
    """Too many requests."""

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__(f"rate limited, retry after {retry_after}")
        self.retry_after = retry_after


class ParseError(CarrierError):
    """Unexpected response format."""


class Carrier(ABC):
    """A parcel carrier."""

    key: str
    name: str

    @staticmethod
    @abstractmethod
    def matches(number: str) -> Match:
        """Return how well a normalised number matches this carrier."""

    @abstractmethod
    async def fetch(self, number: str, postcode: str | None) -> TrackingResult:
        """Fetch and normalise tracking data."""

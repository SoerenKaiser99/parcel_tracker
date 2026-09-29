"""Carrier base class and errors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum
from zoneinfo import ZoneInfo

from ..models import TrackingResult

BERLIN = ZoneInfo("Europe/Berlin")


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

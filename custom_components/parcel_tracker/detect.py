"""Tracking number normalisation and carrier detection."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .carriers.base import Carrier, Match

_STRIP = re.compile(r"[\s\-]")


class UnsupportedNumber(ValueError):
    """Number cannot be tracked."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def normalize(number: str) -> str:
    """Remove spaces/hyphens and upper-case."""
    return _STRIP.sub("", number).upper()


def candidates(number: str, carriers: Mapping[str, Carrier | type[Carrier]]) -> list[str]:
    """Return carrier keys that may handle the number, best match first."""
    if not number:
        raise UnsupportedNumber("empty")
    if number.startswith("TBA"):
        raise UnsupportedNumber("amazon")
    scored = [(c.matches(number), key) for key, c in carriers.items()]
    hits = [(m, key) for m, key in scored if m > Match.NO]
    hits.sort(key=lambda item: item[0], reverse=True)
    if hits and hits[0][0] is Match.SURE:
        return [key for m, key in hits if m is Match.SURE]
    return [key for _, key in hits]

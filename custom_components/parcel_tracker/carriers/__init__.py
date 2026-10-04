"""Carrier adapters (no Home Assistant imports)."""

from __future__ import annotations

import aiohttp

from .base import Carrier
from .dhl import DhlCarrier
from .dpd import DpdCarrier
from .gls import GlsCarrier
from .hermes import HermesCarrier


def build_carriers(
    session: aiohttp.ClientSession, dhl_api_key: str | None, country: str | None = None
) -> dict[str, Carrier]:
    """Instantiate all carriers available in this release.

    ``country`` (``DE``, ``AT``, ``CH``) only picks the path of the GLS lookup.
    """
    return {
        "dhl": DhlCarrier(session, dhl_api_key),
        "dpd": DpdCarrier(),
        "hermes": HermesCarrier(session),
        "gls": GlsCarrier(session, country),
    }

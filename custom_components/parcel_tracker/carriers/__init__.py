"""Carrier adapters (no Home Assistant imports)."""

from __future__ import annotations

import aiohttp

from .base import Carrier
from .dhl import DhlCarrier
from .dpd import DpdCarrier
from .hermes import HermesCarrier


def build_carriers(session: aiohttp.ClientSession, dhl_api_key: str | None) -> dict[str, Carrier]:
    """Instantiate all carriers available in this release."""
    return {
        "dhl": DhlCarrier(session, dhl_api_key),
        "dpd": DpdCarrier(),
        "hermes": HermesCarrier(session),
    }

"""Hermes Germany via the keyless tracking endpoint of myhermes.de.

Response shape and status codes follow ha-parcel-integrations/ha-hermes (MIT):
a JSON array whose first element is the parcel, ``parcelProgress`` newest first,
the stable English ``parcelStatus`` per event and the localised ``historyText``.
The endpoint exposes no delivery day, so the ETA stays with what mails told.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp

from ..const import MAX_EVENTS
from ..models import ParcelStatus, TrackingEvent, TrackingResult
from .base import Carrier, CarrierUnavailable, Match, NotFound, ParseError, RateLimited

_LOGGER = logging.getLogger(__name__)

HERMES_URL = "https://api.my-deliveries.de/tnt/v2/shipments/search"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_HEADERS = {"Accept": "application/json", "X-Language": "de"}

_STATUS = {
    **dict.fromkeys(
        ("ANNOUNCED", "ORDER_INFO_RECEIVED", "PREANNOUNCED", "PARCELSHOP_DROP_OFF"),
        ParcelStatus.PRE_TRANSIT,
    ),
    **dict.fromkeys(
        (
            "SHIPMENT_PICKED_UP", "TAKEN_OVER_BY_HERMES", "HANDED_OVER_TO_HERMES",
            "PARCELSHOP_COLLECTED_BY_DRIVER", "IN_TRANSIT", "SORTED", "ARRIVED_AT_DEPOT",
            "ARRIVED_IN_DESTINATION_REGION",
        ),
        ParcelStatus.IN_TRANSIT,
    ),
    "ARRIVED_AT_DELIVERY_DEPOT": ParcelStatus.AT_DELIVERY_DEPOT,
    **dict.fromkeys(
        ("DELIVERY_TOUR_STARTED", "OUT_FOR_DELIVERY", "NEXT_STOP"),
        ParcelStatus.OUT_FOR_DELIVERY,
    ),
    **dict.fromkeys(
        ("PARCELSHOP_ITEMS_FOR_COLLECTION", "READY_FOR_COLLECTION"),
        ParcelStatus.AWAITING_PICKUP,
    ),
    **dict.fromkeys(
        (
            "DELIVERED_HOMEDELIVERY", "DELIVERED_NEIGHBOUR", "DELIVERED_PARCELSHOP",
            "DELIVERED_PARCELBOX", "DELIVERED_MAILBOX", "DELIVERED_DROPOFF", "DELIVERED",
            "PICKED_UP_BY_RECIPIENT", "COLLECTED",
        ),
        ParcelStatus.DELIVERED,
    ),
    **dict.fromkeys(
        (
            "RETURN_DELIVERED_TO_SENDER", "RETURN_TO_SENDER", "RETURN", "NOT_DELIVERABLE",
            "UNKNOWN_WHEREABOUTS",
        ),
        ParcelStatus.EXCEPTION,
    ),
}
# Booking a drop-off place is no movement (it can come before the pickup): skipped.
_IGNORED = frozenset({"EDL_BOOKED_DROPOFF"})
_WARNED: set[str] = set()
# The API's text for these names the drop-off place ("Hinter dem …"): never stored.
_FIXED_TEXT = {"DELIVERED_DROPOFF": "Am Wunschablageort zugestellt"}
_EDL_TEXT = "Wunschablageort gebucht"


def _label(event: dict[str, Any]) -> str | None:
    """Event text; fixed German texts for drop-off events instead of the raw one."""
    code = event.get("parcelStatus") or ""
    if code in _FIXED_TEXT:
        return _FIXED_TEXT[code]
    if code.startswith("EDL_"):
        return _EDL_TEXT
    return event.get("historyText") or code or None


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _map(code: str) -> ParcelStatus:
    if (status := _STATUS.get(code)) is not None:
        return status
    if code not in _WARNED:
        _WARNED.add(code)
        _LOGGER.warning(
            "Unknown Hermes status %s shown as 'unknown'; please report it to Paket Tracker",
            code,
        )
    return ParcelStatus.UNKNOWN


def parse_hermes(data: Any) -> TrackingResult:
    """Normalise the search answer (a JSON array, element 0 is the parcel)."""
    if not isinstance(data, list):
        raise ParseError("Hermes answer is not a JSON array")
    if not data:
        raise NotFound("Hermes knows no parcel for this number")
    parcel = data[0]
    if not isinstance(parcel, dict):
        raise ParseError("Hermes array element is not an object")
    progress = [e for e in parcel.get("parcelProgress") or [] if isinstance(e, dict)]
    current = next(
        (e for e in progress if e.get("parcelStatus") and e["parcelStatus"] not in _IGNORED),
        None,
    )
    status = _map(current["parcelStatus"]) if current else ParcelStatus.UNKNOWN
    delivered_at = _ts(current.get("timestamp")) if status is ParcelStatus.DELIVERED else None
    attributes = parcel.get("parcelAttributes")
    if isinstance(attributes, dict) and attributes.get("delivered"):
        if status is not ParcelStatus.DELIVERED:
            status = ParcelStatus.DELIVERED
            delivered_at = _ts(attributes.get("deliveredTimestamp"))
    events = [
        TrackingEvent(timestamp=stamp, text=label, location=None)
        for e in progress
        if (stamp := _ts(e.get("timestamp")))
        and (label := _label(e))
    ][:MAX_EVENTS]
    text = _label(current) if current else None
    return TrackingResult(
        status=status,
        status_text=text,
        eta_date=None,
        eta_from=None,
        eta_to=None,
        location=None,
        pickup_point=None,
        pickup_until=None,
        delivered_at=delivered_at,
        events=events,
    )


class HermesCarrier(Carrier):
    """Hermes Germany (keyless, number only)."""

    key = "hermes"
    name = "Hermes"

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    @staticmethod
    def matches(number: str) -> Match:
        if len(number) == 20 and number[0] == "H" and number[1:].isdigit():
            return Match.SURE
        if len(number) == 14 and number.isdigit():
            return Match.POSSIBLE
        return Match.NO

    async def fetch(self, number: str, postcode: str | None) -> TrackingResult:
        try:
            async with self._session.get(
                f"{HERMES_URL}/{number}", headers=_HEADERS, timeout=_TIMEOUT
            ) as resp:
                if resp.status in (400, 404):
                    raise NotFound(number)
                if resp.status == 429:
                    retry = resp.headers.get("Retry-After")
                    raise RateLimited(int(retry) if retry and retry.isdigit() else None)
                if resp.status != 200:
                    raise CarrierUnavailable(f"Hermes HTTP {resp.status}")
                try:
                    data = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise ParseError("Hermes returned a non-JSON body") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CarrierUnavailable(str(err)) from err
        return parse_hermes(data)

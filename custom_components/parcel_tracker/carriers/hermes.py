"""Hermes Germany via the keyless tracking endpoint of myhermes.de.

Response shape and status codes follow ha-parcel-integrations/ha-hermes (MIT):
a JSON array whose first element is the parcel, ``parcelProgress`` newest first,
the stable English ``parcelStatus`` per event and the localised ``historyText``.
The endpoint exposes no delivery day, so the ETA stays with what mails told.

A parcel handed to a PaketShop waits there for its recipient: "awaiting pickup",
never "delivered" (as GLS' DELIVEREDPS and DHL's Packstation). The code Hermes sends
for that step is not known for sure, so the German text of the step is read as well.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import aiohttp

from ..const import MAX_EVENTS
from ..models import ParcelStatus, TrackingEvent, TrackingResult
from .base import (
    Carrier,
    CarrierUnavailable,
    Match,
    NotFound,
    ParseError,
    RateLimited,
    plain_text,
)

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
            "DELIVERED_HOMEDELIVERY", "DELIVERED_NEIGHBOUR", "DELIVERED_PARCELBOX",
            "DELIVERED_MAILBOX", "DELIVERED_DROPOFF", "DELIVERED", "PICKED_UP_BY_RECIPIENT",
            "COLLECTED",
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
# Delivered to a PaketShop, not to the recipient: the parcel waits there. The collection
# has its own later event (PICKED_UP_BY_RECIPIENT, COLLECTED); should Hermes report it
# under this code as well, its text tells ("… erfolgreich abgeholt").
_SHOP_DELIVERED = frozenset({"DELIVERED_PARCELSHOP"})
# Texts of the waiting step ("… liegt im Hermes PaketShop … zur Abholung bereit"). The
# word PaketShop alone says nothing ("wird … an den PaketShop zugestellt").
_WAITING_TEXT = re.compile(r"zur\s+abholung\s+bereit|\babholbereit\b", re.IGNORECASE)
# "liegt … zur Abholung" in this order is the present tense, whatever else follows.
_LIES_THERE_TEXT = re.compile(
    r"\bliegt\b.*(?:\babholung\b|\babholbereit\b)", re.IGNORECASE | re.DOTALL
)
_CAN_BE_COLLECTED_TEXT = re.compile(r"\bkann\b.*\babgeholt\s+werden\b", re.IGNORECASE | re.DOTALL)
# An announcement of the step ("sobald …", "wird … bereit liegen") is not the step.
_ANNOUNCED_TEXT = re.compile(r"\b(?:sobald|demnächst)\b", re.IGNORECASE)
_FUTURE_TEXT = re.compile(r"\bwird\b", re.IGNORECASE)
_NOT_COLLECTED_TEXT = re.compile(r"\bnicht\b[^.]*\babgeholt\b", re.IGNORECASE)
_COLLECTED_TEXT = re.compile(r"\bwurde\b.*\babgeholt\b", re.IGNORECASE | re.DOTALL)
# Narrower for a code nobody knows: drivers collect parcels as well.
_COLLECTED_FOR_SURE_TEXT = re.compile(r"\berfolgreich\s+abgeholt\b", re.IGNORECASE)
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
    raw = event.get("historyText")
    return (plain_text(raw) if isinstance(raw, str) else raw) or code or None


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


def _waits(text: str) -> bool:
    """True when the text says the parcel lies ready for collection right now."""
    if _ANNOUNCED_TEXT.search(text):
        return False
    if _CAN_BE_COLLECTED_TEXT.search(text) or _LIES_THERE_TEXT.search(text):
        return True
    return bool(_WAITING_TEXT.search(text)) and not _FUTURE_TEXT.search(text)


def _status(event: dict[str, Any]) -> ParcelStatus:
    """Status of the current event: its code, for the PaketShop steps also its text.

    The text is only compared, never stored anywhere else and never logged: it names
    the shop and its address.
    """
    code = event["parcelStatus"]
    raw = event.get("historyText")
    text = raw if isinstance(raw, str) else ""
    if code in _SHOP_DELIVERED:
        collected = (
            _COLLECTED_TEXT.search(text) is not None
            and _NOT_COLLECTED_TEXT.search(text) is None
            and not _waits(text)
        )
        return ParcelStatus.DELIVERED if collected else ParcelStatus.AWAITING_PICKUP
    status = _map(code)  # an unknown code is warned about, whatever its text tells
    if status is ParcelStatus.UNKNOWN:
        if _waits(text):
            return ParcelStatus.AWAITING_PICKUP
        if _COLLECTED_FOR_SURE_TEXT.search(text) and not _NOT_COLLECTED_TEXT.search(text):
            return ParcelStatus.DELIVERED
    return status


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
    status = _status(current) if current else ParcelStatus.UNKNOWN
    delivered_at = _ts(current.get("timestamp")) if status is ParcelStatus.DELIVERED else None
    attributes = parcel.get("parcelAttributes")
    if isinstance(attributes, dict) and attributes.get("delivered"):
        # Not for a parcel waiting in a PaketShop: whatever the flag means there, the
        # recipient does not have it yet. The collection is an event of its own.
        if status not in (ParcelStatus.DELIVERED, ParcelStatus.AWAITING_PICKUP):
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

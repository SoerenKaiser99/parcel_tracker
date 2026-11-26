"""Österreichische Post via its public tracking API (tracking number only, no account).

One keyless GraphQL POST per number, the endpoint the Post app uses.
Endpoint, query and state vocabulary after ha-parcel-integrations/ha-oesterreichische-post
(MIT). Only the number is sent; of the answer the recipient's address text and the
shipper's address are never read.

The answer's events come in no fixed order: the newest by timestamp tells the status.
Post stamps in Austrian local time without an offset.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

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
VIENNA = ZoneInfo("Europe/Vienna")
POST_AT_URL = "https://api.post.at/sendungen/sv/graphqlPublic"
_TIMEOUT = aiohttp.ClientTimeout(total=25)
_HEADERS = {"Accept-Language": "de", "Content-Type": "application/json"}
_INVALID_CODE = "INVALID_ARGUMENT_IDENTITY_CODE"

QUERY = """
query ShipmentPublic($id: String!) {
  einzelsendung(sendungsnummer: $id) {
    status estimatedDelivery { startDate endDate startTime endTime }
    sendungsEvents { trackingStateKey text timestamp eventPlaceName }
  }
}
"""

# Domestic parcels: 22 digits starting "10" (sure); 24 digits are Post's too but not only
# Post's (a guess). International UPU S10 ending "AT": sent from Austria, but on its way
# the parcel may belong to another post or to DHL (a guess, DHL stays in the game).
_DOMESTIC = re.compile(r"10\d{20}")
_DOMESTIC_24 = re.compile(r"\d{24}")
_S10_AT = re.compile(r"[A-Z]{2}\d{9}AT")

# Post's TrackingState vocabulary (after camelCase -> UPPER_SNAKE).
_STATUS: dict[str, ParcelStatus] = {
    "PENDING_INFORMATION": ParcelStatus.PRE_TRANSIT,
    "PARCEL_STAMP": ParcelStatus.PRE_TRANSIT,
    "AVISO": ParcelStatus.PRE_TRANSIT,
    "ALLES_POST": ParcelStatus.PRE_TRANSIT,
    "DELIVERY_HAND_OVER": ParcelStatus.IN_TRANSIT,
    "IN_DISTRIBUTION": ParcelStatus.IN_TRANSIT,
    "CUSTOMS_CLEARANCE": ParcelStatus.IN_TRANSIT,
    "DELIVERY_IN_CUSTOMS": ParcelStatus.IN_TRANSIT,
    "IN_DELIVERY": ParcelStatus.OUT_FOR_DELIVERY,
    "NOTIFIED": ParcelStatus.AWAITING_PICKUP,
    "READY_FOR_PICK_UP": ParcelStatus.AWAITING_PICKUP,
    "READY_FOR_PICK_UP_STATION": ParcelStatus.AWAITING_PICKUP,
    "READY_FOR_PICK_UP_POINT": ParcelStatus.AWAITING_PICKUP,
    "READY_FOR_PICK_UP_BOX": ParcelStatus.AWAITING_PICKUP,
    "DELIVERED": ParcelStatus.DELIVERED,
    "DELIVERY_PARKED": ParcelStatus.DELIVERED,
    "DELIVERY_IN_RETURN": ParcelStatus.EXCEPTION,
    "DELIVERY_DELAYED": ParcelStatus.EXCEPTION,
    "DELIVERY_INTERUPTED": ParcelStatus.EXCEPTION,  # (sic, Post's spelling)
    "NOT_REACHABLE": ParcelStatus.EXCEPTION,
    "DELIVERY_ATTEMPT_FAILED": ParcelStatus.EXCEPTION,
    "RETURNED_TO_SENDER": ParcelStatus.EXCEPTION,
}
_WARNED: set[str] = set()
_CAMEL = re.compile(r"([a-z0-9])([A-Z])")


def state_key(key: Any) -> str | None:
    """'readyForPickUp' -> 'READY_FOR_PICK_UP'."""
    if not key:
        return None
    return _CAMEL.sub(r"\1_\2", str(key)).upper()


def _stamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=VIENNA)


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _clock(day: date | None, value: Any) -> datetime | None:
    if day is None or not value:
        return None
    try:
        return datetime.combine(day, time.fromisoformat(str(value)), VIENNA)
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return plain_text(value).strip() or None


def parse_post_at(shipment: dict[str, Any]) -> TrackingResult:
    """Normalise the ``einzelsendung`` object."""
    raw_events = shipment.get("sendungsEvents") or []
    if not isinstance(raw_events, list):
        raise ParseError("Post: sendungsEvents is no list")
    dated = [
        (stamp, event)
        for event in raw_events
        if isinstance(event, dict) and (stamp := _stamp(event.get("timestamp")))
    ]
    dated.sort(key=lambda item: item[0], reverse=True)

    # The newest scan with a state decides. A state not known here is reported as unknown
    # rather than skipping back to an older one ("in delivery" followed by a failed attempt
    # must not stay "in delivery").
    status = ParcelStatus.UNKNOWN
    newest = next((key for _, e in dated if (key := state_key(e.get("trackingStateKey")))), None)
    if newest is not None:
        mapped = _STATUS.get(newest)
        if mapped is not None:
            status = mapped
        elif newest not in _WARNED:
            _WARNED.add(newest)
            _LOGGER.warning(
                "Unknown Österreichische Post state %s; please report it to Paket Tracker",
                newest,
            )
    if not dated:
        # Post knows the number, nothing is scanned yet: the label is printed.
        status = ParcelStatus.PRE_TRANSIT

    events = [
        TrackingEvent(
            timestamp=stamp,
            text=_text(event.get("text")) or state_key(event.get("trackingStateKey")) or "",
            location=_text(event.get("eventPlaceName")),
        )
        for stamp, event in dated
    ][:MAX_EVENTS]

    eta = shipment.get("estimatedDelivery")
    eta = eta if isinstance(eta, dict) else {}
    first, last = _day(eta.get("startDate")), _day(eta.get("endDate"))
    open_parcel = status not in (ParcelStatus.DELIVERED, ParcelStatus.AWAITING_PICKUP)
    delivered_at = next(
        (
            stamp
            for stamp, event in dated
            if _STATUS.get(state_key(event.get("trackingStateKey")) or "")
            is ParcelStatus.DELIVERED
        ),
        None,
    )
    return TrackingResult(
        status=status,
        # Post's own "status" is a short code ("ZU"): the newest scan's words say more.
        status_text=(events[0].text if events else None) or _text(shipment.get("status")),
        eta_date=first if open_parcel else None,
        eta_latest=last if open_parcel and last and first and last > first else None,
        eta_from=_clock(first, eta.get("startTime")) if open_parcel else None,
        eta_to=_clock(last or first, eta.get("endTime")) if open_parcel else None,
        location=events[0].location if events else None,
        pickup_point=None,
        pickup_until=None,
        delivered_at=delivered_at if status is ParcelStatus.DELIVERED else None,
        events=events,
    )


class PostAtCarrier(Carrier):
    """Österreichische Post (public tracking API, keyless)."""

    key = "post_at"
    name = "Österreichische Post"

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    @staticmethod
    def matches(number: str) -> Match:
        if _DOMESTIC.fullmatch(number):
            return Match.SURE
        if _DOMESTIC_24.fullmatch(number) or _S10_AT.fullmatch(number):
            return Match.POSSIBLE
        return Match.NO

    async def fetch(self, number: str, postcode: str | None) -> TrackingResult:
        body = {"query": QUERY, "variables": {"id": number}}
        try:
            async with self._session.post(
                POST_AT_URL, json=body, headers=_HEADERS, timeout=_TIMEOUT
            ) as resp:
                status = resp.status
                if status == 429:
                    retry = resp.headers.get("Retry-After")
                    raise RateLimited(int(retry) if retry and retry.isdigit() else None)
                if status >= 500 or status in (401, 403):
                    raise CarrierUnavailable(f"Post HTTP {status}")
                try:
                    payload = await resp.json(content_type=None)
                except ValueError as err:
                    if status != 200:
                        raise CarrierUnavailable(f"Post HTTP {status}") from err
                    raise ParseError("Post returned no JSON") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CarrierUnavailable(str(err)) from err
        if not isinstance(payload, dict):
            raise ParseError("Post answer is no object")
        if errors := payload.get("errors"):
            if any(
                isinstance(e, dict)
                and isinstance(e.get("extensions"), dict)
                and e["extensions"].get("code") == _INVALID_CODE
                for e in (errors if isinstance(errors, list) else [])
            ):
                raise NotFound(f"Post rejects {number}")
            raise CarrierUnavailable(f"Post HTTP {status}: GraphQL error")
        if status != 200:
            raise ParseError(f"Post HTTP {status}")
        data = payload.get("data")
        shipment = data.get("einzelsendung") if isinstance(data, dict) else None
        if not isinstance(shipment, dict):
            raise NotFound(number)
        return parse_post_at(shipment)

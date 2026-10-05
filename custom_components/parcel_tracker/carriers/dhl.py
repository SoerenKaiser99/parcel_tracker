"""DHL via the official Shipment Tracking – Unified API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import aiohttp

from ..const import MAX_EVENTS
from ..models import ParcelStatus, TrackingEvent, TrackingResult
from .base import (
    BERLIN,
    AuthError,
    Carrier,
    CarrierUnavailable,
    Match,
    MissingCredentials,
    NotFound,
    ParseError,
    RateLimited,
)

DHL_URL = "https://api-eu.dhl.com/track/shipments"
_PROBE_NUMBER = "00340000000000000000"
_TIMEOUT = aiohttp.ClientTimeout(total=20)

_CODE_MAP = {
    "pre-transit": ParcelStatus.PRE_TRANSIT,
    "transit": ParcelStatus.IN_TRANSIT,
    "delivered": ParcelStatus.DELIVERED,
    "failure": ParcelStatus.EXCEPTION,
    "unknown": ParcelStatus.UNKNOWN,
}

_SHORT_CODE_MAP = {
    "ZU": ParcelStatus.DELIVERED,
    "PO": ParcelStatus.OUT_FOR_DELIVERY,
    "VA": ParcelStatus.PRE_TRANSIT,
    "EE": ParcelStatus.IN_TRANSIT,
    "AA": ParcelStatus.IN_TRANSIT,
}
_COUNTRIES = {"deutschland", "germany"}


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BERLIN)


def _locality(node: dict[str, Any] | None) -> str | None:
    raw = (((node or {}).get("location") or {}).get("address") or {}).get("addressLocality")
    if not isinstance(raw, str):
        return raw
    value = raw.strip()
    for country in ("Deutschland", "Germany"):
        if value.lower().endswith(f", {country.lower()}"):
            value = value[: -len(country) - 2].strip()
            break
    if not value or value.lower() in _COUNTRIES:
        return None
    return value


def _refine(status: ParcelStatus, text: str) -> ParcelStatus:
    lower = text.lower()
    if status is not ParcelStatus.IN_TRANSIT:
        return status
    if "zustellfahrzeug" in lower or "in zustellung" in lower:
        return ParcelStatus.OUT_FOR_DELIVERY
    if "zur abholung bereit" in lower or "abholbereit" in lower:
        return ParcelStatus.AWAITING_PICKUP
    if "zustellbasis" in lower:
        return ParcelStatus.AT_DELIVERY_DEPOT
    return status


def parse_dhl(data: dict[str, Any]) -> TrackingResult:
    """Normalise a Unified API response."""
    try:
        shipment = data["shipments"][0]
        current = shipment["status"]
    except (KeyError, IndexError, TypeError) as err:
        raise ParseError("no shipment in DHL response") from err

    text = current.get("description") or current.get("status") or ""
    known = _SHORT_CODE_MAP.get(current.get("status"))
    status = known or _refine(_CODE_MAP.get(current.get("statusCode"), ParcelStatus.UNKNOWN), text)

    frame = shipment.get("estimatedTimeOfDeliveryTimeFrame") or {}
    eta_from = _ts(frame.get("estimatedFrom"))
    eta_to = _ts(frame.get("estimatedThrough"))
    eta_point = _ts(shipment.get("estimatedTimeOfDelivery"))
    eta_date = (eta_from or eta_point).date() if (eta_from or eta_point) else None

    events = [
        TrackingEvent(
            timestamp=_ts(ev.get("timestamp")),
            text=ev.get("description") or ev.get("status") or "",
            location=_locality(ev),
        )
        for ev in (shipment.get("events") or [])[:MAX_EVENTS]
        if ev.get("timestamp")
    ]

    return TrackingResult(
        status=status,
        status_text=text or None,
        eta_date=eta_date,
        eta_from=eta_from,
        eta_to=eta_to,
        location=_locality(current),
        pickup_point=_locality(current) if status is ParcelStatus.AWAITING_PICKUP else None,
        pickup_until=None,
        delivered_at=_ts(current.get("timestamp")) if status is ParcelStatus.DELIVERED else None,
        events=events,
    )


# International shipments: a UPU S10 number issued in Germany ("CQ…DE", "RR…DE"). No other
# carrier's rule takes 13 characters, so it is a sure match.
_S10 = re.compile(r"[A-Z]{2}\d{9}DE")


class DhlCarrier(Carrier):
    """DHL Germany."""

    key = "dhl"
    name = "DHL"

    def __init__(self, session: aiohttp.ClientSession, api_key: str | None) -> None:
        self._session = session
        self._api_key = api_key

    @staticmethod
    def matches(number: str) -> Match:
        if len(number) == 20 and number.isdigit() and number.startswith("00340"):
            return Match.SURE
        if _S10.fullmatch(number):
            return Match.SURE
        if number.startswith("JJD"):
            return Match.POSSIBLE
        if len(number) == 12 and number.isdigit():
            return Match.POSSIBLE
        return Match.NO

    async def _get(self, params: dict[str, str]) -> aiohttp.ClientResponse:
        if not self._api_key:
            raise MissingCredentials("DHL API key missing")
        try:
            return await self._session.get(
                DHL_URL,
                params=params,
                headers={"DHL-API-Key": self._api_key, "Accept": "application/json"},
                timeout=_TIMEOUT,
            )
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CarrierUnavailable(str(err)) from err

    async def fetch(self, number: str, postcode: str | None) -> TrackingResult:
        params = {"trackingNumber": number, "language": "de"}
        if postcode:
            params["recipientPostalCode"] = postcode
        resp = await self._get(params)
        async with resp:
            if resp.status == 200:
                try:
                    data = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise ParseError("DHL returned a non-JSON body") from err
                return parse_dhl(data)
            if resp.status == 404:
                raise NotFound(number)
            if resp.status in (401, 403):
                raise AuthError(f"DHL rejected key ({resp.status})")
            if resp.status == 429:
                retry = resp.headers.get("Retry-After")
                raise RateLimited(int(retry) if retry and retry.isdigit() else None)
            raise CarrierUnavailable(f"DHL HTTP {resp.status}")

    async def validate_key(self) -> bool:
        """True if the key is accepted (probe number answers 404 or 200)."""
        resp = await self._get({"trackingNumber": _PROBE_NUMBER, "language": "de"})
        async with resp:
            return resp.status not in (401, 403)

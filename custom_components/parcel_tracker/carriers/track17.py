"""17track Tracking API v2.2 (optional; numbers are registered only on explicit request).

Only the tracking number and a carrier code go to 17track. The parser keeps time, text and
place of events; ``shipping_info`` and every address field are never read.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from typing import Any

import aiohttp

from ..const import TRACK17_BATCH, TRACK17_MAX_EVENTS
from ..models import ParcelStatus, TrackingEvent, TrackingResult
from .base import (
    BERLIN,
    AuthError,
    CarrierError,
    CarrierUnavailable,
    NotFound,
    ParseError,
    RateLimited,
)

TRACK17_URL = "https://api.17track.net/track/v2.2"
ALREADY_REGISTERED = -18019901
_TIMEOUT = aiohttp.ClientTimeout(total=20)
# Key invalid, not authorised, IP not allowed: nothing works until the settings change.
_AUTH_CODES = frozenset({-18010001, -18010002, -18010005})

EXPIRED = "Expired"
_STATUS = {
    "InfoReceived": ParcelStatus.PRE_TRANSIT,
    "InTransit": ParcelStatus.IN_TRANSIT,
    "OutForDelivery": ParcelStatus.OUT_FOR_DELIVERY,
    "AvailableForPickup": ParcelStatus.AWAITING_PICKUP,
    "Delivered": ParcelStatus.DELIVERED,
    "DeliveryFailure": ParcelStatus.EXCEPTION,
    "Exception": ParcelStatus.EXCEPTION,
    "NotFound": ParcelStatus.UNKNOWN,
    EXPIRED: ParcelStatus.UNKNOWN,
}

# Field groups enrich() may fill (stored in TrackingResult.enriched).
# "status" marks a result that is 17track's as a whole: the carrier has not answered yet.
ENRICH_STATUS = "status"
ENRICH_LOCATION = "location"
ENRICH_ETA = "eta"
ENRICH_WINDOW = "window"
ENRICH_EVENTS = "events"


@dataclass(frozen=True)
class Track17Info:
    """One parsed gettrackinfo entry."""

    result: TrackingResult
    expired: bool  # 17track stopped tracking: no more polls
    carrier: int | None  # carrier code 17track uses


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BERLIN)


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _event(raw: Any) -> TrackingEvent | None:
    """Time, text and place only (never the event's address object)."""
    if not isinstance(raw, dict):
        return None
    stamp = _time(raw.get("time_iso")) or _time(raw.get("time_utc"))
    text = _text(raw.get("description"))
    if stamp is None or text is None:
        return None
    return TrackingEvent(timestamp=stamp, text=text, location=_text(raw.get("location")))


def _events(tracking: Any) -> list[TrackingEvent]:
    providers = tracking.get("providers") if isinstance(tracking, dict) else None
    events: list[TrackingEvent] = []
    for provider in providers or []:
        if isinstance(provider, dict):
            events.extend(e for raw in provider.get("events") or [] if (e := _event(raw)))
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events[:TRACK17_MAX_EVENTS]


def _is_window(start: datetime, end: datetime) -> bool:
    first, last = start.astimezone(BERLIN), end.astimezone(BERLIN)
    whole_day = first.time() == time(0) and last.time() >= time(23, 59)
    return first.date() == last.date() and first < last and not whole_day


def _eta(metrics: Any) -> tuple[date | None, date | None, datetime | None, datetime | None]:
    """(eta_date, eta_latest, eta_from, eta_to) from time_metrics.estimated_delivery_date."""
    estimate = metrics.get("estimated_delivery_date") if isinstance(metrics, dict) else None
    if not isinstance(estimate, dict):
        return None, None, None, None
    end = _time(estimate.get("to"))
    start = _time(estimate.get("from")) or end
    if start is None:
        return None, None, None, None
    first = start.astimezone(BERLIN).date()
    if end is None or end <= start:
        return first, None, None, None
    last = end.astimezone(BERLIN).date()
    if last > first:
        return first, last, None, None
    if _is_window(start, end):
        return first, None, start, end
    return first, None, None, None


def parse_track17(item: Any) -> Track17Info:
    """Normalise one accepted gettrackinfo entry (shipping_info is never read)."""
    if not isinstance(item, dict):
        raise ParseError("17track entry is not an object")
    info = item.get("track_info")
    if not isinstance(info, dict):
        raise NotFound("17track has no tracking information yet")
    latest_status = info.get("latest_status")
    raw_status = str(latest_status.get("status") or "") if isinstance(latest_status, dict) else ""
    status = _STATUS.get(raw_status, ParcelStatus.UNKNOWN)
    latest = info.get("latest_event") if isinstance(info.get("latest_event"), dict) else {}
    events = _events(info.get("tracking"))
    eta_date = eta_latest = eta_from = eta_to = delivered_at = None
    if status is ParcelStatus.DELIVERED:
        newest = _event(latest)
        delivered_at = newest.timestamp if newest else (events[0].timestamp if events else None)
    else:
        eta_date, eta_latest, eta_from, eta_to = _eta(info.get("time_metrics"))
    carrier = item.get("carrier")
    result = TrackingResult(
        status=status,
        status_text=_text(latest.get("description")),
        eta_date=eta_date,
        eta_from=eta_from,
        eta_to=eta_to,
        location=_text(latest.get("location")) or (events[0].location if events else None),
        pickup_point=None,
        pickup_until=None,
        delivered_at=delivered_at,
        events=events,
        eta_latest=eta_latest,
    )
    code = carrier if isinstance(carrier, int) and carrier > 0 else None
    return Track17Info(result=result, expired=raw_status == EXPIRED, carrier=code)


def enrich(base: TrackingResult, extra: TrackingResult) -> TrackingResult:
    """Fill only what the carrier's own answer (``base``) left empty.

    Status, status text and delivery time always stay the carrier's.
    """
    changes: dict[str, Any] = {}
    filled: list[str] = []
    if not base.location and extra.location:
        changes["location"] = extra.location
        filled.append(ENRICH_LOCATION)
    if base.status is not ParcelStatus.DELIVERED and extra.eta_date is not None:
        if base.eta_date is None:
            changes.update(
                eta_date=extra.eta_date,
                eta_latest=extra.eta_latest,
                eta_from=extra.eta_from,
                eta_to=extra.eta_to,
            )
            filled.append(ENRICH_ETA)
        elif (
            base.eta_from is None
            and extra.eta_from is not None
            and extra.eta_date == base.eta_date
        ):
            changes.update(eta_from=extra.eta_from, eta_to=extra.eta_to)
            filled.append(ENRICH_WINDOW)
    if not base.events and extra.events:
        changes["events"] = list(extra.events)
        filled.append(ENRICH_EVENTS)
    if not filled:
        return base
    return replace(base, **changes, enriched=(*base.enriched, *filled))


def standalone(extra: TrackingResult) -> TrackingResult:
    """No carrier answer yet: 17track's whole answer stands in, status included."""
    groups = [ENRICH_STATUS]
    if extra.location:
        groups.append(ENRICH_LOCATION)
    if extra.eta_date is not None:
        groups.append(ENRICH_ETA)
    if extra.events:
        groups.append(ENRICH_EVENTS)
    return replace(extra, events=list(extra.events), enriched=tuple(groups))


def with_track17(
    base: TrackingResult | None, extra: TrackingResult | None
) -> TrackingResult | None:
    """What to show: the carrier's own answer (``base``) plus the last 17track answer.

    Without a carrier answer the 17track answer is shown as a whole; as soon as the
    carrier answers, it is the base again and 17track only fills its gaps.
    """
    if extra is None:
        return base
    if base is None:
        return standalone(extra)
    return enrich(base, extra)


def strip_enrichment(result: TrackingResult | None) -> TrackingResult | None:
    """The carrier's own answer again: drop what 17track filled in.

    None if there is no carrier answer (a result that was 17track's as a whole).
    """
    if result is None or ENRICH_STATUS in result.enriched:
        return None
    if not result.enriched:
        return result
    changes: dict[str, Any] = {"enriched": ()}
    if ENRICH_LOCATION in result.enriched:
        changes["location"] = None
    if ENRICH_ETA in result.enriched:
        changes.update(eta_date=None, eta_latest=None, eta_from=None, eta_to=None)
    if ENRICH_WINDOW in result.enriched:
        changes.update(eta_from=None, eta_to=None)
    if ENRICH_EVENTS in result.enriched:
        changes["events"] = []
    return replace(result, **changes)


class CarrierNotDetected(CarrierError):
    """17track can't tell (or doesn't accept) the carrier of this number."""


class QuotaExhausted(CarrierError):
    """No 17track numbers left."""


class NotRegistered(CarrierError):
    """The number is not (any more) registered at 17track."""


class Track17Disabled(Exception):
    """No 17track API key is configured."""


def error_for(code: Any) -> CarrierError:
    """Exception for a 17track error code."""
    if code in _AUTH_CODES:
        return AuthError(f"17track rejected the key ({code})")
    if code == -18019902:
        return NotRegistered("number not registered at 17track")
    if code in (-18019903, -18019910):
        return CarrierNotDetected(f"17track can't use the carrier ({code})")
    if code == -18019907:
        return RateLimited(None)  # daily limit
    if code == -18019908:
        return QuotaExhausted("17track quota used up")
    if code == -18019909:
        return NotFound("17track has no data yet")
    return CarrierUnavailable(f"17track error {code}")


@dataclass(frozen=True)
class Registration:
    """A number registered at 17track (carrier: the code 17track uses, if it said)."""

    number: str
    carrier: int | None


@dataclass(frozen=True)
class Quota:
    """17track numbers of the account."""

    total: int
    used: int
    remain: int


def _entry(number: str, carrier: int | None) -> dict[str, Any]:
    return {"number": number} if carrier is None else {"number": number, "carrier": carrier}


def _rejections(data: dict[str, Any]) -> dict[str, Any]:
    """number -> error code of the rejected entries."""
    out: dict[str, Any] = {}
    for item in data.get("rejected") or []:
        if isinstance(item, dict) and isinstance(item.get("error"), dict):
            out[str(item.get("number"))] = item["error"].get("code")
    return out


class Track17Client:
    """17track Tracking API v2.2. ``register`` costs 1 quota per new number; the rest is free."""

    def __init__(self, session: aiohttp.ClientSession, key: str) -> None:
        self._session = session
        self._key = key

    async def _post(self, endpoint: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            async with self._session.post(
                f"{TRACK17_URL}/{endpoint}",
                json=payload,
                headers={"17token": self._key},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise AuthError(f"17track HTTP {resp.status}")
                if resp.status == 429:
                    retry = resp.headers.get("Retry-After")
                    raise RateLimited(int(retry) if retry and retry.isdigit() else None)
                if resp.status != 200:
                    raise CarrierUnavailable(f"17track HTTP {resp.status}")
                try:
                    body = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise ParseError("17track returned a non-JSON body") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CarrierUnavailable(str(err)) from err
        if not isinstance(body, dict):
            raise ParseError("17track answer is not an object")
        code = body.get("code")
        if code != 0:
            raise error_for(code)
        data = body.get("data")
        if not isinstance(data, dict):
            raise ParseError("17track answer without data")
        return data

    async def register(self, number: str, carrier: int | None) -> Registration:
        """Register one number (costs 1 quota unless it is already registered)."""
        data = await self._post("register", [_entry(number, carrier)])
        for item in data.get("accepted") or []:
            if isinstance(item, dict) and str(item.get("number")) == number:
                code = item.get("carrier")
                return Registration(number, code if isinstance(code, int) and code > 0 else None)
        code = _rejections(data).get(number)
        if code == ALREADY_REGISTERED:
            return Registration(number, None)
        if code is None:
            raise ParseError("17track neither accepted nor rejected the number")
        raise error_for(code)

    async def gettrackinfo(
        self, items: list[tuple[str, int | None]]
    ) -> dict[str, Track17Info | CarrierError]:
        """Status of registered numbers (free), at most TRACK17_BATCH per call."""
        out: dict[str, Track17Info | CarrierError] = {}
        for start in range(0, len(items), TRACK17_BATCH):
            chunk = items[start : start + TRACK17_BATCH]
            data = await self._post("gettrackinfo", [_entry(n, c) for n, c in chunk])
            for item in data.get("accepted") or []:
                if not isinstance(item, dict):
                    continue
                number = str(item.get("number"))
                try:
                    out[number] = parse_track17(item)
                except CarrierError as err:
                    out[number] = err
            for number, code in _rejections(data).items():
                out[number] = error_for(code)
        return out

    async def getquota(self) -> Quota:
        """Numbers of the account (free)."""
        data = await self._post("getquota", [])
        try:
            return Quota(
                int(data["quota_total"]), int(data["quota_used"]), int(data["quota_remain"])
            )
        except (KeyError, TypeError, ValueError) as err:
            raise ParseError("17track quota answer incomplete") from err

"""UPS via the official Track API (OAuth client credentials), with a monthly call budget.

Only used when a UPS Client ID and Secret are configured; without them UPS parcels
come from mails only. Every tracking call counts towards the budget, token calls
don't. The response is read according to the UPS Track API schema
(getSingleTrackResponseUsingGET); addresses and the drop place are never read.
"""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import aiohttp

from ..const import MAX_EVENTS
from ..models import ParcelStatus, TrackingEvent, TrackingResult
from .base import (
    BERLIN,
    AuthError,
    Carrier,
    CarrierError,
    CarrierUnavailable,
    Match,
    MissingCredentials,
    NotFound,
    ParseError,
    RateLimited,
)

_LOGGER = logging.getLogger(__name__)

UPS_BASE = "https://onlinetools.ups.com"
UPS_TOKEN_URL = f"{UPS_BASE}/security/v1/oauth/token"
UPS_TRACK_URL = f"{UPS_BASE}/api/track/v1/details"
TRANSACTION_SRC = "parcel_tracker"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_TOKEN_MARGIN = timedelta(seconds=60)
_DEFAULT_TOKEN_LIFETIME = 3600  # seconds, when UPS sends no usable expires_in

_TYPES = {
    "M": ParcelStatus.PRE_TRANSIT,
    "MV": ParcelStatus.PRE_TRANSIT,
    "P": ParcelStatus.IN_TRANSIT,
    "I": ParcelStatus.IN_TRANSIT,
    "W": ParcelStatus.IN_TRANSIT,
    "DO": ParcelStatus.IN_TRANSIT,
    "DD": ParcelStatus.IN_TRANSIT,
    "O": ParcelStatus.OUT_FOR_DELIVERY,
    "D": ParcelStatus.DELIVERED,
    "X": ParcelStatus.EXCEPTION,
    "RS": ParcelStatus.EXCEPTION,
    "NA": ParcelStatus.UNKNOWN,
}
_OUT_FOR_DELIVERY_CODES = frozenset({"021"})
# Fallback when an answer carries no status type at all.
_STATUS_CODES = {
    "011": ParcelStatus.DELIVERED,
    "021": ParcelStatus.OUT_FOR_DELIVERY,
    "005": ParcelStatus.IN_TRANSIT,
    "003": ParcelStatus.PRE_TRANSIT,
}
_OUT_FOR_DELIVERY_SHORT = frozenset({"OT"})
_WINDOW_TYPES = frozenset({"EDW", "CDW", "IDW"})
_WARNED: set[str] = set()


class BudgetExhausted(CarrierError):
    """The monthly UPS call budget is used up."""


def month_key(now: datetime) -> str:
    """'YYYY-MM' of ``now`` in Europe/Berlin."""
    return now.astimezone(BERLIN).strftime("%Y-%m")


def next_month_start(now: datetime) -> datetime:
    """Midnight (Berlin) of the first day of the month after ``now``."""
    local = now.astimezone(BERLIN)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return datetime(year, month, 1, tzinfo=BERLIN)


@dataclass
class ApiBudget:
    """Tracking calls made in ``month`` (persisted in the store)."""

    month: str | None = None
    count: int = 0

    def used(self, now: datetime) -> int:
        return self.count if self.month == month_key(now) else 0

    def spend(self, now: datetime) -> None:
        key = month_key(now)
        if self.month != key:
            self.month, self.count = key, 0
        self.count += 1

    def to_dict(self) -> dict[str, Any]:
        return {"month": self.month, "count": self.count}

    @classmethod
    def from_dict(cls, data: Any) -> ApiBudget:
        if not isinstance(data, dict):
            return cls()
        month, count = data.get("month"), data.get("count")
        if not isinstance(month, str) or not isinstance(count, int):
            return cls()
        return cls(month, count)


def _basic(client_id: str, secret: str) -> str:
    """HTTP Basic auth header value for the token request."""
    return "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()


def _day(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return None
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError:
        return None


def _clock(day: date, value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) < 4 or not value[:4].isdigit():
        return None
    try:
        return datetime.combine(day, time(int(value[:2]), int(value[2:4])), tzinfo=BERLIN)
    except ValueError:
        return None


def _map(status: dict[str, Any]) -> ParcelStatus:
    kind = str(status.get("type") or "")
    if not kind:
        return _STATUS_CODES.get(str(status.get("statusCode") or ""), ParcelStatus.UNKNOWN)
    mapped = _TYPES.get(kind)
    if mapped is None:
        if kind not in _WARNED:
            _WARNED.add(kind)
            _LOGGER.warning(
                "Unknown UPS status type %s shown as 'unknown'; please report it to Paket Tracker",
                kind,
            )
        return ParcelStatus.UNKNOWN
    if mapped is ParcelStatus.IN_TRANSIT and (
        status.get("statusCode") in _OUT_FOR_DELIVERY_CODES
        or status.get("code") in _OUT_FOR_DELIVERY_SHORT
    ):
        return ParcelStatus.OUT_FOR_DELIVERY
    return mapped


def _event(activity: dict[str, Any]) -> TrackingEvent | None:
    day = _day(activity.get("date"))
    stamp = _clock(day, activity.get("time")) if day else None
    status = activity.get("status") or {}
    if stamp is None or not status.get("description"):
        return None
    city = ((activity.get("location") or {}).get("address") or {}).get("city") or None
    return TrackingEvent(timestamp=stamp, text=status["description"], location=city)


def parse_ups(data: Any) -> TrackingResult:
    """Normalise a Track API answer (first package of the first shipment)."""
    try:
        shipment = data["trackResponse"]["shipment"][0]
    except (KeyError, IndexError, TypeError) as err:
        raise ParseError("no shipment in UPS response") from err
    packages = shipment.get("package") or []
    if not packages:
        raise NotFound("UPS has no tracking information yet")
    package = packages[0]
    activities = [a for a in package.get("activity") or [] if isinstance(a, dict)]
    latest = (activities[0].get("status") if activities else None) or {}
    current = package.get("currentStatus") or latest
    if not current.get("type"):
        if latest.get("type"):
            current = latest  # currentStatus without a type: the newest activity tells it
        elif not current.get("statusCode") and latest.get("statusCode"):
            current = {**current, "statusCode": latest["statusCode"]}
    status = _map(current)

    days = {d.get("type"): _day(d.get("date")) for d in package.get("deliveryDate") or []}
    window = package.get("deliveryTime") or {}
    eta_date = eta_from = eta_to = delivered_at = None
    if status is ParcelStatus.DELIVERED:
        day = days.get("DEL") or (_day(activities[0].get("date")) if activities else None)
        if day:
            end = window.get("endTime") if window.get("type") == "DEL" else None
            clock = end or (activities[0].get("time") if activities else None)
            delivered_at = _clock(day, clock) or datetime.combine(day, time(0), tzinfo=BERLIN)
    else:
        eta_date = days.get("RDD") or days.get("SDD")
        if eta_date and window.get("type") in _WINDOW_TYPES:
            eta_from = _clock(eta_date, window.get("startTime"))
            eta_to = _clock(eta_date, window.get("endTime"))

    pickup_until = None
    access_point = package.get("accessPointInformation") or {}
    if status is not ParcelStatus.DELIVERED and access_point.get("pickupByDate"):
        status = ParcelStatus.AWAITING_PICKUP
        pickup_until = _day(access_point.get("pickupByDate"))

    events = [e for a in activities if (e := _event(a))][:MAX_EVENTS]
    return TrackingResult(
        status=status,
        status_text=current.get("description") or None,
        eta_date=eta_date,
        eta_from=eta_from,
        eta_to=eta_to,
        location=events[0].location if events else None,
        pickup_point=None,
        pickup_until=pickup_until,
        delivered_at=delivered_at,
        events=events,
    )


class UpsCarrier(Carrier):
    """UPS (official Track API, optional)."""

    key = "ups"
    name = "UPS"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str | None,
        client_secret: str | None,
        budget: ApiBudget,
        limit: int,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self.budget = budget
        self.limit = limit
        self._token: str | None = None
        self._token_until: datetime | None = None
        # Set after rejected credentials: no more calls until the integration reloads.
        self.auth_blocked = False

    @staticmethod
    def matches(number: str) -> Match:
        if len(number) == 18 and number.startswith("1Z") and number.isalnum():
            return Match.SURE
        return Match.NO

    def exhausted(self, now: datetime) -> bool:
        return self.budget.used(now) >= self.limit

    async def _access_token(self, now: datetime) -> str:
        if self._token and self._token_until and now < self._token_until:
            return self._token
        if not self._client_id or not self._client_secret:
            raise MissingCredentials("UPS client ID or secret missing")
        try:
            async with self._session.post(
                UPS_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={"Authorization": _basic(self._client_id, self._client_secret)},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise AuthError(f"UPS rejected the credentials ({resp.status})")
                if resp.status == 429:
                    raise RateLimited(None)
                if resp.status != 200:
                    raise CarrierUnavailable(f"UPS token HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CarrierUnavailable(str(err)) from err
        except ValueError as err:
            raise ParseError("UPS token answer is not JSON") from err
        try:
            token = str(data["access_token"])
        except (KeyError, TypeError) as err:
            raise ParseError("UPS token answer without token") from err
        try:
            lifetime = int(data.get("expires_in"))
        except (TypeError, ValueError):
            lifetime = 0
        if lifetime <= 0:
            lifetime = _DEFAULT_TOKEN_LIFETIME
        self._token = token
        self._token_until = now + timedelta(seconds=lifetime) - _TOKEN_MARGIN
        return token

    async def _track(self, number: str, now: datetime) -> tuple[int, Any, str | None]:
        if self.exhausted(now):
            raise BudgetExhausted(f"UPS budget of {self.limit} calls used up")
        token = await self._access_token(now)
        self.budget.spend(now)
        try:
            async with self._session.get(
                f"{UPS_TRACK_URL}/{number}",
                params={"locale": "de_DE"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "transId": uuid.uuid4().hex,
                    "transactionSrc": TRANSACTION_SRC,
                    "Accept": "application/json",
                },
                timeout=_TIMEOUT,
            ) as resp:
                body = None
                if resp.status == 200:
                    try:
                        body = await resp.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError) as err:
                        raise ParseError("UPS returned a non-JSON body") from err
                return resp.status, body, resp.headers.get("Retry-After")
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CarrierUnavailable(str(err)) from err

    async def fetch(self, number: str, postcode: str | None) -> TrackingResult:
        if self.auth_blocked:
            raise AuthError("UPS credentials were rejected; waiting for a reload")
        try:
            return await self._fetch(number)
        except MissingCredentials:
            raise
        except AuthError:
            self.auth_blocked = True
            raise

    async def _fetch(self, number: str) -> TrackingResult:
        now = datetime.now(BERLIN)
        status, body, retry = await self._track(number, now)
        if status == 401:
            self._token = None  # expired or revoked: fetch a new one and try once more
            status, body, retry = await self._track(number, now)
            if status == 401:
                raise AuthError("UPS rejected the access token twice")
        if status == 200:
            return parse_ups(body)
        if status in (400, 404):
            raise NotFound(number)  # 400: UPS rejects numbers it cannot track
        if status == 403:
            raise AuthError("UPS blocked the request (403)")
        if status == 429:
            raise RateLimited(int(retry) if retry and retry.isdigit() else None)
        raise CarrierUnavailable(f"UPS HTTP {status}")

    async def validate(self) -> bool:
        """True if UPS issues a token for the credentials (no tracking call, no budget)."""
        self._token = None
        try:
            await self._access_token(datetime.now(BERLIN))
        except AuthError:
            return False
        return True

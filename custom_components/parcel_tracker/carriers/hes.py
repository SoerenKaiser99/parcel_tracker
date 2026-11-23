"""Hermes Einrichtungs Service (HES) via the keyless tracking endpoint of myhes.de.

Furniture and large appliances. The page myhes.de/de/tracking/<number> asks
``/api/request/auftragsdaten?parcelNumber=<number>`` without a login or postcode. The
answer names neither the recipient nor the address: only the shipper, the articles, the
depot, the delivery day and window and the steps of the order.

The step shown on the page (``journeycode``) tells the status: 100 order data received,
110 in the central warehouse, 130 in the delivery depot, 140 on its way, 150 delivered.
Its history (``auftragstatusdaten``) is the one the page shows the recipient, newest
last; its times are local (Europe/Berlin) without a zone.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Any

import aiohttp

from ..const import MAX_EVENTS
from ..models import ParcelStatus, TrackingEvent, TrackingResult
from .base import (
    BERLIN,
    Carrier,
    CarrierUnavailable,
    Match,
    NotFound,
    ParseError,
    RateLimited,
    plain_text,
)

_LOGGER = logging.getLogger(__name__)

HES_URL = "https://myhes.de/api/request/auftragsdaten"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_HEADERS = {"Accept": "application/json"}
_NUMBER = re.compile(r"\d{21}")

_JOURNEY = {
    100: ParcelStatus.PRE_TRANSIT,
    110: ParcelStatus.IN_TRANSIT,
    130: ParcelStatus.AT_DELIVERY_DEPOT,
    140: ParcelStatus.OUT_FOR_DELIVERY,
    150: ParcelStatus.DELIVERED,
}
# The steps of the history (``sendungsstatusId``) as seen: they tell the status where the
# page's step is one nobody knows yet. 700 "Deine Sendung wurde erfolgreich zugestellt":
# its time is the time of delivery.
_DELIVERED_STEP = 700
_STEPS = {
    40: ParcelStatus.PRE_TRANSIT,
    **dict.fromkeys((100, 190), ParcelStatus.IN_TRANSIT),
    **dict.fromkeys((300, 307, 308, 310, 500), ParcelStatus.AT_DELIVERY_DEPOT),
    430: ParcelStatus.OUT_FOR_DELIVERY,
    **dict.fromkeys((_DELIVERED_STEP, 790), ParcelStatus.DELIVERED),
}
_WARNED: set[str] = set()
# "Ihre Sendung wird am 20.10.2026 zwischen 10 - 14 Uhr zugestellt." (the depot's own
# step, while ``lieferdatum`` may still be empty)
_DAY_TEXT = re.compile(
    r"\bam\s+(\d{1,2})\.(\d{1,2})\.(\d{4})\s+zwischen\s+(\d{1,2})(?::(\d{2}))?\s*-\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*Uhr"
)
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})|(\d{1,2})\.(\d{1,2})\.(\d{4})")
_CLOCK = re.compile(r"(?:T|\s|^)(\d{1,2}):(\d{2})")


def _stamp(value: Any) -> datetime | None:
    """'2026-10-19 10:30' (local time) as an aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BERLIN)


def _day(value: Any) -> date | None:
    """A day as the answer may write it: ISO ('2026-10-20', also with a time) or German."""
    if not isinstance(value, str) or not (found := _DATE.search(value)):
        return None
    if found.group(1):
        parts = (found.group(1), found.group(2), found.group(3))
    else:
        parts = (found.group(6), found.group(5), found.group(4))
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _clock(day: date, value: Any) -> datetime | None:
    """A time of day ('10:00', '10:00:00', '2026-10-20T10:00:00') on ``day``."""
    if not isinstance(value, str) or not (found := _CLOCK.search(value)):
        return None
    hour, minute = int(found.group(1)), int(found.group(2))
    if hour > 23 or minute > 59:
        return None
    return datetime.combine(day, time(hour, minute), tzinfo=BERLIN)


def _journey_status(journey: dict[str, Any], steps: list[dict[str, Any]]) -> ParcelStatus:
    """The page's step (``journeycode``, a number, also written as text); for a step
    nobody knows yet the newest known step of the history, else "unknown" (the
    coordinator keeps the status known before, see ``KEEP_STATUS_CARRIERS``)."""
    code = journey.get("journeycode")
    try:
        status = _JOURNEY.get(int(code))
    except (TypeError, ValueError):
        status = None
    if status is not None:
        return status
    if str(code) not in _WARNED:
        _WARNED.add(str(code))
        _LOGGER.warning(
            "Unknown HES journeycode %s; please report it to Paket Tracker", code
        )
    return next(
        (
            _STEPS[step.get("sendungsstatusId")]
            for step in reversed(steps)
            if step.get("sendungsstatusId") in _STEPS
        ),
        ParcelStatus.UNKNOWN,
    )


def _eta(order: dict[str, Any], steps: list[dict[str, Any]], today: date):
    """(day, window from, window to) of the delivery: the first of ``_planned`` that is not
    before ``today``. A day gone by no longer holds (the delivery was planned anew, the
    next source may already know the new day); (None, None, None) if none is left."""
    for day, start, end in _planned(order, steps):
        if day >= today:
            return day, start, end
    return None, None, None


def _planned(order: dict[str, Any], steps: list[dict[str, Any]]):
    """The days the answer names, each with its own window, in this order: the order's
    ``lieferdatum``, the ``wunschLieferdatum`` the recipient chose, the depot's newest
    step that names a day ("am 20.10.2026 zwischen 10 - 14 Uhr")."""
    for prefix in ("liefer", "wunschLiefer"):
        if day := _day(order.get(f"{prefix}datum")):
            yield (
                day,
                _clock(day, order.get(f"{prefix}zeitfensterVon")),
                _clock(day, order.get(f"{prefix}zeitfensterBis")),
            )
    for step in reversed(steps):
        text = step.get("sendungsstatus")
        if isinstance(text, str) and (found := _DAY_TEXT.search(text)):
            try:
                day = date(int(found.group(3)), int(found.group(2)), int(found.group(1)))
            except ValueError:
                return
            yield (
                day,
                _clock(day, f"{found.group(4)}:{found.group(5) or '00'}"),
                _clock(day, f"{found.group(6)}:{found.group(7) or '00'}"),
            )
            return  # (an older step's day was planned before the newest one)


def _text(step: dict[str, Any]) -> str | None:
    """The first sentence of a step as the page shows it (the rest invites to act)."""
    raw = step.get("sendungsstatus")
    if not isinstance(raw, str):
        return None
    text = plain_text(raw)
    first = re.split(r"(?<=[.!])\s+", text, maxsplit=1)[0]
    return first or None


def parse_hes(data: Any, today: date | None = None) -> TrackingResult:
    """Normalise the answer of ``auftragsdaten``; ``today`` (local) for tests."""
    if not isinstance(data, dict) or not isinstance(data.get("body"), dict):
        raise ParseError("HES answer is not an object with a body")
    body = data["body"]
    if body.get("exceptionKey") is not None:
        raise NotFound("HES knows no order for this number")
    order = body.get("auftragsdaten")
    if not isinstance(order, dict):
        raise ParseError("HES answer has no order data")
    journey = order.get("statusjourneyDto")
    journey = journey if isinstance(journey, dict) else {}
    steps = [s for s in journey.get("auftragstatusdaten") or [] if isinstance(s, dict)]
    status = _journey_status(journey, steps)
    events = [
        TrackingEvent(timestamp=stamp, text=text, location=None)
        for s in reversed(steps)
        if (stamp := _stamp(s.get("sendungsstatusBuchungszeitpunkt"))) and (text := _text(s))
    ][:MAX_EVENTS]
    delivered_at = None
    if status is ParcelStatus.DELIVERED:
        delivered_at = next(
            (
                _stamp(s.get("sendungsstatusBuchungszeitpunkt"))
                for s in steps
                if s.get("sendungsstatusId") == _DELIVERED_STEP
            ),
            None,
        )
    day = start = end = None
    if status not in (ParcelStatus.DELIVERED, ParcelStatus.UNKNOWN):
        depot = [s for s in journey.get("statusdaten") or [] if isinstance(s, dict)]
        day, start, end = _eta(order, depot, today or datetime.now(BERLIN).date())
    return TrackingResult(
        status=status,
        status_text=events[0].text if events else None,
        eta_date=day,
        eta_from=start,
        eta_to=end,
        location=None,
        pickup_point=None,
        pickup_until=None,
        delivered_at=delivered_at,
        events=events,
    )


class HesCarrier(Carrier):
    """Hermes Einrichtungs Service (keyless, number only)."""

    key = "hes"
    name = "Hermes Einrichtungs Service"

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    @staticmethod
    def matches(number: str) -> Match:
        # 21 digits: no other carrier of ours gives such a number.
        return Match.SURE if _NUMBER.fullmatch(number) else Match.NO

    async def fetch(self, number: str, postcode: str | None) -> TrackingResult:
        try:
            async with self._session.get(
                HES_URL, params={"parcelNumber": number}, headers=_HEADERS, timeout=_TIMEOUT
            ) as resp:
                if resp.status in (400, 404, 409):
                    raise NotFound(number)
                if resp.status == 429:
                    retry = resp.headers.get("Retry-After")
                    raise RateLimited(int(retry) if retry and retry.isdigit() else None)
                if resp.status != 200:
                    raise CarrierUnavailable(f"HES HTTP {resp.status}")
                try:
                    data = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise ParseError("HES returned a non-JSON body") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CarrierUnavailable(str(err)) from err
        return parse_hes(data)

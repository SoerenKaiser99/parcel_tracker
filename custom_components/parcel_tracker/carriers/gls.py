"""GLS via the open tracking lookup of gls-group.com (no key, no cookies).

Response shape after ha-parcel-integrations/ha-gls (MIT): ``rstt028`` (number + postcode)
answers a flat object with ``progressBar`` and ``history`` (newest first); ``rstt029``
(number only) answers ``{"tuStatus": [entry]}`` without history, with ``arrivalTime``.
Only status, texts, times and the delivery day are read: ``signature``, ``references``,
``infos`` and every address field are never touched.
"""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

import aiohttp

from ..const import GLS_MAX_EVENTS
from ..models import ParcelStatus, TrackingEvent, TrackingResult
from .base import (
    BERLIN,
    Carrier,
    CarrierUnavailable,
    Match,
    NotFound,
    ParseError,
    RateLimited,
)

_LOGGER = logging.getLogger(__name__)

GLS_BASE = "https://gls-group.com/app/service/open/rest"
# Country/language path of the lookup per configured country. Checked live on 2026-10-04
# with an invalid number: AT/de answers exactly like DE/de (same JSON, same lastError
# codes, German texts). CH/de answers in the same shape but with English texts, like any
# unknown path does, so Switzerland (and everything else) stays on DE/de.
_PATHS = {"de": "DE/de", "at": "AT/de"}
_DEFAULT_PATH = "DE/de"
GLS_URL = f"{GLS_BASE}/{_DEFAULT_PATH}"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_HEADERS = {"Accept": "application/json"}
_CALLER = "witt002"  # the caller id of the public GLS tracking page
# lastError codes: unknown reference, not carried, input too short.
_NOT_FOUND_CODES = frozenset({"E206", "E800", "E801"})
_POSTCODE_MISMATCH = "E609"
_MIN_LENGTH = 8  # shorter input cannot be a GLS number: not asked at all
_MAX_RETRY_AFTER = 24 * 60 * 60  # seconds: a longer (or absurd) Retry-After waits a day

# progressBar.statusInfo, compared exactly: DELIVEREDPS (ParcelShop) is not DELIVERED.
_STATUS = {
    "PREADVICE": ParcelStatus.PRE_TRANSIT,
    **dict.fromkeys(("PROCESSING", "INTRANSIT", "MULTIPACK"), ParcelStatus.IN_TRANSIT),
    "INWAREHOUSE": ParcelStatus.AT_DELIVERY_DEPOT,
    "INDELIVERY": ParcelStatus.OUT_FOR_DELIVERY,
    **dict.fromkeys(("DELIVEREDPS", "INPICKUP"), ParcelStatus.AWAITING_PICKUP),
    "DELIVERED": ParcelStatus.DELIVERED,
    **dict.fromkeys(
        ("NOTDELIVERED", "NOTPICKEDUP", "RETURNED", "CANCELLED"), ParcelStatus.EXCEPTION
    ),
    "UNAVAILABLE": ParcelStatus.UNKNOWN,
}
_WARNED: set[str] = set()
# For invalid numbers GLS sometimes answers 200 with a dummy parcel: no owner code, or
# every event code there is.
_DUMMY_EVENT_CODES = 50
_DATE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")
_WINDOW = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})\s*(?:[–-]|bis)\s*(\d{1,2}):(\d{2})(?![\d:])")
_NO_ETA: tuple[date | None, datetime | None, datetime | None] = (None, None, None)


def gls_url(country: str | None) -> str:
    """Base URL of both lookups for a country (``de``, ``at``, ``ch``, any case)."""
    key = country.strip().lower() if isinstance(country, str) else ""
    path = _PATHS.get(key, _DEFAULT_PATH)
    return f"{GLS_BASE}/{path}"


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    """Display text (GLS escapes umlauts as HTML entities)."""
    return (html.unescape(value).strip() or None) if isinstance(value, str) else None


def _retry_after(value: str | None) -> int | None:
    """Seconds of a ``Retry-After`` header, at most a day; None for anything else."""
    text = (value or "").strip()
    if not (text.isascii() and text.isdigit()):
        return None  # missing, a date, negative, not a number
    text = text.lstrip("0")  # leading zeros are no magnitude
    # More than six digits is over a day anyway: a huge number is never converted.
    return _MAX_RETRY_AFTER if len(text) > 6 else min(int(text or 0), _MAX_RETRY_AFTER)


def _stamp(day: Any, clock: Any) -> datetime | None:
    """``date`` + ``time`` of a history entry as local Europe/Berlin time."""
    if not isinstance(day, str) or not isinstance(clock, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{day} {clock}", fmt).replace(tzinfo=BERLIN)
        except ValueError:
            continue
    return None


def _status(progress: dict[str, Any]) -> ParcelStatus:
    if progress.get("retourFlag") is True:
        return ParcelStatus.EXCEPTION
    code = progress.get("statusInfo")
    if not isinstance(code, str) or not code:
        return ParcelStatus.UNKNOWN
    if (status := _STATUS.get(code)) is not None:
        return status
    if code not in _WARNED:
        _WARNED.add(code)
        _LOGGER.warning(
            "Unknown GLS status %s shown as 'unknown'; please report it to Paket Tracker", code
        )
    return ParcelStatus.UNKNOWN


def _status_text(progress: dict[str, Any], history: list[dict[str, Any]]) -> str | None:
    """Text of the current progress step, else the bar's heading, else the newest event."""
    for step in _list(progress.get("statusBar")):
        if isinstance(step, dict) and step.get("imageStatus") == "CURRENT":
            if text := _text(step.get("statusText")):
                return text
            break
    newest = _text(history[0].get("evtDscr")) if history else None
    return _text(progress.get("statusText")) or newest


def _eta(value: Any) -> tuple[date | None, datetime | None, datetime | None]:
    """(day, from, to) of the free text ``arrivalTime.value``.

    Its format is not documented: a day is taken only if exactly one DD.MM.YYYY date is
    in the text, a window only if exactly one HH:MM–HH:MM range is.
    """
    if not isinstance(value, str):
        return _NO_ETA
    days = {match.groups() for match in _DATE.finditer(value)}
    if len(days) != 1:
        return _NO_ETA
    day_no, month, year = (int(part) for part in days.pop())
    try:
        day = date(year, month, day_no)
    except ValueError:
        return _NO_ETA
    windows = _WINDOW.findall(value)
    if len(windows) != 1:
        return day, None, None
    hour1, minute1, hour2, minute2 = (int(part) for part in windows[0])
    try:
        start = datetime(year, month, day_no, hour1, minute1, tzinfo=BERLIN)
        end = datetime(year, month, day_no, hour2, minute2, tzinfo=BERLIN)
    except ValueError:
        return day, None, None
    return (day, start, end) if start < end else (day, None, None)


def _is_dummy(entry: dict[str, Any]) -> bool:
    has_owner = any(
        isinstance(owner, dict) and owner.get("code") for owner in _list(entry.get("owners"))
    )
    progress = entry.get("progressBar")
    codes = _list(progress.get("evtNos")) if isinstance(progress, dict) else []
    return not has_owner or len(codes) > _DUMMY_EVENT_CODES


def parse_gls(data: Any, now: datetime) -> TrackingResult:
    """Normalise an rstt028 (flat) or rstt029 (``tuStatus``) answer.

    ``now`` is the poll time: the delivery time of a delivered parcel without history.
    """
    if not isinstance(data, dict):
        raise ParseError("GLS answer is not a JSON object")
    entry = data
    if "tuStatus" in data:
        found = data["tuStatus"]
        if not isinstance(found, list):
            raise ParseError("GLS tuStatus is not a list")
        if not found:
            raise NotFound("GLS knows no parcel for this number")
        entry = found[0]
        if not isinstance(entry, dict):
            raise ParseError("GLS tuStatus element is not an object")
        if _is_dummy(entry):
            raise NotFound("GLS answered with a dummy parcel")
    progress = entry.get("progressBar")
    if not isinstance(progress, dict):
        raise ParseError("GLS answer has no progressBar")
    history = [e for e in _list(entry.get("history")) if isinstance(e, dict)]
    status = _status(progress)
    events = [
        TrackingEvent(timestamp=stamp, text=text, location=None)
        for e in history
        if (stamp := _stamp(e.get("date"), e.get("time"))) and (text := _text(e.get("evtDscr")))
    ][:GLS_MAX_EVENTS]
    delivered = status is ParcelStatus.DELIVERED
    arrival = entry.get("arrivalTime")
    eta = _eta(arrival.get("value")) if isinstance(arrival, dict) and not delivered else _NO_ETA
    delivered_at = (events[0].timestamp if events else now) if delivered else None
    return TrackingResult(
        status=status,
        status_text=_status_text(progress, history),
        eta_date=eta[0],
        eta_from=eta[1],
        eta_to=eta[2],
        location=None,
        pickup_point=None,
        pickup_until=None,
        delivered_at=delivered_at,
        events=events,
    )


class GlsCarrier(Carrier):
    """GLS (open lookup; with a postcode the answer includes the history)."""

    key = "gls"
    name = "GLS"

    def __init__(self, session: aiohttp.ClientSession, country: str | None = None) -> None:
        self._session = session
        self.url = gls_url(country)
        # Parcel number -> postcode GLS refused for it (E609). In memory only: asked
        # once more after a restart, and again when another postcode is set.
        self._postcode_refused: dict[str, str] = {}

    @staticmethod
    def matches(number: str) -> Match:
        # 12 digits are deliberately no GLS match: eBay item numbers look like that.
        return Match.SURE if len(number) == 11 and number.isdigit() else Match.NO

    async def _ask(self, url: str, params: dict[str, str]) -> Any | None:
        """JSON of one lookup; None when GLS says the postcode does not match (E609)."""
        try:
            async with self._session.get(
                url, params=params, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=False
            ) as resp:
                status = resp.status
                if 300 <= status < 400:
                    # GLS closed rstt001 this way (redirect to "register-api-access").
                    raise CarrierUnavailable(f"GLS HTTP {status}: the open lookup seems closed")
                if status in (403, 429):
                    raise RateLimited(_retry_after(resp.headers.get("Retry-After")))
                try:
                    data = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    data = None  # the maintenance page is HTML
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CarrierUnavailable(str(err)) from err
        error = data.get("lastError") if isinstance(data, dict) else None
        if error == _POSTCODE_MISMATCH:
            return None
        if error in _NOT_FOUND_CODES or status == 404:
            raise NotFound(f"GLS {error or status}")
        if status != 200 or data is None:
            raise CarrierUnavailable(f"GLS HTTP {status} without a usable answer")
        return data

    async def fetch(self, number: str, postcode: str | None) -> TrackingResult:
        if len(number) < _MIN_LENGTH:
            raise NotFound(number)
        now = datetime.now(UTC)
        millis = str(int(time.time() * 1000))
        code = (postcode or "").replace(" ", "")
        if code and self._postcode_refused.get(number) != code:
            data = await self._ask(
                f"{self.url}/rstt028/{quote(number, safe='')}",
                {"caller": _CALLER, "millis": millis, "tuOwnerCode": "", "postalCode": code},
            )
            if data is not None:
                self._postcode_refused.pop(number, None)
                return parse_gls(data, now)
            # Postcode of another address (E609): the lookup by number still tells the
            # status. Remembered, so later polls cost one request instead of two.
            self._postcode_refused[number] = code
        data = await self._ask(
            f"{self.url}/rstt029",
            {"match": number, "type": "", "caller": _CALLER, "millis": millis},
        )
        if data is None:
            raise NotFound(number)
        return parse_gls(data, now)

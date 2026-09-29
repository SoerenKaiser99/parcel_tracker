"""DPD via the public my.dpd.de tracking page (tracking number only, no postcode).

The page renders the current status and five milestone dates server-side. Location,
delivery window and time are only shown after a postcode check that is protected by a
captcha, so they are intentionally not used.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime, time, timedelta

import aiohttp

from ..const import MAX_EVENTS
from ..models import ParcelStatus, TrackingEvent, TrackingResult
from .base import BERLIN, Carrier, CarrierUnavailable, Match, NotFound, ParseError

DPD_ENTRY_URL = "https://my.dpd.de/redirect.aspx"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
_TIMEOUT = aiohttp.ClientTimeout(total=25)
_PARCEL_NO_ID = "ContentPlaceHolder1_repParcelList_labParcelNo_0"
_STATUS_ID = "ContentPlaceHolder1_repParcelList_labDeliveryStatus_0"

# Milestones oldest -> newest: (element id part, status, label)
_STAGES = (
    ("Start", ParcelStatus.PRE_TRANSIT, "Paketinfo an DPD übergeben"),
    ("OnTheRoad", ParcelStatus.IN_TRANSIT, "Paket unterwegs"),
    ("DeliveryDepot", ParcelStatus.AT_DELIVERY_DEPOT, "Paket im Paketzustellzentrum"),
    ("CarLoad", ParcelStatus.OUT_FOR_DELIVERY, "Paket in Zustellung"),
    ("Delivered", ParcelStatus.DELIVERED, "Paket zugestellt"),
)
_PICKUP_WORDS = ("paketshop", "abhol")
_DAY_MONTH = re.compile(r"(\d{1,2})\.(\d{1,2})\.")


def _span(page: str, element_id: str) -> str | None:
    match = re.search(rf'id="{re.escape(element_id)}"[^>]*>([^<]*)<', page)
    return html_lib.unescape(match.group(1)).strip() if match else None


def _stage_date(text: str | None, today: date) -> date | None:
    """'29.09.' -> date; the year is inferred (a date >7 days in the future is last year)."""
    match = _DAY_MONTH.fullmatch(text or "")
    if not match:
        return None
    day, month = int(match.group(1)), int(match.group(2))
    try:
        candidate = date(today.year, month, day)
        if candidate > today + timedelta(days=7):
            candidate = date(today.year - 1, month, day)
    except ValueError:
        return None
    return candidate


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), BERLIN)


def parse_dpd(page: str, today: date) -> TrackingResult:
    """Normalise the my.dpd.de tracking page."""
    if _span(page, _PARCEL_NO_ID) is None:
        raise NotFound("DPD page shows no parcel")
    status_text = _span(page, _STATUS_ID) or None
    reached = [
        (status, label, day)
        for key, status, label in _STAGES
        if (day := _stage_date(_span(page, f"ContentPlaceHolder1_labStatus{key}Date"), today))
    ]
    if not reached and status_text is None:
        raise ParseError("DPD page has neither status text nor milestone dates")

    status = reached[-1][0] if reached else ParcelStatus.UNKNOWN
    if (
        status_text
        and status is not ParcelStatus.DELIVERED
        and any(word in status_text.lower() for word in _PICKUP_WORDS)
    ):
        status = ParcelStatus.AWAITING_PICKUP

    last_day = reached[-1][2] if reached else None
    events = [
        TrackingEvent(timestamp=_midnight(day), text=label, location=None)
        for _, label, day in reversed(reached)
    ][:MAX_EVENTS]

    return TrackingResult(
        status=status,
        status_text=status_text,
        eta_date=last_day if status is ParcelStatus.OUT_FOR_DELIVERY else None,
        eta_from=None,
        eta_to=None,
        location=None,
        pickup_point=None,
        pickup_until=None,
        delivered_at=_midnight(last_day) if status is ParcelStatus.DELIVERED and last_day else None,
        events=events,
    )


class DpdCarrier(Carrier):
    """DPD Germany (public web tracking)."""

    key = "dpd"
    name = "DPD"

    @staticmethod
    def matches(number: str) -> Match:
        return Match.POSSIBLE if len(number) == 14 and number.isdigit() else Match.NO

    async def fetch(self, number: str, postcode: str | None) -> TrackingResult:
        headers = {"User-Agent": _UA, "Accept-Language": "de-DE,de;q=0.9"}
        try:
            async with aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(), headers=headers, timeout=_TIMEOUT
            ) as session:
                async with session.get(
                    DPD_ENTRY_URL, params={"action": "12", "parcelno": number}
                ) as resp:
                    if resp.status != 200:
                        raise CarrierUnavailable(f"DPD HTTP {resp.status}")
                    if "showerror" in str(resp.url).lower():
                        raise CarrierUnavailable("DPD returned its error page")
                    try:
                        page = await resp.text()
                    except UnicodeDecodeError as err:
                        raise ParseError("DPD returned an undecodable page") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CarrierUnavailable(str(err)) from err
        return parse_dpd(page, datetime.now(BERLIN).date())

"""The carrier's public tracking page of a parcel (no Home Assistant imports)."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote

from .carriers.gls import gls_number
from .models import Parcel

# The German pages, also for Austria and Switzerland: they find a parcel by its number
# alone. ``{}`` takes the URL-encoded number.
_PAGES: dict[str, str] = {
    "dhl": "https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode={}",
    "dpd": "https://tracking.dpd.de/status/de_DE/parcel/{}",
    "gls": "https://www.gls-pakete.de/sendungsverfolgung?match={}",
    "hermes": "https://www.myhermes.de/empfangen/sendungsverfolgung/sendungsinformation#{}",
    "ups": "https://www.ups.com/track?loc=de_DE&tracknum={}",
}
# The form of a number a page knows the parcel by, where it differs from the stored one:
# GLS finds a parcel by its 11 digits, without the check digit.
_PAGE_NUMBER: dict[str, Callable[[str], str]] = {"gls": gls_number}


def tracking_url(parcel: Parcel) -> str | None:
    """The page of the carrier that shows this parcel, None if there is none.

    A shop order (Amazon, eBay, AliExpress) links with the carrier number it took over
    (``tracking_ref`` at ``tracking_carrier``); without one it has no page. Neither has a
    parcel that only 17track knows, one whose carrier "Automatisch" has not found yet,
    or one of a carrier without a page here.
    """
    if parcel.tracking_ref:
        carrier, number = parcel.tracking_carrier, parcel.tracking_ref
    else:
        carrier, number = parcel.carrier, parcel.number
    page = _PAGES.get(carrier) if carrier else None
    if page is None or not number:
        return None
    number = _PAGE_NUMBER.get(carrier, str)(number)
    # Nothing is safe: a number is never trusted to be only letters and digits.
    return page.format(quote(number, safe=""))

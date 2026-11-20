"""The carrier's public tracking page of a parcel (no Home Assistant imports)."""

from __future__ import annotations

import re
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
    "hes": "https://myhes.de/de/tracking/{}",
    "ups": "https://www.ups.com/track?loc=de_DE&tracknum={}",
}
# The form of a number a page knows the parcel by, where it differs from the stored one:
# GLS finds a parcel by its 11 digits, without the check digit.
_PAGE_NUMBER: dict[str, Callable[[str], str]] = {"gls": gls_number}
# Amazon's own tracking page of a shipment (only for the signed-in buyer): the order as
# Amazon writes it ("AMZ" + 17 digits, "P2" … for a further shipment) and the shipment's id.
_AMAZON_PAGE = (
    "https://www.amazon.de/progress-tracker/package?orderId={}&packageIndex=0&shipmentId={}"
)
_AMAZON_ORDER = re.compile(r"AMZ(\d{3})(\d{7})(\d{7})(?:P\d+)?")


def tracking_url(parcel: Parcel) -> str | None:
    """The page that shows this parcel, None if there is none.

    The carrier's page first. A shop order (Amazon, eBay, AliExpress, Eventim) links with the
    carrier number it took over (``tracking_ref`` at ``tracking_carrier``); without a page
    for it, an Amazon order links to Amazon's page of its newest shipment
    (``shipment_ids``). Otherwise there is no page: neither for a parcel that only 17track
    knows, one whose carrier "Automatisch" has not found yet, nor one of a carrier without a
    page here.
    """
    return _carrier_page(parcel) or _amazon_page(parcel)


def _amazon_page(parcel: Parcel) -> str | None:
    if parcel.carrier != "amazon" or not parcel.shipment_ids:
        return None
    order = _AMAZON_ORDER.fullmatch(parcel.number)
    if order is None:
        return None
    return _AMAZON_PAGE.format("-".join(order.groups()), quote(parcel.shipment_ids[-1], safe=""))


def _carrier_page(parcel: Parcel) -> str | None:
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

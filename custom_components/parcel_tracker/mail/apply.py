"""Apply parsed mail updates to the parcel list (no Home Assistant imports)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from ..carriers.gls import gls_number
from ..carriers.track17 import strip_enrichment, with_track17
from ..const import MAX_EVENTS, OPTIONAL_API_CARRIERS, SHOP_CARRIERS
from ..models import (
    NO_ETA_STATUSES,
    PROGRESS_STEP,
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)
from .base import (
    MailUpdate,
    brand_of,
    carrier_key,
    is_carrier_display,
    is_carrier_title,
    title_key,
)

_DROP_ETA = NO_ETA_STATUSES - {ParcelStatus.DELIVERED}

SHOP_TEXT = {
    ParcelStatus.PRE_TRANSIT: "Bestellt",
    ParcelStatus.IN_TRANSIT: "Versendet",
    ParcelStatus.OUT_FOR_DELIVERY: "In Zustellung",
    ParcelStatus.AWAITING_PICKUP: "Abholbereit",
    ParcelStatus.DELIVERED: "Zugestellt",
}
CARRIER_TEXT = {
    ParcelStatus.PRE_TRANSIT: "Angekündigt",
    ParcelStatus.IN_TRANSIT: "Unterwegs",
    ParcelStatus.OUT_FOR_DELIVERY: "In Zustellung",
    ParcelStatus.AWAITING_PICKUP: "Abholbereit",
    ParcelStatus.DELIVERED: "Zugestellt",
}


@dataclass
class Change:
    """A parcel that a mail created or changed."""

    parcel: Parcel
    old_status: ParcelStatus | None
    created: bool


def _step(status: ParcelStatus | None) -> int:
    return PROGRESS_STEP.get(status, 0) if status else 0


def _forward(parcel: Parcel, update: MailUpdate, now: datetime) -> bool:
    """Take status/ETA/code from the mail unless it would move the parcel backwards."""
    changed = False
    shown = parcel.result
    # Build on what the carrier and earlier mails said; what 17track filled in is put
    # back afterwards, so it stays 17track's (and a newer 17track answer can replace it).
    old = strip_enrichment(shown)
    # "Backwards" is measured against what is shown, also if that is 17track's status.
    if update.status is not None and _step(update.status) >= _step(parcel.status):
        texts = SHOP_TEXT if parcel.carrier in SHOP_CARRIERS else CARRIER_TEXT
        text = texts.get(update.status, update.status.value)
        events = list(old.events) if old else []
        if old is None or old.status is not update.status:
            events.insert(0, TrackingEvent(update.sent_at, text, None))
        if update.eta_date:
            eta = (update.eta_date, update.eta_from, update.eta_to, update.eta_latest)
        elif old and update.status not in _DROP_ETA:
            # (a delivered parcel keeps its day: it is the day shown as delivered)
            eta = (old.eta_date, old.eta_from, old.eta_to, old.eta_latest)
        else:
            eta = (None, None, None, None)
        delivered = update.status is ParcelStatus.DELIVERED
        result = TrackingResult(
            status=update.status,
            status_text=text,
            eta_date=eta[0],
            eta_from=eta[1],
            eta_to=eta[2],
            eta_latest=eta[3],
            location=old.location if old else None,
            pickup_point=None,
            pickup_until=None,
            delivered_at=(update.delivered_at or update.sent_at) if delivered else None,
            events=events[:MAX_EVENTS],
        )
        result = with_track17(result, parcel.track17_result)
        if shown is None or shown.to_dict() != result.to_dict():
            parcel.result = result
            parcel.last_change_at = now
            changed = True
    if parcel.status is ParcelStatus.DELIVERED:
        if parcel.delivery_code:
            parcel.delivery_code = parcel.delivery_code_day = None
            changed = True
    elif update.delivery_code and update.delivery_code != parcel.delivery_code:
        parcel.delivery_code = update.delivery_code
        parcel.delivery_code_day = update.eta_date or update.sent_at.date()
        changed = True
    return changed


def _order_parcels(parcels: dict[str, Parcel], carrier: str, number: str) -> list[Parcel]:
    siblings = [
        p
        for p in parcels.values()
        if p.carrier == carrier and (p.number == number or p.number.startswith(f"{number}P"))
    ]
    return sorted(siblings, key=lambda p: (len(p.number), p.number))


def _take_shop_facts(parcel: Parcel, update: MailUpdate) -> bool:
    """Carrier hint and carrier number a shop mail names; True if something changed."""
    changed = False
    hint = update.shipping_carrier_hint
    if hint and parcel.shipping_carrier_hint != hint:
        parcel.shipping_carrier_hint = hint
        changed = True
    if update.tracking_ref and parcel.tracking_ref is None:
        parcel.tracking_ref = update.tracking_ref
        parcel.tracking_carrier = update.tracking_carrier
        parcel.next_poll_at = None
        changed = True
    return changed


def _apply_order(parcels: dict[str, Parcel], update: MailUpdate, now: datetime) -> Change | None:
    """A shop order ("AMZ…"/"EBAY…"): one parcel per order, suffix for further shipments."""
    siblings = _order_parcels(parcels, update.carrier, update.number)
    key = title_key(update.title) if update.title else None
    target = next(
        (p for p in siblings if key and p.mail_title and title_key(p.mail_title) == key), None
    )
    if target is None and siblings:
        further_shipment = (
            key is not None
            and update.status is ParcelStatus.IN_TRANSIT
            and all(_step(p.status) >= _step(ParcelStatus.IN_TRANSIT) for p in siblings)
        )
        if not further_shipment:
            open_ = [p for p in siblings if p.status is not ParcelStatus.DELIVERED]
            target = (open_ or siblings)[0]
    if target is None:
        count = len(siblings) + 1
        number = update.number if count == 1 else f"{update.number}P{count}"
        name = update.title if count == 1 or not update.title else f"{update.title} ({count})"
        target = Parcel(number, update.carrier, "mail", name, now, now, mail_title=update.title)
        parcels[number] = target
        _take_shop_facts(target, update)
        _forward(target, update, now)
        return Change(target, None, True)
    if target.mail_title is None and update.title:
        target.mail_title = update.title
        target.name = target.name or update.title
    old = target.status
    facts = _take_shop_facts(target, update)
    forwarded = _forward(target, update, now)
    if facts and not forwarded:
        target.last_change_at = now
    return Change(target, old, False) if facts or forwarded else None


def _in_window(parcel: Parcel, day) -> bool:
    result = parcel.result
    if result is None or result.eta_date is None:
        return False
    return result.eta_date <= day <= (result.eta_latest or result.eta_date)


def _hint_key(parcel: Parcel) -> str | None:
    """The carrier a shop mail named, as our key.

    Parcels stored by an older version hold the mail's raw text (e.g. "GLS Paket").
    """
    hint = parcel.shipping_carrier_hint
    return (carrier_key(hint) or hint) if hint else None


_SENT_DAY_STATUSES = (ParcelStatus.OUT_FOR_DELIVERY, ParcelStatus.DELIVERED)


def _mail_day(update: MailUpdate):
    """The day a carrier mail is about: the day it names, else for "in Zustellung" and
    "zugestellt" the day it was sent."""
    if update.eta_date:
        return update.eta_date
    return update.sent_at.date() if update.status in _SENT_DAY_STATUSES else None


def _brand_candidate(orders: list[Parcel], update: MailUpdate) -> Parcel | None:
    """The one open Amazon order whose title begins with the brand the carrier mail names.

    Deliberately narrow: only Amazon orders (never eBay), none that names another carrier
    than the mail's; all words of the brand must begin the title (whole words, any case) of
    exactly one of them. The mail's day must lie in the order's day or window; if one of the
    two has no day, the order must be shipped ("Versendet"). A mail about a delivery never
    takes an order that is only "Bestellt".
    """
    brand = brand_of(update.title)
    if brand is None:
        return None
    words = r"\s+".join(re.escape(word) for word in brand.split())
    begins = re.compile(rf"{words}(?![^\W_])", re.IGNORECASE)
    matches = [
        p
        for p in orders
        if p.carrier == "amazon"
        and _hint_key(p) in (None, update.carrier)
        and begins.match((p.mail_title or p.name or "").strip())
    ]
    if len(matches) != 1:
        return None
    order = matches[0]
    shipped = _step(order.status) >= _step(ParcelStatus.IN_TRANSIT)
    if update.status is ParcelStatus.DELIVERED and not shipped:
        return None
    day = _mail_day(update)
    dated = order.result is not None and order.result.eta_date is not None
    if day and dated:
        return order if _in_window(order, day) else None
    return order if order.status is ParcelStatus.IN_TRANSIT else None


def _merge_candidate(parcels: dict[str, Parcel], update: MailUpdate) -> Parcel | None:
    """The one open shop order a carrier mail belongs to, if unambiguous.

    The order qualifies when the carrier mail names its shop or the shop mail named
    this carrier; the day must match the order's day or window (without a day: the
    order must be in transit). A mail that names another company than the shop (the
    brand that sells at Amazon) may still belong to an order: see ``_brand_candidate``.
    """
    orders = [
        p
        for p in parcels.values()
        if p.carrier in SHOP_CARRIERS
        and p.tracking_ref is None
        and p.status is not ParcelStatus.DELIVERED
    ]
    open_orders = [
        p for p in orders if p.carrier == update.shop or _hint_key(p) == update.carrier
    ]
    if update.eta_date:
        matches = [p for p in open_orders if _in_window(p, update.eta_date)]
    else:
        matches = [p for p in open_orders if p.status is ParcelStatus.IN_TRANSIT]
    if len(matches) == 1:
        return matches[0]
    if not matches and update.shop is None:
        return _brand_candidate(orders, update)
    return None


def _mail_name(update: MailUpdate) -> str | None:
    """The name a carrier mail gives; a carrier's own display name is none."""
    title = update.title
    return title if title and not is_carrier_title(title) else None


def _apply_tracking(parcels: dict[str, Parcel], update: MailUpdate, now: datetime) -> Change | None:
    number = update.number.upper()
    name = _mail_name(update)
    target = parcels.get(number) or next(
        (p for p in parcels.values() if p.tracking_ref == number), None
    )
    if target is None and update.carrier == "gls":
        # Typed in with the check digit GLS shows in mails and links: the same parcel.
        target = next(
            (
                p
                for p in parcels.values()
                if p.carrier == "gls"
                and p.number != number
                and gls_number(p.number) == number
            ),
            None,
        )
    if target is None and update.status is not None:
        target = _merge_candidate(parcels, update)
        if target is not None:
            old = target.status
            target.tracking_ref = number
            target.tracking_carrier = update.carrier
            target.next_poll_at = None
            target.last_change_at = now
            _forward(target, update, now)
            return Change(target, old, False)
    if target is None:
        target = Parcel(number, update.carrier, "mail", name, now, now)
        parcels[number] = target
        _forward(target, update, now)
        return Change(target, None, True)
    old = target.status
    named = False
    # Older versions stored a carrier's display name ("DHL Zustell-Update") as the name: it
    # counts as no name. Any other name stays, also "Hermes" or "DHL Express" (the model
    # cannot tell who set it).
    unnamed = target.name is None or is_carrier_display(target.name)
    if unnamed and name and target.carrier not in SHOP_CARRIERS:
        target.name = name  # e.g. the shop a Hermes mail names
        named = True
    target_carrier = target.poll_target[0] if target.poll_target else None
    if target.poll_target is not None and target_carrier not in OPTIONAL_API_CARRIERS:
        # A mail is a good moment to ask the carrier again (not UPS: calls cost budget).
        target.next_poll_at = None
    forwarded = _forward(target, update, now)
    return Change(target, old, False) if forwarded or named else None


def apply_update(parcels: dict[str, Parcel], update: MailUpdate, now: datetime) -> Change | None:
    """Create or advance the matching parcel in ``parcels`` (mutated in place)."""
    if update.carrier in SHOP_CARRIERS:
        return _apply_order(parcels, update, now)
    return _apply_tracking(parcels, update, now)

"""Apply parsed mail updates to the parcel list (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..const import MAX_EVENTS, OPTIONAL_API_CARRIERS, SHOP_CARRIERS
from ..models import PROGRESS_STEP, Parcel, ParcelStatus, TrackingEvent, TrackingResult
from .base import MailUpdate, title_key

SHOP_TEXT = {
    ParcelStatus.PRE_TRANSIT: "Bestellt",
    ParcelStatus.IN_TRANSIT: "Versendet",
    ParcelStatus.OUT_FOR_DELIVERY: "In Zustellung",
    ParcelStatus.DELIVERED: "Zugestellt",
}
CARRIER_TEXT = {
    ParcelStatus.PRE_TRANSIT: "Angekündigt",
    ParcelStatus.IN_TRANSIT: "Unterwegs",
    ParcelStatus.OUT_FOR_DELIVERY: "In Zustellung",
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
    old = parcel.result
    if update.status is not None and _step(update.status) >= _step(parcel.status):
        texts = SHOP_TEXT if parcel.carrier in SHOP_CARRIERS else CARRIER_TEXT
        text = texts.get(update.status, update.status.value)
        events = list(old.events) if old else []
        if old is None or old.status is not update.status:
            events.insert(0, TrackingEvent(update.sent_at, text, None))
        if update.eta_date:
            eta = (update.eta_date, update.eta_from, update.eta_to, update.eta_latest)
        elif old:
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
        if old is None or old.to_dict() != result.to_dict():
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


def _merge_candidate(parcels: dict[str, Parcel], update: MailUpdate) -> Parcel | None:
    """The one open shop order a carrier mail belongs to, if unambiguous.

    The order qualifies when the carrier mail names its shop or the shop mail named
    this carrier; the day must match the order's day or window (without a day: the
    order must be in transit).
    """
    open_orders = [
        p
        for p in parcels.values()
        if p.carrier in SHOP_CARRIERS
        and p.tracking_ref is None
        and p.status is not ParcelStatus.DELIVERED
        and (p.carrier == update.shop or p.shipping_carrier_hint == update.carrier)
    ]
    if update.eta_date:
        matches = [p for p in open_orders if _in_window(p, update.eta_date)]
    else:
        matches = [p for p in open_orders if p.status is ParcelStatus.IN_TRANSIT]
    return matches[0] if len(matches) == 1 else None


def _apply_tracking(parcels: dict[str, Parcel], update: MailUpdate, now: datetime) -> Change | None:
    number = update.number.upper()
    target = parcels.get(number) or next(
        (p for p in parcels.values() if p.tracking_ref == number), None
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
        target = Parcel(number, update.carrier, "mail", update.title, now, now)
        parcels[number] = target
        _forward(target, update, now)
        return Change(target, None, True)
    old = target.status
    named = False
    if target.name is None and update.title and target.carrier not in SHOP_CARRIERS:
        target.name = update.title  # e.g. the shop a Hermes mail names
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

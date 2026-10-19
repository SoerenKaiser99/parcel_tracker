"""Apply parsed mail updates to the parcel list (no Home Assistant imports)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from ..carriers.gls import gls_number
from ..carriers.track17 import strip_enrichment, with_track17
from ..const import (
    CARRIER_NAMES,
    FOLD_DAYS_AFTER,
    FOLD_DAYS_BEFORE,
    MAX_EVENTS,
    NEW_DELIVERY_MAX_AGE,
    OPTIONAL_API_CARRIERS,
    ORDER_OVERDUE_DAYS,
    SHOP_CARRIERS,
    SINGLE_PARCEL_SHOPS,
)
from ..models import (
    NO_ETA_STATUSES,
    PROGRESS_STEP,
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)
from .base import (
    ATTEMPT_TEXT,
    DELAY_TEXT,
    PROBLEM_TEXT,
    MailUpdate,
    brand_of,
    carrier_key,
    is_carrier_display,
    is_carrier_title,
    shop_of,
    title_key,
)

_DROP_ETA = NO_ETA_STATUSES - {ParcelStatus.DELIVERED}
# A postponed delivery (MailUpdate.postponed) never takes these back.
_ARRIVED = frozenset({ParcelStatus.DELIVERED, ParcelStatus.AWAITING_PICKUP})
# Words a shop's mail about a postponed delivery brings. They tell one moment: a later
# mail that only repeats the status does not keep them (see ``_forward``).
_POSTPONED_TEXTS = frozenset({ATTEMPT_TEXT, DELAY_TEXT, PROBLEM_TEXT})

SHOP_TEXT = {
    ParcelStatus.PRE_TRANSIT: "Bestellt",
    ParcelStatus.IN_TRANSIT: "Versendet",
    ParcelStatus.OUT_FOR_DELIVERY: "In Zustellung",
    ParcelStatus.AWAITING_PICKUP: "Abholbereit",
    ParcelStatus.DELIVERED: "Zugestellt",
}
# Status text of a shop order closed because no delivery mail came (see order_overdue).
ASSUMED_TEXT = "Abgeschlossen ohne Zustellbestätigung"
# Status text of a parcel the user marked as received (see mark_received).
MANUAL_TEXT = "Erhalten (von Hand markiert)"
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
    # The order took in a carrier's parcel that was delivered already and whose delivery
    # waits for no announcement: the box's delivery is told. The order's change is its
    # own event, but no notification (see the coordinator's ``_mail_changed``).
    told: bool = False
    # A mail made this parcel, delivered right away, and it is news all the same: a
    # carrier's parcel (see ``_apply_tracking``) or a further box of a known order (see
    # ``_apply_order``). The coordinator announces it once as delivered.
    announce: bool = False


def _step(status: ParcelStatus | None) -> int:
    return PROGRESS_STEP.get(status, 0) if status else 0


def _newest(events: list[TrackingEvent]) -> datetime | None:
    """The time of the newest line of a history (lines without a time zone do not count:
    they cannot be compared with a mail's time)."""
    times = [e.timestamp for e in events if e.timestamp and e.timestamp.tzinfo is not None]
    return max(times, default=None)


def _known_before(parcel: Parcel) -> datetime:
    """The time of the newest thing known about an order when it was closed on its own:
    its newest history line that is not the closing itself, or the newest mail that told
    its status (``Parcel.last_mail_at``: a mail that only repeats a status leaves no
    line), whichever is later. Without either: the time the order was made.

    A mail tells news about a closed order if it was sent after that, whenever it is
    read. Not the time of the closing: after a pause the closing comes first and the
    mails that waited are read afterwards, and they are news all the same.
    """
    result = parcel.result
    closing = (ASSUMED_TEXT, result.status_text)
    line = _newest([e for e in result.events if e.text not in closing])
    mail = parcel.last_mail_at
    if mail is not None and mail.tzinfo is None:
        mail = None  # (cannot be compared with a mail's time)
    if line is not None and mail is not None:
        return max(line, mail)
    return line or mail or parcel.added_at


def closed_at(parcel: Parcel) -> datetime:
    """When an order was closed on its own: the time of its closing line in the history
    (for the shop's confirmation the time of that mail), else of its last change.

    What a carrier tells about a closed order is news if it is dated after that.
    """
    result = parcel.result
    closing = (ASSUMED_TEXT, result.status_text)
    return _newest([e for e in result.events if e.text in closing]) or parcel.last_change_at


def tells_newer(parcel: Parcel, events: list[TrackingEvent]) -> bool:
    """Does a carrier's history hold a line dated after an order was closed on its own?

    A line that names only a day (00:00, as DPD dates them) counts if it is of the day
    of the closing: it may well have been written after it. Lines without a time zone
    cannot be compared and do not count.
    """
    closed = closed_at(parcel)
    for event in events:
        at = event.timestamp
        if at is None or at.tzinfo is None:
            continue
        if at > closed:
            return True
        if at.timetz().replace(tzinfo=None) == time(0) and (
            at.date() == closed.astimezone(at.tzinfo).date()
        ):
            return True
    return False


def _delivery_told(parcel: Parcel) -> bool:
    """Was the delivery of a delivered carrier parcel announced (``delivery_announced``)?

    A parcel stored by an older version has no mark: it counts as announced if its
    history shows it had a status before (more than one line), since a change to
    "delivered" is always told. With a single line "delivered" was its first status,
    which nobody is told about.
    """
    if parcel.delivery_announced is not None:
        return parcel.delivery_announced
    return parcel.result is not None and len(parcel.result.events) > 1


def _remember_mail(parcel: Parcel, update: MailUpdate) -> None:
    """Keep the time of the newest mail that told a shop order's status."""
    if parcel.carrier not in SHOP_CARRIERS:
        return
    if parcel.last_mail_at is None or update.sent_at > parcel.last_mail_at:
        parcel.last_mail_at = update.sent_at


def _forward(parcel: Parcel, update: MailUpdate, now: datetime) -> bool:
    """Take status/ETA/code from the mail unless it would move the parcel backwards.

    Nothing at all for a parcel the user marked as received: the hand mark wins.
    """
    if parcel.manual_delivered:
        return False
    changed = False
    shown = parcel.result
    # Build on what the carrier and earlier mails said; what 17track filled in is put
    # back afterwards, so it stays 17track's (and a newer 17track answer can replace it).
    old = strip_enrichment(shown)
    # An order closed without a delivery mail is not delivered for sure: whatever a mail
    # tells afterwards holds, the real delivery as well as a new day or "in Zustellung".
    assumed = parcel.assumed_delivered
    if update.confirmation:
        return _confirm(parcel, update, now)
    # "Afterwards" is meant by the mail's own time: one that is older than what was
    # known when the order was closed (``_known_before``) and is read late tells nothing
    # new. Only the real delivery still counts then: it says for sure that, and when,
    # the order came.
    late = (
        assumed
        and update.status is not ParcelStatus.DELIVERED
        and update.sent_at <= _known_before(parcel)
    )
    # A postponed delivery is a step back the carrier itself tells; what has arrived stays.
    # Only from a mail that is not older than the newest line of the history: read late
    # (the announcement of the evening before after "HEUTE", a delivery problem after the
    # next "wird zugestellt") it takes back what came after it.
    last_line = _newest(old.events) if old else None
    postponed = (
        update.postponed
        and parcel.status not in _ARRIVED
        and (last_line is None or update.sent_at >= last_line)
    )
    # "Backwards" is measured against what is shown, also if that is 17track's status.
    if (
        update.status is not None
        and not late
        and (assumed or postponed or _step(update.status) >= _step(parcel.status))
    ):
        # (after ``late`` was told: this mail is not measured against itself)
        _remember_mail(parcel, update)
        parcel.assumed_delivered = False
        texts = SHOP_TEXT if parcel.carrier in SHOP_CARRIERS else CARRIER_TEXT
        text = update.status_text or texts.get(update.status, update.status.value)
        same = old is not None and old.status is update.status and not assumed
        newest = _newest(old.events) if same else None
        # A mail read late (it is older than the newest line of the history) that brings
        # no new status tells nothing the history does not know: words and history stay.
        stale = newest is not None and update.sent_at < newest
        own_words = False
        if stale:
            text = old.status_text
        elif update.status_text is not None:
            own_words = same and old.status_text != text
        elif (
            same
            and parcel.carrier in SHOP_CARRIERS
            and old.status_text
            and old.status_text in _POSTPONED_TEXTS
            and not update.postponed
        ):
            # "Zustellung versucht" told one moment: the next mail of the same status is
            # the plain status again, with a line of its own in the history.
            own_words = True
        elif same and parcel.carrier in SHOP_CARRIERS and old.status_text:
            # A shop mail that only repeats the status ("Neuer Lieferstatus") keeps the
            # words an earlier mail or the carrier gave it ("Im Zielland angekommen").
            text = old.status_text
        events = list(old.events) if old else []
        if old is None or old.status is not update.status or assumed or own_words:
            events.insert(0, TrackingEvent(update.sent_at, text, None))
        if update.eta_date:
            eta = (update.eta_date, update.eta_from, update.eta_to, update.eta_latest)
        elif (
            old
            and update.status not in _DROP_ETA
            and (
                not postponed
                or (
                    update.status_text != DELAY_TEXT
                    and old.eta_date
                    and old.eta_date > update.sent_at.date()
                )
            )
        ):
            # (a delivered parcel keeps its day: it is the day shown as delivered; a
            # postponed delivery that names no new day has none - but a day after the
            # mail's own is not the one an attempt takes back: the carrier named it
            # already. A delay says that every day known so far is too early.)
            eta = (old.eta_date, old.eta_from, old.eta_to, old.eta_latest)
        else:
            eta = (None, None, None, None)
        delivered = update.status is ParcelStatus.DELIVERED
        delivered_at = (update.delivered_at or update.sent_at) if delivered else None
        if delivered_at and same and old.delivered_at and old.delivered_at < delivered_at:
            # A delivery is never told before it happened: the earliest word of it is the
            # closest. A shop tells it hours after the carrier (AliExpress "Paket …
            # wurde zugestellt" two to three hours after DHL's "liegt im Briefkasten").
            delivered_at = old.delivered_at
        elif delivered_at and same and old.delivered_at and delivered_at < old.delivered_at:
            # (the line of the delivery in the history moves with it)
            events = [
                replace(e, timestamp=delivered_at) if e.timestamp == old.delivered_at else e
                for e in events
            ]
        # Where a parcel ready for pickup waits: what this mail names, else (it is still
        # there) what an earlier mail named. Any other status has no pickup point.
        pickup = update.status is ParcelStatus.AWAITING_PICKUP
        still = pickup and old is not None and old.status is ParcelStatus.AWAITING_PICKUP
        pickup_point = update.pickup_point or (old.pickup_point if still else None)
        pickup_until = update.pickup_until or (old.pickup_until if still else None)
        result = TrackingResult(
            status=update.status,
            status_text=text,
            eta_date=eta[0],
            eta_from=eta[1],
            eta_to=eta[2],
            eta_latest=eta[3],
            location=old.location if old else None,
            pickup_point=pickup_point if pickup else None,
            pickup_until=pickup_until if pickup else None,
            delivered_at=delivered_at,
            events=events[:MAX_EVENTS],
        )
        result = with_track17(result, parcel.track17_result)
        if shown is None or assumed or shown.to_dict() != result.to_dict():
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


def _confirm(parcel: Parcel, update: MailUpdate, now: datetime) -> bool:
    """The shop confirms the delivery days afterwards (``MailUpdate.confirmation``).

    That is the shop's word, not an arrival anybody saw, and it comes days late. So:

    - An order that is delivered for real keeps its time of delivery and its history.
    - An order with a carrier number whose result changed in the last ORDER_OVERDUE_DAYS
      days is left to the carrier: it tells the delivery itself, with its time. Once
      nothing new came for longer (the carrier never knew the number, or never says
      "delivered"), the shop's word is the best there is.
    - Any other open order is closed like one without a delivery mail: delivered, but
      only assumed (``close_unconfirmed``), with the shop's words. Nothing is pushed, and
      it never counts as delivered today.
    - An order that was closed on its own already stays what it is: without a time of
      delivery, and the days it is kept go on counting from the closing. Only the words
      change. Nothing for a confirmation older than what was known at the closing
      (``_known_before``), or one whose words the order shows already.
    """
    result = parcel.result
    text = update.status_text or SHOP_TEXT[ParcelStatus.DELIVERED]
    if parcel.assumed_delivered:
        if result.status_text == text or update.sent_at <= _known_before(parcel):
            return False
        events = [TrackingEvent(update.sent_at, text, None), *result.events]
        parcel.result = replace(result, status_text=text, events=events[:MAX_EVENTS])
        return True
    if parcel.status is ParcelStatus.DELIVERED:
        return False
    fresh = now - parcel.last_change_at <= timedelta(days=ORDER_OVERDUE_DAYS)
    if parcel.tracking_ref is not None and fresh:
        return False
    close_unconfirmed(parcel, now, text, update.sent_at)
    return True


def _order_parcels(parcels: dict[str, Parcel], carrier: str, number: str) -> list[Parcel]:
    siblings = [
        p
        for p in parcels.values()
        if p.carrier == carrier and (p.number == number or p.number.startswith(f"{number}P"))
    ]
    return sorted(siblings, key=lambda p: (len(p.number), p.number))


def _order_index(order: str, number: str) -> int:
    """Which entry of an order a number is: 1 for the order's own, n for "…P<n>"."""
    suffix = number[len(order) + 1 :] if number != order else ""
    return int(suffix) if suffix.isdigit() else 1


def _numbered(title: str, index: int) -> str:
    """An entry's name: its item, with the number of the entry from the second one on."""
    return title if index == 1 else f"{title} ({index})"


def _shop_box(carrier: str, index: int) -> str:
    """The name of a further entry whose mails named no item yet ("Amazon-Sendung (2)")."""
    return f"{CARRIER_NAMES[carrier]}-Sendung ({index})"


def _new_number(parcels: dict[str, Parcel], siblings: list[Parcel], order: str) -> str:
    """The number of a new entry of an order: the order's own while it has none, else the
    one after the highest it has ("…P3" after "…P2").

    Never the number of an entry that is there: one the user removed leaves a gap, and
    counting the entries would hand out a number that is taken.
    """
    if not siblings and order not in parcels:
        return order
    index = max((_order_index(order, p.number) for p in siblings), default=1) + 1
    while f"{order}P{index}" in parcels:
        index += 1
    return f"{order}P{index}"


def _take_shop_facts(
    parcels: dict[str, Parcel], parcel: Parcel, update: MailUpdate, now: datetime
) -> bool:
    """Carrier hint and carrier number a shop mail names; True if the order changed.

    Nothing for an order the user marked as received: nobody is asked about it any more.

    The number is the order's from now on, unless it is tracked on its own already:

    - as a parcel a carrier's mail made: that parcel is folded into the order right here
      (``_fold``), so one entry is left and the carrier is asked once. The order keeps
      what only it knew (``_joined``), and its status change, if this is one, is the
      order's own news: the caller tells it;
    - as a parcel the user added by hand, or marked as received: the user's own entry
      wins. It stays as it is and the order does NOT take the number, so the carrier is
      not asked a second time about the same box.

    An order that has a number already keeps it. A second, different number of an order
    that is always one entry (SINGLE_PARCEL_SHOPS: AliExpress sends an order in several
    boxes) becomes a carrier's parcel of its own, see ``_further_parcel``.
    """
    if parcel.manual_delivered:
        return False
    changed = False
    hint = update.shipping_carrier_hint
    if hint and parcel.shipping_carrier_hint != hint:
        parcel.shipping_carrier_hint = hint
        changed = True
    number = update.tracking_ref
    if not number:
        return changed
    if parcel.tracking_ref is None:
        own = parcels.get(number)
        if own is None or own is parcel:
            parcel.tracking_ref = number
            parcel.tracking_carrier = update.tracking_carrier
            parcel.next_poll_at = None
            changed = True
        elif (
            own.carrier not in SHOP_CARRIERS
            and own.carrier_mode == "mail"
            and own.tracking_ref is None
            and not own.manual_delivered
        ):
            _fold(parcels, own, parcel, keep=True)
            changed = True
    elif parcel.tracking_ref != number and parcel.carrier in SINGLE_PARCEL_SHOPS:
        _further_parcel(parcels, parcel, update, now)
    return changed


def _remember_shipment(parcel: Parcel, update: MailUpdate) -> None:
    """Keep Amazon's id of the shipment a mail names with the entry it went to.

    It tells which entry of an order the later mails of that box go to (``_by_shipment``)
    and gives the link to Amazon's tracking page (``links.tracking_url``). Keeping it is
    never told: no change of the order, no news. Kept for an entry the user marked as
    received as well: the hand mark stays as it is (``_forward``), and without the id
    every later mail of that box would make an entry of its own.
    """
    if update.shipment_id and update.shipment_id not in parcel.shipment_ids:
        parcel.shipment_ids.append(update.shipment_id)


def _further_parcel(
    parcels: dict[str, Parcel], order: Parcel, update: MailUpdate, now: datetime
) -> None:
    """The second box of an order that has a carrier number already: a parcel of its own.

    Named after the shop only ("AliExpress-Sendung": which items are in it is not told),
    with the status of the mail. It belongs to this order, so it is never folded into
    another one (``Parcel.order_checked``). Nothing if the number is tracked already,
    on its own or by another order, or if no carrier of ours has such a number.
    """
    number, carrier = update.tracking_ref, update.tracking_carrier
    if (
        not carrier
        or carrier in SHOP_CARRIERS
        or number in parcels
        or any(p.tracking_ref == number for p in parcels.values())
    ):
        return
    name = f"{CARRIER_NAMES[order.carrier]}-Sendung"
    extra = Parcel(number, carrier, "mail", name, now, now, order_checked=True)
    parcels[number] = extra
    status = update.status if _step(update.status) < _step(ParcelStatus.DELIVERED) else None
    words = MailUpdate(number, carrier, status, update.sent_at, status_text=update.status_text)
    _forward(extra, words, now)


def _same_item(parcel: Parcel, key: str | None) -> bool:
    return bool(key and parcel.mail_title and title_key(parcel.mail_title) == key)


def _names_item(parcel: Parcel, key: str | None) -> bool:
    """Like ``_same_item``, but a title cut short counts as well: the subject of a shipping
    mail may name only the first word ("Lsa…"), the order's mail names it in full."""
    theirs = title_key(parcel.mail_title) if parcel.mail_title else ""
    return bool(key and theirs) and (theirs.startswith(key) or key.startswith(theirs))


def _only_ordered(parcel: Parcel) -> bool:
    """No box was told for this entry yet: it is only ordered ("Bestellt"), or it was
    closed while it was, without a delivery mail (``close_unconfirmed``).

    The first box of an order takes such an entry over (``_by_shipment``, ``_take_over``);
    a closed one comes back to life with it, as with any later mail of the shop.
    """
    if parcel.shipment_ids:
        return False
    if parcel.status is ParcelStatus.PRE_TRANSIT:
        return True
    if not parcel.assumed_delivered or parcel.tracking_ref is not None:
        return False
    result = parcel.result
    closing = (ASSUMED_TEXT, result.status_text)
    ordered = SHOP_TEXT[ParcelStatus.PRE_TRANSIT]
    return all(e.text == ordered for e in result.events if e.text not in closing)


def _by_shipment(siblings: list[Parcel], update: MailUpdate) -> Parcel | None:
    """The entry of an order a mail that names its shipment (Amazon's id) goes to.

    The id is the box's own, the same in every mail about it, so it wins over the title:
    two boxes of one item ("2 x …" sent on two days) are two entries, and a box whose
    title grows ("… und 2 weitere Artikel") stays one. Older versions kept every id with
    the entry its mail went to, so two entries may hold the same one: then the one that
    names the mail's item, else the first. An id no entry has yet is a box that is new
    here. It takes an entry no box was told for yet:

    - the one that names its item, or else the order itself while no box was told for it
      (``_only_ordered``: the first box takes it over);
    - for a mail that names no item (an old "Zugestellt" mail), the first open one, or
      else the order itself as above.

    None if there is none: the box is a further shipment, an entry of its own (the caller
    makes it), whatever its status and title.
    """
    shipment = update.shipment_id
    key = title_key(update.title) if update.title else None
    if held := [p for p in siblings if shipment in p.shipment_ids]:
        return next((p for p in held if _names_item(p, key)), held[0])
    free = [p for p in siblings if not p.shipment_ids]
    open_ = (p for p in free if p.status is not ParcelStatus.DELIVERED)
    named = (p for p in free if _names_item(p, key)) if key is not None else open_
    return next(named, None) or next((p for p in free if _only_ordered(p)), None)


def _take_over(target: Parcel, update: MailUpdate) -> None:
    """The first box of an order takes over the entry made when it was ordered.

    The order's mail named its first item; from now on the entry is this box, so it is
    named after the item the box holds. Later mails find it by that name (and a box with
    the first item finds its own entry, not this one). Not for a name the user typed in,
    and not for a shop whose mails name an order's items in turn.
    """
    if (
        update.carrier in SINGLE_PARCEL_SHOPS
        or not update.title
        or not _only_ordered(target)
        or _step(update.status) <= _step(ParcelStatus.PRE_TRANSIT)
        or _names_item(target, title_key(update.title))
    ):
        return
    target.mail_title = update.title
    if not target.name_manual and target.number == update.number:
        target.name = update.title


def _apply_order(parcels: dict[str, Parcel], update: MailUpdate, now: datetime) -> Change | None:
    """A shop order ("AMZ…"/"EBAY…"/"ALI…"/"EVT…"): one parcel per order, suffix for further
    shipments (never for AliExpress and Eventim: their mails name an order's items in turn).

    A mail that names its shipment (Amazon's id) goes by it (``_by_shipment``). Any other
    goes by the item it names, else to the order's first open entry; it is a further
    shipment only as "Versendet" with an item no entry names, once every entry of the
    order is shipped. A further entry takes the number after the highest one the order
    has (``_new_number``) and is named after its item with that number: "… (3)".
    """
    siblings = _order_parcels(parcels, update.carrier, update.number)
    key = title_key(update.title) if update.title else None
    if update.shipment_id and siblings:
        target = _by_shipment(siblings, update)
        further_shipment = target is None
    else:
        target = next((p for p in siblings if _same_item(p, key)), None)
        further_shipment = False
    if target is None and siblings and not further_shipment:
        # (a postponed delivery is news about a shipment there is, never a further one)
        further_shipment = (
            key is not None
            and update.carrier not in SINGLE_PARCEL_SHOPS
            and not update.postponed
            and update.status is ParcelStatus.IN_TRANSIT
            and all(_step(p.status) >= _step(ParcelStatus.IN_TRANSIT) for p in siblings)
        )
        if not further_shipment:
            open_ = [p for p in siblings if p.status is not ParcelStatus.DELIVERED]
            target = (open_ or siblings)[0]
    if target is None:
        number = _new_number(parcels, siblings, update.number)
        index = _order_index(update.number, number)
        if update.title:
            name = _numbered(update.title, index)
        else:
            # (a further box whose mail names no item, see ``_by_shipment``)
            name = _shop_box(update.carrier, index) if index > 1 else None
        target = Parcel(number, update.carrier, "mail", name, now, now, mail_title=update.title)
        parcels[number] = target
        _take_shop_facts(parcels, target, update, now)
        _remember_shipment(target, update)
        _forward(target, update, now)
        # A first status is no news - but a further box of an order that is delivered as
        # soon as it is known (the mails before were never read, or named no box of
        # their own) is: it is the order's box that just came, like a carrier's parcel
        # delivered right away (``_apply_tracking``). Never the order's first entry, and
        # not for a mail read late: nothing came just now.
        news = (
            bool(siblings)
            and target.status is ParcelStatus.DELIVERED
            and not target.assumed_delivered
            and now - update.sent_at <= NEW_DELIVERY_MAX_AGE
        )
        return Change(target, None, True, announce=news)
    _take_over(target, update)
    if target.mail_title is None and update.title:
        target.mail_title = update.title
        index = _order_index(update.number, target.number)
        if not target.name_manual and target.name in (None, _shop_box(update.carrier, index)):
            # (a box whose mails named no item so far: now one does)
            target.name = _numbered(update.title, index)
    old = target.status
    own = parcels.get(update.tracking_ref) if update.tracking_ref else None
    facts = _take_shop_facts(parcels, target, update, now)
    _remember_shipment(target, update)
    # A carrier's parcel of that number was folded into the order just now. If it was
    # delivered, its delivery was announced (``_delivery_told``) and nothing about it
    # waits to be announced, the box's delivery is told: known from what is stored, so
    # it holds after a restart as well. A delivery nobody heard of is the order's news.
    told = (
        own is not None
        and own is not target
        and update.tracking_ref not in parcels
        and own.status is ParcelStatus.DELIVERED
        and own.unannounced_from is None
        and _delivery_told(own)
    )
    forwarded = _forward(target, update, now)
    if facts and not forwarded:
        target.last_change_at = now
    return Change(target, old, False, told) if facts or forwarded else None


def _in_window(parcel: Parcel, day) -> bool:
    result = parcel.result
    if result is None or result.eta_date is None:
        return False
    return result.eta_date <= day <= (result.eta_latest or result.eta_date)


def _near_window(parcel: Parcel, day: date) -> bool:
    """True if ``day`` lies in the order's day or window or a few days around it
    (FOLD_DAYS_BEFORE, FOLD_DAYS_AFTER)."""
    result = parcel.result
    if result is None or result.eta_date is None:
        return False
    first = result.eta_date - timedelta(days=FOLD_DAYS_BEFORE)
    last = (result.eta_latest or result.eta_date) + timedelta(days=FOLD_DAYS_AFTER)
    return first <= day <= last


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


def _seller_shipped(order: Parcel) -> bool:
    """True if every shipment Amazon named for the order is sent by the seller itself.

    Amazon's shipment ids (``Parcel.shipment_ids``, from the link to its tracking page)
    begin with "D" for "Versand durch Verkäufer": a marketplace seller sends the box with a
    carrier of its own, and that carrier's mail names the seller, never Amazon. Shipments
    Amazon sends itself began with "U" until February 2026 and with "T" since. The format
    is Amazon's own and nowhere documented, so only the "D" is checked: it held for every
    seller's shipment seen so far. Should Amazon ever give a "D" to boxes it sends itself,
    such orders would wrongly be ruled out for mails naming Amazon.
    An order without an id is none either: nothing is known about it.
    """
    ids = order.shipment_ids
    return order.carrier == "amazon" and bool(ids) and all(i.startswith("D") for i in ids)


def _merge_candidate(
    parcels: dict[str, Parcel], update: MailUpdate, delivered: date | None = None
) -> Parcel | None:
    """The one open shop order a carrier mail belongs to, if unambiguous.

    The order qualifies when the carrier mail names its shop or the shop mail named
    this carrier; the day must match the order's day or window (without a day: the
    order must be in transit). A mail that names another company than the shop (the
    brand that sells at Amazon) may still belong to an order: see ``_brand_candidate``.

    A mail that names Amazon never goes to an Amazon order whose shipments are all sent by
    the seller (``_seller_shipped``): the seller's carrier names the seller, so a mail
    naming Amazon is about a box Amazon sent, another one. This only rules an order out,
    it never picks one; the way by the brand stays open for such an order, as that is
    how the seller's mails find it.

    ``delivered`` is the day a parcel was delivered: one that is matched afterwards (see
    ``fold_delivered``), or the day of a "zugestellt" mail about a number nobody knows
    yet (see ``_apply_tracking``). The order must be in transit, and if it names a day or
    window, that day must lie in or close to it (``_near_window``: carriers are a day
    early or late). An order for quite other days waits for another box, whoever carries
    it.
    """
    orders = [
        p
        for p in parcels.values()
        if p.carrier in SHOP_CARRIERS
        and p.tracking_ref is None
        and p.status is not ParcelStatus.DELIVERED
    ]
    open_orders = [
        p
        for p in orders
        if (p.carrier == update.shop or _hint_key(p) == update.carrier)
        and not (update.shop == "amazon" and _seller_shipped(p))
    ]
    if delivered:
        matches = [
            p
            for p in open_orders
            if p.status is ParcelStatus.IN_TRANSIT
            and (p.result.eta_date is None or _near_window(p, delivered))
        ]
    elif update.eta_date:
        matches = [p for p in open_orders if _in_window(p, update.eta_date)]
    else:
        matches = [p for p in open_orders if p.status is ParcelStatus.IN_TRANSIT]
    if len(matches) == 1:
        return matches[0]
    if not matches and update.shop is None:
        return _brand_candidate(orders, update)
    return None


def _apply_orderless(
    parcels: dict[str, Parcel], update: MailUpdate, now: datetime
) -> Change | None:
    """A shop's status mail that names no order (AliExpress "Packstück" with a number no
    carrier of ours has): the status goes to the one open order that fits
    (``_merge_candidate``), else nowhere. Never creates a parcel."""
    target = _merge_candidate(parcels, update)
    if target is None:
        return None
    old = target.status
    return Change(target, old, False) if _forward(target, update, now) else None


def fold_delivered(
    parcels: dict[str, Parcel], parcel: Parcel, delivered: datetime, announced: bool = True
) -> Parcel | None:
    """Close the one open shop order a delivered carrier parcel belongs to; None if none.

    For a parcel a carrier mail created on its own because no order fitted then (the
    order mail came later, or the parcel had no status yet). It is matched like its
    "zugestellt" mail would be now, by the same rules (``_merge_candidate``): from what
    the mail left in the parcel, its carrier and the company name, and ``delivered``, the
    time of delivery in the local time zone. The order ends up as if the mail had been
    merged right away: it carries the carrier's number and result, and the parcel of its
    own is dropped from ``parcels``. Never for a parcel somebody added by hand, and never
    into an order a mail changed after the delivery (it was shipped or ordered later, so
    it is another box). The day of the delivery must lie in or close to the days the
    order names, if it names any (see ``_merge_candidate``).

    Never for a parcel marked as received by hand either: that is the user's word about
    this one entry at the moment of the tap, not a delivery anybody saw, so it closes
    no order.

    The delivery is announced once: if the parcel's own announcement is still waiting,
    or was never made (``announced`` False: the parcel had no status before it was
    delivered, and a first status is no news), the order takes it over; otherwise the
    order is closed without one. A name the user typed in on the parcel goes along.
    """
    if (
        parcel.carrier is None
        or parcel.carrier in SHOP_CARRIERS
        or parcel.carrier_mode != "mail"
        or parcel.tracking_ref is not None
        or parcel.status is not ParcelStatus.DELIVERED
        or parcel.manual_delivered
        or parcels.get(parcel.number) is not parcel
    ):
        return None
    name = parcel.name
    update = MailUpdate(
        number=parcel.number,
        carrier=parcel.carrier,
        status=ParcelStatus.DELIVERED,
        sent_at=delivered,
        title=name,
        shop=shop_of(name) if name else None,
    )
    order = _merge_candidate(parcels, update, delivered.date())
    if order is None or order.last_change_at > delivered:
        return None
    waiting = not announced or parcel.unannounced_from not in (None, ParcelStatus.DELIVERED)
    order.unannounced_from = (order.unannounced_from or order.status) if waiting else None
    _fold(parcels, parcel, order)
    return order


def _joined(ours: TrackingResult | None, theirs: TrackingResult | None) -> TrackingResult | None:
    """The carrier's result (``theirs``) for an order that had a result of its own.

    The carrier's values hold. The order keeps what only it knew: its day or window if
    the carrier names none (and the parcel is still on its way), and its history lines,
    put together with the carrier's, newest first. A parcel nobody told anything about
    yet takes nothing away from the order.
    """
    if theirs is None or ours is None:
        return theirs or ours
    changes: dict = {}
    if theirs.eta_date is None and theirs.status not in NO_ETA_STATUSES:
        changes.update(
            eta_date=ours.eta_date,
            eta_latest=ours.eta_latest,
            eta_from=ours.eta_from,
            eta_to=ours.eta_to,
        )
    events = [*theirs.events, *(e for e in ours.events if e not in theirs.events)]
    if all(e.timestamp and e.timestamp.tzinfo is not None for e in events):
        events.sort(key=lambda e: e.timestamp, reverse=True)
    # (a carrier's long history, GLS or 17track, is never cut by this)
    changes["events"] = events[: max(MAX_EVENTS, len(theirs.events))]
    return replace(theirs, **changes)


def _fold(parcels: dict[str, Parcel], parcel: Parcel, order: Parcel, keep: bool = False) -> None:
    """Make a carrier's parcel and the shop order it belongs to one entry: the order.

    The order ends up as if the carrier's number had been its own from the start: it
    carries the number and the carrier's result, and the parcel is dropped from
    ``parcels``. A name the user typed in on the parcel goes along. With ``keep`` (the
    order is still open and names the number itself) the order keeps what only it knew,
    see ``_joined``. Who tells what happened is up to the caller.
    """
    if parcel.name and parcel.name_manual:
        order.name, order.name_manual = parcel.name, True
    order.tracking_ref = parcel.number
    order.tracking_carrier = parcel.carrier
    if keep:
        order.result = _joined(order.result, parcel.result)
        order.last_change_at = max(order.last_change_at, parcel.last_change_at)
    else:
        order.result = parcel.result
        order.last_change_at = parcel.last_change_at
    if parcel.result is not None:
        # (an order closed on its own that takes a carrier's result is not assumed any more)
        order.assumed_delivered = False
    order.last_poll_at = parcel.last_poll_at
    order.next_poll_at = None
    order.last_error = None
    order.error_streak = 0
    order.first_error_at = None
    order.delivery_code = order.delivery_code_day = None
    # A 17track registration belongs to the carrier's number: it moves along.
    order.track17 = parcel.track17
    order.track17_carrier = parcel.track17_carrier
    order.track17_next_at = None
    order.track17_result = parcel.track17_result
    # (what the carrier last told about the number goes along with it)
    order.carrier_status = parcel.carrier_status
    del parcels[parcel.number]


def close_unconfirmed(
    parcel: Parcel, now: datetime, text: str = ASSUMED_TEXT, at: datetime | None = None
) -> None:
    """Close a shop order no delivery mail came for (see ``schedule.order_overdue``).

    Delivered, so everything that tidies up delivered parcels applies, but marked
    (``assumed_delivered``) and without a time of delivery: nobody knows it. The day the
    mails named stays. A later mail of the shop takes the mark away again (``_forward``).

    Also for an order the shop itself calls delivered days later (``_confirm``): then with
    the shop's words (``text``) and the time of its mail in the history (``at``).
    """
    old = parcel.result
    events = [TrackingEvent(at or now, text, None), *(old.events if old else [])]
    parcel.result = TrackingResult(
        status=ParcelStatus.DELIVERED,
        status_text=text,
        eta_date=old.eta_date if old else None,
        eta_from=old.eta_from if old else None,
        eta_to=old.eta_to if old else None,
        location=None,
        pickup_point=None,
        pickup_until=None,
        delivered_at=None,
        events=events[:MAX_EVENTS],
        eta_latest=old.eta_latest if old else None,
    )
    parcel.assumed_delivered = True
    parcel.last_change_at = now
    parcel.delivery_code = parcel.delivery_code_day = None


def mark_received(parcel: Parcel, now: datetime) -> None:
    """Mark a parcel as received by hand ("Erhalten"): delivered now, for good.

    For what never gets its "delivered": an order without a delivery mail, a parcel whose
    delivery mail is missing or that is stuck on "Abholbereit", a carrier nobody can ask.
    The time of delivery is ``now``; the history stays and gets a line of its own. What
    told the way there is dropped (day, window, pickup point, an error, the delivery
    code), and so is the mark of an order closed without a delivery mail: now somebody
    confirmed it. Nobody is asked about the parcel any more, and nothing changes it
    again (``Parcel.manual_delivered``; see ``_forward`` and the coordinator).

    An order that was closed on its own already is only confirmed: the mark and the
    words change, but nobody knows when it came. It gets no time of delivery (so it
    never counts as delivered today, see ``schedule.delivered_today``), and the days it
    is kept go on counting from the closing.
    """
    old = parcel.result
    closed = parcel.assumed_delivered
    events = [TrackingEvent(now, MANUAL_TEXT, None), *(old.events if old else [])]
    parcel.result = TrackingResult(
        status=ParcelStatus.DELIVERED,
        status_text=MANUAL_TEXT,
        eta_date=None,
        eta_from=None,
        eta_to=None,
        location=None,
        pickup_point=None,
        pickup_until=None,
        delivered_at=None if closed else now,
        # (a long history, GLS or 17track, loses its oldest line, never the newest)
        events=events[: max(MAX_EVENTS, len(events) - 1)],
    )
    parcel.manual_delivered = True
    parcel.assumed_delivered = False
    if not closed:
        parcel.last_change_at = now
    parcel.delivery_code = parcel.delivery_code_day = None
    parcel.last_error = None
    parcel.error_streak = 0
    parcel.first_error_at = None
    parcel.next_poll_at = None
    parcel.track17_next_at = None


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
        # "Zugestellt" without a day of its own: the mail's day is the day of delivery,
        # and the order's days must fit it like for a parcel folded in afterwards.
        delivered = update.status is ParcelStatus.DELIVERED and not update.eta_date
        target = _merge_candidate(parcels, update, _mail_day(update) if delivered else None)
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
        # A first status is no news - but a delivery whose mail names a shop or a company
        # is: it is somebody's order that just came, and no order here took it (its days
        # are others, or it is not known). Not for a mail read late: nothing came just now.
        news = (
            target.status is ParcelStatus.DELIVERED
            and (name is not None or update.shop is not None)
            and now - update.sent_at <= NEW_DELIVERY_MAX_AGE
        )
        return Change(target, None, True, announce=news)
    old = target.status
    named = False
    # Older versions stored a carrier's display name ("DHL Zustell-Update") as the name: it
    # counts as no name. Any other name stays, also "Hermes" or "DHL Express" (the model
    # cannot tell who set it).
    unnamed = target.name is None or is_carrier_display(target.name)
    if unnamed and name and target.carrier not in SHOP_CARRIERS:
        target.name = name  # e.g. the shop a Hermes mail names
        target.name_manual = False  # the mail's name, whoever typed in the replaced one
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
        if not update.number:
            return _apply_orderless(parcels, update, now)
        return _apply_order(parcels, update, now)
    return _apply_tracking(parcels, update, now)

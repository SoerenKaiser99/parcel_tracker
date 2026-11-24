"""Apply parsed mail updates to the parcel list (no Home Assistant imports)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from ..carriers.gls import gls_number
from ..carriers.track17 import strip_enrichment, with_track17
from ..const import (
    CARRIER_DAYS_EARLY,
    CARRIER_DAYS_LATE,
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
    CLOSED_STATUSES,
    MORE_ITEMS,
    NO_ETA_STATUSES,
    PROGRESS_STEP,
    OrderItem,
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
    name_parts,
)
from .base import (
    ATTEMPT_TEXT,
    DELAY_TEXT,
    PROBLEM_TEXT,
    READY_TEXT,
    RETURNED_TEXT,
    MailUpdate,
    brand_of,
    carrier_key,
    is_carrier_display,
    is_carrier_title,
    is_seller,
    names_more_items,
    shop_of,
    title_key,
)
from .shipping import SOON_TEXT

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
# The lines of an order's history before anything left (see ``_never_shipped``).
_ORDERED_TEXTS = frozenset({SHOP_TEXT[ParcelStatus.PRE_TRANSIT], READY_TEXT})
# Status text of a shop order closed because no delivery mail came (see order_overdue).
ASSUMED_TEXT = "Abgeschlossen ohne Zustellbestätigung"
# Status text of a parcel the user marked as received (see mark_received).
MANUAL_TEXT = "Erhalten (von Hand markiert)"
# Status text of a shop order the shop cancelled (see _cancel_order).
CANCELLED_TEXT = "Storniert"
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
    # waits for no announcement: the box's delivery is told. Or the order came along in
    # the box of another order whose change the same mail told (``MailUpdate.along``, set
    # by the coordinator's ``_handle_mail``). The order's change is its own event, but no
    # notification (see the coordinator's ``_mail_changed``).
    told: bool = False
    # A mail made this parcel, delivered right away, and it is news all the same: a
    # carrier's parcel (see ``_apply_tracking``) or a further box of a known order (see
    # ``_apply_order``). The coordinator announces it once as delivered.
    announce: bool = False
    # The mail was a "wird gleich zugestellt" whose window the parcel took, the first of
    # its day for this parcel (see ``apply_update``): the coordinator tells "Kommt gleich".
    soon: bool = False


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


def _soon_window(parcel: Parcel, result: TrackingResult | None) -> bool:
    """Is the window shown the one of a "wird gleich zugestellt" (``Parcel.soon_until``)?"""
    return (
        result is not None
        and parcel.soon_until is not None
        and result.eta_to == parcel.soon_until
    )


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
    changed = False
    if update.outgoing and not parcel.outgoing:
        parcel.outgoing = True
        # (a parcel somebody sent is no gift for anybody)
        parcel.gift = False
        parcel.gift_for = []
        changed = True
    if parcel.manual_delivered:
        return changed
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
    # (a cancelled order has no step: every status a mail of the shop tells opens it again)
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
        soon = update.status_text == SOON_TEXT and update.eta_to is not None
        window = (update.eta_from, update.eta_to)
        if soon and update.eta_to <= now:
            # "Wird gleich zugestellt" read after its minutes have passed (the mailbox
            # was read late, Home Assistant was down): a window that is over says nothing.
            soon = False
            window = (None, None)
        if update.eta_date and not (stale and _soon_window(parcel, old)):
            # (a mail read late, "kommt heute zwischen …", keeps the window of the newer
            # "wird gleich zugestellt")
            eta = (update.eta_date, *window, update.eta_latest)
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
        if soon and eta[2] == update.eta_to and parcel.soon_until != update.eta_to:
            parcel.soon_until = update.eta_to
            changed = True
    if parcel.status is ParcelStatus.DELIVERED:
        if parcel.delivery_code:
            parcel.delivery_code = parcel.delivery_code_day = None
            changed = True
    elif (
        update.delivery_code
        and not parcel.outgoing
        and update.delivery_code != parcel.delivery_code
    ):
        parcel.delivery_code = update.delivery_code
        parcel.delivery_code_day = update.eta_date or update.sent_at.date()
        changed = True
    if parcel.status is ParcelStatus.DELIVERED:
        # Due at delivery: once delivered there is nothing left to pay or to tell.
        changed = parcel.clear_customs() or changed
    elif update.customs_amount is not None and not parcel.outgoing:
        taken = (update.customs_amount, update.customs_currency, update.customs_cash)
        if taken != (parcel.customs_amount, parcel.customs_currency, parcel.customs_cash):
            parcel.customs_amount = update.customs_amount
            parcel.customs_currency = update.customs_currency
            parcel.customs_cash = update.customs_cash
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


# The number of a further entry of an order ("…P2") behind the order's own.
_FURTHER_ENTRY = re.compile(r"P\d+$")


def order_of(number: str) -> str:
    """The order an entry belongs to: its number without "P<n>" ("AMZ…P2" → "AMZ…")."""
    return _FURTHER_ENTRY.sub("", number)


def _order_parcels(parcels: dict[str, Parcel], carrier: str, number: str) -> list[Parcel]:
    siblings = [
        p for p in parcels.values() if p.carrier == carrier and order_of(p.number) == number
    ]
    return sorted(siblings, key=lambda p: (len(p.number), p.number))


def _order_index(order: str, number: str) -> int:
    """Which entry of an order a number is: 1 for the order's own, n for "…P<n>"."""
    suffix = number[len(order) + 1 :] if number != order else ""
    return int(suffix) if suffix.isdigit() else 1


def _shop_box(carrier: str) -> str:
    """The name of a further entry whose mails named no item yet ("Amazon-Sendung")."""
    return f"{CARRIER_NAMES[carrier]}-Sendung"


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
    parcels: dict[str, Parcel],
    parcel: Parcel,
    update: MailUpdate,
    now: datetime,
    gift: bool = False,
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
            and not own.outgoing
        ):
            _fold(parcels, own, parcel, keep=True)
            changed = True
    elif parcel.tracking_ref != number and parcel.carrier in SINGLE_PARCEL_SHOPS:
        _further_parcel(parcels, parcel, update, now, gift)
    return changed


def _cancelled_before(parcel: Parcel, update: MailUpdate) -> bool:
    """Tell whether the order was cancelled after the mail of ``update`` was sent.

    Mails are not read in the order they were sent (forwarded by hand, handed in later):
    only a mail newer than the cancellation, the newest line of the history, opens the
    order again (see ``_cancel_order``).
    """
    if parcel.status is not ParcelStatus.CANCELLED:
        return False
    return update.sent_at <= parcel.result.events[0].timestamp


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


def _remember_sellers(parcel: Parcel, update: MailUpdate) -> None:
    """Keep the marketplace seller a mail names with the entry it went to.

    A carrier's mail that names it finds the order by it (``_brand_candidate``), as long as
    the entry's mails named no other one. Keeping it is never told, like the shipment's id
    (``_remember_shipment``). Two are kept at most: a second one is all it takes to know
    the entry has no single seller.
    """
    if update.seller and update.seller not in parcel.sellers and len(parcel.sellers) < 2:
        parcel.sellers.append(update.seller)


def _remember_items(parcel: Parcel, update: MailUpdate) -> None:
    """Keep the items the mail lists with the entry it went to.

    The order's mail names all items of the order, a mail about a box those in the box, so
    the list of the newest mail holds: which items, and how many of each. A mail sent
    before the one the entry's items came from (``Parcel.items_at``) changes nothing: read
    late, an order's mail must not give a box the items of the whole order. Nor does a mail
    about the whole order ("Bestellt") once the entry is a box (it has a shipment's id).
    Keeping them is never told, like the shipment's id (``_remember_shipment``).

    The entry is named after its first item in full (the subject cuts it short, and it may
    name an item that is not in this box); how many more it holds is shown behind it
    (``models.name_parts``). Not a name the user typed in, and not without a title (a mail
    without HTML part): then the subject names it, as before.
    """
    if not update.items:
        return
    if update.status is ParcelStatus.PRE_TRANSIT and parcel.shipment_ids:
        return
    # A box's mail gives an entry that is only ordered the box's items whenever it was
    # sent: the entry's are what was ordered, less what was cancelled since (``_cancel_part``).
    boxed = _only_ordered(parcel) and _step(update.status) >= _step(ParcelStatus.IN_TRANSIT)
    if parcel.items_at is not None and update.sent_at < parcel.items_at and not boxed:
        return
    parcel.items, parcel.items_at = list(update.items), update.sent_at
    if not parcel.name_manual and (title := _items_title(parcel.items)):
        parcel.name = title


def _new_box(update: MailUpdate) -> bool:
    """Can the mail tell a box of an order nobody knew of: "Versendet", and neither a
    postponed delivery nor news about a box on its way (``MailUpdate.updates_box``)?"""
    return (
        update.status is ParcelStatus.IN_TRANSIT
        and not update.postponed
        and not update.updates_box
    )


def _parts(entries: list[Parcel]) -> tuple[list[Parcel], list[Parcel]]:
    """The entries of an order that are only ordered (``_only_ordered``) and its boxes."""
    waiting = [p for p in entries if _only_ordered(p)]
    return waiting, [p for p in entries if not _only_ordered(p)]


def _same_time(one: datetime, other: datetime) -> bool:
    """Were two mails sent at the same time, as a copy tells it? To the second, or to the
    minute where one of them has no seconds: a mail forwarded by hand quotes the
    original's time without them. Two mails of the same minute with seconds of their own
    are two mails."""
    if one.second and other.second:
        return int(one.timestamp()) == int(other.timestamp())
    return int(one.timestamp() // 60) == int(other.timestamp() // 60)


def _told_then(parcel: Parcel, update: MailUpdate, text: str | None) -> bool:
    """Has the entry's history a line of these words from the time the mail was sent
    (``_same_time``)?"""
    return parcel.result is not None and any(
        e.text == text and _same_time(e.timestamp, update.sent_at) for e in parcel.result.events
    )


def _articles(items) -> set[str | None]:
    return {item.article_id for item in items}


def cancelled_part(parcel: Parcel) -> bool:
    """A further entry of an order ("…P3") that is cancelled: items cancelled from what was
    only ordered (``_cancel_part``), or a rest cancelled as a whole. It tells what will not
    come, and nothing more: no mail goes to it (``_apply_order``), nor does it make an order
    look split (``_merge_candidate``) or keep a removed one there (the coordinator's
    ``_removed_lately``), nor is it announced as a new parcel (``_added_since``). The
    order's own entry is never one: cancelled as a whole, a later mail opens it again, as
    before. Nor is a box the carrier brought back (``_brought_back``): it is a box of the
    order, whose mails find it to change nothing."""
    return (
        parcel.status is ParcelStatus.CANCELLED
        and parcel.number != order_of(parcel.number)
        and not _brought_back(parcel)
    )


def _rest(parcel: Parcel) -> bool:
    """What a box of an order left (``_split``): a further entry of the order ("…P2") that
    is only ordered. Told by its number, not by the entries stored: once the order's boxes
    are cleaned up, it may be the order's only one."""
    return parcel.number != order_of(parcel.number) and _only_ordered(parcel)


def _box_gone(siblings: list[Parcel], update: MailUpdate) -> bool:
    """Is a mail about a box of a split order of which only what is not shipped yet is
    left (its boxes cleaned up or deleted) about a box that is gone?

    So if it lists none of the articles left, or it lists no article numbers and is no new
    box (``_new_box``: a "Versendet" may be the rest's own box): it changes nothing. Else
    it would take what is left over, shipped or delivered with the box's items, and those
    would be lost. An article Amazon lists under another number than the order did looks
    the same, and so does news about the rest's own box whose "Versendet" was never read
    and whose mail lists no article numbers; both are left out as well.
    """
    if not siblings or _step(update.status) < _step(ParcelStatus.IN_TRANSIT):
        return False
    # (the order's own entry is its first box: while it is there, no box is gone)
    if not all(_rest(p) for p in siblings):
        return False
    articles = _articles(update.items)
    held = set().union(*(_articles(p.items) for p in siblings))
    if articles and held and None not in articles | held:
        return not articles & held
    return not _new_box(update)


def _copy_of_box(siblings: list[Parcel], update: MailUpdate) -> Parcel | None:
    """The box of an order a mail without Amazon's id is a copy of (forwarded by hand: a
    message id of its own): the one box that holds the same articles and whose history has
    the mail's line from the time the mail was sent (``_same_time``).

    A copy of a box's "Versendet" is that box, never a new one: else it would split what
    is left once more (``_split``). Two boxes of the same articles told at the same time
    without an id look alike: the second is taken for the first. None for a mail that
    lists no article numbers (then ``_by_items`` and the title decide, as before).
    """
    if _step(update.status) < _step(ParcelStatus.IN_TRANSIT) or not update.items:
        return None
    articles = _articles(update.items)
    if None in articles:
        return None
    text = update.status_text or SHOP_TEXT.get(update.status)
    found = [
        p
        for p in siblings
        if not _only_ordered(p)
        and _articles(p.items) == articles
        and _told_then(p, update, text)
    ]
    return found[0] if len(found) == 1 else None


def _rest_or_box(entries: list[Parcel], update: MailUpdate, key: str | None) -> list[Parcel]:
    """Of the entries of a split order (``_split``: some only ordered, some boxes), those a
    box's mail goes to: a new box (``_new_box``) to what is only ordered, unless its title
    names a box and not that (a box's "Versendet" again, cut short); any other mail about a
    box to the boxes, never to what is not shipped yet. All entries for any other mail, or
    for an order that is not split."""
    waiting, boxes = _parts(entries)
    if not waiting or not boxes or _step(update.status) < _step(ParcelStatus.IN_TRANSIT):
        return entries
    if not _new_box(update):
        return boxes
    named = [p for p in boxes if _names_item(p, key)]
    return named if named and not any(_names_item(p, key) for p in waiting) else waiting


def _less(items: list[OrderItem], taken: list[OrderItem]) -> list[OrderItem] | None:
    """``items`` without what is ``taken`` (what a box holds, or what the shop cancelled):
    each article less the quantity taken of it, by article number. "Menge: 2" may come as
    1 + 1 in two boxes, so quantities are taken away, not whole items.

    None if that is not known for sure: an item without an article number on either side
    (a mail without HTML part), or nothing taken is one of ``items`` (it is about another
    order). An article taken that ``items`` does not list takes nothing away.
    """
    if not items or not taken or any(i.article_id is None for i in (*items, *taken)):
        return None
    left: dict[str | None, int] = {}
    for item in taken:
        left[item.article_id] = left.get(item.article_id, 0) + item.quantity
    if not any(item.article_id in left for item in items):
        return None
    rest = []
    for item in items:
        gone = min(item.quantity, left.get(item.article_id, 0))
        if gone:
            left[item.article_id] -= gone
        if item.quantity > gone:
            rest.append(replace(item, quantity=item.quantity - gone))
    return rest


def _items_title(items: list[OrderItem]) -> str | None:
    """The name of the first of these items that has one (``_listed``: an item whose link
    shows no text has none)."""
    return next((item.title for item in items if item.title), None)


def _split(
    parcels: dict[str, Parcel],
    ordered: Parcel,
    box: Parcel,
    update: MailUpdate,
    now: datetime,
    gift: bool = False,
) -> None:
    """A box took over an entry that was only ordered (``ordered``: that entry as it was
    before the box's mail): what of its items the box does not hold (``_less``) stays
    ordered, in an entry of its own.

    The box keeps the entry's number, so a sensor never changes its number: the order's
    first box is the order's own entry ("AMZ…"), what is left becomes "…P2", and the next
    box takes that one over in turn (``_by_shipment``: an entry without id that is only
    ordered). The new entry is what the old one was: "Bestellt" with the order's history,
    day, owner, gift and seller; a gift also while the Geschenkmodus is on (``gift``), like
    a further box of the same mail. It is made quietly: an order that is not shipped yet
    is no news, and the box tells its own change.

    Nothing if the box holds an article the entry does not list: then the two lists do not
    tell the same articles alike (another order's items in the box, an article under
    another number), and what is left is not known for sure. Nor if the mail lists fewer
    items than its title tells (its item, and "… und 2 weitere Artikel"): what it leaves
    out would stay ordered in a rest that never comes, as the cancellations check
    (``amazon._listed_cancelled``).
    """
    ordered_articles = {item.article_id for item in ordered.items}
    if any(item.article_id not in ordered_articles for item in box.items):
        return
    more = MORE_ITEMS.search(update.title) if update.title else None
    if more and len(box.items) < 1 + int(more.group(1)):
        return
    rest = _less(ordered.items, box.items)
    if not rest:
        return
    # (the next free number, "…P3"; named after the first of the items left, how many more
    # there are is shown behind it, see ``models.name_parts``)
    order = update.number
    number = _new_number(parcels, _order_parcels(parcels, box.carrier, order), order)
    title = _items_title(rest)
    entry = Parcel(
        number,
        box.carrier,
        "mail",
        title or _shop_box(box.carrier),
        now,
        now,
        mail_title=title,
        items=rest,
        # (closed without a delivery mail it stays so: the next box opens it again)
        result=replace(ordered.result),
        assumed_delivered=ordered.assumed_delivered,
        items_at=ordered.items_at,
        last_mail_at=ordered.last_mail_at,
        sellers=list(ordered.sellers),
        gift=gift or ordered.gift,
        gift_for=list(ordered.gift_for),
        owner=ordered.owner,
        owner_manual=ordered.owner_manual,
    )
    parcels[number] = entry
    if ordered.tracking_ref is not None:
        # A carrier's number told for the order before Amazon named the box is the box's,
        # and so is what the carrier told: the rest keeps only the shop's own lines.
        lines = [e for e in ordered.result.events if e.text in _ORDERED_TEXTS]
        text = SHOP_TEXT[ParcelStatus.PRE_TRANSIT]
        entry.result = TrackingResult(
            status=ParcelStatus.PRE_TRANSIT,
            status_text=text,
            eta_date=None,
            eta_from=None,
            eta_to=None,
            location=None,
            pickup_point=None,
            pickup_until=None,
            delivered_at=None,
            events=lines or [TrackingEvent(ordered.items_at or now, text, None)],
        )


def _by_items(siblings: list[Parcel], update: MailUpdate) -> Parcel | None:
    """The entry of an order with more than one a box's mail without Amazon's id goes to,
    by the articles it lists.

    A new box (``_new_box``) goes to the entry that is only ordered and holds one of its
    articles: what was left of the order (``_split``). Any mail about a box goes to the box
    that holds the same articles. What is only ordered takes such a mail only if no box
    holds any of its articles: then the mail is about the box it was sent in, whose
    "Versendet" was never read. Each only if it is the one entry that fits; None if none
    fits for sure (then the title decides, as without items).
    """
    if _step(update.status) < _step(ParcelStatus.IN_TRANSIT) or not update.items:
        return None
    articles = {item.article_id for item in update.items}
    if None in articles or len(siblings) < 2:
        return None
    held = {p.number: {item.article_id for item in p.items} for p in siblings}
    ordered, shipped = _parts(siblings)
    waiting = [p for p in ordered if articles & held[p.number]]
    boxes = [p for p in shipped if held[p.number] == articles]
    if _new_box(update):
        found = (waiting, boxes)
    elif any(articles & held[p.number] for p in shipped):
        found = (boxes,)
    else:
        found = (waiting,)
    return next((entries[0] for entries in found if len(entries) == 1), None)


def _gift_for(*parcels: Parcel) -> list[str]:
    """The persons the gifts among these entries are for, each once (a box of a gift order
    is hidden from them as well)."""
    return list(dict.fromkeys(person for p in parcels if p.gift for person in p.gift_for))


def _further_parcel(
    parcels: dict[str, Parcel],
    order: Parcel,
    update: MailUpdate,
    now: datetime,
    gift: bool = False,
) -> None:
    """The second box of an order that has a carrier number already: a parcel of its own.

    Named after the shop only ("AliExpress-Sendung": which items are in it is not told),
    with the status of the mail. It belongs to this order, so it is never folded into
    another one (``Parcel.order_checked``). It is a gift if the order is one, whatever the
    mode is now (``gift``): the second box of a gift must not tell what is in it. Nothing if
    the number is tracked already, on its own or by another order, or if no carrier of ours
    has such a number.
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
    extra = Parcel(
        number,
        carrier,
        "mail",
        name,
        now,
        now,
        order_checked=True,
        gift=gift or order.gift,
        gift_for=_gift_for(order),
        # The order's owner with its hand mark ("everybody" set by hand stays so).
        owner=order.owner,
        owner_manual=order.owner_manual,
    )
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
    return _same_start(key or "", theirs)


def _same_start(key: str, other: str) -> bool:
    """Do two title keys (``title_key``) name the same item, one of them cut short?"""
    return bool(key and other) and (other.startswith(key) or key.startswith(other))


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


def _further_shipment(siblings: list[Parcel], update: MailUpdate, key: str | None) -> bool:
    """A mail no entry of the order took is a further shipment: a new box (``_new_box``:
    "Versendet", no postponed delivery or news about a box there is) with an item, once
    every entry is shipped."""
    return (
        key is not None
        and update.carrier not in SINGLE_PARCEL_SHOPS
        and _new_box(update)
        and all(_step(p.status) >= _step(ParcelStatus.IN_TRANSIT) for p in siblings)
    )


def _by_shipment(siblings: list[Parcel], update: MailUpdate) -> Parcel | None:
    """The entry of an order a mail that names its shipment (Amazon's id) goes to.

    The id is the box's own, the same in every mail about it, so it wins over the title:
    two boxes of one item ("2 x …" sent on two days) are two entries, and a box whose
    title grows ("… und 2 weitere Artikel") stays one. Older versions kept every id with
    the entry its mail went to, so two entries may hold the same one: then the one that
    names the mail's item, else the first.

    An id no entry has yet is a box that is new here. While every entry has an id of its
    own, it is a further shipment. Otherwise it may be the box of an entry whose mails
    named no id (read before the ids were kept, or without the link): only those count,
    one with another id is another box. Of those it takes

    - the one its articles tell (``_by_items``: a box whose "Versendet" came without the
      link takes no other box's mail), else the one that names its item, else the order
      itself while no box was told for it (``_only_ordered``: the first box takes it
      over); of a split order a new box takes what is not shipped yet, any other mail a
      box (``_rest_or_box``);
    - else what a mail without id would take: none for a further shipment
      (``_further_shipment``), else the first open one, else the first.

    None if there is none: the box is a further shipment, an entry of its own (the caller
    makes it).
    """
    shipment = update.shipment_id
    key = title_key(update.title) if update.title else None
    if held := [p for p in siblings if shipment in p.shipment_ids]:
        return next((p for p in held if _names_item(p, key)), held[0])
    if not (free := [p for p in siblings if not p.shipment_ids]):
        return None
    # (the articles first: a title cut short may name two entries, "Beispiel…")
    if (by_items := _by_items(free, update)) is not None:
        return by_items
    if key is not None and (named := next((p for p in free if _names_item(p, key)), None)):
        return named
    free = _rest_or_box(free, update, key)
    if ordered := next((p for p in free if _only_ordered(p)), None):
        return ordered
    if _further_shipment(siblings, update, key):
        return None
    open_ = [p for p in free if p.status not in CLOSED_STATUSES]
    return (open_ or free)[0]


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


def _inherit_owner(box: Parcel, siblings: list[Parcel], owner: str | None) -> None:
    """A further box belongs to whom the order belongs: a detected or hand-set owner,
    with its hand mark; "everybody" set by hand on the order keeps the box everybody's
    (and a mail never claims it). The mail's owner only if the order has neither."""
    owned = next((p for p in siblings if p.owner), None)
    if owned is not None:
        box.owner, box.owner_manual = owned.owner, owned.owner_manual
    elif any(p.owner_manual for p in siblings):
        box.owner, box.owner_manual = None, True
    else:
        box.owner = owner


def _claim(parcel: Parcel, owner: str | None) -> None:
    """Give a parcel the owner a mail names, if it has none yet.

    The first detected owner wins: a later mail that names another person does not move
    the parcel (a forward of the same mail to somebody else must not take it away). An
    owner set by hand (``owner_manual``, also "everybody") is never touched by a mail.
    Only detected and hand-set owners are stored; the default person for unclear mails
    is not (the coordinator's ``effective_owner`` adds it when it is read).
    """
    if owner is not None and parcel.owner is None and not parcel.owner_manual:
        parcel.owner = owner


def _apply_order(
    parcels: dict[str, Parcel],
    update: MailUpdate,
    now: datetime,
    gift: bool = False,
    owner: str | None = None,
) -> Change | None:
    """A shop order ("AMZ…"/"EBAY…"/"ALI…"/"EVT…"): one parcel per order, suffix for further
    shipments (never for AliExpress and Eventim: their mails name an order's items in turn).

    A mail that names its shipment (Amazon's id) goes by it (``_by_shipment``). Any other
    goes by the articles it lists once the order has more than one entry (``_by_items``),
    else by the item it names, else to the order's first open entry (of a split order: a
    new box to what is only ordered, any other mail about a box to a box); it is a further
    shipment only as a new box (``_new_box``) with an item no entry names, once every entry
    of the order is shipped. A further entry takes the number after the highest one the
    order has (``_new_number``, "…P3") and is named after its item, without that number.

    A box that takes over an entry that was only ordered leaves what it does not hold
    ordered, in an entry of its own (``_split``). An order's mail read only after its boxes'
    makes none: then nothing tells what was cancelled in between. A copy of a box's mail
    without id (forwarded by hand) goes to that box, never to what is left
    (``_copy_of_box``). What was cancelled of the order takes no mail (``cancelled_part``),
    nor does what is left of it a mail about a box that is gone (``_box_gone``). A box the
    carrier brought back takes its mails, to change nothing (``_brought_back``).
    """
    entries = _order_parcels(parcels, update.carrier, update.number)
    # (what was cancelled of it takes no mail: ``cancelled_part``)
    siblings = [p for p in entries if not cancelled_part(p)]
    if _box_gone(siblings, update):
        return None
    key = title_key(update.title) if update.title else None
    if update.shipment_id and siblings:
        target = _by_shipment(siblings, update)
        further_shipment = target is None
    else:
        target = (
            _copy_of_box(siblings, update)
            or _by_items(siblings, update)
            or next((p for p in siblings if _same_item(p, key)), None)
        )
        further_shipment = False
    if target is None and siblings and not further_shipment:
        further_shipment = _further_shipment(siblings, update, key)
        if not further_shipment:
            # What is open comes first; else the mail opens a cancelled shipment again
            # (it was not shipped yet, like one that is only "Bestellt").
            open_ = [p for p in siblings if p.status not in CLOSED_STATUSES]
            cancelled = [p for p in siblings if p.status is ParcelStatus.CANCELLED]
            candidates = open_ or cancelled or siblings
            # A split order (``_split``): a new box goes to what is only ordered, any other
            # mail about a box to a box (``_rest_or_box``).
            split = {p.number for p in _rest_or_box(siblings, update, key)}
            candidates = [p for p in candidates if p.number in split] or [
                p for p in siblings if p.number in split
            ]
            target = candidates[0]
    if target is None and update.along and siblings:
        # An order that came along in another order's box makes no further entry: no
        # phantom "…P2" delivered next to its entry, left behind when its own box has
        # another id. (An order never seen makes its first one, as a mail read before the
        # order's own mails does; those find it by its id.)
        return None
    if target is not None and (_brought_back(target) or _cancelled_before(target, update)):
        return None
    if target is None:
        number = _new_number(parcels, entries, update.number)
        if update.title:
            name = update.title
        else:
            # (a further box whose mail names no item, see ``_by_shipment``)
            name = _shop_box(update.carrier) if number != update.number else None
        # A further box of a gift order is a gift as well, also when the mode is off by now.
        target = Parcel(
            number,
            update.carrier,
            "mail",
            name,
            now,
            now,
            mail_title=update.title,
            gift=gift or any(p.gift for p in siblings),
            gift_for=_gift_for(*siblings),
        )
        _inherit_owner(target, siblings, owner)
        parcels[number] = target
        _take_shop_facts(parcels, target, update, now, gift)
        _remember_shipment(target, update)
        _remember_sellers(target, update)
        _remember_items(target, update)
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
    _claim(target, owner)
    # A box's mail to an entry that is only ordered: the entry as it was, for what the box
    # leaves of it (``_split``). Only ordered as ``_by_shipment`` and ``_take_over`` tell it,
    # also with a carrier's number told for it already; the lists it reads copied.
    box_mail = _step(update.status) >= _step(ParcelStatus.IN_TRANSIT) and bool(update.items)
    ordered = (
        replace(
            target,
            items=list(target.items),
            sellers=list(target.sellers),
            gift_for=list(target.gift_for),
        )
        if box_mail and _only_ordered(target)
        else None
    )
    _take_over(target, update)
    if target.mail_title is None and update.title:
        target.mail_title = update.title
        if not target.name_manual and name_parts(target)[0] in (None, _shop_box(update.carrier)):
            # (a box whose mails named no item so far: now one does)
            target.name = update.title
    old = target.status
    own = parcels.get(update.tracking_ref) if update.tracking_ref else None
    facts = _take_shop_facts(parcels, target, update, now, gift)
    # (the items first: an entry is only ordered until it keeps the box's id. The items of
    # the whole order are no entry's once it is split, also when only its rest is left
    # (``_rest``): an order's mail gives none then)
    if not (update.status is ParcelStatus.PRE_TRANSIT and (len(siblings) > 1 or _rest(target))):
        _remember_items(target, update)
    _remember_shipment(target, update)
    _remember_sellers(target, update)
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
    # Not delivered: a carrier's parcel a mail made told every status of its own (its
    # first one as well), so the status the order takes over with it is told already,
    # also after a restart emptied the push memory. Nothing of it may wait to be told.
    told = told or (
        own is not None
        and own is not target
        and update.tracking_ref not in parcels
        and own.status not in (None, ParcelStatus.UNKNOWN, ParcelStatus.DELIVERED)
        and own.status is target.status
        and own.unannounced_from is None
    )
    if facts and not forwarded:
        target.last_change_at = now
    # (the box's mail gave the entry the box's items, ``_remember_items``: also one read too
    # late to change its status, the entry is that box all the same)
    if ordered is not None:
        _split(parcels, ordered, target, update, now, gift)
    return Change(target, old, False, told) if facts or forwarded else None


def _in_window(
    parcel: Parcel, day, early: int = CARRIER_DAYS_EARLY, late: int = CARRIER_DAYS_LATE
) -> bool:
    """True if a carrier mail's ``day`` fits the order's day or window: in it, or up to
    ``early`` days before or ``late`` days after it (the shop's day is an estimate, the
    carrier's box often comes a little earlier, now and then a day later)."""
    result = parcel.result
    if result is None or result.eta_date is None:
        return False
    first = result.eta_date - timedelta(days=early)
    last = (result.eta_latest or result.eta_date) + timedelta(days=late)
    return first <= day <= last


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
    """The one open Amazon order of the brand the carrier mail names.

    An order is of the brand if all words of the brand begin its title (whole words, any
    case: the seller sells its own make), or if the brand is the name of the marketplace
    seller its mails named (``is_seller``: the seller sells other makes and sends the box
    with a carrier of its own, whose mail names the seller). Only while its mails named
    that one seller: an entry that was told of two (an order's mail named one, a box's mail
    another) has none it can be found by. And only once Amazon named its shipments, all of
    them sent by the seller (``_seller_shipped``): the text of Amazon's mails never tells
    who sends the box, "Verkauf durch …" stands for a box Amazon sends ("Versand durch
    Amazon") as well. Such a box never comes with the seller's own carrier, whose mail is
    then about another order, one from the seller's own shop. A carrier's mail before
    Amazon's "Versendet" is a parcel of its own until its delivery (``fold_delivered``).

    By its title, too, only an order whose shipments Amazon did not name (``shipment_ids``
    empty) or named as all sent by the seller: a box Amazon sends itself is told by its
    carrier as Amazon's, never by the brand or the seller, also when another seller sells
    it. Such an order is no candidate at all, so it never makes the one of the seller
    ambiguous. A brand of one word of four letters needs all shipments named as sent by
    the seller: such a word is often a plain one ("Glas", "Koch") that begins many a title.

    Deliberately narrow: only Amazon orders (never eBay), none that names another carrier
    than the mail's, and exactly one of them must be of the brand. The mail's day must lie
    in the order's day or window, for a shipped order ("Versendet") also a little around
    it (``_in_window``); if one of the two has no day, the order must be shipped. A mail
    about a delivery never takes an order that is only "Bestellt".
    """
    brand = brand_of(update.title)
    if brand is None:
        return None
    words = r"\s+".join(re.escape(word) for word in brand.split())
    begins = re.compile(rf"{words}(?![^\W_])", re.IGNORECASE)
    # (one word of four letters, "Abcd": often a plain word too, "Glas", "Koch", that
    # begins many a title; only an order Amazon says the seller sends is found by it)
    short = " " not in brand and len(re.sub(r"[\W\d_]", "", brand)) < 5
    matches = [
        p
        for p in orders
        if p.carrier == "amazon"
        and _hint_key(p) in (None, update.carrier)
        and (_seller_shipped(p) or not (short or p.shipment_ids))
        and (
            begins.match((p.mail_title or p.name or "").strip())
            or (
                len(p.sellers) == 1
                and is_seller(brand, p.sellers[0])
                and _seller_shipped(p)
            )
        )
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
        # (a little around the order's days only once it is shipped, as in _merge_candidate)
        if order.status is ParcelStatus.IN_TRANSIT:
            return order if _in_window(order, day) else None
        return order if _in_window(order, day, 0, 0) else None
    return order if order.status is ParcelStatus.IN_TRANSIT else None


def _seller_shipped(order: Parcel) -> bool:
    """True if every shipment Amazon named for the order is sent by the seller itself.

    Amazon's shipment ids (``Parcel.shipment_ids``, from the link to its tracking page)
    begin with "D" for "Versand durch Verkäufer": a marketplace seller sends the box with a
    carrier of its own, and that carrier's mail names the seller, never Amazon. Shipments
    Amazon sends itself began with "U" until February 2026 and with "T" since. The format
    is Amazon's own and nowhere documented, so only the "D" is checked: it held for every
    seller's shipment seen so far. Should Amazon ever give a "D" to boxes it sends itself,
    such orders would wrongly be ruled out for mails naming Amazon, and a mail naming their
    seller could find them (``_brand_candidate``).
    An order without an id is none either: nothing is known about it.
    """
    ids = order.shipment_ids
    return order.carrier == "amazon" and bool(ids) and all(i.startswith("D") for i in ids)


def _merge_candidate(
    parcels: dict[str, Parcel], update: MailUpdate, delivered: date | None = None
) -> Parcel | None:
    """The one open shop order a carrier mail belongs to, if unambiguous.

    The order qualifies when the carrier mail names its shop or the shop mail named
    this carrier; the day must match the order's day or window. If no order's does, the
    day may lie a little around it (``_in_window``), but only for a shipped Amazon order
    of a mail that names Amazon, whose shop mail named no other carrier; one that is only
    ordered there leaves the mail to none. Without a day, the order must be in transit. A
    mail that names another company than the shop (the brand or the marketplace seller
    that sells at Amazon) may still belong to an order: see ``_brand_candidate``.

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

    What of a split order is not shipped yet (``_split``) is never a candidate: a carrier
    carries a box, and the boxes of that order are its other entries. It takes a carrier's
    mail only once Amazon named it a box of its own.
    """
    # (what of a split order is not shipped yet: a rest, ``_rest``, also once its boxes are
    # cleaned up; or an order's entry that is only ordered next to others of it)
    entries = Counter(
        (p.carrier, order_of(p.number))
        for p in parcels.values()
        if p.carrier in SHOP_CARRIERS and not cancelled_part(p)
    )
    orders = [
        p
        for p in parcels.values()
        if p.carrier in SHOP_CARRIERS
        and p.tracking_ref is None
        and p.status not in CLOSED_STATUSES
        and not (_rest(p) or entries[(p.carrier, order_of(p.number))] > 1 and _only_ordered(p))
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
        # An order whose own day fits wins over one the carrier is a little early or late
        # for. That leeway only for an Amazon order the mail names Amazon for (its day is
        # Amazon's cautious estimate; an eBay or AliExpress order's is the seller's), not
        # for one that merely named this carrier or named another one, and only once it
        # is shipped: an order that is only "Bestellt" may be quite another box. It still
        # makes the shipped one ambiguous, as the box may as well be its own.
        exact = [p for p in open_orders if _in_window(p, update.eta_date, 0, 0)]
        near = [
            p
            for p in open_orders
            if p.carrier == update.shop == "amazon"
            and _hint_key(p) in (None, update.carrier)
            and _in_window(p, update.eta_date)
        ]
        shipped = all(p.status is ParcelStatus.IN_TRANSIT for p in near)
        matches = exact or (near if shipped else [])
    else:
        matches = [p for p in open_orders if p.status is ParcelStatus.IN_TRANSIT]
    if len(matches) == 1:
        return matches[0]
    if not matches and update.shop is None:
        return _brand_candidate(orders, update)
    return None


def _apply_orderless(
    parcels: dict[str, Parcel], update: MailUpdate, now: datetime, owner: str | None = None
) -> Change | None:
    """A shop's status mail that names no order (AliExpress "Packstück" with a number no
    carrier of ours has): the status goes to the one open order that fits
    (``_merge_candidate``), else nowhere. Never creates a parcel."""
    target = _merge_candidate(parcels, update)
    if target is None:
        return None
    _claim(target, owner)
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
        or parcel.outgoing
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
    order.gift = order.gift or parcel.gift
    order.gift_for = _gift_for(order, parcel)
    # The order's owner wins (also "everybody" set on it by hand), else the carrier
    # parcel's; the hand mark goes with the owner.
    if order.owner is None and not order.owner_manual:
        order.owner, order.owner_manual = parcel.owner, parcel.owner_manual
    order.tracking_ref = parcel.number
    order.tracking_carrier = parcel.carrier
    if order.customs_amount is None and parcel.customs_amount is not None:
        # (the duty a DHL mail named belongs to the order that takes the parcel in)
        order.customs_amount = parcel.customs_amount
        order.customs_currency = parcel.customs_currency
        order.customs_cash = parcel.customs_cash
    if parcel.soon_until is not None and (
        order.soon_until is None or parcel.soon_until > order.soon_until
    ):
        # (the window of a "wird gleich zugestellt" goes along with the carrier's result)
        order.soon_until = parcel.soon_until
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
    parcel.clear_customs()


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
    parcel.clear_customs()
    parcel.last_error = None
    parcel.error_streak = 0
    parcel.first_error_at = None
    parcel.next_poll_at = None
    parcel.track17_next_at = None


def _never_shipped(parcel: Parcel) -> bool:
    """Has nothing of an order left yet?

    "Bestellt", or closed without a delivery mail while its history tells nothing but the
    order: no shipping, no delivery the shop confirmed (``_confirm``).
    """
    result = parcel.result
    if result is None or parcel.tracking_ref is not None:
        return False
    if result.status is ParcelStatus.PRE_TRANSIT:
        return True
    return (
        parcel.assumed_delivered
        and result.status_text == ASSUMED_TEXT
        and all(e.text in _ORDERED_TEXTS for e in result.events if e.text != ASSUMED_TEXT)
    )


def _cancels_all(parcel: Parcel, update: MailUpdate) -> bool:
    """Does the cancellation take all of the order?

    A mail about the order does (it names no item). One about items only if the order is
    that one item: its title names it (cut short counts, see ``_names_item``) and no
    further one ("… und 2 weitere Artikel"), nor do its items (what of a split order is not
    shipped yet is named after its first item alone, see ``_split``).
    """
    if update.title is None:
        return True
    title = parcel.mail_title
    return (
        title is not None
        and not names_more_items(title)
        and len(parcel.items) <= 1
        and _names_item(parcel, title_key(update.title))
    )


def _without_title(items: list[OrderItem], title: str) -> list[OrderItem] | None:
    """``items`` without the one article whose name the cancellation's title names (cut
    short counts, as in ``_names_item``), all of it: the mail tells no quantity. None unless
    exactly one article fits, and for a title that names further items ("… und 1 weiterer
    Artikel"): which ones is not told."""
    if names_more_items(title) or not (key := title_key(title)):
        return None
    named = [i for i in items if i.title and _same_start(key, title_key(i.title))]
    return [i for i in items if i is not named[0]] if len(named) == 1 else None


def _cancelled_items(
    entries: list[Parcel], update: MailUpdate
) -> tuple[Parcel, list[OrderItem]] | None:
    """The entry of an order a cancellation of items takes them from, and what it holds
    afterwards (``_less``: by article number and quantity; without article numbers by the
    item the title names, ``_without_title``).

    Only an entry that is only ordered and knows its items (``_only_ordered``): what is on its
    way comes anyway. None if the mail is about the whole order (no title), or if not
    exactly one entry holds what it cancels.
    """
    if update.title is None:
        return None
    found = []
    for entry in entries:
        if not _only_ordered(entry) or not entry.items:
            continue
        if update.items and all(i.article_id for i in update.items):
            left = _less(entry.items, list(update.items))
        else:
            left = _without_title(entry.items, update.title)
        if left is not None:
            found.append((entry, left))
    return found[0] if len(found) == 1 else None


def _cancelled_by(parcel: Parcel, update: MailUpdate) -> bool:
    """Did this cancellation make the entry what it is? Then the mail is a copy read again
    (forwarded by hand: a message id of its own), and it takes nothing more.

    The entry is cancelled, its line "Storniert" has the time the mail was sent
    (``_same_time``), and it holds what the mail cancels: the same articles, else (no
    article numbers) the item its title names. So two cancellations read in any order each
    take their own items, and only a copy finds its entry.
    """
    if parcel.status is not ParcelStatus.CANCELLED or not _told_then(
        parcel, update, update.status_text or CANCELLED_TEXT
    ):
        return False
    articles = _articles(update.items)
    if update.items and None not in articles:
        return _articles(parcel.items) == articles
    return update.title is not None and _names_item(parcel, title_key(update.title))


def _cancel_part(
    parcels: dict[str, Parcel],
    entry: Parcel,
    left: list[OrderItem],
    update: MailUpdate,
    now: datetime,
    gift: bool = False,
) -> Change:
    """Some items of an entry that is only ordered were cancelled: it holds the others
    (``left``) and is named after the first of them, as if they had been all it was
    ordered with. Still "Bestellt", so it is no news: the change tells no status. What was
    cancelled is an entry of its own (``_cancelled_entry``).

    The entry's items are never older than this mail (``Parcel.items_at``): an order's
    mail read late does not bring back what was cancelled (``_remember_items``).
    """
    by_article = bool(update.items) and None not in _articles(update.items)
    taken = (
        _less(entry.items, left) or []
        if by_article
        else [i for i in entry.items if not any(i is j for j in left)]
    )
    _cancelled_entry(parcels, entry, taken, update, now, gift)
    entry.items = left
    if entry.items_at is None or entry.items_at < update.sent_at:
        entry.items_at = update.sent_at
    title = _items_title(left)
    if not entry.name_manual:
        entry.name = title or _shop_box(entry.carrier)
    entry.mail_title = title
    entry.last_change_at = now
    return Change(entry, entry.status, False)


def _cancelled_entry(
    parcels: dict[str, Parcel],
    entry: Parcel,
    taken: list[OrderItem],
    update: MailUpdate,
    now: datetime,
    gift: bool = False,
) -> None:
    """The items a cancellation took from an entry that is only ordered (``_cancel_part``),
    in an entry of their own ("…P3") that is "Storniert": what will not come shows, and is
    kept as long as any cancelled order. Owner, gift and seller are the entry's; a gift
    also while the Geschenkmodus is on (``gift``).

    Made quietly, like the rest of a split order (``_split``): a cancellation is no news.
    It takes no mail afterwards (``cancelled_part``); its line "Storniert" with the time
    of the mail tells a copy of the cancellation (``_cancelled_by``).
    """
    order = order_of(entry.number)
    number = _new_number(parcels, _order_parcels(parcels, entry.carrier, order), order)
    title = _items_title(taken) or update.title
    lines = [e for e in entry.result.events if e.text in _ORDERED_TEXTS]
    events = [TrackingEvent(update.sent_at, CANCELLED_TEXT, None), *lines]
    parcels[number] = Parcel(
        number,
        entry.carrier,
        "mail",
        title or _shop_box(entry.carrier),
        now,
        now,
        mail_title=title,
        items=taken,
        items_at=update.sent_at,
        result=TrackingResult(
            status=ParcelStatus.CANCELLED,
            status_text=CANCELLED_TEXT,
            eta_date=None,
            eta_from=None,
            eta_to=None,
            location=None,
            pickup_point=None,
            pickup_until=None,
            delivered_at=None,
            events=events[:MAX_EVENTS],
        ),
        last_mail_at=update.sent_at,
        sellers=list(entry.sellers),
        gift=gift or entry.gift,
        gift_for=list(entry.gift_for),
        owner=entry.owner,
        owner_manual=entry.owner_manual,
    )


def _cancel_order(
    parcels: dict[str, Parcel], update: MailUpdate, now: datetime, gift: bool = False
) -> Change | None:
    """The shop cancelled an order: closed with a status of its own, "Storniert".

    Only the one order that has not left yet (``_never_shipped``) and that the mail
    cancels all of (``_cancels_all``): what is on its way comes anyway, what has arrived
    stays, and the rest of an order whose items were cancelled in part still comes. So a
    cancellation read only after the mail about the shipment (mails are not read in the
    order they were sent) closes nothing either. Nothing is created. The day the mails
    named goes: nothing comes. A mail the shop sends after that opens the order again
    (``_apply_order``).

    A box the carrier brings back to the shop (``MailUpdate.returned``: Amazon refunds it)
    is the exception: shipped, it will not come (``_bring_back``).

    An entry that knows its items loses the ones a mail cancels (``_cancelled_items``):
    what is left is still ordered, and no box or rest of the order holds them later
    (``_split``); what was cancelled is an entry of its own (``_cancel_part``). Once
    nothing is left, the entry itself is cancelled. Cancellations of items count in any
    order they are read; a copy of one (forwarded by hand) takes nothing more
    (``_cancelled_by``).

    Known limits, both rare: a cancellation read before the order's first mail (cancelled
    right after ordering) finds no order and is lost, the order then waits until it is
    closed without a delivery mail. And a mail sent before the cancellation but read after
    it is dropped altogether (``_cancelled_before`` compares the times of the mails).
    """
    entries = _order_parcels(parcels, update.carrier, update.number)
    if update.title is not None and any(_cancelled_by(p, update) for p in entries):
        return None
    if update.returned:
        return _bring_back(entries, update, now)
    if part := _cancelled_items(entries, update):
        entry, left = part
        if left:
            return _cancel_part(parcels, entry, left, update, now, gift)
        # (cancelled as a whole only while nothing of it left: a carrier's number told for
        # it may be a box on its way)
        waiting = [entry] if _never_shipped(entry) else []
    else:
        waiting = [p for p in entries if _never_shipped(p) and _cancels_all(p, update)]
    if len(waiting) != 1:
        return None
    return _close_cancelled(waiting[0], update, now)


def _close_cancelled(target: Parcel, update: MailUpdate, now: datetime) -> Change:
    """Close an entry as cancelled, in the mail's words ("Storniert", "Zurück an Amazon"):
    no day, no code, never asked again (``schedule.poll_interval``, 17track as well)."""
    old = target.result
    text = update.status_text or CANCELLED_TEXT
    # (the line in the history carries the time of the mail, the change is now)
    events = [TrackingEvent(update.sent_at, text, None), *old.events]
    target.result = TrackingResult(
        status=ParcelStatus.CANCELLED,
        status_text=text,
        eta_date=None,
        eta_from=None,
        eta_to=None,
        location=None,
        pickup_point=None,
        pickup_until=None,
        delivered_at=None,
        # (a carrier's long history, GLS or 17track, stays as long as it was, as when a
        # parcel is marked as received: nothing asks for it again)
        events=events[: max(MAX_EVENTS, len(events) - 1)],
    )
    target.assumed_delivered = False
    target.last_change_at = now
    target.delivery_code = target.delivery_code_day = None
    target.track17_next_at = None
    # (nothing is due nor failing for a box that will not come: a box often goes back for
    # duty nobody paid)
    target.clear_customs()
    target.last_error = target.first_error_at = None
    target.error_streak = 0
    return Change(target, old.status, False)


def _bring_back(entries: list[Parcel], update: MailUpdate, now: datetime) -> Change | None:
    """A box the carrier brings back to the shop (``MailUpdate.returned``): closed as
    "Storniert" in the mail's words, "Zurück an Amazon", for good (``_brought_back``).

    The refund comes only for a box that was shipped, so it closes only a box the order
    knows: the one entry that holds what is refunded (``_holding_refund``), shipped
    (``_shipped``) and holding nothing else (``_only_refunded``: a box goes back whole, one
    that holds more is not the one told). Nothing in any other case: no entry or more
    than one holds it ("Menge: 2" in two boxes, which one went back is not told), or the
    box's mails were not read yet. A refund is never a cancellation of what is still to
    come.
    """
    holding = _holding_refund(entries, update)
    if len(holding) != 1:
        return None
    box = holding[0]
    if not _shipped(box) or box.status is ParcelStatus.CANCELLED:
        return None
    return _close_cancelled(box, update, now) if _only_refunded(box, update) else None


def _brought_back(parcel: Parcel) -> bool:
    """A box the carrier brought back to the shop (``_bring_back``). For good: no mail
    changes it any more, neither the shop's nor the carrier's (a delivery then is the one
    to the shop), see ``_apply_order`` and ``_apply_tracking``."""
    return parcel.status is ParcelStatus.CANCELLED and parcel.result.status_text == RETURNED_TEXT


def _shipped(parcel: Parcel) -> bool:
    """Has a box of this entry left: Amazon named it (``_only_ordered``), or a carrier's
    number was told for it, also while it is still "Bestellt"."""
    return not _only_ordered(parcel) or parcel.tracking_ref is not None


def _holding_refund(entries: list[Parcel], update: MailUpdate) -> list[Parcel]:
    """The entries of an order that hold an item a refund names (``MailUpdate.returned``):
    by article number where both know it, else by the item's name, the names of the items
    the entry holds, or its title if it knows none (a subject may name a box cut short,
    "Beispiel…"). Shipped or not: an entry that is only ordered holding the same item
    ("Menge: 2" in two boxes) makes it unknown which one went back.

    What is cancelled of the order (``cancelled_part``) holds nothing, nor does a box
    brought back already (``_brought_back``: a copy of the mail is told by
    ``_cancelled_by``) or one delivered for real: what arrived and was sent back is the
    user's own return.
    """
    articles = _articles(update.items)
    by_article = bool(update.items) and None not in articles
    key = title_key(update.title) if update.title else ""

    def holds(parcel: Parcel) -> bool:
        known = _articles(parcel.items)
        if by_article and parcel.items and None not in known:
            return bool(articles & known)
        if titles := [title_key(i.title) for i in parcel.items if i.title]:
            return any(_same_start(key, title) for title in titles)
        return _names_item(parcel, key)

    return [
        p
        for p in entries
        if not cancelled_part(p)
        and not _brought_back(p)
        and not (p.status is ParcelStatus.DELIVERED and not p.assumed_delivered)
        and holds(p)
    ]


def _only_refunded(box: Parcel, update: MailUpdate) -> bool:
    """Does the box hold nothing but what a refund names: by article number and quantity
    where both know them (``_less``). Else only one item on both sides, of the same
    quantity, the box's named as the refunded one; a box that knows no items, by its
    title, which must not tell further ones ("… und 2 weitere Artikel"). Not if that is
    not known: a box of several items whose mails named no article numbers stays."""
    if (left := _less(box.items, list(update.items))) is not None:
        return not left
    key = title_key(update.title) if update.title else ""
    if len(update.items) > 1:
        return False
    count = update.items[0].quantity if update.items else 1
    if box.items:
        [item, *more] = box.items
        return (
            not more
            and item.quantity == count
            and item.title is not None
            and _same_start(key, title_key(item.title))
        )
    return count == 1 and not MORE_ITEMS.search(box.mail_title or "") and _names_item(box, key)


def _mail_name(update: MailUpdate) -> str | None:
    """The name a carrier mail gives; a carrier's own display name is none."""
    title = update.title
    return title if title and not is_carrier_title(title) else None


def _apply_tracking(
    parcels: dict[str, Parcel],
    update: MailUpdate,
    now: datetime,
    gift: bool = False,
    owner: str | None = None,
) -> Change | None:
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
    if target is None and update.status is not None and not update.outgoing:
        # "Zugestellt" without a day of its own: the mail's day is the day of delivery,
        # and the order's days must fit it like for a parcel folded in afterwards.
        delivered = update.status is ParcelStatus.DELIVERED and not update.eta_date
        target = _merge_candidate(parcels, update, _mail_day(update) if delivered else None)
        if target is not None:
            _claim(target, owner)
            old = target.status
            target.tracking_ref = number
            target.tracking_carrier = update.carrier
            target.next_poll_at = None
            target.last_change_at = now
            _forward(target, update, now)
            return Change(target, old, False)
    if target is None:
        target = Parcel(
            number, update.carrier, "mail", name, now, now,
            gift=gift and not update.outgoing, owner=owner,
        )
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
    if _brought_back(target):
        # (on its way back to the shop: a delivery then is the one to the shop)
        return None
    _claim(target, owner)
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


def apply_update(
    parcels: dict[str, Parcel],
    update: MailUpdate,
    now: datetime,
    gift: bool = False,
    owner: str | None = None,
) -> Change | None:
    """Create or advance the matching parcel in ``parcels`` (mutated in place).

    ``gift``: the Geschenkmodus is on, so every parcel created here is a gift.
    ``owner``: the person the mail's headers name (None: unclear). A parcel created here
    gets it; one that exists gets it only while it has no owner (``_claim``). Setting the
    owner alone is no change that is told.

    A "wird gleich zugestellt" is news once a day per parcel (``Change.soon``): DHL often
    sends it twice within minutes, and the second one only moves the window on.
    """
    if update.carrier in SHOP_CARRIERS:
        if update.status is ParcelStatus.CANCELLED:
            return _cancel_order(parcels, update, now, gift)
        if not update.number:
            return _apply_orderless(parcels, update, now, owner)
        return _apply_order(parcels, update, now, gift, owner)
    if update.status_text != SOON_TEXT:
        return _apply_tracking(parcels, update, now, gift, owner)
    # (the parcel the mail lands on may be an order that took in the carrier's parcel: both
    # numbers are looked at)
    before = {n: p.soon_until for n, p in parcels.items() if p.soon_until is not None}
    change = _apply_tracking(parcels, update, now, gift, owner)
    if change is not None and update.eta_to is not None:
        parcel = change.parcel
        if parcel.soon_until == update.eta_to:
            known = before.get(parcel.number) or before.get(parcel.tracking_ref or "")
            change.soon = known is None or known.date() != update.eta_to.date()
    return change

"""Text and targets of the push notification for a status change (plain Python,
nothing else).

One German line per change. It names the parcel by its name (or the last four
digits of its number; with the option "Namen ausblenden" by its carrier and those
digits, unless the user typed the name in), the carrier and, where known, today's
time window or the pickup branch; instead of the usual sentence the mail's own words where
they are one of a few fixed phrases ("Zustellung versucht"). Never part of it: the delivery
code, the whole tracking number, addresses, a drop-off place, or any other status or event
text of the carrier.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from .const import (
    DEFAULT_NOTIFY_EVENTS,
    NOTIFY_EVENTS,
    NOTIFY_SERVICE_PREFIX,
    NOTIFY_SERVICES_HIDDEN,
    SHOP_CARRIERS,
)
from .mail.aliexpress import CUSTOMS_TEXT, HANDED_OVER_TEXT
from .mail.base import ATTEMPT_TEXT, DELAY_TEXT, PROBLEM_TEXT, READY_TEXT
from .mail.shipping import DAMAGED_TEXT
from .models import (
    Parcel,
    ParcelStatus,
    carrier_name,
    display_name,
    name_parts,
    short_number,
    with_more,
)

__all__ = [
    "DEFAULT_NOTIFY_EVENTS",
    "NOTIFY_EVENTS",
    "TITLE",
    "build_notification",
    "notification_tag",
    "notify_event",
    "service_name",
    "service_target",
]

TITLE = "Paket Tracker"
MAX_NAME = 40
_SERVICE_NAME = re.compile(r"[a-z0-9_]+")


def service_target(name: str) -> str:
    """How the classic service ``notify.<name>`` is stored as a target."""
    return f"{NOTIFY_SERVICE_PREFIX}{name}"


def service_name(target: object) -> str | None:
    """'pushover' for the stored target 'service:pushover'; None for anything else
    (an entity ID, a name no service can have, a service that is no target)."""
    if not isinstance(target, str) or not target.startswith(NOTIFY_SERVICE_PREFIX):
        return None
    name = target[len(NOTIFY_SERVICE_PREFIX):]
    if not _SERVICE_NAME.fullmatch(name) or name in NOTIFY_SERVICES_HIDDEN:
        return None
    return name


def notification_tag(number: str) -> str:
    """Tag of all notifications of one parcel for the Home Assistant app: a later one
    replaces the earlier one. Same format as the blueprint; a hash, never the number."""
    digest = hashlib.md5(str(number).encode(), usedforsecurity=False).hexdigest()
    return f"parcel_tracker_{digest}"


def _short(text: str | None) -> str:
    """One line, at most 40 characters."""
    value = " ".join((text or "").split())
    return value if len(value) <= MAX_NAME else value[: MAX_NAME - 1].rstrip() + "…"


def _label(parcel: Parcel, hide_names: bool = False) -> str:
    """'<name> (<carrier>)'; without a name 'Paket …<last four digits>'.

    With ``hide_names`` only a name the user typed in is named; every other parcel is
    its neutral name, which tells the carrier already ('DHL-Paket …2557').
    """
    if parcel.gift:
        name = display_name(parcel, hide_names)
    elif hide_names:
        if not (parcel.name and parcel.name_manual):
            return display_name(parcel, True)
        name = _short(parcel.name)
    else:
        # (the name is cut, the further items always stay: "… (+2)")
        title, more = name_parts(parcel)
        name = (
            (with_more(_short(title), more) if title else "")
            or _short(parcel.mail_title)
            or f"Paket {short_number(parcel.number)}"
        )
    carrier = carrier_name(parcel)
    return f"{name} ({carrier})" if carrier else name


def _window_today(parcel: Parcel, now: datetime) -> str:
    """' – heute 14:00–16:00 Uhr' when a whole time window for today is known."""
    result = parcel.result
    if result.eta_from is None or result.eta_to is None:
        return ""
    start, end = result.eta_from, result.eta_to
    if now.tzinfo is not None:
        if start.tzinfo is not None:
            start = start.astimezone(now.tzinfo)
        if end.tzinfo is not None:
            end = end.astimezone(now.tzinfo)
    if start.date() != now.date():
        return ""
    return f" – heute {start:%H:%M}–{end:%H:%M} Uhr"


def _money(amount: float, currency: str) -> str:
    """'12,34 €' (German writing: comma for the cents, a dot between the thousands)."""
    text = f"{amount:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{text} {'€' if currency == 'EUR' else currency}"


def _customs(parcel: Parcel) -> str:
    """' – Einfuhrabgaben 12,34 € bar bereithalten' while import duty is due; only when the
    amount is known (a DHL mail named it, see ``Parcel.customs_due``)."""
    due = parcel.customs_due
    if due is None:
        return ""
    amount, currency, cash = due
    return f" – Einfuhrabgaben {_money(amount, currency)} " + (
        "bar bereithalten" if cash else "bei Zustellung"
    )


def _pickup(parcel: Parcel) -> str:
    """' – <place>' and ' bis <day>' if known: named by the carrier or by a shop's pickup
    mail (Amazon "Paket zur Abholung bereit"). A result that is 17track's alone names no
    place of ours."""
    result = parcel.result
    text = ""
    if "status" not in result.enriched and (place := _short(result.pickup_point)):
        text += f" – {place}"
    if result.pickup_until is not None:
        text += f" bis {result.pickup_until:%d.%m.}"
    return text


_ARRIVED = frozenset({ParcelStatus.DELIVERED, ParcelStatus.AWAITING_PICKUP})

# A mail's own words for its status (``TrackingResult.status_text``) that may replace the
# usual sentence: fixed phrases the parsers set themselves. Anything else in the status
# text (a carrier's event text, a drop-off place) never reaches a notification.
_OWN_WORDS = frozenset(
    {
        ATTEMPT_TEXT,
        DELAY_TEXT,
        PROBLEM_TEXT,
        READY_TEXT,
        DAMAGED_TEXT,
        HANDED_OVER_TEXT,
        CUSTOMS_TEXT,
    }
)
# The emoji in front of each status's line.
_ICON = {
    ParcelStatus.PRE_TRANSIT: "🛒",
    ParcelStatus.IN_TRANSIT: "🚚",
    ParcelStatus.AT_DELIVERY_DEPOT: "🏭",
    ParcelStatus.OUT_FOR_DELIVERY: "📦",
    ParcelStatus.AWAITING_PICKUP: "📍",
    ParcelStatus.DELIVERED: "✅",
    ParcelStatus.EXCEPTION: "⚠️",
    ParcelStatus.CANCELLED: "❌",
}
_ANNOUNCED_ICON = "📋"


def notify_event(parcel: Parcel) -> str | None:
    """The event of the options (``NOTIFY_EVENTS``) the parcel's status belongs to.

    Mostly the status itself. "pre_transit" is "ordered" for a shop's order and
    "announced" for a carrier's parcel. None without a status, or for "unknown".
    """
    if parcel.result is None or parcel.result.status is ParcelStatus.UNKNOWN:
        return None
    status = parcel.result.status
    if status is ParcelStatus.PRE_TRANSIT:
        return "ordered" if parcel.carrier in SHOP_CARRIERS else "announced"
    return status.value


def _outgoing(
    parcel: Parcel, label: str, old_status: ParcelStatus | None
) -> tuple[str, str] | None:
    """A parcel the user sent: only its arrival, once (ready for pickup and then
    delivered is one arrival, also with a step back in between: ``Parcel.arrival_told``).
    No place, no deadline: those are the recipient's."""
    status = parcel.result.status
    if status not in _ARRIVED or old_status in _ARRIVED or parcel.arrival_told:
        return None
    if status is ParcelStatus.DELIVERED:
        return TITLE, f"✅ Dein verschicktes Paket {label} wurde zugestellt"
    return TITLE, f"✅ Dein verschicktes Paket {label} liegt beim Empfänger zur Abholung bereit"


def build_notification(
    parcel: Parcel, old_status: ParcelStatus | None, now: datetime, hide_names: bool = False
) -> tuple[str, str] | None:
    """(title, message) for the parcel's new status, or None if it is not announced.

    ``now`` is the local time; it decides whether a time window is "today".
    ``hide_names`` is the option "Namen ausblenden" (see ``_label``).
    """
    result = parcel.result
    if result is None or result.status is old_status:
        return None
    if parcel.assumed_delivered:
        return None  # closed without a delivery mail: nothing arrived just now
    if parcel.manual_delivered:
        return None  # marked as received by hand: the user knows
    label = _label(parcel, hide_names)
    if parcel.outgoing:
        return _outgoing(parcel, label, old_status)
    event = notify_event(parcel)
    if event is None:
        return None
    icon = _ANNOUNCED_ICON if event == "announced" else _ICON[result.status]
    if result.status_text in _OWN_WORDS:
        # The mail's own words say more than the status: "Zustellung versucht".
        return TITLE, f"{icon} {label}: {result.status_text}"
    match event:
        case "ordered":
            message = f"{label} wurde bestellt"
        case "announced":
            message = f"{label} ist angekündigt"
        case "in_transit":
            message = f"{label} ist unterwegs"
        case "at_delivery_depot":
            message = f"{label} ist im Zustelldepot"
        case "out_for_delivery":
            message = f"{label} ist in Zustellung{_window_today(parcel, now)}{_customs(parcel)}"
        case "delivered":
            message = f"{label} wurde zugestellt"
        case "awaiting_pickup":
            message = f"{label} liegt zur Abholung bereit{_pickup(parcel)}"
        case "exception":
            message = f"{label}: Problem bei der Zustellung"
        case _:  # "cancelled"
            message = f"{label} wurde storniert"
    return TITLE, f"{icon} {message}"

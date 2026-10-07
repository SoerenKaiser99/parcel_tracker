"""Text and targets of the push notification for a status change (plain Python,
nothing else).

One German line per change. It names the parcel by its name (or the last four
digits of its number), the carrier and, where known, today's time window or the
pickup branch. Never part of it: the delivery code, the whole tracking number,
addresses, a drop-off place, or any status or event text of the carrier.
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
)
from .models import Parcel, ParcelStatus, carrier_name

__all__ = [
    "DEFAULT_NOTIFY_EVENTS",
    "NOTIFY_EVENTS",
    "TITLE",
    "build_notification",
    "notification_tag",
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


def _label(parcel: Parcel) -> str:
    """'<name> (<carrier>)'; without a name 'Paket …<last four digits>'."""
    name = _short(parcel.name) or _short(parcel.mail_title) or f"Paket …{parcel.number[-4:]}"
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


def _pickup(parcel: Parcel) -> str:
    """' – <branch>' if the carrier itself named it, ' bis <day>' if known."""
    result = parcel.result
    text = ""
    from_carrier = parcel.poll_target is not None and "status" not in result.enriched
    if from_carrier and (place := _short(result.pickup_point)):
        text += f" – {place}"
    if result.pickup_until is not None:
        text += f" bis {result.pickup_until:%d.%m.}"
    return text


def build_notification(
    parcel: Parcel, old_status: ParcelStatus | None, now: datetime
) -> tuple[str, str] | None:
    """(title, message) for the parcel's new status, or None if it is not announced.

    ``now`` is the local time; it decides whether a time window is "today".
    """
    result = parcel.result
    if result is None or result.status is old_status:
        return None
    if parcel.assumed_delivered:
        return None  # closed without a delivery mail: nothing arrived just now
    label = _label(parcel)
    match result.status:
        case ParcelStatus.OUT_FOR_DELIVERY:
            message = f"📦 {label} ist in Zustellung{_window_today(parcel, now)}"
        case ParcelStatus.DELIVERED:
            message = f"✅ {label} wurde zugestellt"
        case ParcelStatus.AWAITING_PICKUP:
            message = f"📍 {label} liegt zur Abholung bereit{_pickup(parcel)}"
        case ParcelStatus.EXCEPTION:
            message = f"⚠️ {label}: Problem bei der Zustellung"
        case _:
            return None
    return TITLE, message

"""Diagnostics download for Paket Tracker.

Meant to be attached to a public bug report, so it only carries what explains a
problem: settings without secrets, masked numbers, statuses, error codes, counters
and times. Never: API keys, passwords, the mailbox user, the postcode, names and
titles, plain numbers, delivery codes, places, event or status texts, mail contents,
the notify targets (entity IDs and service names carry device names).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant

from .const import (
    CONF_COUNTRY,
    CONF_DHL_API_KEY,
    CONF_IMAP_HOST,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_INTERVAL,
    CONF_MOVE_PROCESSED,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    CONF_READ_OTP,
    CONF_TRACK17_API_KEY,
    CONF_UPS_BUDGET,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    DEFAULT_NOTIFY_EVENTS,
    DEFAULT_UPS_BUDGET,
    NOTIFY_EVENTS,
    NOTIFY_SERVICE_PREFIX,
    VERSION,
    entry_country,
    known_country,
)
from .coordinator import ParcelCoordinator
from .models import Parcel, TrackingResult, _iso

# Settings that say nothing about the person. Every other key of the entry (keys,
# passwords, UPS ID/secret, mailbox user, postcode, anything added later) is redacted.
# The IMAP host is only named if it belongs to a public provider (see below), the
# country only as one of the three on offer.
SAFE_KEYS = frozenset(
    {
        CONF_COUNTRY,
        CONF_KEEP_DELIVERED_DAYS,
        CONF_IMAP_HOST,
        CONF_MOVE_PROCESSED,
        CONF_READ_OTP,
        CONF_MAIL_INTERVAL,
        CONF_UPS_BUDGET,
    }
)

# Mail providers everyone can use: such a host says nothing about the person. An own
# server (often a domain with the family name, or an address at home) is just "custom".
PUBLIC_IMAP_DOMAINS = frozenset(
    {
        "mailbox.org",
        "gmx.net", "gmx.de", "gmx.at", "gmx.ch", "gmx.com",
        "web.de",
        "gmail.com", "googlemail.com",
        "outlook.com", "office365.com", "hotmail.com", "live.com",
        "icloud.com", "me.com",
        "yahoo.com", "yahoo.de",
        "t-online.de",
        "posteo.de",
        "ionos.de", "ionos.com", "1und1.de",
        "strato.de",
        "freenet.de",
        "aol.com",
    }
)
# Proton Mail Bridge runs on the same machine.
LOCAL_IMAP_HOSTS = frozenset({"127.0.0.1", "localhost"})
CUSTOM_HOST = "custom"
_HOST = re.compile(r"[a-z0-9.-]+")

# Prefixes that tell the kind of number and stay readable: our own shop-order marks,
# DHL's JJD, Hermes' H (each in front of digits) and UPS' 1Z.
_PREFIX = re.compile(r"(?:EBAY|AMZ|JJD|H)(?=\d)|1Z(?=[0-9A-Z])", re.IGNORECASE)
# Carrier keys, modes and error codes are short identifiers; free text is not passed on.
_CODE = re.compile(r"[a-z0-9_]{1,40}")
_HIDDEN = "other"


def mask_number(number: str | None) -> str | None:
    """Format-preserving mask: digits -> 9, letters -> A, same length, known prefix kept."""
    if number is None:
        return None
    match = _PREFIX.match(number)
    prefix = match.group().upper() if match else ""

    def mask(char: str) -> str:
        if char.isdigit():
            return "9"
        if char.isalpha():
            return "A"
        return char if char.isascii() and char.isprintable() else "?"

    return prefix + "".join(mask(char) for char in number[len(prefix) :])


def _code(value: Any) -> str | None:
    """A short identifier as it is; anything that could be free text becomes "other"."""
    if value is None:
        return None
    return value if isinstance(value, str) and _CODE.fullmatch(value) else _HIDDEN


def public_imap_host(host: Any) -> Any:
    """The host of a public mail provider as it is, every other host as "custom".

    An unset host (empty or None) stays visible as "not set".
    """
    if host is None or host == "":
        return host
    if not isinstance(host, str):
        return CUSTOM_HOST
    name = host.strip().lower()
    if not _HOST.fullmatch(name):
        return CUSTOM_HOST
    if name in LOCAL_IMAP_HOSTS:
        return name
    labels = name.split(".")
    if any(".".join(labels[i:]) in PUBLIC_IMAP_DOMAINS for i in range(len(labels))):
        return name
    return CUSTOM_HOST


def _redact(data: Mapping[str, Any]) -> dict[str, Any]:
    shown = async_redact_data(dict(data), set(data) - SAFE_KEYS)
    if CONF_IMAP_HOST in shown:
        shown[CONF_IMAP_HOST] = public_imap_host(shown[CONF_IMAP_HOST])
    if CONF_COUNTRY in shown:
        shown[CONF_COUNTRY] = known_country(shown[CONF_COUNTRY])
    return shown


def _parcel(parcel: Parcel) -> dict[str, Any]:
    result: TrackingResult | None = parcel.result
    code = parcel.track17_carrier
    return {
        "number": mask_number(parcel.number),
        "carrier": _code(parcel.carrier),
        "carrier_mode": _code(parcel.carrier_mode),
        "tracking_carrier": _code(parcel.tracking_carrier),
        "has_tracking_ref": parcel.tracking_ref is not None,
        "tracking_ref": mask_number(parcel.tracking_ref),
        "shipping_carrier_hint": _code(parcel.shipping_carrier_hint),
        "status": result.status.value if result else None,
        "assumed_delivered": parcel.assumed_delivered,
        "order_checked": parcel.order_checked,
        "last_error": _code(parcel.last_error),
        "error_streak": parcel.error_streak,
        "first_error_at": _iso(parcel.first_error_at),
        "added_at": _iso(parcel.added_at),
        "last_change_at": _iso(parcel.last_change_at),
        "last_poll_at": _iso(parcel.last_poll_at),
        "next_poll_at": _iso(parcel.next_poll_at),
        "has_name": bool(parcel.name),
        "has_mail_title": bool(parcel.mail_title),
        "has_eta": bool(result and result.eta_date),
        "has_window": bool(result and (result.eta_from or result.eta_to)),
        "has_location": bool(result and result.location),
        "has_pickup_point": bool(result and result.pickup_point),
        "has_delivery_code": parcel.delivery_code is not None,
        "event_count": len(result.events) if result else 0,
        "enriched": [_code(group) for group in result.enriched] if result else [],
        "track17": parcel.track17,
        "track17_carrier": code if isinstance(code, int) else None,
        "track17_next_at": _iso(parcel.track17_next_at),
        "has_track17_result": parcel.track17_result is not None,
    }


def _notifications(options: Mapping[str, Any]) -> dict[str, Any]:
    """How many notify targets of which kind and which events; never their names."""
    stored = options.get(CONF_NOTIFY_TARGETS)
    stored = stored if isinstance(stored, (list, tuple)) else ()
    targets = [target for target in stored if isinstance(target, str)]
    services = sum(1 for target in targets if target.startswith(NOTIFY_SERVICE_PREFIX))
    chosen = options.get(CONF_NOTIFY_EVENTS, DEFAULT_NOTIFY_EVENTS)
    chosen = chosen if isinstance(chosen, (list, tuple)) else ()
    return {
        "targets": len(targets),
        "entity_targets": len(targets) - services,
        "service_targets": services,
        "events": [event for event in NOTIFY_EVENTS if event in chosen],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    coordinator: ParcelCoordinator = entry.runtime_data
    state = coordinator.diagnostics()
    budget = coordinator.store.ups_budget
    return {
        "integration_version": VERSION,
        "home_assistant_version": HA_VERSION,
        "country": entry_country(entry),
        "entry": {"data": _redact(entry.data), "options": _redact(entry.options)},
        "carriers": {
            "active": list(coordinator.carriers),
            "credentials": {
                "dhl": bool(entry.data.get(CONF_DHL_API_KEY)),
                "ups": bool(
                    entry.data.get(CONF_UPS_CLIENT_ID) and entry.data.get(CONF_UPS_CLIENT_SECRET)
                ),
                "track17": bool(entry.data.get(CONF_TRACK17_API_KEY)),
                "mail": coordinator.mailbox is not None,
            },
            "dhl_calls_today": state["dhl_calls_today"],
        },
        "ups_budget": {
            "month": budget.month,
            "count": budget.count,
            "limit": int(entry.options.get(CONF_UPS_BUDGET, DEFAULT_UPS_BUDGET)),
            "active": "ups" in coordinator.carriers,
        },
        "track17": state["track17"],
        "mail_import": state["mail_import"],
        "notifications": _notifications(entry.options),
        "pending_announcements": state["pending_announcements"],
        "parcels": [_parcel(parcel) for parcel in coordinator.store.parcels.values()],
    }

"""Data model for Paket Tracker (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from .const import CARRIER_OTHER, MAIL_CARRIERS


class ParcelStatus(StrEnum):
    """Unified parcel status."""

    PRE_TRANSIT = "pre_transit"
    IN_TRANSIT = "in_transit"
    AT_DELIVERY_DEPOT = "at_delivery_depot"
    OUT_FOR_DELIVERY = "out_for_delivery"
    AWAITING_PICKUP = "awaiting_pickup"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    UNKNOWN = "unknown"


# Progress bar step 1..5 (0 = not shown)
PROGRESS_STEP: dict[ParcelStatus, int] = {
    ParcelStatus.PRE_TRANSIT: 1,
    ParcelStatus.IN_TRANSIT: 2,
    ParcelStatus.AT_DELIVERY_DEPOT: 3,
    ParcelStatus.OUT_FOR_DELIVERY: 4,
    ParcelStatus.AWAITING_PICKUP: 4,
    ParcelStatus.DELIVERED: 5,
    ParcelStatus.EXCEPTION: 0,
    ParcelStatus.UNKNOWN: 0,
}


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass(frozen=True)
class TrackingEvent:
    """One scan event."""

    timestamp: datetime
    text: str
    location: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"timestamp": _iso(self.timestamp), "text": self.text, "location": self.location}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackingEvent:
        return cls(_dt(data["timestamp"]), data["text"], data.get("location"))


@dataclass
class TrackingResult:
    """Normalised carrier answer."""

    status: ParcelStatus
    status_text: str | None
    eta_date: date | None
    eta_from: datetime | None
    eta_to: datetime | None
    location: str | None
    pickup_point: str | None
    pickup_until: date | None
    delivered_at: datetime | None
    events: list[TrackingEvent] = field(default_factory=list)
    eta_latest: date | None = None  # last day of a delivery window (eta_date = first day)
    # Field groups filled from 17track ("status", "location", "eta", "window", "events");
    # "status" marks a result that is 17track's as a whole (no carrier answer yet).
    enriched: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "status_text": self.status_text,
            "eta_date": _iso(self.eta_date),
            "eta_latest": _iso(self.eta_latest),
            "eta_from": _iso(self.eta_from),
            "eta_to": _iso(self.eta_to),
            "location": self.location,
            "pickup_point": self.pickup_point,
            "pickup_until": _iso(self.pickup_until),
            "delivered_at": _iso(self.delivered_at),
            "events": [e.to_dict() for e in self.events],
            "enriched": list(self.enriched),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackingResult:
        return cls(
            status=ParcelStatus(data["status"]),
            status_text=data.get("status_text"),
            eta_date=_d(data.get("eta_date")),
            eta_from=_dt(data.get("eta_from")),
            eta_to=_dt(data.get("eta_to")),
            location=data.get("location"),
            pickup_point=data.get("pickup_point"),
            pickup_until=_d(data.get("pickup_until")),
            delivered_at=_dt(data.get("delivered_at")),
            events=[TrackingEvent.from_dict(e) for e in data.get("events", [])],
            eta_latest=_d(data.get("eta_latest")),
            enriched=tuple(data.get("enriched") or ()),
        )


@dataclass
class Parcel:
    """A tracked parcel as stored."""

    number: str
    carrier: str | None
    carrier_mode: str  # "auto" | "manual" | "mail"
    name: str | None
    added_at: datetime
    last_change_at: datetime
    last_poll_at: datetime | None = None
    next_poll_at: datetime | None = None
    result: TrackingResult | None = None
    last_error: str | None = None
    error_streak: int = 0
    first_error_at: datetime | None = None
    tracking_ref: str | None = None
    tracking_carrier: str | None = None
    mail_title: str | None = None
    shipping_carrier_hint: str | None = None  # carrier a shop mail named, e.g. "hermes"
    # Delivery one-time code: kept in memory only, never written by to_dict().
    delivery_code: str | None = None
    delivery_code_day: date | None = None
    # 17track (registered only on explicit request; persisted).
    track17: bool = False
    track17_carrier: int | None = None  # 17track carrier code
    track17_next_at: datetime | None = None  # None while registered = polling ended
    track17_result: TrackingResult | None = None  # last 17track answer, re-applied after polls

    @property
    def status(self) -> ParcelStatus | None:
        return self.result.status if self.result else None

    @property
    def poll_target(self) -> tuple[str | None, str] | None:
        """(carrier key or None for auto, number) to poll, or None if mail-only."""
        if self.tracking_ref:
            return self.tracking_carrier, self.tracking_ref
        if self.carrier in MAIL_CARRIERS or self.carrier == CARRIER_OTHER:
            return None
        return self.carrier, self.number

    @property
    def track17_target(self) -> tuple[str | None, str] | None:
        """(carrier key, number) to register at and ask 17track; None for a shop order
        that has no carrier number yet."""
        if self.tracking_ref:
            return self.tracking_carrier, self.tracking_ref
        if self.carrier in MAIL_CARRIERS:
            return None
        return self.carrier, self.number

    def active_code(self, today: date) -> str | None:
        """The delivery code while it is valid (until the end of its day)."""
        if self.delivery_code and self.delivery_code_day and today <= self.delivery_code_day:
            return self.delivery_code
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "carrier": self.carrier,
            "carrier_mode": self.carrier_mode,
            "name": self.name,
            "added_at": _iso(self.added_at),
            "last_change_at": _iso(self.last_change_at),
            "last_poll_at": _iso(self.last_poll_at),
            "next_poll_at": _iso(self.next_poll_at),
            "result": self.result.to_dict() if self.result else None,
            "last_error": self.last_error,
            "error_streak": self.error_streak,
            "first_error_at": _iso(self.first_error_at),
            "tracking_ref": self.tracking_ref,
            "tracking_carrier": self.tracking_carrier,
            "mail_title": self.mail_title,
            "shipping_carrier_hint": self.shipping_carrier_hint,
            "track17": self.track17,
            "track17_carrier": self.track17_carrier,
            "track17_next_at": _iso(self.track17_next_at),
            "track17_result": self.track17_result.to_dict() if self.track17_result else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Parcel:
        return cls(
            number=data["number"],
            carrier=data.get("carrier"),
            carrier_mode=data.get("carrier_mode", "auto"),
            name=data.get("name"),
            added_at=_dt(data["added_at"]),
            last_change_at=_dt(data["last_change_at"]),
            last_poll_at=_dt(data.get("last_poll_at")),
            next_poll_at=_dt(data.get("next_poll_at")),
            result=TrackingResult.from_dict(data["result"]) if data.get("result") else None,
            last_error=data.get("last_error"),
            error_streak=data.get("error_streak", 0),
            first_error_at=_dt(data.get("first_error_at")),
            tracking_ref=data.get("tracking_ref"),
            tracking_carrier=data.get("tracking_carrier"),
            mail_title=data.get("mail_title"),
            shipping_carrier_hint=data.get("shipping_carrier_hint"),
            track17=bool(data.get("track17", False)),
            track17_carrier=data.get("track17_carrier"),
            track17_next_at=_dt(data.get("track17_next_at")),
            track17_result=(
                TrackingResult.from_dict(data["track17_result"])
                if data.get("track17_result")
                else None
            ),
        )

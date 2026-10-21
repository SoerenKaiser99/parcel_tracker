"""Persistent parcel list."""

from __future__ import annotations

import logging
from dataclasses import replace

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .carriers.base import has_markup, plain_text
from .carriers.ups import ApiBudget
from .const import MAIL_DEDUP_KEEP, STORAGE_KEY, STORAGE_VERSION
from .models import Parcel, TrackingEvent, TrackingResult

_LOGGER = logging.getLogger(__name__)


class DuplicateParcel(Exception):
    """Parcel number already tracked."""


def _scrubbed(text: str | None) -> str | None:
    """A stored text without HTML; a text without any tag stays exactly as it is."""
    if not isinstance(text, str) or not has_markup(text):
        return text
    return plain_text(text) or None


def _scrub_result(result: TrackingResult | None) -> bool:
    """Drop HTML from a stored result's texts in place; True if anything changed.

    Up to v0.3.33 a carrier's text was stored as it came, and DHL sent HTML (issue #18).
    """
    if result is None:
        return False
    texts = (result.status_text, result.location, result.pickup_point)
    result.status_text, result.location, result.pickup_point = map(_scrubbed, texts)
    changed = texts != (result.status_text, result.location, result.pickup_point)
    # Every line stays, also one that was nothing but tags (its text is then ""): how
    # many lines an old parcel's history has decides whether its delivery was told
    # (``mail.apply._delivery_told``). A text without a tag, also a missing one, stays.
    events = [_scrub_event(e) for e in result.events]
    if events != result.events:
        result.events = events
        changed = True
    return changed


def _scrub_event(event: TrackingEvent) -> TrackingEvent:
    text, location = event.text, event.location
    if isinstance(text, str) and has_markup(text):
        text = plain_text(text)
    location = _scrubbed(location)
    if (text, location) == (event.text, event.location):
        return event
    return replace(event, text=text, location=location)


def scrub_markup(parcel: Parcel) -> bool:
    """Drop HTML from the texts a parcel stored from carriers; True if any was dropped."""
    first = _scrub_result(parcel.result)
    return _scrub_result(parcel.track17_result) or first


class ParcelStore:
    """Wraps HA Store."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.parcels: dict[str, Parcel] = {}
        self.message_ids: list[str] = []
        # Geschenkmodus: new parcels are gifts while it is on.
        self.gift_mode = False
        # Mutated in place by the UPS carrier, so keep the same object across loads.
        self.ups_budget = ApiBudget()

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}

        # Treat stored data that isn't a dict or parcels that isn't a list as empty
        if not isinstance(data, dict):
            data = {}

        parcels_data = data.get("parcels", [])
        if not isinstance(parcels_data, list):
            parcels_data = []

        self.parcels = {}
        scrubbed = 0
        for item in parcels_data:
            try:
                if not isinstance(item, dict):
                    continue
                parcel = Parcel.from_dict(item)
                self.parcels[parcel.number] = parcel
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.warning("Skipping unreadable stored parcel: %s", err)
                continue
            scrubbed += scrub_markup(parcel)

        ids = data.get("message_ids", [])
        self.message_ids = [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []
        self.gift_mode = data.get("gift_mode") is True
        loaded = ApiBudget.from_dict(data.get("ups_budget"))
        self.ups_budget.month, self.ups_budget.count = loaded.month, loaded.count
        if scrubbed:
            # Written back at once, so the file holds no link either (only the count is
            # logged, never a text).
            _LOGGER.info("Removed HTML from the stored texts of %d parcel(s)", scrubbed)
            await self.async_save()

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "parcels": [p.to_dict() for p in self.parcels.values()],
                "message_ids": self.message_ids[-MAIL_DEDUP_KEEP:],
                "ups_budget": self.ups_budget.to_dict(),
                "gift_mode": self.gift_mode,
            }
        )

    def add(self, parcel: Parcel) -> None:
        if parcel.number in self.parcels:
            raise DuplicateParcel(parcel.number)
        self.parcels[parcel.number] = parcel

    def remove(self, number: str) -> Parcel:
        return self.parcels.pop(number)

    def get(self, number: str) -> Parcel | None:
        return self.parcels.get(number)

    def remember_message(self, message_id: str) -> bool:
        """Record a processed Message-ID; False if it was already known."""
        if message_id in self.message_ids:
            return False
        self.message_ids.append(message_id)
        del self.message_ids[:-MAIL_DEDUP_KEEP]
        return True

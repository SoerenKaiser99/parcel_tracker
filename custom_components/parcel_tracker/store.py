"""Persistent parcel list."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import MAIL_DEDUP_KEEP, STORAGE_KEY, STORAGE_VERSION
from .models import Parcel

_LOGGER = logging.getLogger(__name__)


class DuplicateParcel(Exception):
    """Parcel number already tracked."""


class ParcelStore:
    """Wraps HA Store."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.parcels: dict[str, Parcel] = {}
        self.message_ids: list[str] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}

        # Treat stored data that isn't a dict or parcels that isn't a list as empty
        if not isinstance(data, dict):
            data = {}

        parcels_data = data.get("parcels", [])
        if not isinstance(parcels_data, list):
            parcels_data = []

        self.parcels = {}
        for item in parcels_data:
            try:
                if not isinstance(item, dict):
                    continue
                parcel = Parcel.from_dict(item)
                self.parcels[parcel.number] = parcel
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.warning("Skipping unreadable stored parcel: %s", err)

        ids = data.get("message_ids", [])
        self.message_ids = [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "parcels": [p.to_dict() for p in self.parcels.values()],
                "message_ids": self.message_ids[-MAIL_DEDUP_KEEP:],
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

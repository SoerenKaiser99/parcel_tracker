"""Delivery calendar."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import ParcelConfigEntry
from .coordinator import ParcelCoordinator
from .models import Parcel, ParcelStatus


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ParcelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ParcelCalendar(entry.runtime_data)])


def _event(p: Parcel) -> CalendarEvent | None:
    r = p.result
    if not r or not r.eta_date or r.status is ParcelStatus.DELIVERED:
        return None
    if r.eta_date < dt_util.now().date():
        return None
    summary = f"Paket: {p.name or p.number}"
    if r.eta_from and r.eta_to:
        return CalendarEvent(start=r.eta_from, end=r.eta_to, summary=summary, location=r.location)
    return CalendarEvent(
        start=r.eta_date, end=r.eta_date + timedelta(days=1), summary=summary, location=r.location
    )


class ParcelCalendar(CoordinatorEntity[ParcelCoordinator], CalendarEntity):
    """calendar.pakete"""

    _attr_icon = "mdi:package-variant"

    def __init__(self, coordinator: ParcelCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_calendar"
        self.entity_id = "calendar.pakete"
        self._attr_name = "Pakete"

    @property
    def available(self) -> bool:
        return True

    def _events(self) -> list[CalendarEvent]:
        events = [e for p in self.coordinator.store.parcels.values() if (e := _event(p))]
        return sorted(events, key=lambda e: e.start_datetime_local)

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [e for e in self._events() if e.end_datetime_local >= now]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            e for e in self._events()
            if e.start_datetime_local < end_date and e.end_datetime_local > start_date
        ]

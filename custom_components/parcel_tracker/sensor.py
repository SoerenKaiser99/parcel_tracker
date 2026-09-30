"""Sensors for Paket Tracker."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import ParcelConfigEntry
from .const import CARRIER_NAMES
from .coordinator import ParcelCoordinator
from .models import PROGRESS_STEP, Parcel, ParcelStatus
from .schedule import days_until


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _remove_ghost_entities(hass: HomeAssistant, entry_id: str, parcels: dict) -> None:
    """Drop stale parcel sensor registry entries left by a first refresh
    that already dropped the parcel (e.g. removed before platforms loaded),
    so no ``unavailable`` sensor with no attributes lingers for the card.
    """
    registry = er.async_get(hass)
    prefix = f"{entry_id}_"
    for reg_entry in list(er.async_entries_for_config_entry(registry, entry_id)):
        if not reg_entry.entity_id.startswith("sensor."):
            continue
        if not reg_entry.unique_id.startswith(prefix):
            continue
        suffix = reg_entry.unique_id[len(prefix):]
        if suffix == "today":
            continue
        if suffix not in parcels:
            registry.async_remove(reg_entry.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ParcelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: dict[str, ParcelSensor] = {}
    _remove_ghost_entities(hass, entry.entry_id, coordinator.store.parcels)
    async_add_entities([TodaySensor(coordinator)])

    @callback
    def _sync() -> None:
        current = set(coordinator.store.parcels)
        new = [ParcelSensor(coordinator, n) for n in current - known.keys()]
        for sensor in new:
            known[sensor.number] = sensor
        if new:
            async_add_entities(new)
        registry = er.async_get(hass)
        for number in list(known.keys() - current):
            sensor = known.pop(number)
            if sensor.entity_id and registry.async_get(sensor.entity_id):
                registry.async_remove(sensor.entity_id)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class ParcelSensor(CoordinatorEntity[ParcelCoordinator], SensorEntity):
    """One tracked parcel."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [s.value for s in ParcelStatus]
    _attr_translation_key = "parcel"
    _attr_icon = "mdi:package-variant-closed"
    _unrecorded_attributes = frozenset({"events", "status_text", "delivery_code"})

    def __init__(self, coordinator: ParcelCoordinator, number: str) -> None:
        super().__init__(coordinator)
        self.number = number
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{number}"
        self.entity_id = f"sensor.paket_{slugify(number)}"

    @property
    def _parcel(self) -> Parcel | None:
        return self.coordinator.store.get(self.number)

    @property
    def available(self) -> bool:
        return self._parcel is not None

    @property
    def name(self) -> str:
        p = self._parcel
        if p and p.name:
            return p.name
        carrier = CARRIER_NAMES.get(p.carrier, p.carrier) if p and p.carrier else "Paket"
        return f"{carrier} {self.number}"

    @property
    def native_value(self) -> str:
        p = self._parcel
        return (p.status or ParcelStatus.UNKNOWN).value if p else ParcelStatus.UNKNOWN.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self._parcel
        if p is None:
            return {}
        r = p.result
        today = dt_util.now().date()
        return {
            "carrier": p.carrier,
            "number": p.number,
            "name": p.name,
            "eta_date": _iso(r.eta_date) if r else None,
            "eta_latest": _iso(r.eta_latest) if r else None,
            "eta_from": _iso(r.eta_from) if r else None,
            "eta_to": _iso(r.eta_to) if r else None,
            "days_until": days_until(r.eta_date, today) if r else None,
            "location": r.location if r else None,
            "pickup_point": r.pickup_point if r else None,
            "pickup_until": _iso(r.pickup_until) if r else None,
            "status_text": r.status_text if r else None,
            "last_update": _iso(p.last_poll_at),
            "stale": p.last_error is not None and r is not None,
            "last_error": p.last_error,
            "progress": PROGRESS_STEP[r.status] if r else 0,
            "delivered_at": _iso(r.delivered_at) if r else None,
            "events": [e.to_dict() for e in r.events] if r else [],
            "tracking_ref": p.tracking_ref,
            "delivery_code": p.active_code(today),
        }


class TodaySensor(CoordinatorEntity[ParcelCoordinator], SensorEntity):
    """Number of parcels expected today."""

    _attr_translation_key = "today"
    _attr_has_entity_name = False
    _attr_icon = "mdi:truck-delivery"

    def __init__(self, coordinator: ParcelCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_today"
        self.entity_id = "sensor.pakete_heute"
        self._attr_name = "Pakete heute"

    @property
    def available(self) -> bool:
        return True

    def _today(self) -> list[Parcel]:
        today = dt_util.now().date()
        return [
            p for p in self.coordinator.store.parcels.values()
            if p.result and p.result.eta_date == today and p.status is not ParcelStatus.DELIVERED
        ]

    @property
    def native_value(self) -> int:
        return len(self._today())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "parcels": [
                {
                    "number": p.number,
                    "name": p.name,
                    "carrier": p.carrier,
                    "eta_from": _iso(p.result.eta_from),
                    "eta_to": _iso(p.result.eta_to),
                }
                for p in self._today()
            ]
        }

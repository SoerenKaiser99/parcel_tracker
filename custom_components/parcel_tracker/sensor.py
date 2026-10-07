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
from .carriers.track17 import ENRICH_LOCATION
from .const import CARRIER_OTHER, TRACK17_SOURCE, VERSION
from .coordinator import ParcelCoordinator
from .models import PROGRESS_STEP, Parcel, ParcelStatus
from .models import carrier_name as _carrier_name
from .schedule import ParcelSummary, days_until, summarize


def _iso(value) -> str | None:
    return value.isoformat() if value else None


# Unique-id suffixes of the fixed sensors (everything else is a parcel number).
_FIXED = frozenset(
    {"today", "active", "possible", "delivered_today", "awaiting_pickup", "track17_quota"}
)


def _location_source(parcel: Parcel) -> str | None:
    r = parcel.result
    if r is None or not r.location:
        return None
    if ENRICH_LOCATION in r.enriched or parcel.carrier == CARRIER_OTHER:
        return TRACK17_SOURCE
    return None


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
        if suffix in _FIXED:
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
    async_add_entities([
        TodaySensor(coordinator),
        *(GroupCountSensor(coordinator, *group) for group in _GROUP_SENSORS),
        Track17QuotaSensor(coordinator),
    ])

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
        return f"{(_carrier_name(p) if p else None) or 'Paket'} {self.number}"

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
            "carrier_name": _carrier_name(p),
            "number": p.number,
            "name": p.name,
            "eta_date": _iso(r.eta_date) if r else None,
            "eta_latest": _iso(r.eta_latest) if r else None,
            "eta_from": _iso(r.eta_from) if r else None,
            "eta_to": _iso(r.eta_to) if r else None,
            "days_until": days_until(r.eta_date, today) if r else None,
            "location": r.location if r else None,
            "location_source": _location_source(p),
            "pickup_point": r.pickup_point if r else None,
            "pickup_until": _iso(r.pickup_until) if r else None,
            "status_text": r.status_text if r else None,
            "last_update": _iso(p.last_poll_at),
            "stale": p.last_error is not None and r is not None,
            "last_error": p.last_error,
            "progress": PROGRESS_STEP[r.status] if r else 0,
            "delivered_at": _iso(r.delivered_at) if r else None,
            # A shop order closed without a delivery mail: "delivered" is only assumed.
            "assumed_delivered": p.assumed_delivered,
            "events": [e.to_dict() for e in r.events] if r else [],
            "tracking_ref": p.tracking_ref,
            "tracking_carrier": p.tracking_carrier,
            "shipping_carrier_hint": p.shipping_carrier_hint,
            "delivery_code": p.active_code(today),
            "track17": p.track17,
            "track17_carrier": p.track17_carrier,
        }


def _items(parcels: list[Parcel]) -> list[dict[str, Any]]:
    """The parcels of a summary sensor's list attribute."""
    return [
        {
            "number": p.number,
            "name": p.name,
            "carrier": p.carrier,
            "eta_from": _iso(p.result.eta_from) if p.result else None,
            "eta_to": _iso(p.result.eta_to) if p.result else None,
        }
        for p in parcels
    ]


class _SummarySensor(CoordinatorEntity[ParcelCoordinator], SensorEntity):
    """A fixed sensor that counts parcels; the rules are in schedule.summarize()."""

    _attr_has_entity_name = False

    @property
    def available(self) -> bool:
        return True

    def _summary(self) -> ParcelSummary:
        now = dt_util.now()  # "today" and "changed today" are meant in the home's time zone
        return summarize(self.coordinator.store.parcels.values(), now.date(), now.tzinfo)


class TodaySensor(_SummarySensor):
    """Number of parcels that come today for sure; ranges including today are "possible".

    Parcels delivered today and those waiting at a pickup point are listed too, they do
    not count (a waiting parcel with a fixed day today counts by that day, as before).
    """

    _attr_translation_key = "today"
    _attr_icon = "mdi:truck-delivery"
    _unrecorded_attributes = frozenset({"integration_version"})

    def __init__(self, coordinator: ParcelCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_today"
        self.entity_id = "sensor.pakete_heute"
        self._attr_name = "Pakete heute"

    @property
    def native_value(self) -> int:
        return len(self._summary().sure)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self._summary()
        return {
            "parcels": _items(summary.sure),
            "possible": _items(summary.possible),
            "possible_count": len(summary.possible),
            "delivered_today": _items(summary.delivered_today),
            "delivered_today_count": len(summary.delivered_today),
            "awaiting_pickup": _items(summary.awaiting_pickup),
            "awaiting_pickup_count": len(summary.awaiting_pickup),
            # The card compares this with its own version: a browser that still runs the
            # card from before an update shows a hint to reload the page.
            "integration_version": VERSION,
        }


# One sensor per list of the summary: (list of ParcelSummary = unique-id suffix and
# translation key, entity id, name, icon). The entity ids are fixed here, like
# sensor.pakete_heute: dashboards, the card and the README name them.
_GROUP_SENSORS = (
    ("active", "sensor.pakete_unterwegs", "Pakete unterwegs", "mdi:truck-fast"),
    ("possible", "sensor.pakete_moeglich", "Pakete möglich", "mdi:calendar-question"),
    (
        "delivered_today",
        "sensor.pakete_zugestellt_heute",
        "Pakete zugestellt heute",
        "mdi:package-variant-closed-check",
    ),
    ("awaiting_pickup", "sensor.pakete_abholbereit", "Pakete abholbereit", "mdi:locker-multiple"),
)


class GroupCountSensor(_SummarySensor):
    """Number of parcels in one list of the summary, e.g. all that are not delivered yet.

    A state of its own for dashboards (visibility conditions) and automations; the
    parcels are in the attribute ``parcels``, shaped like those of sensor.pakete_heute.
    """

    def __init__(
        self, coordinator: ParcelCoordinator, group: str, entity_id: str, name: str, icon: str
    ) -> None:
        super().__init__(coordinator)
        self._group = group
        self._attr_translation_key = group
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{group}"
        self.entity_id = entity_id
        self._attr_name = name
        self._attr_icon = icon

    def _parcels(self) -> list[Parcel]:
        return getattr(self._summary(), self._group)

    @property
    def native_value(self) -> int:
        return len(self._parcels())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"parcels": _items(self._parcels())}


class Track17QuotaSensor(CoordinatorEntity[ParcelCoordinator], SensorEntity):
    """17track numbers left (the free account has 200 once)."""

    _attr_translation_key = "track17_quota"
    _attr_has_entity_name = False
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: ParcelCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_track17_quota"
        self.entity_id = "sensor.paket_tracker_17track_kontingent"
        self._attr_name = "Paket Tracker 17track-Kontingent"

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.track17 is not None
            and not self.coordinator.track17_blocked
        )

    @property
    def native_value(self) -> int | None:
        quota = self.coordinator.track17_quota
        return quota.remain if quota else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        quota = self.coordinator.track17_quota
        return {"total": quota.total if quota else None, "used": quota.used if quota else None}

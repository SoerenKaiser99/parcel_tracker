"""The switch "Geschenkmodus": parcels added while it is on are gifts."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ParcelConfigEntry
from .coordinator import ParcelCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ParcelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([GiftModeSwitch(entry.runtime_data)])


class GiftModeSwitch(CoordinatorEntity[ParcelCoordinator], SwitchEntity):
    """On: every new parcel is a gift. Only a gift viewer (or an automation) turns it off."""

    _attr_translation_key = "gift_mode"
    _attr_has_entity_name = False
    _attr_icon = "mdi:gift"
    # A config entity is not exposed to Assist by default: a voice satellite runs without
    # a user, and a call without a user may turn the mode off.
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ParcelCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_gift_mode"
        self.entity_id = "switch.paket_tracker_geschenkmodus"
        self._attr_name = "Geschenkmodus"

    @property
    def is_on(self) -> bool:
        return self.coordinator.gift_mode

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_gift_mode(True, self._user_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_gift_mode(False, self._user_id)

    @property
    def _user_id(self) -> str | None:
        return self._context.user_id if self._context else None

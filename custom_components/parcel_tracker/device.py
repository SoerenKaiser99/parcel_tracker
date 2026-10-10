"""The device of a config entry: where the automation editor offers the triggers."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, VERSION

DEVICE_NAME = "Paket Tracker"


def async_register_device(hass: HomeAssistant, entry_id: str) -> dr.DeviceEntry:
    """Create (or update) the service device "Paket Tracker" of a config entry.

    It is there for the device triggers (see ``device_trigger``) and has no entities on
    purpose: Home Assistant builds the name of an entity on a device from the name of the
    device and its own, also without ``has_entity_name`` ("Pakete heute" would become
    "Paket Tracker Pakete heute"). Names and entity ids stay as they always were.
    """
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, entry_id)},
        name=DEVICE_NAME,
        manufacturer=DEVICE_NAME,
        model="Sendungsverfolgung",
        sw_version=VERSION,
        entry_type=dr.DeviceEntryType.SERVICE,
    )

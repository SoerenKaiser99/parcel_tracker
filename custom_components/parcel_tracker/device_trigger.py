"""Device triggers: the status event, offered by the automation editor.

Every trigger is an event trigger on ``parcel_tracker_status_changed`` under the hood,
filtered by the config entry of the device and, except for the generic one, by the new
status. An automation reads the event as usual: ``trigger.event.data.name``,
``trigger.event.data.number``, ``trigger.event.data.new_status``, …
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import (
    DEVICE_TRIGGER_BASE_SCHEMA,
    InvalidDeviceAutomationConfig,
)
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, EVENT_STATUS_CHANGED, NOTIFY_EVENTS

# Any status change, also the ones that have no trigger of their own.
TRIGGER_STATUS_CHANGED = "status_changed"
# In the order the editor lists them: the statuses a notification can announce (each is
# the ``new_status`` of the event), then the generic one.
TRIGGER_TYPES = (*NOTIFY_EVENTS, TRIGGER_STATUS_CHANGED)

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES)}
)


def _entry_id(hass: HomeAssistant, device_id: str) -> str | None:
    """The config entry a device of ours stands for, None for any other device."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    return next((value for domain, value in device.identifiers if domain == DOMAIN), None)


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, str]]:
    """The triggers of the service device "Paket Tracker"."""
    if _entry_id(hass, device_id) is None:
        return []
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in TRIGGER_TYPES
    ]


def _event_data(entry_id: str, trigger_type: str) -> dict[str, Any]:
    """The fields of the status event a trigger asks for.

    Always the config entry: the device of another entry never fires for these parcels.
    "delivered" asks for a confirmed delivery; a shop order closed without a delivery
    mail (``assumed``) only fires the generic trigger.
    """
    data: dict[str, Any] = {"entry_id": entry_id}
    if trigger_type != TRIGGER_STATUS_CHANGED:
        data["new_status"] = trigger_type
    if trigger_type == "delivered":
        data["assumed"] = False
    return data


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Listen for the status event on behalf of a device trigger."""
    entry_id = _entry_id(hass, config[CONF_DEVICE_ID])
    if entry_id is None:
        raise InvalidDeviceAutomationConfig(
            f"Device {config[CONF_DEVICE_ID]} is no Paket Tracker device"
        )
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: EVENT_STATUS_CHANGED,
            event_trigger.CONF_EVENT_DATA: _event_data(entry_id, config[CONF_TYPE]),
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )

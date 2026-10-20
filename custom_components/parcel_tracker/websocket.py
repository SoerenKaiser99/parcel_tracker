"""WebSocket commands of the Geschenkmodus (read by the card)."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .detect import normalize
from .links import tracking_url


def _coordinator(hass: HomeAssistant):
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the commands (once; the integration's async_setup runs once)."""
    websocket_api.async_register_command(hass, ws_gift_name)
    websocket_api.async_register_command(hass, ws_gift_viewer)


@websocket_api.websocket_command(
    {vol.Required("type"): "parcel_tracker/gift_name", vol.Required("number"): str}
)
@websocket_api.async_response
async def ws_gift_name(hass: HomeAssistant, connection, msg: dict) -> None:
    """The real name, mail title and link of a parcel, for gift viewers only."""
    coordinator = _coordinator(hass)
    if coordinator is None or not coordinator.is_gift_viewer(connection.user.id):
        connection.send_error(msg["id"], "not_allowed", "Not allowed to see gifts")
        return
    parcel = coordinator.store.parcels.get(normalize(msg["number"]))
    if parcel is None:
        connection.send_error(msg["id"], "not_found", "Parcel not found")
        return
    connection.send_result(
        msg["id"],
        {
            "name": parcel.name,
            "mail_title": parcel.mail_title,
            "tracking_url": tracking_url(parcel),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "parcel_tracker/gift_viewer"})
@websocket_api.async_response
async def ws_gift_viewer(hass: HomeAssistant, connection, msg: dict) -> None:
    """Whether the calling user may see gifts."""
    coordinator = _coordinator(hass)
    viewer = coordinator is not None and coordinator.is_gift_viewer(connection.user.id)
    connection.send_result(msg["id"], {"viewer": viewer})

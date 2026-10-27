"""WebSocket commands read by the card: the Geschenkmodus and the delivery code."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

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
    websocket_api.async_register_command(hass, ws_delivery_code)


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
    if parcel is not None and coordinator.is_gift_recipient(parcel, connection.user.id):
        # A gift for this user's person: as for somebody who may not see gifts.
        connection.send_error(msg["id"], "not_allowed", "Not allowed to see gifts")
        return
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
    """Whether the calling user may see gifts, and the gifts for the user's person
    (``Parcel.gift_for``), which the card shows as to somebody who may not see gifts."""
    coordinator = _coordinator(hass)
    user_id = connection.user.id
    viewer = coordinator is not None and coordinator.is_gift_viewer(user_id)
    hidden = coordinator.hidden_gifts(user_id) if viewer else []
    connection.send_result(msg["id"], {"viewer": viewer, "hidden": hidden})


@websocket_api.websocket_command(
    {vol.Required("type"): "parcel_tracker/delivery_code", vol.Required("number"): str}
)
@websocket_api.async_response
async def ws_delivery_code(hass: HomeAssistant, connection, msg: dict) -> None:
    """The parcel's delivery code (one-time password) for the card, asked for on a tap.

    It is a secret (it hands over the parcel), so it is no attribute in the state machine.
    Any logged-in user gets it, a gift's as well (it is needed at the door). None: the
    option "Zustell-Codes mitlesen" is off, the parcel is unknown or has no valid code.
    """
    if connection.user is None:
        connection.send_error(msg["id"], "not_allowed", "Not logged in")
        return
    coordinator = _coordinator(hass)
    parcel = coordinator.store.parcels.get(normalize(msg["number"])) if coordinator else None
    code = coordinator.delivery_code(parcel, dt_util.now().date()) if parcel else None
    connection.send_result(msg["id"], {"code": code})

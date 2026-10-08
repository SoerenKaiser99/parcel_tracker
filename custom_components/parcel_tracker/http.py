"""HTTP endpoint that takes one raw mail, without a mailbox."""

from __future__ import annotations

from http import HTTPStatus

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView

from .const import DOMAIN


class ImportMailView(HomeAssistantView):
    """POST one raw RFC 822 mail (.eml) as the body; answers what became of it.

    Not a service: Home Assistant fires every service call with its data as an event,
    so the whole mail would cross the event bus and end up in the recorder database.
    A request body reaches only this handler. Needs a login like every /api view;
    Home Assistant itself rejects a body above its limit (16 MB) with 413.
    """

    url = "/api/parcel_tracker/import_mail"
    name = "api:parcel_tracker:import_mail"

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app[KEY_HASS]
        if request.content_type.startswith("multipart/"):
            # A form upload wraps the mail: the parser would find no headers in it.
            return self.json_message(
                "Send the mail itself as the request body, not as a form upload.",
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            )
        # A byte order mark or a blank line in front would hide the headers as well.
        raw = (await request.read()).removeprefix(b"\xef\xbb\xbf").lstrip()
        if not raw:
            return self.json_message("The request body is empty.", HTTPStatus.BAD_REQUEST)
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        result = await entries[0].runtime_data.async_import_raw_mail(raw) if entries else None
        if result is None:
            return self.json_message(
                "Parcel Tracker is not set up or not loaded.", HTTPStatus.SERVICE_UNAVAILABLE
            )
        return self.json(result)

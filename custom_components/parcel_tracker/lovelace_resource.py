"""Keep the card registered as a Lovelace module resource (storage mode)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import CARD_URL, VERSION

_LOGGER = logging.getLogger(__name__)


def plan_resource(items: list[dict[str, Any]], url: str) -> tuple[str, str | None]:
    """Decide what to do: ("create", None), ("update", id) or ("none", None)."""
    for item in items:
        current = str(item.get("url", ""))
        if current.split("?", 1)[0] == CARD_URL:
            if current == url:
                return "none", None
            return "update", item.get("id")
    return "create", None


async def async_ensure_resource(hass: HomeAssistant, *_: Any) -> None:
    """Create or update the module resource. Never raises."""
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415

        data = hass.data.get(LOVELACE_DATA)
        if data is None:
            _LOGGER.info("Lovelace not available, card resource not registered")
            return
        resources = data.resources
        if getattr(data, "resource_mode", "storage") != "storage" or not hasattr(
            resources, "async_create_item"
        ):
            _LOGGER.info("Lovelace resources in YAML mode, card resource not registered")
            return
        await resources.async_get_info()  # ensures the collection is loaded
        url = f"{CARD_URL}?v={VERSION}"
        action, item_id = plan_resource(resources.async_items(), url)
        if action == "create":
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Registered card resource %s", url)
        elif action == "update" and item_id:
            await resources.async_update_item(item_id, {"res_type": "module", "url": url})
            _LOGGER.info("Updated card resource to %s", url)
        else:
            _LOGGER.debug("Card resource %s already registered", url)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register the Paket Tracker card as a Lovelace resource: %s", err)

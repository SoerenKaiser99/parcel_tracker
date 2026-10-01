"""Keep the card registered as a Lovelace module resource (storage mode).

In YAML mode the resources cannot be written; a repair issue says what to add.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CARD_URL, DOMAIN, LOCAL_CARD_URL

ISSUE_YAML = "card_resource_yaml"

_LOGGER = logging.getLogger(__name__)


def _is_ours(item: dict[str, Any]) -> bool:
    return str(item.get("url", "")).split("?", 1)[0] in (CARD_URL, LOCAL_CARD_URL)


def plan_resource(
    items: list[dict[str, Any]], url: str
) -> tuple[str, str | None, list[str]]:
    """Decide what to do: (action, kept_id, ids_to_delete).

    action is "create", "update" or "none". Of several of our resources one is
    kept (preferring one already at ``url``); the others are deleted.
    """
    ours = [i for i in items if _is_ours(i)]
    if not ours:
        return "create", None, []
    keep = next((i for i in ours if i.get("url") == url), ours[0])
    extras = [str(i["id"]) for i in ours if i is not keep]
    action = "none" if keep.get("url") == url else "update"
    return action, keep.get("id"), extras


def _yaml_mode(hass: HomeAssistant, resources: Any, url: str) -> None:
    """YAML resources cannot be written: tell the user to list the card by hand."""
    if any(_is_ours(item) for item in resources.async_items() or []):
        ir.async_delete_issue(hass, DOMAIN, ISSUE_YAML)
        return
    _LOGGER.info("Lovelace resources in YAML mode, card resource not registered")
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_YAML,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_YAML,
        translation_placeholders={"url": url},
    )


async def async_ensure_resource(hass: HomeAssistant, url: str) -> None:
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
            _yaml_mode(hass, resources, url)
            return
        ir.async_delete_issue(hass, DOMAIN, ISSUE_YAML)
        await resources.async_get_info()  # ensures the collection is loaded
        action, item_id, extras = plan_resource(resources.async_items(), url)
        if action == "create":
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Registered card resource %s", url)
        elif action == "update" and item_id:
            await resources.async_update_item(item_id, {"res_type": "module", "url": url})
            _LOGGER.info("Updated card resource to %s", url)
        else:
            _LOGGER.debug("Card resource %s already registered", url)
        for extra_id in extras:
            await resources.async_delete_item(extra_id)
            _LOGGER.info("Removed duplicate card resource %s", extra_id)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register the Paket Tracker card as a Lovelace resource: %s", err)

"""Paket Tracker integration."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.ssl import client_context

from .card_install import BUNDLED_CARD, CARD_FILE, card_hash, card_url, install_card
from .carriers import build_carriers
from .const import (
    CARD_URL,
    CARRIER_AUTO,
    CONF_DHL_API_KEY,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USER,
    DEFAULT_IMAP_HOST,
    DOMAIN,
)
from .coordinator import ParcelCoordinator
from .detect import UnsupportedNumber
from .lovelace_resource import async_ensure_resource
from .mail.imap import MailboxClient
from .store import DuplicateParcel, ParcelStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ParcelConfigEntry = ConfigEntry[ParcelCoordinator]


def _coordinator(hass: HomeAssistant) -> ParcelCoordinator:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_tracked")
    return entries[0].runtime_data


def _err(key: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=key)


def _dhl_key(entry: ConfigEntry) -> str | None:
    """Read the DHL key from entry.data (the single source of truth)."""
    return entry.data.get(CONF_DHL_API_KEY)


def _mailbox(entry: ConfigEntry) -> MailboxClient | None:
    """IMAP client when a user (options) and a password (data) are configured."""
    user = entry.options.get(CONF_IMAP_USER)
    password = entry.data.get(CONF_IMAP_PASSWORD)
    if not user or not password:
        return None
    return MailboxClient(
        entry.options.get(CONF_IMAP_HOST) or DEFAULT_IMAP_HOST,
        user,
        password,
        ssl_context=client_context(),
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register card and services once."""
    # In the test harness `http` may not be set up, so hass.http can be None.
    # Guard the static-path registration; the card is exercised in a real HA.
    if getattr(hass, "http", None) is not None:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(BUNDLED_CARD), False)]
        )

    # /local (config/www) is served from the very start of HA, unlike our own
    # static path; clients that hit a not-yet-registered URL cache the failure.
    target = Path(hass.config.path("www", "parcel_tracker", CARD_FILE))
    try:
        digest, www_existed, _written = await hass.async_add_executor_job(
            install_card, BUNDLED_CARD, target
        )
    except OSError as err:
        _LOGGER.warning(
            "Could not copy the card to %s (%s); serving it from %s", target, err, CARD_URL
        )
        digest = await hass.async_add_executor_job(lambda: card_hash(BUNDLED_CARD.read_bytes()))
        www_existed = False
    if not www_existed:
        _LOGGER.info(
            "Created the www folder; the card is served from %s for now and "
            "from /local after the next Home Assistant restart",
            CARD_URL,
        )
    url = card_url(digest, www_existed)
    if "frontend" in hass.config.components:
        add_extra_js_url(hass, url)

    # Lovelace is an after_dependency, so its resource collection is ready here;
    # don't wait for EVENT_HOMEASSISTANT_STARTED, which can come very late.
    hass.async_create_task(async_ensure_resource(hass, url), eager_start=False)

    async def add(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_add(
                call.data["number"], call.data.get("carrier", CARRIER_AUTO), call.data.get("name")
            )
        except UnsupportedNumber as err:
            raise _err(err.reason) from err
        except DuplicateParcel as err:
            raise _err("duplicate") from err
        except ValueError as err:
            raise _err("unknown_carrier") from err

    async def remove(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_remove(call.data["number"])
        except KeyError as err:
            raise _err("not_tracked") from err

    async def rename(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_rename(call.data["number"], call.data.get("name"))
        except KeyError as err:
            raise _err("not_tracked") from err

    async def refresh(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_refresh_parcels(call.data.get("number"))
        except KeyError as err:
            raise _err("not_tracked") from err

    number = vol.All(cv.string, vol.Length(min=1))
    hass.services.async_register(
        DOMAIN, "add_parcel", add,
        schema=vol.Schema({
            vol.Required("number"): number,
            vol.Optional("carrier", default=CARRIER_AUTO): vol.In([CARRIER_AUTO, "dhl", "dpd"]),
            vol.Optional("name"): cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN, "remove_parcel", remove, schema=vol.Schema({vol.Required("number"): number})
    )
    hass.services.async_register(
        DOMAIN, "rename_parcel", rename,
        schema=vol.Schema({vol.Required("number"): number, vol.Optional("name"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, "refresh", refresh, schema=vol.Schema({vol.Optional("number"): number})
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ParcelConfigEntry) -> bool:
    """Set up from a config entry."""
    store = ParcelStore(hass)
    await store.async_load()
    carriers = build_carriers(async_get_clientsession(hass), _dhl_key(entry))
    mailbox = _mailbox(entry)
    if mailbox is None:
        _mail_import_off(hass, entry)
    coordinator = ParcelCoordinator(hass, entry, store, carriers, mailbox)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


def _mail_import_off(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """No mailbox configured: drop mail repair issues and an orphaned password."""
    for issue in ("imap_auth", "amazon_unrecognized"):
        ir.async_delete_issue(hass, DOMAIN, issue)
    if not entry.options.get(CONF_IMAP_USER) and CONF_IMAP_PASSWORD in entry.data:
        data = {k: v for k, v in entry.data.items() if k != CONF_IMAP_PASSWORD}
        hass.config_entries.async_update_entry(entry, data=data)


async def _reload(hass: HomeAssistant, entry: ParcelConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ParcelConfigEntry) -> bool:
    """Unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

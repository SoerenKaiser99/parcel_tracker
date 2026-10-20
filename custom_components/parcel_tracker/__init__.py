"""Paket Tracker integration."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .card_install import (
    BUNDLED_CARD,
    CARD_FILE,
    card_hash,
    card_url,
    install_card,
    local_is_served,
)
from .carriers import build_carriers
from .carriers.base import AuthError, CarrierError
from .carriers.track17 import (
    CarrierNotDetected,
    QuotaExhausted,
    Track17Client,
    Track17Disabled,
)
from .carriers.ups import ApiBudget, UpsCarrier
from .config_flow import mailbox_context
from .const import (
    CARD_URL,
    CARRIER_AUTO,
    CARRIER_OTHER,
    CONF_DHL_API_KEY,
    CONF_IMAP_FOLDER,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_PORT,
    CONF_IMAP_SECURITY,
    CONF_IMAP_USER,
    CONF_TRACK17_API_KEY,
    CONF_UPS_BUDGET,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    DEFAULT_IMAP_HOST,
    DEFAULT_UPS_BUDGET,
    DOMAIN,
    IMAP_SECURITY_SSL,
    SELECTABLE_CARRIERS,
    entry_country,
)
from .coordinator import ParcelCoordinator
from .detect import UnsupportedNumber
from .device import async_register_device
from .http import ImportMailView
from .lovelace_resource import async_ensure_resource
from .mail.imap import MailboxClient, clean_security, looks_local
from .store import DuplicateParcel, ParcelStore
from .websocket import async_register_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ParcelConfigEntry = ConfigEntry[ParcelCoordinator]

TRACK17_ISSUES = ("track17_auth", "track17_quota_low", "track17_quota_exhausted")


def _coordinator(hass: HomeAssistant) -> ParcelCoordinator:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_tracked")
    return entries[0].runtime_data


def _err(key: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=key)


def _track17_err(err: Exception) -> ServiceValidationError:
    """German/English text for a failed 17track request."""
    if isinstance(err, Track17Disabled):
        return _err("track17_off")
    if isinstance(err, CarrierNotDetected):
        return _err("track17_carrier")
    if isinstance(err, QuotaExhausted):
        return _err("track17_quota")
    if isinstance(err, AuthError):
        return _err("track17_auth")
    return _err("track17_unavailable")


def _dhl_key(entry: ConfigEntry) -> str | None:
    """Read the DHL key from entry.data (the single source of truth)."""
    return entry.data.get(CONF_DHL_API_KEY)


def _mailbox(entry: ConfigEntry) -> MailboxClient | None:
    """IMAP client when a user (options) and a password (data) are configured."""
    user = entry.options.get(CONF_IMAP_USER)
    password = entry.data.get(CONF_IMAP_PASSWORD)
    if not user or not password:
        return None
    # Nothing stored (every entry from before v0.3.32): TLS with a checked certificate
    # on port 993, as always. The TLS context comes from Home Assistant, ready-made.
    security = clean_security(entry.options.get(CONF_IMAP_SECURITY))
    return MailboxClient(
        entry.options.get(CONF_IMAP_HOST) or DEFAULT_IMAP_HOST,
        user,
        password,
        ssl_context=mailbox_context(security),
        # No folder stored (every entry from before v0.3.29): INBOX, as always.
        folder=entry.options.get(CONF_IMAP_FOLDER),
        port=entry.options.get(CONF_IMAP_PORT),
        security=security,
    )


def _insecure_mail_hint(hass: HomeAssistant, mailbox: MailboxClient | None) -> None:
    """A hint in the repairs while the mailbox is read without verified encryption from
    a server that does not look like one in the own network (see ``looks_local``).

    The options flow cannot warn after saving, so this stands in for it. It can be
    ignored, and stays ignored over reloads; it goes away on its own once the
    connection is verified again, the host is a local one or the import is off.
    """
    if (
        mailbox is not None
        and mailbox.security != IMAP_SECURITY_SSL
        and not looks_local(mailbox.host)
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            "imap_insecure",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="imap_insecure",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "imap_insecure")


def _ups_carrier(hass: HomeAssistant, entry: ConfigEntry, budget: ApiBudget) -> UpsCarrier | None:
    """UPS Track API client when ID and secret (data) and a budget > 0 (options) are set."""
    client_id = entry.data.get(CONF_UPS_CLIENT_ID)
    secret = entry.data.get(CONF_UPS_CLIENT_SECRET)
    limit = int(entry.options.get(CONF_UPS_BUDGET, DEFAULT_UPS_BUDGET))
    if not client_id or not secret or limit <= 0:
        return None
    return UpsCarrier(async_get_clientsession(hass), client_id, secret, budget, limit)


def _track17_client(hass: HomeAssistant, entry: ConfigEntry) -> Track17Client | None:
    """17track client when a key is stored in entry.data."""
    key = entry.data.get(CONF_TRACK17_API_KEY)
    return Track17Client(async_get_clientsession(hass), key) if key else None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register card and services once."""
    # In the test harness `http` may not be set up, so hass.http can be None.
    # Guard the static-path registration; the card is exercised in a real HA.
    if getattr(hass, "http", None) is not None:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(BUNDLED_CARD), False)]
        )
        hass.http.register_view(ImportMailView())

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
        use_local = False
    else:
        # The folder existing is not enough: HA serves /local only if www was
        # there when HA started. Without hass.http (tests) the folder decides.
        served = local_is_served(hass)
        use_local = www_existed if served is None else served
        if not use_local:
            _LOGGER.info(
                "Home Assistant does not serve /local yet (the www folder is new); "
                "the card is served from %s for now and from /local after the "
                "next Home Assistant restart",
                CARD_URL,
            )
    url = card_url(digest, use_local)

    # The card is delivered only as a Lovelace resource, never as a frontend
    # extra module (add_extra_js_url): index.html imports extra modules in
    # parallel with app.js, whose scoped-custom-element-registry polyfill replaces
    # window.customElements. A card evaluated before that registers on the native
    # registry and the dashboard reports "Custom element doesn't exist".
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
        except (Track17Disabled, CarrierError) as err:
            raise _track17_err(err) from err
        except ValueError as err:
            raise _err("unknown_carrier") from err

    async def remove(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_remove(
                call.data["number"], call.context.user_id
            )
        except KeyError as err:
            raise _err("not_tracked") from err

    async def rename(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_rename(
                call.data["number"], call.data.get("name"), call.context.user_id
            )
        except KeyError as err:
            raise _err("not_tracked") from err

    async def mark_delivered(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_mark_delivered(call.data["number"])
        except KeyError as err:
            raise _err("not_tracked") from err
        except ValueError as err:
            raise _err("cancelled" if str(err) == "cancelled" else "already_delivered") from err

    async def refresh(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_refresh_parcels(call.data.get("number"))
        except KeyError as err:
            raise _err("not_tracked") from err

    async def track_17track(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_track17(call.data["number"])
        except KeyError as err:
            raise _err("not_tracked") from err
        except (Track17Disabled, CarrierError) as err:
            raise _track17_err(err) from err
        except ValueError as err:
            raise _err("track17_not_possible") from err

    async def set_gift(call: ServiceCall) -> None:
        try:
            await _coordinator(hass).async_set_gift(
                call.data.get("number"),
                call.data["open_parcels"],
                call.data["gift"],
                call.context.user_id,
            )
        except KeyError as err:
            raise _err("not_tracked") from err
        except ValueError as err:
            raise _err("gift_target") from err

    number = vol.All(cv.string, vol.Length(min=1))
    hass.services.async_register(
        DOMAIN, "add_parcel", add,
        schema=vol.Schema({
            vol.Required("number"): number,
            vol.Optional("carrier", default=CARRIER_AUTO): vol.In(
                [CARRIER_AUTO, *SELECTABLE_CARRIERS, CARRIER_OTHER]
            ),
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
        DOMAIN, "mark_delivered", mark_delivered,
        schema=vol.Schema({vol.Required("number"): number}),
    )
    hass.services.async_register(
        DOMAIN, "refresh", refresh, schema=vol.Schema({vol.Optional("number"): number})
    )
    hass.services.async_register(
        DOMAIN, "track_17track", track_17track,
        schema=vol.Schema({vol.Required("number"): number}),
    )
    hass.services.async_register(
        DOMAIN, "set_gift", set_gift,
        schema=vol.Schema({
            vol.Optional("number"): number,
            vol.Optional("open_parcels", default=False): cv.boolean,
            vol.Required("gift"): cv.boolean,
        }),
    )
    async_register_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ParcelConfigEntry) -> bool:
    """Set up from a config entry."""
    store = ParcelStore(hass)
    await store.async_load()
    carriers = build_carriers(
        async_get_clientsession(hass), _dhl_key(entry), entry_country(entry)
    )
    if ups := _ups_carrier(hass, entry, store.ups_budget):
        carriers["ups"] = ups
    else:
        for issue in ("ups_auth", "ups_budget"):
            ir.async_delete_issue(hass, DOMAIN, issue)
    mailbox = _mailbox(entry)
    if mailbox is None:
        _mail_import_off(hass, entry)
    _insecure_mail_hint(hass, mailbox)
    track17 = _track17_client(hass, entry)
    if track17 is None:
        for issue in TRACK17_ISSUES:
            ir.async_delete_issue(hass, DOMAIN, issue)
    coordinator = ParcelCoordinator(hass, entry, store, carriers, mailbox, track17=track17)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    async_register_device(hass, entry.entry_id)
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

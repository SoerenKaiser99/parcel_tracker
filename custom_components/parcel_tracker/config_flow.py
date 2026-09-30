"""Config flow for Paket Tracker."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util.ssl import client_context

from .carriers.base import CarrierUnavailable
from .carriers.dhl import DhlCarrier
from .const import (
    CONF_DHL_API_KEY,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_INTERVAL,
    CONF_MAIL_SECTION,
    CONF_MOVE_PROCESSED,
    CONF_POSTCODE,
    CONF_READ_OTP,
    DEFAULT_IMAP_HOST,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DEFAULT_MAIL_INTERVAL,
    DEFAULT_MOVE_PROCESSED,
    DEFAULT_POSTCODE,
    DEFAULT_READ_OTP,
    DOMAIN,
    MAX_KEEP_DELIVERED_DAYS,
    MAX_MAIL_INTERVAL,
    MIN_KEEP_DELIVERED_DAYS,
    MIN_MAIL_INTERVAL,
)
from .mail.imap import ImapAuthError, ImapUnavailable, MailboxClient

_POSTCODE = re.compile(r"^\d{5}$")
_KEY = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_DAYS = NumberSelector(
    NumberSelectorConfig(
        min=MIN_KEEP_DELIVERED_DAYS, max=MAX_KEEP_DELIVERED_DAYS, mode=NumberSelectorMode.BOX
    )
)
_MINUTES = NumberSelector(
    NumberSelectorConfig(
        min=MIN_MAIL_INTERVAL, max=MAX_MAIL_INTERVAL, mode=NumberSelectorMode.BOX
    )
)


def _mail_section(current: Mapping[str, Any]) -> section:
    """Collapsible 'mail import' block of the options form."""
    return section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_IMAP_HOST, default=current.get(CONF_IMAP_HOST) or DEFAULT_IMAP_HOST
                ): str,
                vol.Optional(
                    CONF_IMAP_USER,
                    description={"suggested_value": current.get(CONF_IMAP_USER, "")},
                ): str,
                vol.Optional(CONF_IMAP_PASSWORD): _KEY,
                vol.Optional(
                    CONF_MOVE_PROCESSED,
                    default=current.get(CONF_MOVE_PROCESSED, DEFAULT_MOVE_PROCESSED),
                ): bool,
                vol.Optional(
                    CONF_READ_OTP, default=current.get(CONF_READ_OTP, DEFAULT_READ_OTP)
                ): bool,
                vol.Optional(
                    CONF_MAIL_INTERVAL,
                    default=current.get(CONF_MAIL_INTERVAL, DEFAULT_MAIL_INTERVAL),
                ): _MINUTES,
            }
        ),
        {"collapsed": not current.get(CONF_IMAP_USER)},
    )


def _schema(
    defaults: Mapping[str, Any],
    with_key: bool,
    suggested_postcode: str | None = None,
    mail: Mapping[str, Any] | None = None,
) -> vol.Schema:
    fields: dict = {}
    if with_key:
        fields[vol.Optional(CONF_DHL_API_KEY)] = _KEY
    if suggested_postcode is not None:
        fields[
            vol.Optional(CONF_POSTCODE, description={"suggested_value": suggested_postcode})
        ] = str
    else:
        fields[
            vol.Optional(CONF_POSTCODE, default=defaults.get(CONF_POSTCODE, DEFAULT_POSTCODE))
        ] = str
    fields[
        vol.Required(
            CONF_KEEP_DELIVERED_DAYS,
            default=defaults.get(CONF_KEEP_DELIVERED_DAYS, DEFAULT_KEEP_DELIVERED_DAYS),
        )
    ] = _DAYS
    if mail is not None:
        fields[vol.Optional(CONF_MAIL_SECTION, default={})] = _mail_section(mail)
    return vol.Schema(fields)


def _validate_postcode(user_input: dict[str, Any]) -> str:
    """Return the stripped postcode; caller checks `_POSTCODE` on non-empty values."""
    return (user_input.get(CONF_POSTCODE) or "").strip()


async def _check_key(hass, key: str | None) -> str | None:
    """Return an error code or None."""
    if not key:
        return None
    try:
        ok = await DhlCarrier(async_get_clientsession(hass), key).validate_key()
    except CarrierUnavailable:
        return "cannot_connect"
    return None if ok else "invalid_key"


async def _check_mailbox(hass, host: str, user: str, password: str) -> str | None:
    """Log in and select INBOX; return an error code or None."""
    try:
        client = MailboxClient(host, user, password, ssl_context=client_context())
        await hass.async_add_executor_job(client.check_login)
    except ImapAuthError:
        return "imap_auth"
    except ImapUnavailable:
        return "imap_cannot_connect"
    return None


class ParcelTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors: dict[str, str] = {}
        if user_input is not None:
            key_value = (user_input.get(CONF_DHL_API_KEY) or "").strip()
            postcode = _validate_postcode(user_input)
            if postcode and not _POSTCODE.match(postcode):
                errors[CONF_POSTCODE] = "invalid_postcode"
            elif err := await _check_key(self.hass, key_value):
                errors[CONF_DHL_API_KEY] = err
            else:
                if CONF_DHL_API_KEY in user_input:
                    user_input[CONF_DHL_API_KEY] = key_value
                user_input[CONF_POSTCODE] = postcode
                user_input[CONF_KEEP_DELIVERED_DAYS] = int(user_input[CONF_KEEP_DELIVERED_DAYS])
                return self.async_create_entry(title="Paket Tracker", data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}, True), errors=errors
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key_value = (user_input.get(CONF_DHL_API_KEY) or "").strip()
            err = await _check_key(self.hass, key_value)
            if err is None:
                user_input[CONF_DHL_API_KEY] = key_value
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=user_input
                )
            errors[CONF_DHL_API_KEY] = err
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_DHL_API_KEY): _KEY}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ParcelTrackerOptionsFlow()


class ParcelTrackerOptionsFlow(OptionsFlow):
    """Change key, postcode, keep days and the mail import.

    Secrets (DHL key, IMAP password) are stored in the config entry's ``data``
    (the same place reauth writes the key) so flows never disagree about which
    secret is current; an empty secret field keeps the stored one. Everything
    else lives in ``options``.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            mail = user_input.get(CONF_MAIL_SECTION) or {}
            host = (mail.get(CONF_IMAP_HOST) or "").strip() or DEFAULT_IMAP_HOST
            user = (mail.get(CONF_IMAP_USER) or "").strip()
            new_password = mail.get(CONF_IMAP_PASSWORD) or ""
            stored_password = self.config_entry.data.get(CONF_IMAP_PASSWORD, "")
            password = new_password or stored_password
            # Only log in again when the login data changed, so saving e.g. the
            # postcode works while the mail server is down.
            login_changed = (
                host != (self.config_entry.options.get(CONF_IMAP_HOST) or DEFAULT_IMAP_HOST)
                or user != (self.config_entry.options.get(CONF_IMAP_USER) or "")
                or (bool(new_password) and new_password != stored_password)
            )
            postcode = _validate_postcode(user_input)
            key_value = (user_input.get(CONF_DHL_API_KEY) or "").strip()
            if postcode and not _POSTCODE.match(postcode):
                errors[CONF_POSTCODE] = "invalid_postcode"
            elif key_value and (err := await _check_key(self.hass, key_value)):
                errors[CONF_DHL_API_KEY] = err
            elif user and not password:
                errors["base"] = "imap_password_missing"
            elif (
                user
                and login_changed
                and (err := await _check_mailbox(self.hass, host, user, password))
            ):
                errors["base"] = err
            else:
                new_options = {
                    CONF_POSTCODE: postcode,
                    CONF_KEEP_DELIVERED_DAYS: int(user_input[CONF_KEEP_DELIVERED_DAYS]),
                    CONF_IMAP_HOST: host,
                    CONF_IMAP_USER: user,
                    CONF_MOVE_PROCESSED: bool(
                        mail.get(CONF_MOVE_PROCESSED, DEFAULT_MOVE_PROCESSED)
                    ),
                    CONF_READ_OTP: bool(mail.get(CONF_READ_OTP, DEFAULT_READ_OTP)),
                    CONF_MAIL_INTERVAL: int(mail.get(CONF_MAIL_INTERVAL, DEFAULT_MAIL_INTERVAL)),
                }
                data = dict(self.config_entry.data)
                if key_value:
                    data[CONF_DHL_API_KEY] = key_value
                if user and new_password:
                    data[CONF_IMAP_PASSWORD] = new_password
                if not user:
                    data.pop(CONF_IMAP_PASSWORD, None)  # mail import off: drop the secret
                if data != self.config_entry.data:
                    # Update data and options together so this is a single reload,
                    # not one from async_update_entry and another from the options save.
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=data, options=new_options
                    )
                return self.async_create_entry(data=new_options)
        shown = {**current, **(user_input or {})}
        mail_shown = {**current, **((user_input or {}).get(CONF_MAIL_SECTION) or {})}
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                shown,
                True,
                suggested_postcode=shown.get(CONF_POSTCODE, ""),
                mail=mail_shown,
            ),
            errors=errors,
        )

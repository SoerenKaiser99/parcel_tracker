"""Config flow for Paket Tracker."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .carriers.base import CarrierUnavailable
from .carriers.dhl import DhlCarrier
from .const import (
    CONF_DHL_API_KEY,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_POSTCODE,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DEFAULT_POSTCODE,
    DOMAIN,
    MAX_KEEP_DELIVERED_DAYS,
    MIN_KEEP_DELIVERED_DAYS,
)

_POSTCODE = re.compile(r"^\d{5}$")
_KEY = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_DAYS = NumberSelector(
    NumberSelectorConfig(
        min=MIN_KEEP_DELIVERED_DAYS, max=MAX_KEEP_DELIVERED_DAYS, mode=NumberSelectorMode.BOX
    )
)


def _schema(
    defaults: Mapping[str, Any], with_key: bool, suggested_postcode: str | None = None
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
    """Change key, postcode, keep days.

    The DHL key is stored in the config entry's ``data`` (the same place
    reauth writes it) so the two flows never disagree about which key is
    current. Only postcode and keep-days live in ``options``.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            postcode = _validate_postcode(user_input)
            if postcode and not _POSTCODE.match(postcode):
                errors[CONF_POSTCODE] = "invalid_postcode"
            else:
                # Only validate if a non-empty key was provided
                key_value = (user_input.get(CONF_DHL_API_KEY) or "").strip()
                if key_value and (err := await _check_key(self.hass, key_value)):
                    errors[CONF_DHL_API_KEY] = err
                elif not errors:
                    new_options = {
                        CONF_POSTCODE: postcode,
                        CONF_KEEP_DELIVERED_DAYS: int(user_input[CONF_KEEP_DELIVERED_DAYS]),
                    }
                    if key_value:
                        # Update data and options together so this is a single reload,
                        # not one from async_update_entry and another from the options save.
                        self.hass.config_entries.async_update_entry(
                            self.config_entry,
                            data={**self.config_entry.data, CONF_DHL_API_KEY: key_value},
                            options=new_options,
                        )
                    return self.async_create_entry(data=new_options)
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                user_input or current,
                True,
                suggested_postcode=(user_input or current).get(CONF_POSTCODE, ""),
            ),
            errors=errors,
        )

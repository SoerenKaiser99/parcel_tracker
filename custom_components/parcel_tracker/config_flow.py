"""Config flow for Paket Tracker."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback, split_entity_id, valid_entity_id
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util.ssl import client_context

from .carriers.base import AuthError, CarrierError, CarrierUnavailable
from .carriers.dhl import DhlCarrier
from .carriers.track17 import Track17Client
from .carriers.ups import ApiBudget, UpsCarrier
from .const import (
    CONF_COUNTRY,
    CONF_DHL_API_KEY,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_ENABLED,
    CONF_MAIL_INTERVAL,
    CONF_MAIL_SECTION,
    CONF_MOVE_PROCESSED,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_SECTION,
    CONF_NOTIFY_TARGETS,
    CONF_POSTCODE,
    CONF_READ_OTP,
    CONF_TRACK17_API_KEY,
    CONF_UPS_BUDGET,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    CONF_UPS_ENABLED,
    CONF_UPS_SECTION,
    COUNTRIES,
    DEFAULT_IMAP_HOST,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DEFAULT_MAIL_INTERVAL,
    DEFAULT_MOVE_PROCESSED,
    DEFAULT_NOTIFY_EVENTS,
    DEFAULT_POSTCODE,
    DEFAULT_READ_OTP,
    DEFAULT_UPS_BUDGET,
    DOMAIN,
    MAX_KEEP_DELIVERED_DAYS,
    MAX_MAIL_INTERVAL,
    MAX_UPS_BUDGET,
    MIN_KEEP_DELIVERED_DAYS,
    MIN_MAIL_INTERVAL,
    MIN_UPS_BUDGET,
    NOTIFY_EVENTS,
    NOTIFY_SERVICE_ALL,
    POSTCODE_DIGITS,
    entry_country,
    known_country,
)
from .mail.imap import ImapAuthError, ImapUnavailable, MailboxClient
from .notification import service_name, service_target

_COUNTRY = SelectSelector(
    SelectSelectorConfig(
        options=list(COUNTRIES), mode=SelectSelectorMode.DROPDOWN, translation_key="country"
    )
)
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

_BUDGET = NumberSelector(
    NumberSelectorConfig(min=MIN_UPS_BUDGET, max=MAX_UPS_BUDGET, mode=NumberSelectorMode.BOX)
)

# Selector option labels cannot be translated; the integration is German.
_SERVICE_LABEL = "Dienst notify.{}"
_GONE_LABEL = "{} (nicht mehr vorhanden)"
_NOTIFY_EVENTS = SelectSelector(
    SelectSelectorConfig(
        options=list(NOTIFY_EVENTS),
        multiple=True,
        mode=SelectSelectorMode.LIST,
        translation_key="notify_events",
    )
)


def _is_target(value: object) -> bool:
    """A notify entity ID ("notify.tablet") or a classic service ("service:pushover")."""
    if service_name(value) is not None:
        return True
    return (
        isinstance(value, str)
        and valid_entity_id(value)
        and split_entity_id(value)[0] == "notify"
    )


def _stored_targets(current: Mapping[str, Any]) -> list[str]:
    """The stored targets; anything that can be no target is left out.

    Whether a target exists in Home Assistant right now does not matter here.
    """
    stored = current.get(CONF_NOTIFY_TARGETS)
    if not isinstance(stored, (list, tuple)):
        return []
    return [target for target in stored if _is_target(target)]


def _available_targets(hass: HomeAssistant) -> list[SelectOptionDict]:
    """What can be notified right now: the notify entities by their name, then the
    classic services registered under ``notify`` (``notify.notify`` last).

    A classic service and an entity of the same integration are both listed: there
    is no reliable way to tell that they reach the same device, and the label says
    which kind each one is.
    """
    entities = sorted(
        hass.states.async_all("notify"),
        key=lambda state: (state.name.casefold(), state.entity_id),
    )
    services = sorted(
        (
            name
            for name in hass.services.async_services_for_domain("notify")
            # only what can be stored as a target and found again when notifying
            if service_name(service_target(name)) is not None
        ),
        key=lambda name: (name == NOTIFY_SERVICE_ALL, name),
    )
    return [
        *(SelectOptionDict(value=state.entity_id, label=state.name) for state in entities),
        *(
            SelectOptionDict(value=service_target(name), label=_SERVICE_LABEL.format(name))
            for name in services
        ),
    ]


def _targets_selector(
    available: Sequence[SelectOptionDict], chosen: Sequence[str]
) -> SelectSelector:
    """One multi-select of everything on offer plus the chosen targets that are gone.

    A chosen (stored) target that does not exist (any more) stays in the list,
    labelled as such: otherwise the prefilled form would not pass its own validation
    and an untouched save would fail. It is only dropped when the user unticks it.
    """
    options = list(available)
    known = {option["value"] for option in options}
    for target in dict.fromkeys(chosen):
        if target in known:
            continue
        name = service_name(target)
        label = _SERVICE_LABEL.format(name) if name is not None else target
        options.append(SelectOptionDict(value=target, label=_GONE_LABEL.format(label)))
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            multiple=True,
            custom_value=False,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _stored_events(current: Mapping[str, Any]) -> list[str]:
    """The stored events in their fixed order; the defaults if nothing usable is stored."""
    stored = current.get(CONF_NOTIFY_EVENTS, DEFAULT_NOTIFY_EVENTS)
    if not isinstance(stored, (list, tuple)):
        return list(DEFAULT_NOTIFY_EVENTS)
    return [event for event in NOTIFY_EVENTS if event in stored]


def _notify_section(
    current: Mapping[str, Any], available: Sequence[SelectOptionDict] = ()
) -> section:
    """Collapsible 'notifications' block of the options form.

    Both lists are prefilled through ``default`` with the stored value, so an
    untouched form sends back what is stored. No targets = notifications off;
    the explicit ``notify_enabled`` switch empties them as well, in case a
    frontend leaves an emptied selection out of what it sends.
    """
    targets = _stored_targets(current)
    return section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_NOTIFY_ENABLED,
                    default=bool(current.get(CONF_NOTIFY_ENABLED, bool(targets))),
                ): bool,
                vol.Optional(CONF_NOTIFY_TARGETS, default=targets): _targets_selector(
                    available, targets
                ),
                vol.Optional(CONF_NOTIFY_EVENTS, default=_stored_events(current)): _NOTIFY_EVENTS,
            }
        ),
        {"collapsed": not targets},
    )


def _ups_section(current: Mapping[str, Any]) -> section:
    """Collapsible 'UPS live status' block of the options form.

    The client ID is prefilled through ``default`` (never ``suggested_value``): a
    field the frontend leaves out or sends empty then comes back as the stored ID.
    Switching the API off is the explicit ``ups_enabled`` switch.
    """
    client_id = current.get(CONF_UPS_CLIENT_ID) or ""
    return section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_UPS_ENABLED,
                    default=bool(current.get(CONF_UPS_ENABLED, bool(client_id))),
                ): bool,
                vol.Optional(CONF_UPS_CLIENT_ID, default=client_id or vol.UNDEFINED): str,
                vol.Optional(CONF_UPS_CLIENT_SECRET): _KEY,
                vol.Optional(
                    CONF_UPS_BUDGET, default=current.get(CONF_UPS_BUDGET, DEFAULT_UPS_BUDGET)
                ): _BUDGET,
            }
        ),
        {"collapsed": not current.get(CONF_UPS_CLIENT_ID)},
    )


def _mail_section(current: Mapping[str, Any]) -> section:
    """Collapsible 'mail import' block of the options form.

    The user is prefilled through ``default`` (never ``suggested_value``): a field
    the frontend leaves out or sends empty then comes back as the stored user.
    Switching the import off is the explicit ``mail_enabled`` switch.
    """
    user = current.get(CONF_IMAP_USER) or ""
    return section(
        vol.Schema(
            {
                vol.Optional(
                    CONF_MAIL_ENABLED, default=bool(current.get(CONF_MAIL_ENABLED, bool(user)))
                ): bool,
                vol.Optional(
                    CONF_IMAP_HOST, default=current.get(CONF_IMAP_HOST) or DEFAULT_IMAP_HOST
                ): str,
                vol.Optional(CONF_IMAP_USER, default=user or vol.UNDEFINED): str,
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
    ups: Mapping[str, Any] | None = None,
    track17: bool = False,
    notify: Mapping[str, Any] | None = None,
    notify_available: Sequence[SelectOptionDict] = (),
) -> vol.Schema:
    fields: dict = {}
    if with_key:
        fields[vol.Optional(CONF_DHL_API_KEY)] = _KEY
    if track17:
        fields[vol.Optional(CONF_TRACK17_API_KEY)] = _KEY
    fields[
        vol.Optional(CONF_COUNTRY, default=known_country(defaults.get(CONF_COUNTRY)))
    ] = _COUNTRY
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
    # No ``default`` on the section markers: with one, the frontend starts from
    # that (empty) dict and never prefills the fields inside the section.
    if mail is not None:
        fields[vol.Optional(CONF_MAIL_SECTION)] = _mail_section(mail)
    if ups is not None:
        fields[vol.Optional(CONF_UPS_SECTION)] = _ups_section(ups)
    if notify is not None:
        fields[vol.Optional(CONF_NOTIFY_SECTION)] = _notify_section(notify, notify_available)
    return vol.Schema(fields)


def _validate_postcode(user_input: dict[str, Any]) -> str:
    """Return the stripped postcode; caller checks non-empty values with `_postcode_error`."""
    return (user_input.get(CONF_POSTCODE) or "").strip()


def _postcode_error(postcode: str, country: str) -> str | None:
    """Error code for a postcode that does not fit the country, else None.

    Germany has 5 digits (``invalid_postcode``), Austria and Switzerland have 4
    (``invalid_postcode_4``); the error text names the length.
    """
    digits = POSTCODE_DIGITS[country]
    if re.fullmatch(rf"[0-9]{{{digits}}}", postcode):
        return None
    return "invalid_postcode" if digits == 5 else f"invalid_postcode_{digits}"


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


async def _check_ups(hass, client_id: str, secret: str) -> str | None:
    """Ask UPS for a token (no tracking call, no budget); return an error code or None."""
    carrier = UpsCarrier(async_get_clientsession(hass), client_id, secret, ApiBudget(), 1)
    try:
        ok = await carrier.validate()
    except CarrierError:
        return "ups_cannot_connect"
    return None if ok else "ups_auth"


async def _check_track17(hass, key: str) -> str | None:
    """Ask 17track for the quota (costs nothing); return an error code or None."""
    try:
        await Track17Client(async_get_clientsession(hass), key).getquota()
    except AuthError:
        return "track17_invalid_key"
    except CarrierError:
        return "track17_cannot_connect"
    return None


class ParcelTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors: dict[str, str] = {}
        # Prefilled with the country of Home Assistant if it is one on offer.
        suggested = known_country(self.hass.config.country)
        if user_input is not None:
            key_value = (user_input.get(CONF_DHL_API_KEY) or "").strip()
            postcode = _validate_postcode(user_input)
            country = known_country(user_input.get(CONF_COUNTRY) or suggested)
            if postcode and (err := _postcode_error(postcode, country)):
                errors[CONF_POSTCODE] = err
            elif err := await _check_key(self.hass, key_value):
                errors[CONF_DHL_API_KEY] = err
            else:
                if CONF_DHL_API_KEY in user_input:
                    user_input[CONF_DHL_API_KEY] = key_value
                user_input[CONF_COUNTRY] = country
                user_input[CONF_POSTCODE] = postcode
                user_input[CONF_KEEP_DELIVERED_DAYS] = int(user_input[CONF_KEEP_DELIVERED_DAYS])
                return self.async_create_entry(title="Paket Tracker", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema({CONF_COUNTRY: suggested, **(user_input or {})}, True),
            errors=errors,
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
    """Change keys, country, postcode, keep days, the mail import, the UPS API, the 17track key
    and the push notifications.

    Secrets (DHL key, 17track key, IMAP password, UPS client ID and secret) are stored in the
    config entry's ``data`` (the same place reauth writes the key) so flows never
    disagree about which secret is current. Everything else lives in ``options``.

    A field that is missing or empty in the submitted form means "unchanged": the
    frontend omits emptied optional fields and has sent sections without their
    prefilled values, so nothing stored may depend on a field arriving. The mail
    import and the UPS API are only removed through their explicit switches
    (``mail_enabled``/``ups_enabled`` submitted as False). The postcode is the one
    exception: it is not a secret and emptying it is how it is removed.

    The country (``DE``, ``AT``, ``CH``) decides how many digits the postcode has; the
    postcode is checked against the country submitted with it, so a stored postcode
    that no longer fits a changed country is a form error and never dropped silently.
    An entry without a stored country behaves as Germany and shows Germany; the
    country is only written to the options once it is stored there or was changed.

    Notifications are on while targets are stored. A submitted empty list of
    targets switches them off, as does ``notify_enabled`` submitted as False; a
    missing list keeps the stored one. Switching them on without any target is
    a form error (``notify_no_target``). Targets are notify entities (stored as
    their entity ID) and classic notify services (stored as ``service:<name>``);
    only what the form offered can be chosen. A stored target that does not exist
    (any more) stays on offer and stored until it is unticked, and is skipped when
    sending.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        stored_country = entry_country(self.config_entry)
        if user_input is not None:
            options = self.config_entry.options
            mail = user_input.get(CONF_MAIL_SECTION) or {}
            stored_host = options.get(CONF_IMAP_HOST) or DEFAULT_IMAP_HOST
            stored_user = options.get(CONF_IMAP_USER) or ""
            # Off only on an explicit "False" while an import is set up; a user
            # typed into a not yet configured form sets the import up either way.
            mail_off = mail.get(CONF_MAIL_ENABLED) is False and bool(stored_user)
            host = (mail.get(CONF_IMAP_HOST) or "").strip() or stored_host
            user = "" if mail_off else (mail.get(CONF_IMAP_USER) or "").strip() or stored_user
            new_password = mail.get(CONF_IMAP_PASSWORD) or ""
            stored_password = self.config_entry.data.get(CONF_IMAP_PASSWORD, "")
            password = new_password or stored_password
            # Only log in again when the login data changed, so saving e.g. the
            # postcode works while the mail server is down.
            login_changed = (
                host != stored_host
                or user != stored_user
                or (bool(new_password) and new_password != stored_password)
            )
            ups = user_input.get(CONF_UPS_SECTION) or {}
            stored_id = self.config_entry.data.get(CONF_UPS_CLIENT_ID) or ""
            ups_off = ups.get(CONF_UPS_ENABLED) is False and bool(stored_id)
            ups_id = "" if ups_off else (ups.get(CONF_UPS_CLIENT_ID) or "").strip() or stored_id
            new_secret = (ups.get(CONF_UPS_CLIENT_SECRET) or "").strip()
            stored_secret = self.config_entry.data.get(CONF_UPS_CLIENT_SECRET, "")
            ups_secret = new_secret or stored_secret
            # Only ask UPS again when ID or secret changed (saving works while UPS is down).
            ups_changed = ups_id != stored_id or (
                bool(new_secret) and new_secret != stored_secret
            )
            notify = user_input.get(CONF_NOTIFY_SECTION) or {}
            stored_targets = _stored_targets(options)
            # Off only on an explicit "False" while targets are stored; targets picked
            # in a form that had none yet switch the notifications on either way.
            notify_off = notify.get(CONF_NOTIFY_ENABLED) is False and bool(stored_targets)
            if notify_off:
                targets: list[str] = []
            elif isinstance(notify.get(CONF_NOTIFY_TARGETS), list):
                targets = list(dict.fromkeys(notify[CONF_NOTIFY_TARGETS]))
            else:
                targets = stored_targets
            # Switched on in a form that had no targets, and none chosen.
            notify_no_target = (
                notify.get(CONF_NOTIFY_ENABLED) is True and not stored_targets and not targets
            )
            if isinstance(notify.get(CONF_NOTIFY_EVENTS), list):
                chosen = set(notify[CONF_NOTIFY_EVENTS])
                events = [event for event in NOTIFY_EVENTS if event in chosen]
            else:
                events = _stored_events(options)
            postcode = _validate_postcode(user_input)
            key_value = (user_input.get(CONF_DHL_API_KEY) or "").strip()
            track17_key = (user_input.get(CONF_TRACK17_API_KEY) or "").strip()
            country = known_country(user_input.get(CONF_COUNTRY) or stored_country)
            if postcode and (err := _postcode_error(postcode, country)):
                errors[CONF_POSTCODE] = err
            elif notify_no_target:
                errors["base"] = "notify_no_target"
            elif key_value and (err := await _check_key(self.hass, key_value)):
                errors[CONF_DHL_API_KEY] = err
            elif track17_key and (err := await _check_track17(self.hass, track17_key)):
                errors[CONF_TRACK17_API_KEY] = err
            elif user and not password:
                errors["base"] = "imap_password_missing"
            elif (
                user
                and login_changed
                and (err := await _check_mailbox(self.hass, host, user, password))
            ):
                errors["base"] = err
            elif ups_id and not ups_secret:
                errors["base"] = "ups_secret_missing"
            elif (
                ups_id
                and ups_changed
                and (err := await _check_ups(self.hass, ups_id, ups_secret))
            ):
                errors["base"] = err
            else:
                # A setting missing from the form keeps its stored value.
                new_options = {
                    CONF_POSTCODE: postcode,
                    CONF_KEEP_DELIVERED_DAYS: int(user_input[CONF_KEEP_DELIVERED_DAYS]),
                    CONF_IMAP_HOST: host,
                    CONF_IMAP_USER: user,
                    CONF_MOVE_PROCESSED: bool(
                        mail.get(
                            CONF_MOVE_PROCESSED,
                            options.get(CONF_MOVE_PROCESSED, DEFAULT_MOVE_PROCESSED),
                        )
                    ),
                    CONF_READ_OTP: bool(
                        mail.get(CONF_READ_OTP, options.get(CONF_READ_OTP, DEFAULT_READ_OTP))
                    ),
                    CONF_MAIL_INTERVAL: int(
                        mail.get(
                            CONF_MAIL_INTERVAL,
                            options.get(CONF_MAIL_INTERVAL, DEFAULT_MAIL_INTERVAL),
                        )
                    ),
                    CONF_UPS_BUDGET: int(
                        ups.get(CONF_UPS_BUDGET, options.get(CONF_UPS_BUDGET, DEFAULT_UPS_BUDGET))
                    ),
                    CONF_NOTIFY_TARGETS: targets,
                    CONF_NOTIFY_EVENTS: events,
                }
                if CONF_COUNTRY in options or country != stored_country:
                    new_options[CONF_COUNTRY] = country
                data = dict(self.config_entry.data)
                if key_value:
                    data[CONF_DHL_API_KEY] = key_value
                if track17_key:
                    data[CONF_TRACK17_API_KEY] = track17_key
                if user and new_password:
                    data[CONF_IMAP_PASSWORD] = new_password
                if mail_off:  # switched off explicitly: drop the secret
                    data.pop(CONF_IMAP_PASSWORD, None)
                if ups_id:
                    data[CONF_UPS_CLIENT_ID] = ups_id
                    if new_secret:
                        data[CONF_UPS_CLIENT_SECRET] = new_secret
                if ups_off:  # switched off explicitly: drop ID and secret
                    data.pop(CONF_UPS_CLIENT_ID, None)
                    data.pop(CONF_UPS_CLIENT_SECRET, None)
                if data != self.config_entry.data:
                    # Update data and options together so this is a single reload,
                    # not one from async_update_entry and another from the options save.
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=data, options=new_options
                    )
                return self.async_create_entry(data=new_options)
        shown = {**current, CONF_COUNTRY: stored_country, **(user_input or {})}
        mail_shown = {**current, **((user_input or {}).get(CONF_MAIL_SECTION) or {})}
        ups_shown = {**current, **((user_input or {}).get(CONF_UPS_SECTION) or {})}
        notify_shown = {**current, **((user_input or {}).get(CONF_NOTIFY_SECTION) or {})}
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                shown,
                True,
                suggested_postcode=shown.get(CONF_POSTCODE, ""),
                mail=mail_shown,
                ups=ups_shown,
                track17=True,
                notify=notify_shown,
                notify_available=_available_targets(self.hass),
            ),
            errors=errors,
        )

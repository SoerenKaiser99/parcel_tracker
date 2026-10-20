"""Config flow for Paket Tracker."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback, split_entity_id, valid_entity_id
from homeassistant.data_entry_flow import section
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
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
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import slugify
from homeassistant.util.ssl import client_context, client_context_no_verify

from .carriers.base import AuthError, CarrierError, CarrierUnavailable
from .carriers.dhl import DhlCarrier
from .carriers.track17 import Track17Client
from .carriers.ups import ApiBudget, UpsCarrier
from .const import (
    CONF_ADDRESSES,
    CONF_CONFIGURED_PERSON,
    CONF_COUNTRY,
    CONF_DEFAULT_OWNER,
    CONF_DHL_API_KEY,
    CONF_GIFT_SECTION,
    CONF_GIFT_VIEWERS,
    CONF_HIDE_NAMES,
    CONF_IMAP_FOLDER,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_PORT,
    CONF_IMAP_SECURITY,
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
    CONF_PERSON,
    CONF_PERSONS,
    CONF_PLAIN_NAMES,
    CONF_POSTCODE,
    CONF_READ_OTP,
    CONF_REMOVE_PERSON,
    CONF_SHARED_ADDRESSES,
    CONF_TRACK17_API_KEY,
    CONF_UPS_BUDGET,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    CONF_UPS_ENABLED,
    CONF_UPS_SECTION,
    COUNTRIES,
    DEFAULT_GIFT_VIEWERS,
    DEFAULT_HIDE_NAMES,
    DEFAULT_IMAP_FOLDER,
    DEFAULT_IMAP_HOST,
    DEFAULT_IMAP_PORT,
    DEFAULT_IMAP_SECURITY,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DEFAULT_MAIL_INTERVAL,
    DEFAULT_MOVE_PROCESSED,
    DEFAULT_NOTIFY_EVENTS,
    DEFAULT_OWNER,
    DEFAULT_PLAIN_NAMES,
    DEFAULT_POSTCODE,
    DEFAULT_READ_OTP,
    DEFAULT_UPS_BUDGET,
    DOMAIN,
    IMAP_SECURITIES,
    IMAP_SECURITY_NOVERIFY,
    IMAP_SECURITY_PLAIN,
    MAX_IMAP_PORT,
    MAX_KEEP_DELIVERED_DAYS,
    MAX_MAIL_INTERVAL,
    MAX_UPS_BUDGET,
    MIN_IMAP_PORT,
    MIN_KEEP_DELIVERED_DAYS,
    MIN_MAIL_INTERVAL,
    MIN_UPS_BUDGET,
    NOTIFY_APP_SERVICE_PREFIX,
    NOTIFY_EVENTS,
    NOTIFY_SERVICE_ALL,
    POSTCODE_DIGITS,
    entry_country,
    known_country,
)
from .mail.imap import (
    ImapAuthError,
    ImapCertificateError,
    ImapFolderNotFound,
    ImapLoginDisabled,
    ImapUnavailable,
    MailboxClient,
    clean_folder,
    clean_port,
    clean_security,
    is_reserved_folder,
)
from .models import PersonConfig, person_configs, shared_addresses
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
_PORT = NumberSelector(
    NumberSelectorConfig(min=MIN_IMAP_PORT, max=MAX_IMAP_PORT, mode=NumberSelectorMode.BOX)
)
_SECURITY = SelectSelector(
    SelectSelectorConfig(
        options=list(IMAP_SECURITIES),
        mode=SelectSelectorMode.DROPDOWN,
        translation_key="imap_security",
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


_PERSON_PICK = EntitySelector(EntitySelectorConfig(domain="person"))
_ADDRESSES = TextSelector(TextSelectorConfig(multiline=True))
_REMOVE = BooleanSelector()
# Enough to catch a name or a typo without "@"; the mail server decides the rest.
_ADDRESS = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_ALL_LABEL = "allen"
# Behind a person set up here that Home Assistant no longer has (translated, see
# ``_stale_hint``); this English text only if the translation cannot be read.
_STALE_KEY = f"component.{DOMAIN}.selector.configured_person.options.stale"
_STALE_HINT = "no longer in Home Assistant"


async def _stale_hint(hass: HomeAssistant) -> str:
    """The hint behind a person that is gone, in Home Assistant's language."""
    texts = await async_get_translations(hass, hass.config.language, "selector", {DOMAIN})
    return texts.get(_STALE_KEY) or _STALE_HINT


def _addresses(text: str) -> list[str]:
    """One address per line: trimmed, lower case, empty lines and repeats dropped."""
    lines = (line.strip().lower() for line in text.splitlines())
    return list(dict.fromkeys(line for line in lines if line))


def _person_name(hass: HomeAssistant, person: str) -> str:
    state = hass.states.get(person)
    return state.name if state is not None else person


def _suggested_targets(hass: HomeAssistant, person: str, offered: set[str]) -> list[str]:
    """The notify targets of the phones the person is tracked by (``device_trackers``
    of her state): a notify entity of the tracker's device, else the classic service
    ``notify.mobile_app_<device name>`` of the Home Assistant app. Only what the form
    offers is suggested."""
    state = hass.states.get(person)
    trackers = state.attributes.get("device_trackers") if state is not None else None
    if not isinstance(trackers, list):
        return []
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    found: list[str] = []
    for tracker in trackers:
        entry = entities.async_get(tracker) if isinstance(tracker, str) else None
        if entry is None or entry.device_id is None:
            continue
        notify = sorted(
            item.entity_id
            for item in er.async_entries_for_device(entities, entry.device_id)
            if item.domain == "notify" and item.entity_id in offered
        )
        if notify:
            found.extend(notify)
            continue
        device = devices.async_get(entry.device_id)
        for name in (device.name, device.name_by_user) if device is not None else ():
            service = NOTIFY_APP_SERVICE_PREFIX + slugify(name or "")
            if name and service_target(service) in offered:
                found.append(service_target(service))
                break
    return list(dict.fromkeys(found))


def _with_owner(options: dict[str, Any], owner: object) -> dict[str, Any]:
    """Store "Unklare Pakete gehören" only when it is a person set up in ``options``."""
    if owner != DEFAULT_OWNER and owner in {p.person for p in person_configs(options)}:
        options[CONF_DEFAULT_OWNER] = owner
    else:
        options.pop(CONF_DEFAULT_OWNER, None)
    return options


def _with_shared(options: dict[str, Any], shared: list[str]) -> dict[str, Any]:
    """Store "Gemeinsame Adressen" only when there is one."""
    if shared:
        options[CONF_SHARED_ADDRESSES] = shared
    else:
        options.pop(CONF_SHARED_ADDRESSES, None)
    return options


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


def _stored_viewers(current: Mapping[str, Any]) -> list[str]:
    """The stored gift viewers (person entity IDs); nobody if nothing usable is stored."""
    stored = current.get(CONF_GIFT_VIEWERS, DEFAULT_GIFT_VIEWERS)
    if not isinstance(stored, (list, tuple)):
        return []
    return list(dict.fromkeys(v for v in stored if isinstance(v, str) and v))


def _gift_section(current: Mapping[str, Any]) -> section:
    """Collapsible 'gift mode' block of the options form: who may see gifts.

    Prefilled through ``default`` with the stored persons, so an untouched form
    sends back what is stored.
    """
    viewers = _stored_viewers(current)
    return section(
        vol.Schema(
            {
                vol.Optional(CONF_GIFT_VIEWERS, default=viewers): EntitySelector(
                    EntitySelectorConfig(domain="person", multiple=True)
                ),
            }
        ),
        {"collapsed": not viewers},
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


def _shown_folder(value: object) -> str:
    """The folder for the form: what is stored or was typed, INBOX if that is nothing."""
    return value.strip() if isinstance(value, str) and value.strip() else DEFAULT_IMAP_FOLDER


def _mail_section(current: Mapping[str, Any]) -> section:
    """Collapsible 'mail import' block of the options form.

    The user is prefilled through ``default`` (never ``suggested_value``): a field
    the frontend leaves out or sends empty then comes back as the stored user.
    Switching the import off is the explicit ``mail_enabled`` switch. The folder is
    prefilled the same way, with INBOX while none is stored; so are the port (993) and
    the kind of connection (TLS with a checked certificate).
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
                vol.Optional(
                    CONF_IMAP_PORT, default=clean_port(current.get(CONF_IMAP_PORT))
                ): _PORT,
                vol.Optional(
                    CONF_IMAP_SECURITY, default=clean_security(current.get(CONF_IMAP_SECURITY))
                ): _SECURITY,
                vol.Optional(CONF_IMAP_USER, default=user or vol.UNDEFINED): str,
                vol.Optional(CONF_IMAP_PASSWORD): _KEY,
                vol.Optional(
                    CONF_IMAP_FOLDER, default=_shown_folder(current.get(CONF_IMAP_FOLDER))
                ): str,
                vol.Optional(
                    CONF_MOVE_PROCESSED,
                    default=current.get(CONF_MOVE_PROCESSED, DEFAULT_MOVE_PROCESSED),
                ): bool,
                vol.Optional(
                    CONF_READ_OTP, default=current.get(CONF_READ_OTP, DEFAULT_READ_OTP)
                ): bool,
                vol.Optional(
                    CONF_PLAIN_NAMES,
                    default=current.get(CONF_PLAIN_NAMES, DEFAULT_PLAIN_NAMES) is True,
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
    hide_names: bool = False,
    gift: Mapping[str, Any] | None = None,
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
    if hide_names:
        # Prefilled through ``default``: an untouched form sends back what is stored.
        fields[
            vol.Optional(
                CONF_HIDE_NAMES,
                default=defaults.get(CONF_HIDE_NAMES, DEFAULT_HIDE_NAMES) is True,
            )
        ] = bool
    # No ``default`` on the section markers: with one, the frontend starts from
    # that (empty) dict and never prefills the fields inside the section.
    if mail is not None:
        fields[vol.Optional(CONF_MAIL_SECTION)] = _mail_section(mail)
    if ups is not None:
        fields[vol.Optional(CONF_UPS_SECTION)] = _ups_section(ups)
    if notify is not None:
        fields[vol.Optional(CONF_NOTIFY_SECTION)] = _notify_section(notify, notify_available)
    if gift is not None:
        fields[vol.Optional(CONF_GIFT_SECTION)] = _gift_section(gift)
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


def mailbox_context(security: str):
    """Home Assistant's shared TLS context for a kind of connection; None without TLS.

    Both are built when Home Assistant starts, so none is ever created (and no
    certificate loaded) in the event loop.
    """
    if security == IMAP_SECURITY_PLAIN:
        return None
    if security == IMAP_SECURITY_NOVERIFY:
        return client_context_no_verify()
    return client_context()


async def _check_mailbox(
    hass,
    host: str,
    user: str,
    password: str,
    folder: str = DEFAULT_IMAP_FOLDER,
    port: int = DEFAULT_IMAP_PORT,
    security: str = DEFAULT_IMAP_SECURITY,
) -> str | None:
    """Log in and select the folder to read; return an error code or None."""
    try:
        client = MailboxClient(
            host,
            user,
            password,
            ssl_context=mailbox_context(security),
            folder=folder,
            port=port,
            security=security,
        )
        await hass.async_add_executor_job(client.check_login)
    except ImapAuthError:
        return "imap_auth"
    except ImapFolderNotFound:  # a kind of "unavailable": asked for first
        return "folder_not_found"
    except ImapCertificateError:  # likewise
        return "imap_certificate"
    except ImapLoginDisabled:  # likewise; nothing of the login was sent
        return "imap_login_disabled"
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
    """A menu of two parts. "Einstellungen" (``settings``): keys, country, postcode, keep
    days, "Namen ausblenden", the mail import, the UPS API, the 17track key and the push
    notifications. "Personen" (``persons``): addresses and notify targets per person and
    who unclear parcels belong to; each part leaves the options of the other as they are.

    Secrets (DHL key, 17track key, IMAP password, UPS client ID and secret) are stored in the
    config entry's ``data`` (the same place reauth writes the key) so flows never
    disagree about which secret is current. Everything else lives in ``options``.

    A field that is missing or empty in the submitted form means "unchanged": the
    frontend omits emptied optional fields and has sent sections without their
    prefilled values, so nothing stored may depend on a field arriving. The mail
    import and the UPS API are only removed through their explicit switches
    (``mail_enabled``/``ups_enabled`` submitted as False). The postcode is the one
    exception: it is not a secret and emptying it is how it is removed.

    The folder of the mailbox that is read (``imap_folder``) is INBOX while none is
    stored; it is only written to the options once it is stored there or differs from
    INBOX. A changed folder is selected once on the mail server before it is stored
    (``folder_not_found``; never created), together with the login check when that is
    due anyway. The two folders mails are filed into are refused (``folder_reserved``).

    The port (``imap_port``) and the kind of connection (``imap_security``: ``ssl``,
    ``ssl_noverify``, ``plain``) of the mail server are 993 and ``ssl`` while none is
    stored; like the folder each is only written to the options once it is stored there
    or differs from that. Both are login data: a change runs the login check with the
    new values before anything is stored. Choosing ``plain`` never changes the port.

    The country (``de``, ``at``, ``ch``) decides how many digits the postcode has; the
    postcode is checked against the country submitted with it, so a stored postcode
    that no longer fits a changed country is a form error and never dropped silently.
    An entry without a stored country behaves as Germany and shows Germany; the
    country is only written to the options once it is stored there or was changed.

    "Namen ausblenden" (``hide_names``) is a plain switch. Missing from the submitted
    form, it keeps its stored value; like the country it is only written to the options
    once it is stored there or was switched on.

    Notifications are on while targets are stored. A submitted empty list of
    targets switches them off, as does ``notify_enabled`` submitted as False; a
    missing list keeps the stored one. Switching them on without any target is
    a form error (``notify_no_target``). Targets are notify entities (stored as
    their entity ID) and classic notify services (stored as ``service:<name>``);
    only what the form offered can be chosen. A stored target that does not exist
    (any more) stays on offer and stored until it is unticked, and is skipped when
    sending.
    """

    _person: str = ""
    _default_owner: str = DEFAULT_OWNER
    _shared: list[str] | None = None  # "Gemeinsame Adressen" as submitted on "persons"

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """A menu: the settings as before, or the persons."""
        return self.async_show_menu(step_id="init", menu_options=["settings", "persons"])

    async def async_step_persons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a person to set up (or none), choose who unclear parcels belong to and
        which addresses several persons share ("Gemeinsame Adressen").

        Without a person picked this saves both right away; an untouched form changes
        nothing. Shared addresses are one per line, stored trimmed and in lower case and
        only when there is one; an address of a person (``address_twice``) or without
        the shape of a mail address (``address_invalid``) is a form error.
        """
        errors: dict[str, str] = {}
        options = self.config_entry.options
        configs = person_configs(options)
        stored_shared = list(shared_addresses(options))
        shown_shared = "\n".join(stored_shared)
        # Persons removed from Home Assistant stay listed (to edit or remove them) but
        # are not offered for unclear parcels; such a stored choice is shown as "all".
        present = [c.person for c in configs if self.hass.states.get(c.person) is not None]
        stored_owner = options.get(CONF_DEFAULT_OWNER, DEFAULT_OWNER)
        if stored_owner not in present:
            stored_owner = DEFAULT_OWNER
        if user_input is not None:
            self._default_owner = user_input.get(CONF_DEFAULT_OWNER, stored_owner)
            text = user_input.get(CONF_SHARED_ADDRESSES)
            shared = _addresses(text) if isinstance(text, str) else stored_shared
            persons_addresses = {a for config in configs for a in config.addresses}
            if any(not _ADDRESS.fullmatch(a) for a in shared):
                errors[CONF_SHARED_ADDRESSES] = "address_invalid"
            elif any(a in persons_addresses for a in shared):
                errors[CONF_SHARED_ADDRESSES] = "address_twice"
            else:
                self._shared = shared
                for key in (CONF_CONFIGURED_PERSON, CONF_PERSON):
                    person = user_input.get(key)
                    if isinstance(person, str) and person:
                        self._person = person
                        return await self.async_step_person()
                return self.async_create_entry(
                    data=_with_shared(_with_owner(dict(options), self._default_owner), shared)
                )
            shown_shared = text if isinstance(text, str) else shown_shared
            if self._default_owner in (DEFAULT_OWNER, *present):
                stored_owner = self._default_owner
        owners = [SelectOptionDict(value=DEFAULT_OWNER, label=_ALL_LABEL)] + [
            SelectOptionDict(value=person, label=_person_name(self.hass, person))
            for person in present
        ]
        fields: dict[Any, Any] = {}
        if configs:
            stale = (
                await _stale_hint(self.hass)
                if any(c.person not in present for c in configs)
                else _STALE_HINT
            )
            fields[vol.Optional(CONF_CONFIGURED_PERSON)] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(
                            value=c.person,
                            label=_person_name(self.hass, c.person)
                            if c.person in present
                            else f"{c.person} ({stale})",
                        )
                        for c in configs
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        fields[vol.Optional(CONF_PERSON)] = _PERSON_PICK
        return self.async_show_form(
            step_id="persons",
            data_schema=vol.Schema(
                {
                    **fields,
                    vol.Optional(CONF_DEFAULT_OWNER, default=stored_owner): SelectSelector(
                        SelectSelectorConfig(
                            options=owners,
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key=CONF_DEFAULT_OWNER,
                        )
                    ),
                    vol.Optional(CONF_SHARED_ADDRESSES, default=shown_shared): _ADDRESSES,
                }
            ),
            errors=errors,
        )

    async def async_step_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Addresses and notify targets of the picked person, or remove her.

        Addresses are one per line, stored trimmed and in lower case; an address of
        another person or a shared one (``address_twice``) or without the shape of a
        mail address (``address_invalid``) is a form error. Missing from the submitted form, the
        addresses and the targets keep their stored values. A person without
        addresses and targets is not stored. A new person gets the notify targets of
        her phones suggested.
        """
        errors: dict[str, str] = {}
        options = self.config_entry.options
        person = self._person
        configs = person_configs(options)
        stored = next((config for config in configs if config.person == person), None)
        available = _available_targets(self.hass)
        stored_addresses = list(stored.addresses) if stored is not None else []
        stored_targets = list(stored.notify_targets) if stored is not None else []
        if user_input is not None:
            text = user_input.get(CONF_ADDRESSES)
            addresses = _addresses(text) if isinstance(text, str) else stored_addresses
            chosen = user_input.get(CONF_NOTIFY_TARGETS)
            targets = list(dict.fromkeys(chosen)) if isinstance(chosen, list) else stored_targets
            shared = self._shared if self._shared is not None else list(shared_addresses(options))
            taken = {a for config in configs if config.person != person for a in config.addresses}
            taken.update(shared)
            remove = user_input.get(CONF_REMOVE_PERSON) is True
            if not remove and any(not _ADDRESS.fullmatch(a) for a in addresses):
                errors[CONF_ADDRESSES] = "address_invalid"
            elif not remove and any(a in taken for a in addresses):
                errors[CONF_ADDRESSES] = "address_twice"
            else:
                raw = options.get(CONF_PERSONS)
                entries = [
                    entry
                    for entry in (raw if isinstance(raw, list) else ())
                    if PersonConfig.from_option(entry) is not None
                ]
                if remove or not (addresses or targets):
                    entries = [entry for entry in entries if entry["person"] != person]
                else:
                    value = {
                        "person": person,
                        CONF_ADDRESSES: addresses,
                        CONF_NOTIFY_TARGETS: targets,
                    }
                    if any(entry["person"] == person for entry in entries):
                        entries = [
                            value if entry["person"] == person else entry for entry in entries
                        ]
                    else:
                        entries.append(value)
                new_options = dict(options)
                if entries:
                    new_options[CONF_PERSONS] = entries
                else:
                    new_options.pop(CONF_PERSONS, None)
                return self.async_create_entry(
                    data=_with_shared(_with_owner(new_options, self._default_owner), shared)
                )
        if user_input is not None:
            shown_addresses = user_input.get(CONF_ADDRESSES, "")
            shown_targets = user_input.get(CONF_NOTIFY_TARGETS, stored_targets)
        else:
            shown_addresses = "\n".join(stored_addresses)
            shown_targets = (
                stored_targets
                if stored is not None
                else _suggested_targets(
                    self.hass, person, {option["value"] for option in available}
                )
            )
        return self.async_show_form(
            step_id="person",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ADDRESSES, default=shown_addresses): _ADDRESSES,
                    vol.Optional(CONF_NOTIFY_TARGETS, default=shown_targets): _targets_selector(
                        available, shown_targets
                    ),
                    vol.Optional(CONF_REMOVE_PERSON, default=False): _REMOVE,
                }
            ),
            errors=errors,
            description_placeholders={"person": _person_name(self.hass, person)},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
            # Missing from the form: the stored port and kind of connection (993 and
            # the verifying TLS if there is none, or none that can be used).
            stored_port = clean_port(options.get(CONF_IMAP_PORT))
            port = clean_port(mail.get(CONF_IMAP_PORT, stored_port))
            stored_security = clean_security(options.get(CONF_IMAP_SECURITY))
            security = clean_security(mail.get(CONF_IMAP_SECURITY, stored_security))
            # Only log in again when the login data changed, so saving e.g. the
            # postcode works while the mail server is down.
            login_changed = (
                host != stored_host
                or user != stored_user
                or port != stored_port
                or security != stored_security
                or (bool(new_password) and new_password != stored_password)
            )
            # Missing or emptied: the stored folder (INBOX if there is none).
            stored_folder = clean_folder(options.get(CONF_IMAP_FOLDER))
            folder = clean_folder((mail.get(CONF_IMAP_FOLDER) or "").strip() or stored_folder)
            folder_changed = folder != stored_folder
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
            gift = user_input.get(CONF_GIFT_SECTION) or {}
            if isinstance(gift.get(CONF_GIFT_VIEWERS), list):
                viewers = _stored_viewers(gift)
            else:
                viewers = _stored_viewers(options)
            postcode = _validate_postcode(user_input)
            key_value = (user_input.get(CONF_DHL_API_KEY) or "").strip()
            track17_key = (user_input.get(CONF_TRACK17_API_KEY) or "").strip()
            country = known_country(user_input.get(CONF_COUNTRY) or stored_country)
            stored_plain = options.get(CONF_PLAIN_NAMES, DEFAULT_PLAIN_NAMES) is True
            plain_names = mail.get(CONF_PLAIN_NAMES, stored_plain) is True
            stored_hide = options.get(CONF_HIDE_NAMES, DEFAULT_HIDE_NAMES) is True
            hide = user_input.get(CONF_HIDE_NAMES, stored_hide) is True
            if postcode and (err := _postcode_error(postcode, country)):
                errors[CONF_POSTCODE] = err
            elif notify_no_target:
                errors["base"] = "notify_no_target"
            elif key_value and (err := await _check_key(self.hass, key_value)):
                errors[CONF_DHL_API_KEY] = err
            elif track17_key and (err := await _check_track17(self.hass, track17_key)):
                errors[CONF_TRACK17_API_KEY] = err
            elif folder_changed and is_reserved_folder(folder):
                errors["base"] = "folder_reserved"
            elif user and not password:
                errors["base"] = "imap_password_missing"
            elif (
                user
                and (login_changed or folder_changed)
                and (
                    err := await _check_mailbox(
                        self.hass, host, user, password, folder, port, security
                    )
                )
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
                # Set up under "Personen"; this form leaves them as they are.
                for key in (CONF_PERSONS, CONF_DEFAULT_OWNER, CONF_SHARED_ADDRESSES):
                    if key in options:
                        new_options[key] = options[key]
                if CONF_COUNTRY in options or country != stored_country:
                    new_options[CONF_COUNTRY] = country
                if CONF_HIDE_NAMES in options or hide:
                    new_options[CONF_HIDE_NAMES] = hide
                if CONF_GIFT_VIEWERS in options or viewers:
                    new_options[CONF_GIFT_VIEWERS] = viewers
                if CONF_PLAIN_NAMES in options or plain_names:
                    new_options[CONF_PLAIN_NAMES] = plain_names
                if CONF_IMAP_FOLDER in options or folder != DEFAULT_IMAP_FOLDER:
                    # An untouched form writes back exactly what is stored.
                    new_options[CONF_IMAP_FOLDER] = (
                        folder if folder_changed else options.get(CONF_IMAP_FOLDER, folder)
                    )
                if CONF_IMAP_PORT in options or port != DEFAULT_IMAP_PORT:
                    new_options[CONF_IMAP_PORT] = (
                        port if port != stored_port else options.get(CONF_IMAP_PORT, port)
                    )
                if CONF_IMAP_SECURITY in options or security != DEFAULT_IMAP_SECURITY:
                    new_options[CONF_IMAP_SECURITY] = (
                        security
                        if security != stored_security
                        else options.get(CONF_IMAP_SECURITY, security)
                    )
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
        gift_shown = {**current, **((user_input or {}).get(CONF_GIFT_SECTION) or {})}
        return self.async_show_form(
            step_id="settings",
            data_schema=_schema(
                shown,
                True,
                suggested_postcode=shown.get(CONF_POSTCODE, ""),
                mail=mail_shown,
                ups=ups_shown,
                track17=True,
                notify=notify_shown,
                notify_available=_available_targets(self.hass),
                hide_names=True,
                gift=gift_shown,
            ),
            errors=errors,
        )

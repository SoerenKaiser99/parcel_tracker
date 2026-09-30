"""Polling coordinator for Paket Tracker."""

from __future__ import annotations

import asyncio
import email
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email import policy

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .carriers.base import (
    AuthError,
    Carrier,
    CarrierUnavailable,
    MissingCredentials,
    NotFound,
    ParseError,
    RateLimited,
)
from .const import (
    AMAZON_UNRECOGNIZED_LIMIT,
    CARRIER_AUTO,
    CARRIER_BROKEN_AFTER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MOVE_PROCESSED,
    CONF_POSTCODE,
    CONF_READ_OTP,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DEFAULT_MOVE_PROCESSED,
    DEFAULT_READ_OTP,
    DHL_DAILY_SOFT_LIMIT,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    FOLDER_PROCESSED,
    FOLDER_UNRECOGNIZED,
    MAIL_INTERVAL,
    MAIL_MAX_AGE,
    MAIL_MAX_BACKOFF,
    TICK,
)
from .detect import candidates, normalize
from .mail import parse_mail
from .mail.apply import Change, apply_update
from .mail.base import MailResult, sent_at
from .mail.imap import ImapAuthError, ImapUnavailable, MailboxClient
from .models import Parcel
from .schedule import backoff, poll_interval, should_remove
from .store import ParcelStore

_LOGGER = logging.getLogger(__name__)


@dataclass
class _ParsedMail:
    """Outcome of parsing one raw mail in the executor."""

    message_id: str = ""
    stale: bool = False
    result: MailResult | None = None
    error: Exception | None = None


def _parse_one(raw: bytes, read_otp: bool, now: datetime) -> _ParsedMail:
    item = _ParsedMail()
    try:
        msg = email.message_from_bytes(raw, policy=policy.default)
        item.message_id = str(msg.get("Message-ID") or "").strip()
        try:
            item.stale = now - sent_at(msg) > MAIL_MAX_AGE
        except (TypeError, ValueError):
            item.stale = False  # no usable Date: let the parser decide
        if not item.stale:
            item.result = parse_mail(msg, read_otp)
    except Exception as err:  # noqa: BLE001 - reported per mail by the coordinator
        item.error = err
    return item


def _parse_mails(raws: list[bytes], read_otp: bool, now: datetime) -> list[_ParsedMail]:
    """Parse mails (blocking, runs in the executor)."""
    return [_parse_one(raw, read_otp, now) for raw in raws]


class ParcelCoordinator(DataUpdateCoordinator[dict[str, Parcel]]):
    """Ticks every minute and polls parcels that are due."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: ParcelStore,
        carriers: dict[str, Carrier],
        mailbox: MailboxClient | None = None,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=TICK, config_entry=entry
        )
        self.entry = entry
        self.store = store
        self.carriers = carriers
        self._events_enabled = False
        self._first_fail: dict[str, datetime] = {}
        self._dhl_day: date | None = None
        self._dhl_calls = 0
        self._lock = asyncio.Lock()
        self.mailbox = mailbox
        self._mail_lock = asyncio.Lock()  # one import at a time (tick vs. refresh service)
        self._mail_next: datetime | None = None
        self._mail_streak = 0
        self._amazon_misses = 0

    # ----- settings -----
    @property
    def _postcode(self) -> str | None:
        return self.entry.options.get(CONF_POSTCODE, self.entry.data.get(CONF_POSTCODE))

    @property
    def _keep_days(self) -> int:
        return self.entry.options.get(
            CONF_KEEP_DELIVERED_DAYS,
            self.entry.data.get(CONF_KEEP_DELIVERED_DAYS, DEFAULT_KEEP_DELIVERED_DAYS),
        )

    @property
    def _move_processed(self) -> bool:
        return self.entry.options.get(CONF_MOVE_PROCESSED, DEFAULT_MOVE_PROCESSED)

    @property
    def _read_otp(self) -> bool:
        return self.entry.options.get(CONF_READ_OTP, DEFAULT_READ_OTP)

    # ----- main loop -----
    async def _async_update_data(self) -> dict[str, Parcel]:
        async with self._lock:
            now = dt_util.utcnow()
            changed = self._cleanup(now)
            for parcel in list(self.store.parcels.values()):
                if parcel.poll_target is None:
                    continue  # mail-only carrier: status comes from mails
                if parcel.next_poll_at is None or parcel.next_poll_at <= now:
                    if parcel.status is not None and poll_interval(parcel.status, now) is None:
                        continue
                    await self._poll_safely(parcel, now)
                    changed = True
            if changed:
                await self.store.async_save()
        # Not during the first refresh: setup must not wait for the mailbox.
        if self._events_enabled:
            await self.async_import_mail()
        self._events_enabled = True
        return dict(self.store.parcels)

    def _cleanup(self, now: datetime) -> bool:
        removed = [
            n for n, p in self.store.parcels.items() if should_remove(p, now, self._keep_days)
        ]
        for number in removed:
            self.store.remove(number)
        today = dt_util.as_local(now).date()
        for parcel in self.store.parcels.values():
            if parcel.delivery_code and parcel.active_code(today) is None:
                parcel.delivery_code = parcel.delivery_code_day = None
        return bool(removed)

    # ----- mail import -----
    async def async_import_mail(self) -> None:
        """Fetch unseen mails, apply them to the parcels and file them away.

        Never raises: a broken mail import must not take down the parcel refresh.
        """
        if self.mailbox is None or self._mail_lock.locked():
            return
        async with self._mail_lock:
            now = dt_util.utcnow()
            if self._mail_next is not None and now < self._mail_next:
                return
            # Set before fetching, so a failure can't make the next tick try again at once.
            self._mail_next = now + MAIL_INTERVAL
            try:
                await self._import_mail(self.mailbox, now)
            except ImapAuthError:
                self._mail_failed(now)
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    "imap_auth",
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="imap_auth",
                )
            except ImapUnavailable as err:
                _LOGGER.debug("Parcel mailbox not reachable: %s", err)
                self._mail_failed(now)
            except Exception as err:  # noqa: BLE001 - isolate the import from the refresh
                # Only the error type: mail contents never go into the log.
                _LOGGER.warning("Mail import failed (%s); trying again later", type(err).__name__)
                self._mail_failed(now)

    async def _import_mail(self, mailbox: MailboxClient, now: datetime) -> None:
        mails = await self.hass.async_add_executor_job(mailbox.fetch_unseen)
        ir.async_delete_issue(self.hass, DOMAIN, "imap_auth")
        self._mail_streak = 0
        if not mails:
            return
        parsed = await self.hass.async_add_executor_job(
            _parse_mails, [raw for _, raw in mails], self._read_otp, now
        )
        async with self._lock:
            dispositions = [
                (uid, self._handle_mail(item, now))
                for (uid, _), item in zip(mails, parsed, strict=True)
            ]
            await self.store.async_save()
        try:
            await self.hass.async_add_executor_job(
                mailbox.finish, dispositions, self._move_processed
            )
        except (ImapAuthError, ImapUnavailable) as err:
            # Mails were fetched with PEEK and stay unseen; Message-ID dedup skips them next time.
            _LOGGER.debug("Could not file processed mails: %s", err)

    def _mail_failed(self, now: datetime) -> None:
        self._mail_streak += 1
        delay = min(MAIL_INTERVAL * 2 ** (self._mail_streak - 1), MAIL_MAX_BACKOFF)
        self._mail_next = now + delay

    def _handle_mail(self, item: _ParsedMail, now: datetime) -> str | None:
        """Apply one parsed mail; return its target folder (None = only mark seen)."""
        try:
            if item.message_id and not self.store.remember_message(item.message_id):
                return FOLDER_PROCESSED
            if item.stale:
                return None  # too old to say anything about today's parcels
            if item.error is not None:
                raise item.error
            result = item.result
            if result is None or result.ignored:
                return None
            if result.amazon:
                self._count_amazon(recognized=bool(result.updates))
            if not result.updates:
                return FOLDER_UNRECOGNIZED
            for update in result.updates:
                if change := apply_update(self.store.parcels, update, now):
                    self._mail_changed(change)
        except Exception as err:  # noqa: BLE001 - one odd mail must not stop the import
            # Only the error type: mail contents never go into the log.
            _LOGGER.warning(
                "Could not read a mail (%s); moved it to %s",
                type(err).__name__,
                FOLDER_UNRECOGNIZED,
            )
            return FOLDER_UNRECOGNIZED
        return FOLDER_PROCESSED

    def _count_amazon(self, recognized: bool) -> None:
        if recognized:
            self._amazon_misses = 0
            ir.async_delete_issue(self.hass, DOMAIN, "amazon_unrecognized")
            return
        self._amazon_misses += 1
        if self._amazon_misses >= AMAZON_UNRECOGNIZED_LIMIT:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "amazon_unrecognized",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="amazon_unrecognized",
            )

    def _mail_changed(self, change: Change) -> None:
        parcel = change.parcel
        if (
            self._events_enabled
            and change.old_status is not None
            and parcel.status is not None
            and change.old_status is not parcel.status
        ):
            self._fire(parcel, change.old_status)

    # ----- polling -----
    def _count_dhl(self, now: datetime) -> None:
        today = dt_util.as_local(now).date()
        if self._dhl_day != today:
            self._dhl_day, self._dhl_calls = today, 0
        self._dhl_calls += 1

    async def _poll_safely(self, parcel: Parcel, now: datetime) -> None:
        """Poll one parcel, never letting an unexpected error take down the refresh."""
        try:
            await self._poll(parcel, now)
        except Exception:  # noqa: BLE001 - isolate one bad parcel from the rest
            _LOGGER.exception("Unexpected error polling %s", parcel.number)
            self._fail(parcel, now, parcel.carrier or "unknown", "unavailable", backoff_only=True)

    async def _poll(self, parcel: Parcel, now: datetime) -> None:
        target = parcel.poll_target
        if target is None:
            return
        carrier_key, number = target
        if carrier_key:
            keys = [carrier_key] if carrier_key in self.carriers else []
        else:
            keys = candidates(number, self.carriers)
        parcel.last_poll_at = now
        if not keys:
            parcel.last_error = "carrier_not_found"
            parcel.next_poll_at = now + timedelta(hours=1)
            return
        last_error = "not_found"
        for key in keys:
            carrier = self.carriers[key]
            if key == "dhl":
                self._count_dhl(now)
            try:
                result = await carrier.fetch(number, self._postcode)
            except NotFound:
                continue
            except MissingCredentials:
                last_error = "missing_key"
                continue
            except AuthError:
                self._fail(parcel, now, key, "auth", backoff_only=True)
                if key == "dhl":
                    self._auth_issue()
                return
            except RateLimited as err:
                parcel.last_error = "rate_limited"
                parcel.next_poll_at = now + timedelta(seconds=err.retry_after or 3600)
                return
            except (CarrierUnavailable, ParseError) as err:
                _LOGGER.debug("%s failed for %s: %s", key, parcel.number, err)
                self._fail(parcel, now, key, "unavailable")
                return
            except Exception:  # noqa: BLE001 - never let one carrier bug break polling
                _LOGGER.exception("Unexpected error polling %s", parcel.number)
                self._fail(parcel, now, key, "unavailable", backoff_only=True)
                return
            else:
                self._success(parcel, now, key, result)
                return
        parcel.last_error = last_error
        parcel.next_poll_at = now + timedelta(hours=1)

    def _fail(
        self, parcel: Parcel, now: datetime, key: str, code: str, backoff_only: bool = False
    ) -> None:
        parcel.last_error = code
        parcel.error_streak += 1
        parcel.first_error_at = parcel.first_error_at or now
        parcel.next_poll_at = now + backoff(parcel.error_streak)
        if backoff_only:
            return
        first = self._first_fail.setdefault(key, now)
        if now - first >= CARRIER_BROKEN_AFTER:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"carrier_broken_{key}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="carrier_broken",
                translation_placeholders={"carrier": self.carriers[key].name},
            )

    def _success(self, parcel: Parcel, now: datetime, key: str, result) -> None:
        self._first_fail.pop(key, None)
        ir.async_delete_issue(self.hass, DOMAIN, f"carrier_broken_{key}")
        if key == "dhl":
            ir.async_delete_issue(self.hass, DOMAIN, "dhl_auth")
        old = parcel.status
        if parcel.carrier is None:
            parcel.carrier = key
        if parcel.result is None or parcel.result.to_dict() != result.to_dict():
            parcel.last_change_at = now
        parcel.result = result
        parcel.last_error = None
        parcel.error_streak = 0
        parcel.first_error_at = None
        interval = poll_interval(result.status, now)
        if interval and key == "dhl" and self._dhl_calls > DHL_DAILY_SOFT_LIMIT:
            interval *= 2
        parcel.next_poll_at = now + interval if interval else None
        if old is not None and old != result.status and self._events_enabled:
            self._fire(parcel, old)

    def _fire(self, parcel: Parcel, old) -> None:
        r = parcel.result
        self.hass.bus.async_fire(
            EVENT_STATUS_CHANGED,
            {
                "number": parcel.number,
                "name": parcel.name,
                "carrier": parcel.carrier,
                "old_status": old.value,
                "new_status": r.status.value,
                "eta_date": r.eta_date.isoformat() if r.eta_date else None,
                "eta_from": r.eta_from.isoformat() if r.eta_from else None,
                "eta_to": r.eta_to.isoformat() if r.eta_to else None,
                "location": r.location,
            },
        )

    def _auth_issue(self) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "dhl_auth",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="dhl_auth",
        )
        self.entry.async_start_reauth(self.hass)

    # ----- public API used by services -----
    async def async_add(self, number: str, carrier: str, name: str | None) -> Parcel:
        norm = normalize(number)
        keys = candidates(norm, self.carriers)  # raises UnsupportedNumber
        if carrier != CARRIER_AUTO and carrier not in self.carriers:
            raise ValueError("unknown_carrier")
        now = dt_util.utcnow()
        parcel = Parcel(
            number=norm,
            carrier=None if carrier == CARRIER_AUTO else carrier,
            carrier_mode="auto" if carrier == CARRIER_AUTO else "manual",
            name=(name or "").strip() or None,
            added_at=now,
            last_change_at=now,
        )
        async with self._lock:
            self.store.add(parcel)  # raises DuplicateParcel
            if parcel.carrier is None and not keys:
                parcel.last_error = "carrier_not_found"
                parcel.last_poll_at = now
                parcel.next_poll_at = now + timedelta(hours=1)
            else:
                await self._poll_safely(parcel, now)
            await self.store.async_save()
            self.async_set_updated_data(dict(self.store.parcels))
        return parcel

    async def async_remove(self, number: str) -> None:
        self.store.remove(normalize(number))
        await self.store.async_save()
        self.async_set_updated_data(dict(self.store.parcels))

    async def async_rename(self, number: str, name: str | None) -> None:
        parcel = self.store.parcels[normalize(number)]
        parcel.name = (name or "").strip() or None
        await self.store.async_save()
        self.async_set_updated_data(dict(self.store.parcels))

    async def async_refresh_parcels(self, number: str | None) -> None:
        targets = [self.store.parcels[normalize(number)]] if number else self.store.parcels.values()
        for parcel in targets:
            parcel.next_poll_at = None
        await self.async_refresh()

"""Polling coordinator for Paket Tracker."""

from __future__ import annotations

import asyncio
import email
import logging
from collections import deque
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from email import policy
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .carriers.base import (
    AuthError,
    Carrier,
    CarrierError,
    CarrierUnavailable,
    Match,
    MissingCredentials,
    NotFound,
    ParseError,
    RateLimited,
)
from .carriers.gls import gls_number, has_check_digit
from .carriers.track17 import (
    NotRegistered,
    Quota,
    QuotaExhausted,
    Track17Client,
    Track17Disabled,
    Track17Info,
    strip_enrichment,
    with_track17,
)
from .carriers.ups import BudgetExhausted, UpsCarrier, next_month_start
from .const import (
    AMAZON_UNRECOGNIZED_LIMIT,
    ANNOUNCE_MAX_WAIT,
    CARRIER_AUTO,
    CARRIER_BROKEN_AFTER,
    CARRIER_OTHER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_INTERVAL,
    CONF_MOVE_PROCESSED,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    CONF_POSTCODE,
    CONF_READ_OTP,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DEFAULT_MAIL_INTERVAL,
    DEFAULT_MOVE_PROCESSED,
    DEFAULT_NOTIFY_EVENTS,
    DEFAULT_READ_OTP,
    DHL_DAILY_SOFT_LIMIT,
    DHL_FALLBACK_TRIES,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    FOLDER_PROCESSED,
    FOLDER_UNRECOGNIZED,
    GLS_PROBE_TRIES,
    KEEP_ETA_UNTIL_DAY_CARRIERS,
    MAIL_ETA_CARRIERS,
    MAIL_INTERVAL,
    MAIL_MAX_AGE,
    MAIL_MAX_BACKOFF,
    NOTIFY_APP_SERVICE_PREFIX,
    NOTIFY_SERVICE_PREFIX,
    OPTIONAL_API_CARRIERS,
    TICK,
    TRACK17_CARRIER_CODES,
    TRACK17_FIRST_POLL,
    TRACK17_INTERVAL,
    TRACK17_QUOTA_INTERVAL,
    TRACK17_QUOTA_LOW,
    TRACK17_QUOTA_RETRY,
)
from .detect import candidates, normalize
from .mail import OTHER_DOMAIN, forwarded_original, known_sender_domain, parse_mail
from .mail.apply import Change, apply_update, close_unconfirmed, fold_delivered
from .mail.base import MailResult, is_forwarded, sender, sent_at
from .mail.imap import ImapAuthError, ImapUnavailable, MailboxClient
from .models import (
    NO_ETA_STATUSES,
    PROGRESS_STEP,
    Parcel,
    ParcelStatus,
    TrackingResult,
    carrier_name,
)
from .notification import build_notification, notification_tag, service_name
from .schedule import GLS_MIN_INTERVAL, backoff, order_overdue, poll_interval, should_remove
from .store import DuplicateParcel, ParcelStore

_LOGGER = logging.getLogger(__name__)

# Unrecognised mails remembered for the diagnostics (memory only, gone after a reload).
UNRECOGNIZED_KEEP = 10
# Seconds one notify target may take; after that it counts as failed.
NOTIFY_TIMEOUT = 30
# What an "Automatisch" parcel shows when no carrier asked knows its number (or DHL has
# no key): only then GLS gets its one-time question about 12 digits (see _gls_probe).
_NO_CARRIER_ERRORS = frozenset({"missing_key", "not_found", "carrier_not_found"})


# What became of one mail; the import endpoint returns it as "result".
MAIL_RECOGNIZED = "recognized"
MAIL_UNRECOGNIZED = "unrecognized"
MAIL_IGNORED = "ignored"  # shop advertising, account mails: nothing about parcels
MAIL_STALE = "stale"  # older than MAIL_MAX_AGE
MAIL_DUPLICATE = "duplicate"  # Message-ID already processed
# IMAP folder per outcome (None = only mark seen).
_MAIL_FOLDERS: dict[str, str | None] = {
    MAIL_RECOGNIZED: FOLDER_PROCESSED,
    MAIL_DUPLICATE: FOLDER_PROCESSED,
    MAIL_UNRECOGNIZED: FOLDER_UNRECOGNIZED,
    MAIL_IGNORED: None,
    MAIL_STALE: None,
}


@dataclass
class _ParsedMail:
    """Outcome of parsing one raw mail in the executor."""

    message_id: str = ""
    stale: bool = False
    result: MailResult | None = None
    error: Exception | None = None
    # For the diagnostics: a known shop/carrier domain or "other", never the address.
    domain: str = OTHER_DOMAIN
    forwarded: bool = False


def _parse_one(raw: bytes, read_otp: bool, now: datetime) -> _ParsedMail:
    item = _ParsedMail()
    try:
        msg = email.message_from_bytes(raw, policy=policy.default)
        item.message_id = str(msg.get("Message-ID") or "").strip()
        try:
            # A forward of a known sender's mail is booked under that original sender.
            original = forwarded_original(msg)
            item.domain = known_sender_domain(sender(original or msg)[0])
            item.forwarded = original is not None or is_forwarded(msg)
        except Exception:  # noqa: BLE001 - odd headers: the parser below reports them
            pass
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
        track17: Track17Client | None = None,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=TICK, config_entry=entry
        )
        self.entry = entry
        self.store = store
        self.carriers = carriers
        self._first_refresh_done = False
        # Status changes are announced (event and notification) once the first refresh
        # is done and Home Assistant has started, at the latest ANNOUNCE_MAX_WAIT after
        # that refresh. Found earlier, they wait in the parcel itself
        # (Parcel.unannounced_from, stored), so a reload or a restart loses nothing.
        self._announcing = False
        self._unsub_started: CALLBACK_TYPE | None = None
        self._unsub_wait: CALLBACK_TYPE | None = None
        # Markers cleared by announcing that are not written to disk yet.
        self._unsaved_announced = False
        self._stopped = False
        self._first_fail: dict[str, datetime] = {}
        self._dhl_day: date | None = None
        self._dhl_calls = 0
        self._lock = asyncio.Lock()
        self.mailbox = mailbox
        self._mail_lock = asyncio.Lock()  # one import at a time (tick vs. refresh service)
        self._mail_next: datetime | None = None
        self._mail_streak = 0
        self._mail_last: datetime | None = None  # start of the last import run
        self._mail_error: str | None = None  # "auth" | "unavailable" | "error"
        self._mail_recognized = 0
        self._mail_unrecognized = 0
        # Sender domain (known shop/carrier or "other") and forwarded flag of the last
        # unrecognised mails; nothing else of a mail is kept.
        self.unrecognized_mails: deque[dict[str, Any]] = deque(maxlen=UNRECOGNIZED_KEEP)
        self._amazon_misses = 0
        self.track17 = track17
        self.track17_quota: Quota | None = None
        self.track17_blocked = False  # key rejected: no 17track calls until a reload
        self._t17_quota_next: datetime | None = None
        self._t17_streak = 0
        # Status 17track announced before the carrier's own, older answer took over.
        self._announced: dict[str, ParcelStatus] = {}

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
    def _mail_interval(self) -> timedelta:
        minutes = self.entry.options.get(CONF_MAIL_INTERVAL, DEFAULT_MAIL_INTERVAL)
        return timedelta(minutes=minutes)

    @property
    def _read_otp(self) -> bool:
        return self.entry.options.get(CONF_READ_OTP, DEFAULT_READ_OTP)

    @property
    def _notify_targets(self) -> list[str]:
        """Notify entities and classic services to push to; none = notifications off."""
        return list(self.entry.options.get(CONF_NOTIFY_TARGETS) or ())

    @property
    def _notify_events(self) -> frozenset[str]:
        return frozenset(self.entry.options.get(CONF_NOTIFY_EVENTS, DEFAULT_NOTIFY_EVENTS) or ())

    # ----- main loop -----
    async def _async_update_data(self) -> dict[str, Parcel]:
        async with self._lock:
            now = dt_util.utcnow()
            self._check_ups_budget(now)
            changed = self._cleanup(now)
            for parcel in list(self.store.parcels.values()):
                if not self._pollable(parcel):
                    continue  # mail-only: status comes from mails
                if parcel.next_poll_at is None or parcel.next_poll_at <= now:
                    if parcel.status is not None and poll_interval(parcel.status, now) is None:
                        continue
                    await self._poll_safely(parcel, now)
                    changed = True
            # Not during the first refresh: setup must not wait for 17track.
            if self._first_refresh_done and await self._poll_track17(now):
                changed = True
            if self._settle_orders(now):
                changed = True
            if changed:
                await self.store.async_save()
        # Not during the first refresh: setup must not wait for the mailbox or 17track.
        if self._first_refresh_done:
            await self._quota_if_due()
            await self.async_import_mail()
        elif not self._stopped:
            self._first_refresh_done = True
            # Right away while Home Assistant is running (a reload); during its start
            # once it has started, so automations and notify targets are loaded - but
            # not later than ANNOUNCE_MAX_WAIT from now: the start can hang for minutes.
            unsub = async_at_started(self.hass, self._on_started)
            if not self._announcing:
                self._unsub_started = unsub
                self._unsub_wait = async_call_later(
                    self.hass, ANNOUNCE_MAX_WAIT, self._on_waited
                )
        return dict(self.store.parcels)

    @callback
    def _on_started(self, _hass: HomeAssistant) -> None:
        self._unsub_started = None  # a one-time listener: already gone
        self._start_announcing()

    @callback
    def _on_waited(self, _now: datetime) -> None:
        self._unsub_wait = None  # the timer has fired
        self._start_announcing()

    @callback
    def _stop_waiting(self) -> None:
        """Drop the start listener and the timer, whichever is still there."""
        if self._unsub_started is not None:
            self._unsub_started()
            self._unsub_started = None
        if self._unsub_wait is not None:
            self._unsub_wait()
            self._unsub_wait = None

    @callback
    def _start_announcing(self) -> None:
        """Announce what was found so far, each parcel once, and everything later at once.

        Also picks up what an earlier run of the integration (before a reload or a
        restart) found and could not announce any more. Order: announce, clear the
        marker, write the store. An unload in between waits for that write (see
        async_shutdown), so only a crash in exactly that moment announces a change a
        second time after the restart - rather twice than never.
        """
        self._stop_waiting()
        if self._stopped or self._announcing:
            return
        self._announcing = True
        cleared = False
        for parcel in list(self.store.parcels.values()):
            old = parcel.unannounced_from
            if old is None:
                continue
            parcel.unannounced_from = None
            cleared = True
            # Back at the status it had: nothing to tell.
            if parcel.result is None or parcel.status is old:
                continue
            self._announce(parcel, old)
        if cleared:
            self._unsaved_announced = True
            self.hass.async_create_task(
                self._save_announced(), f"{DOMAIN} save announced", eager_start=True
            )

    async def _save_announced(self) -> None:
        await self.store.async_save()
        self._unsaved_announced = False

    async def async_shutdown(self) -> None:
        """Unload: stop waiting for the start. What was not announced yet stays stored
        with its parcel and is announced by the next coordinator."""
        self._stopped = True
        self._stop_waiting()
        if self._unsaved_announced:
            # Announced a moment ago: the next coordinator must read that from disk.
            # Writes of one store run one after the other, so this ends after the
            # write that announcing started.
            await self._save_announced()
        await super().async_shutdown()

    def _cleanup(self, now: datetime) -> bool:
        removed = [
            n for n, p in self.store.parcels.items() if should_remove(p, now, self._keep_days)
        ]
        for number in removed:
            self.store.remove(number)
            self._announced.pop(number, None)
        today = dt_util.as_local(now).date()
        for parcel in self.store.parcels.values():
            if parcel.delivery_code and parcel.active_code(today) is None:
                parcel.delivery_code = parcel.delivery_code_day = None
        return bool(removed)

    def _settle_orders(self, now: datetime) -> bool:
        """Close shop orders that get no "delivered" mail; True if something changed.

        First a delivered carrier parcel that a mail created on its own is folded into
        the one open order it belongs to (see ``fold_delivered``): the order is delivered
        and carries the number, the parcel of its own is gone, and its sensor with it
        (the sensor platform drops what is no longer stored). Nothing is announced here:
        the delivery was announced with the carrier parcel, or still waits and is
        announced with the order.

        Then every order nobody can ask about whose delivery day is long over is closed
        (see ``order_overdue``). That fires the status event, marked ``assumed``, but
        sends no notification: nothing arrived just now.

        Runs with every refresh and after every mail import, so it also settles what
        was stored before this version. A delivered parcel is looked at once
        (``Parcel.order_checked``, stored): later changes of other orders never make it
        fit after all. A closed order is delivered and matches neither rule again.
        """
        changed = False
        for parcel in list(self.store.parcels.values()):
            if parcel.status is not ParcelStatus.DELIVERED or parcel.order_checked:
                continue
            parcel.order_checked = True
            changed = True
            delivered = parcel.result.delivered_at or parcel.last_change_at
            if fold_delivered(self.store.parcels, parcel, dt_util.as_local(delivered)):
                self._announced.pop(parcel.number, None)
        today = dt_util.as_local(now).date()
        for parcel in self.store.parcels.values():
            if not order_overdue(parcel, today, dt_util.get_default_time_zone()):
                continue
            old = parcel.status
            close_unconfirmed(parcel, now)
            if old is not None:
                self._fire(parcel, old)
            changed = True
        return changed

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
            self._mail_next = now + self._mail_interval
            self._mail_last = now
            try:
                await self._import_mail(self.mailbox, now)
            except ImapAuthError:
                self._mail_failed(now, "auth")
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
                self._mail_failed(now, "unavailable")
            except Exception as err:  # noqa: BLE001 - isolate the import from the refresh
                # Only the error type: mail contents never go into the log.
                _LOGGER.warning("Mail import failed (%s); trying again later", type(err).__name__)
                self._mail_failed(now, "error")

    async def _import_mail(self, mailbox: MailboxClient, now: datetime) -> None:
        mails = await self.hass.async_add_executor_job(mailbox.fetch_unseen)
        ir.async_delete_issue(self.hass, DOMAIN, "imap_auth")
        self._mail_streak = 0
        self._mail_error = None
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
            self._settle_orders(now)
            await self.store.async_save()
        try:
            await self.hass.async_add_executor_job(
                mailbox.finish, dispositions, self._move_processed
            )
        except (ImapAuthError, ImapUnavailable) as err:
            # Mails were fetched with PEEK and stay unseen; Message-ID dedup skips them next time.
            _LOGGER.debug("Could not file processed mails: %s", err)

    def _mail_failed(self, now: datetime, code: str) -> None:
        self._mail_error = code
        self._mail_streak += 1
        delay = min(MAIL_INTERVAL * 2 ** (self._mail_streak - 1), MAIL_MAX_BACKOFF)
        self._mail_next = now + delay

    def _handle_mail(self, item: _ParsedMail, now: datetime) -> str | None:
        """Apply one parsed mail; return its target folder (None = only mark seen)."""
        return _MAIL_FOLDERS[self._apply_mail(item, now)]

    def _apply_mail(
        self,
        item: _ParsedMail,
        now: datetime,
        changed: set[str] | None = None,
        mailbox: bool = True,
    ) -> str:
        """Apply one parsed mail; return its outcome (a key of _MAIL_FOLDERS).

        ``changed`` collects the numbers of the parcels the mail created or changed.
        ``mailbox`` is False for a mail the endpoint handed in: it lies in no folder,
        so it does not count towards the Amazon repair issue that points to one.
        """
        try:
            if item.message_id and not self.store.remember_message(item.message_id):
                return MAIL_DUPLICATE
            if item.stale:
                return MAIL_STALE  # too old to say anything about today's parcels
            if item.error is not None:
                raise item.error
            result = item.result
            if result is None or result.ignored:
                return MAIL_IGNORED
            if result.amazon and mailbox:
                self._count_amazon(recognized=bool(result.updates))
            if not result.updates:
                self._unrecognized(item)
                return MAIL_UNRECOGNIZED
            for update in result.updates:
                if change := apply_update(self.store.parcels, update, now):
                    self._mail_changed(change)
                    if changed is not None:
                        changed.add(change.parcel.number)
        except Exception as err:  # noqa: BLE001 - one odd mail must not stop the import
            # Only the error type: mail contents never go into the log.
            _LOGGER.warning(
                "Could not read a mail (%s); counted it as unrecognized",
                type(err).__name__,
            )
            self._unrecognized(item)
            return MAIL_UNRECOGNIZED
        self._mail_recognized += 1
        return MAIL_RECOGNIZED

    async def async_import_raw_mail(self, raw: bytes) -> dict[str, Any]:
        """Apply one raw RFC 822 mail handed in over the endpoint (no mailbox needed).

        Same parser, dedup (Message-ID) and age limit as the IMAP import; returns the
        outcome and the numbers of the parcels it created or changed.
        """
        now = dt_util.utcnow()
        [item] = await self.hass.async_add_executor_job(
            _parse_mails, [raw], self._read_otp, now
        )
        changed: set[str] = set()
        async with self._lock:
            outcome = self._apply_mail(item, now, changed, mailbox=False)
            settled = self._settle_orders(now)
            await self.store.async_save()
        if changed or settled:
            # Not for a mail that changed nothing: every call would push the next tick back.
            self.async_set_updated_data(dict(self.store.parcels))
        parcels = sorted({stored for number in changed if (stored := self._stored_as(number))})
        return {"result": outcome, "parcels": parcels}

    def _stored_as(self, number: str) -> str | None:
        """Number a parcel is stored under: its own, or the order it was folded into."""
        if number in self.store.parcels:
            return number
        return next(
            (p.number for p in self.store.parcels.values() if p.tracking_ref == number), None
        )

    def _unrecognized(self, item: _ParsedMail) -> None:
        """Count an unrecognised mail; keep only its sender domain class and forwarded flag."""
        self._mail_unrecognized += 1
        self.unrecognized_mails.append({"domain": item.domain, "forwarded": item.forwarded})

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
            change.old_status is not None
            and parcel.status is not None
            and change.old_status is not parcel.status
        ):
            self._fire(parcel, change.old_status)

    # ----- polling -----
    def _check_ups_budget(self, now: datetime) -> None:
        """Once UPS calls are possible again (new month, higher budget), poll waiting parcels."""
        ups = self.carriers.get("ups")
        if isinstance(ups, UpsCarrier) and not ups.exhausted(now):
            ir.async_delete_issue(self.hass, DOMAIN, "ups_budget")
            for parcel in self.store.parcels.values():
                if parcel.last_error == "ups_budget":
                    parcel.next_poll_at = None

    def _budget_used_up(self, parcel: Parcel, now: datetime) -> None:
        """UPS only from mails until the month is over."""
        parcel.last_error = "ups_budget"
        parcel.next_poll_at = next_month_start(now)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "ups_budget",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="ups_budget",
        )

    def _pollable(self, parcel: Parcel) -> bool:
        """A carrier can be asked (UPS only while its API is configured)."""
        target = parcel.poll_target
        if target is None:
            return False
        return target[0] not in OPTIONAL_API_CARRIERS or target[0] in self.carriers

    def _count_dhl(self, now: datetime) -> None:
        today = dt_util.as_local(now).date()
        if self._dhl_day != today:
            self._dhl_day, self._dhl_calls = today, 0
        self._dhl_calls += 1

    async def _poll_safely(self, parcel: Parcel, now: datetime) -> bool:
        """Poll one parcel, never letting an unexpected error take down the refresh.

        True only when the one-time GLS question (see ``_gls_probe``) found that the
        parcel is tracked already under the 11-digit form of its number.
        """
        tried: list[str] = []
        twin = False
        try:
            await self._poll(parcel, now, tried)
        except Exception:  # noqa: BLE001 - isolate one bad parcel from the rest
            _LOGGER.exception("Unexpected error polling %s", parcel.number)
            self._fail(parcel, now, parcel.carrier or "unknown", "unavailable", backoff_only=True)
        else:
            # Only after the regular candidates (DHL) said they do not know the number.
            if parcel.last_error in _NO_CARRIER_ERRORS and self._gls_probe_due(parcel):
                twin = await self._gls_probe(parcel, now, tried)
        if "ups" in tried:
            self._ups_floor(parcel, now)
        if "gls" in tried:
            self._gls_floor(parcel, now)
        return twin

    @staticmethod
    def _gls_floor(parcel: Parcel, now: datetime) -> None:
        """GLS' open lookup is never asked again sooner than 30 minutes, whatever went
        wrong (error backoff, a short Retry-After)."""
        if parcel.next_poll_at is not None and parcel.next_poll_at < now + GLS_MIN_INTERVAL:
            parcel.next_poll_at = now + GLS_MIN_INTERVAL

    def _ups_floor(self, parcel: Parcel, now: datetime) -> None:
        """Every UPS call costs budget: never ask again sooner than the UPS interval,
        whatever went wrong (not found, errors, backoff)."""
        if parcel.next_poll_at is None:
            return
        # Only UPS's own status counts: a 17track "out for delivery" must not make the
        # paid UPS calls more frequent. No own status yet: the default interval (4 h).
        own = strip_enrichment(parcel.result)
        interval = poll_interval(own.status if own else None, now, "ups")
        if interval is not None and parcel.next_poll_at < now + interval:
            parcel.next_poll_at = now + interval

    async def _poll(self, parcel: Parcel, now: datetime, tried: list[str]) -> None:
        if not self._pollable(parcel):
            return
        carrier_key, number = parcel.poll_target
        if carrier_key:
            keys = [carrier_key] if carrier_key in self.carriers else []
        else:
            keys = candidates(number, self.carriers)
        probing = carrier_key is None  # "Automatisch": no carrier failure counted yet
        # No rule takes the number: DHL is the last candidate (see _dhl_fallback).
        fallback = not keys and self._dhl_fallback(parcel)
        if fallback:
            keys = ["dhl"]
        parcel.last_poll_at = now
        if not keys:
            parcel.last_error = "carrier_not_found"
            parcel.error_streak = 0  # left over when the DHL fallback gave up
            parcel.first_error_at = None
            parcel.next_poll_at = now + timedelta(hours=1)
            return
        last_error = "not_found"
        # With several candidates a failing one must not stop the others.
        deferred: tuple[str, Exception] | None = None
        for key in keys:
            carrier = self.carriers[key]
            tried.append(key)
            if key == "dhl":
                self._count_dhl(now)
            try:
                result = await carrier.fetch(number, self._postcode)
            except NotFound:
                continue
            except BudgetExhausted:
                self._budget_used_up(parcel, now)
                return
            except MissingCredentials:
                last_error = "missing_key"
                continue
            except AuthError:
                self._fail(parcel, now, key, "auth", backoff_only=True)
                self._auth_issue(key)
                return
            except (RateLimited, CarrierUnavailable, ParseError) as err:
                _LOGGER.debug("%s failed for %s: %s", key, parcel.number, err)
                deferred = deferred or (key, err)
                continue
            except Exception:  # noqa: BLE001 - never let one carrier bug break polling
                _LOGGER.exception("Unexpected error polling %s", parcel.number)
                self._fail(parcel, now, key, "unavailable", backoff_only=True)
                return
            else:
                self._success(parcel, now, key, result)
                return
        if deferred is not None:
            key, err = deferred
            if isinstance(err, RateLimited):
                parcel.last_error = "rate_limited"
                parcel.next_poll_at = now + timedelta(seconds=err.retry_after or 3600)
                if fallback:
                    parcel.error_streak += 1  # counts towards DHL_FALLBACK_TRIES
            else:
                self._fail(parcel, now, key, "unavailable", backoff_only=probing)
            return
        if fallback:
            # DHL does not know it either: unknown as without a key, and never asked again.
            last_error = "carrier_not_found"
            parcel.error_streak = 0
            parcel.first_error_at = None
        parcel.last_error = last_error
        parcel.next_poll_at = now + timedelta(hours=1)

    def _dhl_fallback(self, parcel: Parcel) -> bool:
        """Ask DHL about a number typed in with "Automatisch" that no carrier's rule takes?

        Only with a DHL key, and only until DHL gave an answer: "not found" marks the
        parcel "carrier_not_found" (as without a key), which ends the asking for good, so
        the hourly look at an unknown number and "Aktualisieren" cost no call. While DHL
        cannot be reached it is tried DHL_FALLBACK_TRIES times in all. Parcels that were
        unknown before v0.3.17 carry that marker already and are not asked.
        """
        return (
            parcel.carrier is None
            and parcel.tracking_ref is None
            and parcel.carrier_mode == "auto"
            and parcel.last_error != "carrier_not_found"
            and parcel.error_streak < DHL_FALLBACK_TRIES
            and getattr(self.carriers.get("dhl"), "configured", False)
        )

    def _gls_probe_due(self, parcel: Parcel) -> bool:
        """Ask GLS the one-time question about a 12-digit number typed in with "Automatisch"?

        12 digits are a GLS parcel number with its check digit, a DHL number or an eBay
        item number, so no rule makes GLS a candidate for them. Only a parcel added by
        hand or service with "Automatisch" that has no carrier yet is asked about, never
        one a mail created and never a shop order. An answer ends the asking for good
        (``Parcel.gls_probes``, stored); while GLS cannot be reached it is tried
        GLS_PROBE_TRIES times in all. Parcels stored unresolved by an older version carry
        no count and get the same single question.
        """
        return (
            parcel.carrier is None
            and parcel.tracking_ref is None
            and parcel.carrier_mode == "auto"
            and parcel.gls_probes < GLS_PROBE_TRIES
            and has_check_digit(parcel.number)
            and callable(getattr(self.carriers.get("gls"), "probe", None))
        )

    async def _gls_probe(self, parcel: Parcel, now: datetime, tried: list[str]) -> bool:
        """Ask GLS with all 12 digits; a hit makes the parcel an ordinary GLS parcel.

        Called after the regular poll left the parcel without a carrier. "Not found"
        leaves it exactly as that poll left it. So does a GLS that cannot be reached or
        limits the rate: no carrier failure, no repair issue, and the next try comes with
        the parcel's next regular poll (never sooner than GLS_MIN_INTERVAL, see
        ``_gls_floor``, and not before a Retry-After is over).

        Returns True when GLS knows the parcel but its 11-digit form is tracked already:
        the parcel then stays as it is and no second GLS entry appears (``async_add``
        refuses the new parcel as a duplicate).
        """
        tried.append("gls")
        parcel.gls_probes += 1
        try:
            result = await self.carriers["gls"].probe(parcel.number)
        except NotFound:
            parcel.gls_probes = GLS_PROBE_TRIES
            return False
        except RateLimited as err:
            _LOGGER.debug("GLS did not answer the question about %s: %s", parcel.number, err)
            wait = now + timedelta(seconds=err.retry_after or 0)
            if parcel.next_poll_at is not None and parcel.next_poll_at < wait:
                parcel.next_poll_at = wait
            return False
        except CarrierError as err:
            _LOGGER.debug("GLS did not answer the question about %s: %s", parcel.number, err)
            return False
        except Exception:  # noqa: BLE001 - a bug here must not touch the parcel's own state
            _LOGGER.exception("Unexpected error asking GLS about %s", parcel.number)
            return False
        parcel.gls_probes = GLS_PROBE_TRIES
        if self._gls_other_form(parcel.number) is not None:
            return True
        self._success(parcel, now, "gls", result)
        return False

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

    def _success(self, parcel: Parcel, now: datetime, key: str, result: TrackingResult) -> None:
        self._first_fail.pop(key, None)
        ir.async_delete_issue(self.hass, DOMAIN, f"carrier_broken_{key}")
        if key in ("dhl", "ups"):
            ir.async_delete_issue(self.hass, DOMAIN, f"{key}_auth")
        known = strip_enrichment(parcel.result)  # the carrier's or a mail's own values
        if (
            key in MAIL_ETA_CARRIERS
            and result.eta_date is None
            and known is not None
            and known.eta_date is not None
            and result.status not in NO_ETA_STATUSES
        ):
            # Hermes never tells a day, GLS not always, DPD only for "out for delivery":
            # keep the day a mail or an earlier lookup named, but not once the parcel is
            # delivered, waits for pickup or ran into a problem (that day no longer holds).
            result = replace(
                result,
                eta_date=known.eta_date,
                eta_latest=known.eta_latest,
                eta_from=known.eta_from,
                eta_to=known.eta_to,
            )
        elif (
            key in KEEP_ETA_UNTIL_DAY_CARRIERS
            and known is not None
            and known.eta_date is not None
            and result.eta_date in (None, known.eta_date)
            and result.eta_from is None
            and result.eta_to is None
            and result.status not in NO_ETA_STATUSES
            and known.eta_date >= dt_util.as_local(now).date()
        ):
            # DHL may take its estimate back and compute it anew: the day and window
            # named before stay while the parcel is on its way, until that day is over.
            # An answer with the same day but without window keeps the window too.
            result = replace(
                result,
                eta_date=known.eta_date,
                eta_latest=known.eta_latest,
                eta_from=known.eta_from,
                eta_to=known.eta_to,
            )
        # 17track only fills what the carrier left empty (place, day/window, history).
        result = with_track17(result, parcel.track17_result)
        if result.status is ParcelStatus.DELIVERED:
            parcel.track17_next_at = None
        old = parcel.status
        took_over = parcel.result is not None and known is None  # shown was 17track's alone
        if parcel.carrier is None:
            parcel.carrier = key
        if parcel.result is None or parcel.result.to_dict() != result.to_dict():
            parcel.last_change_at = now
        parcel.result = result
        parcel.last_error = None
        parcel.error_streak = 0
        parcel.first_error_at = None
        interval = poll_interval(result.status, now, key)
        if interval and key == "dhl" and self._dhl_calls > DHL_DAILY_SOFT_LIMIT:
            interval *= 2
        parcel.next_poll_at = now + interval if interval else None
        if old is not None and old != result.status and self._news(parcel, old, took_over):
            self._fire(parcel, old)

    def _news(self, parcel: Parcel, old: ParcelStatus, took_over: bool) -> bool:
        """Is the carrier's new status worth a status event?

        A parcel shown from 17track alone may be ahead of the carrier. When the carrier's
        first own answer is a step backwards (PROGRESS_STEP), that is no news: no event,
        and the status 17track had announced is remembered, so the carrier reaching it
        later is not announced a second time. Kept in memory only: after a restart in
        between, that one status is announced again.
        """
        status = parcel.result.status
        # A problem the carrier reports is always announced, also right at the takeover.
        if (
            took_over
            and status is not ParcelStatus.EXCEPTION
            and PROGRESS_STEP[status] < PROGRESS_STEP[old]
        ):
            self._announced[parcel.number] = old
            return False
        announced = self._announced.get(parcel.number)
        if announced is not None and PROGRESS_STEP[status] >= PROGRESS_STEP[announced]:
            del self._announced[parcel.number]  # caught up (or beyond): normal from now on
        return status is not announced

    def _fire(self, parcel: Parcel, old: ParcelStatus) -> None:
        """A parcel's status changed: announce it, or keep it until announcing starts.

        Kept in the parcel; every caller saves the store afterwards.
        """
        if self._announcing:
            self._announce(parcel, old)
        elif parcel.unannounced_from is None:
            parcel.unannounced_from = old
        elif parcel.status is parcel.unannounced_from:
            # Back at the status it had before the first change: nothing to tell.
            parcel.unannounced_from = None
        # Otherwise several changes in a row become one, from the oldest status to
        # the latest.

    def _announce(self, parcel: Parcel, old: ParcelStatus) -> None:
        r = parcel.result
        self.hass.bus.async_fire(
            EVENT_STATUS_CHANGED,
            {
                "number": parcel.number,
                "name": parcel.name,
                "carrier": parcel.carrier,
                "carrier_name": carrier_name(parcel),
                "old_status": old.value,
                "new_status": r.status.value,
                "eta_date": r.eta_date.isoformat() if r.eta_date else None,
                "eta_from": r.eta_from.isoformat() if r.eta_from else None,
                "eta_to": r.eta_to.isoformat() if r.eta_to else None,
                "location": r.location,
                # True for a shop order closed without a delivery mail ("delivered" is
                # only assumed); such a change is never pushed.
                "assumed": parcel.assumed_delivered,
            },
        )
        self._notify(parcel, old)

    # ----- push notifications -----
    def _notify(self, parcel: Parcel, old: ParcelStatus) -> None:
        """Push the status change to the chosen notify entities and classic services.

        Called exactly where the status event fires. The text is built right away
        (from the parcel as it is now); sending runs in a task of its own, so it can
        neither delay nor break the refresh or the caller. An order closed without a
        delivery mail is never pushed (``build_notification`` gives no text for it).
        """
        try:
            targets = self._notify_targets
            if not targets or parcel.result.status.value not in self._notify_events:
                return
            built = build_notification(parcel, old, dt_util.now())
            tag = notification_tag(parcel.number)
        except Exception as err:  # noqa: BLE001 - a notification must never break a refresh
            # Only the error type: no parcel data in the log.
            _LOGGER.warning("Could not build a notification (%s)", type(err).__name__)
            return
        if built is None:
            return
        coro = None
        try:
            coro = self._send_notification(targets, *built, tag)
            self.entry.async_create_task(
                self.hass, coro, f"{DOMAIN} notification", eager_start=False
            )
        except Exception as err:  # noqa: BLE001 - a notification must never break a refresh
            if coro is not None:
                coro.close()  # never started: nothing is left un-awaited
            _LOGGER.warning("Could not start sending a notification (%s)", type(err).__name__)

    async def _send_notification(
        self, targets: list[str], title: str, message: str, tag: str
    ) -> None:
        """One service call per target, so one broken or hanging target does not keep
        the others from getting the message. Never raises.

        A notify entity gets ``notify.send_message``; a classic service
        (``service:<name>``) is called as ``notify.<name>`` with title and message.
        Only the classic services of the Home Assistant app also get ``tag``, so the
        later notification of a parcel replaces the earlier one on the phone.
        """

        async def send(service: str, data: dict[str, Any]) -> None:
            async with asyncio.timeout(NOTIFY_TIMEOUT):
                await self.hass.services.async_call("notify", service, data, blocking=True)

        # Skipped quietly: removed entities (no state), unavailable ones, and classic
        # services that are not registered (any more, or not yet).
        calls: list[tuple[str, dict[str, Any]]] = []
        for target in targets:
            if not isinstance(target, str):
                continue
            if target.startswith(NOTIFY_SERVICE_PREFIX):
                name = service_name(target)
                if name is None or not self.hass.services.has_service("notify", name):
                    continue
                data: dict[str, Any] = {"title": title, "message": message}
                if name.startswith(NOTIFY_APP_SERVICE_PREFIX):
                    data["data"] = {"tag": tag}
                calls.append((name, data))
            elif (
                state := self.hass.states.get(target)
            ) is not None and state.state != STATE_UNAVAILABLE:
                calls.append(
                    ("send_message", {"entity_id": target, "title": title, "message": message})
                )
        results = await asyncio.gather(*(send(*call) for call in calls), return_exceptions=True)
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            # Only counts and error types: no parcel data, no target names in the log.
            _LOGGER.warning(
                "Could not send a notification to %d of %d targets (%s)",
                len(errors),
                len(calls),
                ", ".join(sorted({type(err).__name__ for err in errors})),
            )

    def _auth_issue(self, key: str) -> None:
        if key not in ("dhl", "ups"):
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{key}_auth",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=f"{key}_auth",
        )
        if key == "dhl":
            self.entry.async_start_reauth(self.hass)

    # ----- 17track (optional; registration only on explicit request) -----
    def _t17_client(self) -> Track17Client:
        if self.track17 is None:
            raise Track17Disabled("no 17track key configured")
        if self.track17_blocked:
            raise AuthError("17track key rejected; waiting for a reload")
        return self.track17

    def _track17_auth(self) -> None:
        """Key rejected: no more 17track calls until the integration reloads."""
        self.track17_blocked = True
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "track17_auth",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="track17_auth",
        )
        self.async_update_listeners()

    def _quota_issues(self, remain: int) -> None:
        """track17_quota_low at 10 or fewer numbers left, track17_quota_exhausted at none."""
        if remain <= 0:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "track17_quota_exhausted",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="track17_quota_exhausted",
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "track17_quota_exhausted")
        if 0 < remain <= TRACK17_QUOTA_LOW:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "track17_quota_low",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="track17_quota_low",
                translation_placeholders={"remain": str(remain)},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "track17_quota_low")

    async def async_update_quota(self) -> None:
        """Read the 17track quota (free) for the sensor and the repairs."""
        if self.track17 is None or self.track17_blocked:
            return
        now = dt_util.utcnow()
        self._t17_quota_next = now + TRACK17_QUOTA_INTERVAL
        try:
            quota = await self.track17.getquota()
        except AuthError:
            self._track17_auth()
            return
        except CarrierError as err:
            _LOGGER.debug("17track quota not available: %s", err)
            self._t17_quota_next = now + TRACK17_QUOTA_RETRY
            return
        self.track17_quota = quota
        ir.async_delete_issue(self.hass, DOMAIN, "track17_auth")
        self._quota_issues(quota.remain)
        self.async_update_listeners()

    async def _quota_if_due(self) -> None:
        if self.track17 is None or self.track17_blocked:
            return
        if self._t17_quota_next is None or self._t17_quota_next <= dt_util.utcnow():
            await self.async_update_quota()

    async def _poll_track17(self, now: datetime) -> bool:
        """Ask 17track (free) for registered parcels that are due, in batched calls."""
        if self.track17 is None or self.track17_blocked:
            return False
        due = [
            p
            for p in self.store.parcels.values()
            if p.track17
            and p.track17_next_at is not None
            and p.track17_next_at <= now
            and p.track17_target is not None
        ]
        if not due:
            return False
        try:
            infos = await self.track17.gettrackinfo(
                [(p.track17_target[1], p.track17_carrier) for p in due]
            )
        except AuthError:
            self._track17_auth()
            return False
        except CarrierError as err:  # network, 5xx, 429, odd answers: back off, never register
            _LOGGER.debug("17track not reachable: %s", err)
            self._t17_streak += 1
            for parcel in due:
                parcel.track17_next_at = now + backoff(self._t17_streak)
            return True
        self._t17_streak = 0
        for parcel in due:
            self._apply_track17(parcel, infos.get(parcel.track17_target[1]), now)
        return True

    def _apply_track17(
        self, parcel: Parcel, info: Track17Info | CarrierError | None, now: datetime
    ) -> None:
        if isinstance(info, NotRegistered):
            # Gone at 17track: never register again on our own; the card offers it anew.
            parcel.track17 = False
            parcel.track17_next_at = None
            if parcel.carrier == CARRIER_OTHER:
                parcel.last_error = "track17_not_registered"
            else:
                # Nothing of 17track stays behind; the carrier's own error is not touched.
                parcel.track17_result = None
                self._show(parcel, now, strip_enrichment(parcel.result))
            return
        if not isinstance(info, Track17Info):
            # No data yet (-18019909) or an odd answer: quietly again in 6 h.
            parcel.track17_next_at = now + TRACK17_INTERVAL
            return
        if parcel.track17_carrier is None:
            parcel.track17_carrier = info.carrier
        if parcel.carrier == CARRIER_OTHER:
            # 17track is its only source.
            self._show(parcel, now, info.result)
            parcel.last_error = None
        else:
            # Fill the carrier's gaps; without any carrier answer show 17track's whole one.
            parcel.track17_result = info.result
            self._show(parcel, now, with_track17(strip_enrichment(parcel.result), info.result))
        ended = info.expired or parcel.status is ParcelStatus.DELIVERED
        parcel.track17_next_at = None if ended else now + TRACK17_INTERVAL

    def _show(self, parcel: Parcel, now: datetime, result: TrackingResult | None) -> None:
        """Take what a 17track answer made of the parcel's result."""
        old = parcel.status
        before = parcel.result.to_dict() if parcel.result is not None else None
        if before != (result.to_dict() if result is not None else None):
            parcel.last_change_at = now
        parcel.result = result
        if old is not None and result is not None and old != result.status:
            self._fire(parcel, old)

    async def _register17(self, number: str, carrier_key: str | None) -> int | None:
        """Register at 17track (costs 1 number); return the carrier code 17track uses."""
        client = self._t17_client()
        code = TRACK17_CARRIER_CODES.get(carrier_key) if carrier_key else None
        try:
            registration = await client.register(number, code)
        except AuthError:
            self._track17_auth()
            raise
        except QuotaExhausted:
            self._quota_issues(0)
            await self.async_update_quota()  # don't leave a stale count on the sensor
            raise
        return registration.carrier or code

    async def async_track17(self, number: str) -> Parcel:
        """Send a tracked parcel to 17track on explicit request."""
        self._t17_client()
        parcel = self.store.parcels[normalize(number)]  # KeyError: not tracked
        # Everything is checked under the lock: a poll or a mail may change the parcel
        # while this call waits.
        async with self._lock:
            if parcel.track17 or self.store.get(parcel.number) is not parcel:
                return parcel  # already registered (nothing to spend), or removed meanwhile
            target = parcel.track17_target
            if target is None or parcel.status is ParcelStatus.DELIVERED:
                raise ValueError("track17_not_possible")
            carrier_key, poll_number = target
            parcel.track17_carrier = await self._register17(poll_number, carrier_key)
            parcel.track17 = True
            if parcel.last_error == "track17_not_registered":
                parcel.last_error = None
            parcel.track17_next_at = dt_util.utcnow() + TRACK17_FIRST_POLL
            await self.store.async_save()
            self.async_set_updated_data(dict(self.store.parcels))
        await self.async_update_quota()
        return parcel

    async def _add_other(self, number: str, name: str | None) -> Parcel:
        """A carrier without own connection: adding it registers it at 17track first."""
        self._t17_client()
        async with self._lock:
            if self.store.get(number) is not None:
                raise DuplicateParcel(number)  # before registering: nothing spent
            code = await self._register17(number, None)
            now = dt_util.utcnow()
            parcel = Parcel(
                number=number,
                carrier=CARRIER_OTHER,
                carrier_mode="manual",
                name=(name or "").strip() or None,
                added_at=now,
                last_change_at=now,
                track17=True,
                track17_carrier=code,
                track17_next_at=now + TRACK17_FIRST_POLL,
            )
            self.store.add(parcel)
            await self.store.async_save()
            self.async_set_updated_data(dict(self.store.parcels))
        await self.async_update_quota()
        return parcel

    # ----- diagnostics -----
    def diagnostics(self) -> dict[str, Any]:
        """Runtime state for the diagnostics download: counters, times and flags only."""
        today = dt_util.as_local(dt_util.utcnow()).date()
        quota = self.track17_quota
        return {
            "pending_announcements": sum(
                1
                for parcel in self.store.parcels.values()
                if parcel.unannounced_from is not None
                and parcel.status is not parcel.unannounced_from
            ),
            "dhl_calls_today": self._dhl_calls if self._dhl_day == today else 0,
            "track17": {
                "configured": self.track17 is not None,
                "blocked": self.track17_blocked,
                "quota": (
                    {"total": quota.total, "used": quota.used, "remain": quota.remain}
                    if quota is not None
                    else None
                ),
                "quota_next_check": (
                    self._t17_quota_next.isoformat() if self._t17_quota_next else None
                ),
                "error_streak": self._t17_streak,
            },
            "mail_import": {
                "configured": self.mailbox is not None,
                "interval_minutes": int(self._mail_interval.total_seconds() // 60),
                "last_run": self._mail_last.isoformat() if self._mail_last else None,
                # After an error this is the end of the backoff (see error_streak).
                "next_run": self._mail_next.isoformat() if self._mail_next else None,
                "last_error": self._mail_error,
                "error_streak": self._mail_streak,
                "recognized": self._mail_recognized,
                "unrecognized": self._mail_unrecognized,
                "amazon_misses": self._amazon_misses,
                "known_message_ids": len(self.store.message_ids),
                "last_unrecognized": [dict(item) for item in self.unrecognized_mails],
            },
        }

    # ----- public API used by services -----
    async def async_add(self, number: str, carrier: str, name: str | None) -> Parcel:
        norm = normalize(number)
        keys = candidates(norm, self.carriers)  # raises UnsupportedNumber
        if carrier == CARRIER_OTHER:
            return await self._add_other(norm, name)
        mode = "auto" if carrier == CARRIER_AUTO else "manual"
        if carrier == CARRIER_AUTO and not keys and UpsCarrier.matches(norm) is Match.SURE:
            carrier = "ups"  # mail-only until UPS API credentials are configured
        if (
            carrier != CARRIER_AUTO
            and carrier not in self.carriers
            and carrier not in OPTIONAL_API_CARRIERS
        ):
            raise ValueError("unknown_carrier")
        now = dt_util.utcnow()
        parcel = Parcel(
            number=norm,
            carrier=None if carrier == CARRIER_AUTO else carrier,
            carrier_mode=mode,
            name=(name or "").strip() or None,
            added_at=now,
            last_change_at=now,
        )
        async with self._lock:
            if self._gls_twin(parcel) is not None:
                raise DuplicateParcel(norm)
            self.store.add(parcel)  # raises DuplicateParcel
            if (
                parcel.carrier is None
                and not keys
                and not self._dhl_fallback(parcel)
                and not self._gls_probe_due(parcel)
            ):
                parcel.last_error = "carrier_not_found"
                parcel.last_poll_at = now
                parcel.next_poll_at = now + timedelta(hours=1)
            elif parcel.carrier in OPTIONAL_API_CARRIERS and not self._pollable(parcel):
                # UPS without API credentials is never asked: say so the way DHL does
                # without a key. The first poll with credentials replaces the marker.
                parcel.last_error = "missing_key"
            elif await self._poll_safely(parcel, now):
                # GLS knows these 12 digits, and the parcel is tracked with its 11.
                self.store.remove(norm)
                raise DuplicateParcel(norm)
            await self.store.async_save()
            self.async_set_updated_data(dict(self.store.parcels))
        return parcel

    def _gls_twin(self, parcel: Parcel) -> Parcel | None:
        """The GLS parcel already tracked under the other form of this number.

        GLS shows a parcel number with 11 digits or, with its check digit, with 12 (see
        ``gls_number``). Only looked for when "GLS" was chosen for the new parcel: with
        "Automatisch" 12 digits may be another carrier's number.
        """
        if parcel.carrier != "gls":
            return None
        return self._gls_other_form(parcel.number)

    def _gls_other_form(self, number: str) -> Parcel | None:
        """The GLS parcel stored under the other form (11 or 12 digits) of a GLS number."""
        short = gls_number(number)
        return next(
            (
                p
                for p in self.store.parcels.values()
                if p.carrier == "gls"
                and p.tracking_ref is None
                and p.number != number
                and short in (p.number, gls_number(p.number))
            ),
            None,
        )

    async def async_remove(self, number: str) -> None:
        async with self._lock:  # not while a refresh or a registration works on the parcels
            self.store.remove(normalize(number))  # KeyError: not tracked
            self._announced.pop(normalize(number), None)
            await self.store.async_save()
            self.async_set_updated_data(dict(self.store.parcels))

    async def async_rename(self, number: str, name: str | None) -> None:
        parcel = self.store.parcels[normalize(number)]
        parcel.name = (name or "").strip() or None
        await self.store.async_save()
        self.async_set_updated_data(dict(self.store.parcels))

    async def async_refresh_parcels(self, number: str | None) -> None:
        targets = [self.store.parcels[normalize(number)]] if number else self.store.parcels.values()
        now = dt_util.utcnow()
        for parcel in targets:
            parcel.next_poll_at = None
            # 17track is free: ask it now too, but not in the first minutes after registering.
            if (
                parcel.track17_next_at is not None
                and parcel.track17_next_at > now + TRACK17_FIRST_POLL
            ):
                parcel.track17_next_at = now
        # Also check the mailbox now, even while an error backoff is running
        # (an import already in progress still wins via the mail lock).
        self._mail_next = None
        await self.async_refresh()

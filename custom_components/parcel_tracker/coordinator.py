"""Polling coordinator for Paket Tracker."""

from __future__ import annotations

import asyncio
import email
import logging
from dataclasses import dataclass, replace
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
    CarrierError,
    CarrierUnavailable,
    Match,
    MissingCredentials,
    NotFound,
    ParseError,
    RateLimited,
)
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
    CARRIER_AUTO,
    CARRIER_BROKEN_AFTER,
    CARRIER_OTHER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_INTERVAL,
    CONF_MOVE_PROCESSED,
    CONF_POSTCODE,
    CONF_READ_OTP,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DEFAULT_MAIL_INTERVAL,
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
from .mail import parse_mail
from .mail.apply import Change, apply_update
from .mail.base import MailResult, sent_at
from .mail.imap import ImapAuthError, ImapUnavailable, MailboxClient
from .models import PROGRESS_STEP, Parcel, ParcelStatus, TrackingResult
from .schedule import backoff, poll_interval, should_remove
from .store import DuplicateParcel, ParcelStore

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
        track17: Track17Client | None = None,
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
            if self._events_enabled and await self._poll_track17(now):
                changed = True
            if changed:
                await self.store.async_save()
        # Not during the first refresh: setup must not wait for the mailbox or 17track.
        if self._events_enabled:
            await self._quota_if_due()
            await self.async_import_mail()
        self._events_enabled = True
        return dict(self.store.parcels)

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

    async def _poll_safely(self, parcel: Parcel, now: datetime) -> None:
        """Poll one parcel, never letting an unexpected error take down the refresh."""
        tried: list[str] = []
        try:
            await self._poll(parcel, now, tried)
        except Exception:  # noqa: BLE001 - isolate one bad parcel from the rest
            _LOGGER.exception("Unexpected error polling %s", parcel.number)
            self._fail(parcel, now, parcel.carrier or "unknown", "unavailable", backoff_only=True)
        if "ups" in tried:
            self._ups_floor(parcel, now)

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
        parcel.last_poll_at = now
        if not keys:
            parcel.last_error = "carrier_not_found"
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
            else:
                self._fail(parcel, now, key, "unavailable", backoff_only=probing)
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

    def _success(self, parcel: Parcel, now: datetime, key: str, result: TrackingResult) -> None:
        self._first_fail.pop(key, None)
        ir.async_delete_issue(self.hass, DOMAIN, f"carrier_broken_{key}")
        if key in ("dhl", "ups"):
            ir.async_delete_issue(self.hass, DOMAIN, f"{key}_auth")
        known = strip_enrichment(parcel.result)  # the carrier's or a mail's own values
        if (
            key == "hermes"
            and result.eta_date is None
            and known is not None
            and known.eta_date is not None
            and result.status is not ParcelStatus.DELIVERED
        ):
            # The Hermes API tells no day: keep what a mail said.
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
        return status is not announced and self._events_enabled

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
        if (
            old is not None
            and result is not None
            and old != result.status
            and self._events_enabled
        ):
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

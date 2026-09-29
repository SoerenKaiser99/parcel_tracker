"""Polling coordinator for Paket Tracker."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

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
    CARRIER_AUTO,
    CARRIER_BROKEN_AFTER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_POSTCODE,
    DEFAULT_KEEP_DELIVERED_DAYS,
    DHL_DAILY_SOFT_LIMIT,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    TICK,
)
from .detect import candidates, normalize
from .models import Parcel
from .schedule import backoff, poll_interval, should_remove
from .store import ParcelStore

_LOGGER = logging.getLogger(__name__)


class ParcelCoordinator(DataUpdateCoordinator[dict[str, Parcel]]):
    """Ticks every minute and polls parcels that are due."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: ParcelStore,
        carriers: dict[str, Carrier],
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

    # ----- main loop -----
    async def _async_update_data(self) -> dict[str, Parcel]:
        async with self._lock:
            now = dt_util.utcnow()
            changed = self._cleanup(now)
            for parcel in list(self.store.parcels.values()):
                if parcel.next_poll_at is None or parcel.next_poll_at <= now:
                    if parcel.status is not None and poll_interval(parcel.status, now) is None:
                        continue
                    await self._poll_safely(parcel, now)
                    changed = True
            if changed:
                await self.store.async_save()
        self._events_enabled = True
        return dict(self.store.parcels)

    def _cleanup(self, now: datetime) -> bool:
        removed = [
            n for n, p in self.store.parcels.items() if should_remove(p, now, self._keep_days)
        ]
        for number in removed:
            self.store.remove(number)
        return bool(removed)

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
        if parcel.carrier:
            keys = [parcel.carrier] if parcel.carrier in self.carriers else []
        else:
            keys = candidates(parcel.number, self.carriers)
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
                result = await carrier.fetch(parcel.number, self._postcode)
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

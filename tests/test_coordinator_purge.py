"""Coordinator: deleting recognised mails after X days (v0.3.46).

At most once a day, only after a fetch that worked, only with moving on; a failure is
one warning without names and never stops the import.
"""

from __future__ import annotations

from datetime import date, timedelta

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import (
    CONF_DELETE_PROCESSED_DAYS,
    CONF_MOVE_PROCESSED,
    DOMAIN,
)
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.mail.imap import ImapExpungeRefused, ImapUnavailable
from custom_components.parcel_tracker.store import ParcelStore


class FakeMailbox:
    def __init__(self, error: Exception | None = None, purge_error: Exception | None = None):
        self.error = error
        self.purge_error = purge_error
        self.fetches = 0
        self.purges: list[tuple[int, date]] = []
        self.deleted = 3

    def fetch_unseen(self):
        self.fetches += 1
        if self.error:
            raise self.error
        return []

    def finish(self, dispositions, move):
        pass

    def purge_processed(self, days, today):
        self.purges.append((days, today))
        if self.purge_error:
            raise self.purge_error
        return self.deleted


async def _coordinator(hass, mailbox, options=None):
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"}, options=options or {})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    return ParcelCoordinator(hass, entry, store, {}, mailbox)


def _diag(coord):
    return coord.diagnostics()["mail_import"]["delete_processed"]


def _purge_warnings(caplog):
    return [
        r for r in caplog.records
        if r.levelname == "WARNING" and "old recognised mails" in r.msg
    ]


async def _run(coord, freezer, minutes=5):
    await coord.async_import_mail()
    freezer.tick(timedelta(minutes=minutes))


async def test_without_the_option_nothing_is_deleted(hass, freezer):
    freezer.move_to("2026-10-29 10:00:00+00:00")
    mailbox = FakeMailbox()
    coord = await _coordinator(hass, mailbox)
    await _run(coord, freezer)
    assert mailbox.fetches == 1
    assert mailbox.purges == []
    assert _diag(coord) == {"enabled": False, "last_deleted": None}


async def test_zero_days_is_off(hass, freezer):
    freezer.move_to("2026-10-29 10:00:00+00:00")
    mailbox = FakeMailbox()
    coord = await _coordinator(hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: 0})
    await _run(coord, freezer)
    assert mailbox.purges == []


async def test_once_a_day_after_a_working_fetch(hass, freezer):
    freezer.move_to("2026-10-29 10:00:00+00:00")
    mailbox = FakeMailbox()
    coord = await _coordinator(hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: 30})
    await _run(coord, freezer)
    await _run(coord, freezer)
    assert mailbox.fetches == 2
    assert mailbox.purges == [(30, date(2026, 10, 29))]
    assert _diag(coord) == {"enabled": True, "last_deleted": 3}
    # The next day once more.
    freezer.move_to("2026-10-30 10:00:00+00:00")
    mailbox.deleted = 0
    await _run(coord, freezer)
    assert mailbox.purges == [(30, date(2026, 10, 29)), (30, date(2026, 10, 30))]
    assert _diag(coord) == {"enabled": True, "last_deleted": 0}


async def test_the_day_is_the_local_one(hass, freezer):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-10-29 23:30:00+00:00")  # already 30 Oct in Berlin
    mailbox = FakeMailbox()
    coord = await _coordinator(hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: 7})
    await _run(coord, freezer)
    assert mailbox.purges == [(7, date(2026, 10, 30))]


async def test_never_with_moving_off(hass, freezer):
    freezer.move_to("2026-10-29 10:00:00+00:00")
    mailbox = FakeMailbox()
    coord = await _coordinator(
        hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: 30, CONF_MOVE_PROCESSED: False}
    )
    await _run(coord, freezer)
    assert mailbox.fetches == 1
    assert mailbox.purges == []
    assert _diag(coord) == {"enabled": False, "last_deleted": None}


async def test_never_after_a_failed_fetch(hass, freezer):
    freezer.move_to("2026-10-29 10:00:00+00:00")
    mailbox = FakeMailbox(error=ImapUnavailable("down"))
    coord = await _coordinator(hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: 30})
    await _run(coord, freezer)
    assert mailbox.fetches == 1
    assert mailbox.purges == []


async def test_a_failure_warns_once_without_names_and_the_import_goes_on(hass, freezer, caplog):
    freezer.move_to("2026-10-29 10:00:00+00:00")
    mailbox = FakeMailbox(purge_error=ImapUnavailable("pakete@example.org Paket-Tracker"))
    coord = await _coordinator(hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: 30})
    await _run(coord, freezer)
    assert coord._mail_error is None  # the import itself counts as working
    assert coord._mail_streak == 0
    # Not tried again the same day.
    await _run(coord, freezer)
    assert len(mailbox.purges) == 1
    freezer.move_to("2026-10-30 10:00:00+00:00")
    await _run(coord, freezer)
    assert len(mailbox.purges) == 2
    warnings = _purge_warnings(caplog)
    assert len(warnings) == 1
    text = warnings[0].getMessage()
    assert "ImapUnavailable" in text
    assert "example.org" not in text and "Paket-Tracker" not in text
    assert mailbox.fetches == 3
    assert _diag(coord) == {"enabled": True, "last_deleted": None}
    # Working again: the next failure warns again.
    mailbox.purge_error = None
    freezer.move_to("2026-10-31 10:00:00+00:00")
    await _run(coord, freezer)
    assert _diag(coord) == {"enabled": True, "last_deleted": 3}
    mailbox.purge_error = RuntimeError("x")
    freezer.move_to("2026-11-01 10:00:00+00:00")
    await _run(coord, freezer)
    assert len(_purge_warnings(caplog)) == 2


async def test_a_mailbox_without_the_method_is_left_alone(hass, freezer):
    freezer.move_to("2026-10-29 10:00:00+00:00")

    class Old:
        fetches = 0

        def fetch_unseen(self):
            self.fetches += 1
            return []

    mailbox = Old()
    coord = await _coordinator(hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: 30})
    await _run(coord, freezer)
    assert mailbox.fetches == 1


async def test_odd_stored_values_are_off(hass, freezer):
    freezer.move_to("2026-10-29 10:00:00+00:00")
    for value in ("30", True, -5, 400, None, 30.5):
        mailbox = FakeMailbox()
        coord = await _coordinator(hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: value})
        await _run(coord, freezer)
        assert mailbox.purges == [], value
    mailbox = FakeMailbox()
    coord = await _coordinator(hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: 14.0})
    await _run(coord, freezer)
    assert mailbox.purges == [(14, date(2026, 10, 29))]


async def test_a_refused_expunge_reports_zero_and_warns_once(hass, freezer, caplog):
    freezer.move_to("2026-10-29 10:00:00+00:00")
    mailbox = FakeMailbox(purge_error=ImapExpungeRefused("uid expunge refused"))
    coord = await _coordinator(hass, mailbox, {CONF_DELETE_PROCESSED_DAYS: 30})
    await _run(coord, freezer)
    assert _diag(coord) == {"enabled": True, "last_deleted": 0}
    freezer.move_to("2026-10-30 10:00:00+00:00")
    await _run(coord, freezer)
    warnings = _purge_warnings(caplog)
    assert len(warnings) == 1
    assert "ImapExpungeRefused" in warnings[0].getMessage()
    assert coord._mail_error is None


async def test_diagnostics_say_off_without_a_mailbox(hass):
    coord = await _coordinator(hass, None, {CONF_DELETE_PROCESSED_DAYS: 30})
    assert _diag(coord) == {"enabled": False, "last_deleted": None}

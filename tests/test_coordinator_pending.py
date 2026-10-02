"""Status changes found before announcing starts survive a reload and a restart, and
are announced once Home Assistant has started or, at the latest, two minutes after the
first refresh."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util
from homeassistant.util.async_ import get_scheduled_timer_handles
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.parcel_tracker.const import (
    ANNOUNCE_MAX_WAIT,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.diagnostics import async_get_config_entry_diagnostics
from custom_components.parcel_tracker.models import ParcelStatus
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME
from .test_coordinator_notify import (
    FETCH,
    NUMBER,
    PHONE,
    _change,
    _loaded_entry,
    _restarted,
    _sent,
    _start,
    _started_listeners,
    result,
)

IN_DELIVERY = (PHONE, "Paket Tracker", "📦 Kopfhörer (DHL) ist in Zustellung")


def _changes(events) -> list[tuple[str, str]]:
    return [(e.data["old_status"], e.data["new_status"]) for e in events]


def _timers(hass) -> int:
    """Running timers of the wait for the start (the ones Home Assistant's test
    cleanup would report as lingering)."""
    return sum(
        1
        for handle in get_scheduled_timer_handles(hass.loop)
        if not handle.cancelled() and "ParcelCoordinator._on_waited" in repr(handle._args)
    )


async def _wait(hass, freezer, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def _stored(hass) -> ParcelStore:
    """What a start reads back from disk."""
    store = ParcelStore(hass)
    await store.async_load()
    return store


def test_the_longest_wait_is_two_minutes():
    assert ANNOUNCE_MAX_WAIT == timedelta(seconds=120)


async def test_reload_before_the_start_keeps_the_announcement(hass, freezer):
    """The bug of v0.3.7: Home Assistant was still starting (STARTED came minutes late),
    the options were saved, the entry reloaded - and the push was gone for good."""
    freezer.move_to(DAYTIME)
    with patch(FETCH) as fetch:
        entry = await _loaded_entry(hass, fetch)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        calls = async_mock_service(hass, "notify", "send_message")
        events = async_capture_events(hass, EVENT_STATUS_CHANGED)

        hass.set_state(CoreState.starting)
        fetch.return_value = result(ParcelStatus.OUT_FOR_DELIVERY)
        freezer.tick(timedelta(hours=5))
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.store.parcels[NUMBER].status is ParcelStatus.OUT_FOR_DELIVERY
        assert events == [] and calls == []

        # Options saved while Home Assistant is still starting: the entry reloads.
        freezer.tick(timedelta(seconds=30))
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert events == [] and calls == []
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["pending_announcements"] == 1

        await _start(hass)
        assert _changes(events) == [("in_transit", "out_for_delivery")]
        assert _sent(calls) == [IN_DELIVERY]
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["pending_announcements"] == 0

        # Neither with the next reload nor with the next refresh a second time.
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        await _wait(hass, freezer, timedelta(minutes=5))
        assert len(events) == 1 and len(calls) == 1
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_announced_after_two_minutes_when_the_start_takes_longer(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    listeners = _started_listeners(hass)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert _started_listeners(hass) == listeners + 1

    await _wait(hass, freezer, timedelta(seconds=119))
    assert events == [] and calls == []

    await _wait(hass, freezer, timedelta(seconds=1))
    assert _changes(events) == [("in_transit", "out_for_delivery")]
    assert _sent(calls) == [IN_DELIVERY]
    assert _started_listeners(hass) == listeners  # no longer waiting for the start
    assert (await _stored(hass)).parcels[NUMBER].unannounced_from is None

    # Home Assistant gets there minutes later: nothing a second time.
    await _wait(hass, freezer, timedelta(minutes=4))
    await _start(hass)
    assert len(events) == 1 and len(calls) == 1
    # And everything after that is announced right away.
    await _change(hass, coord, coord.carriers["dhl"], freezer, result(ParcelStatus.DELIVERED))
    assert _changes(events)[1:] == [("out_for_delivery", "delivered")]
    assert len(calls) == 2


async def test_the_two_minutes_count_from_the_first_refresh_only(hass, freezer):
    """Later refreshes while still waiting start no second timer and move nothing."""
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    timers = _timers(hass)
    await coord.async_refresh()
    assert _timers(hass) == timers + 1
    freezer.tick(timedelta(seconds=60))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert _timers(hass) == timers + 1
    assert events == []
    await _wait(hass, freezer, timedelta(seconds=60))
    assert len(events) == 1
    assert _timers(hass) == timers


async def test_the_start_before_the_two_minutes_cancels_the_timer(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    timers = _timers(hass)
    await coord.async_refresh()
    await _start(hass)
    assert len(events) == 1
    assert _timers(hass) == timers
    await _wait(hass, freezer, timedelta(seconds=120))
    assert len(events) == 1


async def test_reload_while_running_starts_no_timer(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    timers = _timers(hass)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1  # right away, as before
    assert _timers(hass) == timers


async def _pending(hass, freezer, current=ParcelStatus.OUT_FOR_DELIVERY):
    """A coordinator after a restart: the parcel was stored as ``current`` with a change
    from "in transit" still to be announced; the carrier has nothing new."""
    coord, carrier = await _restarted(hass, freezer, result(current))
    parcel = coord.store.parcels[NUMBER]
    parcel.result = result(current)
    parcel.unannounced_from = ParcelStatus.IN_TRANSIT
    await coord.store.async_save()
    return ParcelCoordinator(hass, coord.entry, await _stored(hass), {"dhl": carrier}), carrier


async def test_restart_with_a_stored_pending_change_announces_it_once(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _pending(hass, freezer)
    assert coord.store.parcels[NUMBER].unannounced_from is ParcelStatus.IN_TRANSIT
    assert coord.diagnostics()["pending_announcements"] == 1
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert events == [] and calls == []

    await _start(hass)
    assert _changes(events) == [("in_transit", "out_for_delivery")]
    assert _sent(calls) == [IN_DELIVERY]
    assert coord.store.parcels[NUMBER].unannounced_from is None
    assert coord.diagnostics()["pending_announcements"] == 0
    assert (await _stored(hass)).parcels[NUMBER].unannounced_from is None

    # The next start has nothing left to tell.
    hass.set_state(CoreState.starting)
    again = ParcelCoordinator(hass, coord.entry, await _stored(hass), coord.carriers)
    await again.async_refresh()
    await _start(hass)
    assert len(events) == 1 and len(calls) == 1


async def test_a_stored_pending_change_and_a_new_one_are_one_announcement(hass, freezer):
    """Oldest status -> current one, also across a restart."""
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, carrier = await _pending(hass, freezer)
    carrier.answer = result(ParcelStatus.DELIVERED)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.store.parcels[NUMBER].status is ParcelStatus.DELIVERED
    assert coord.store.parcels[NUMBER].unannounced_from is ParcelStatus.IN_TRANSIT
    assert events == [] and calls == []
    await _start(hass)
    assert _changes(events) == [("in_transit", "delivered")]
    assert _sent(calls) == [(PHONE, "Paket Tracker", "✅ Kopfhörer (DHL) wurde zugestellt")]


async def test_a_stored_pending_change_is_announced_right_away_while_running(hass, freezer):
    """A reload once Home Assistant is running: with the first refresh."""
    freezer.move_to(DAYTIME)
    coord, _ = await _pending(hass, freezer)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert _changes(events) == [("in_transit", "out_for_delivery")]
    assert _sent(calls) == [IN_DELIVERY]
    assert (await _stored(hass)).parcels[NUMBER].unannounced_from is None


async def test_the_pending_change_is_stored_with_the_refresh_that_found_it(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    await coord.async_refresh()
    assert (await _stored(hass)).parcels[NUMBER].unannounced_from is ParcelStatus.IN_TRANSIT
    await coord.async_shutdown()
    # Unloading drops nothing.
    assert coord.store.parcels[NUMBER].unannounced_from is ParcelStatus.IN_TRANSIT
    assert (await _stored(hass)).parcels[NUMBER].unannounced_from is ParcelStatus.IN_TRANSIT


async def test_unload_right_after_announcing_does_not_announce_again(hass, freezer):
    """A reload between announcing and writing the store: the unload waits for the
    write, so the next coordinator reads the parcel as announced."""
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, carrier = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)  # announces; nothing awaited yet
    assert len(events) == 1
    await coord.async_shutdown()
    store = await _stored(hass)
    assert store.parcels[NUMBER].unannounced_from is None

    again = ParcelCoordinator(hass, coord.entry, store, {"dhl": carrier})
    await again.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1 and len(calls) == 1


async def test_parcel_removed_while_pending_is_not_announced(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    assert coord.diagnostics()["pending_announcements"] == 1
    await coord.async_remove(NUMBER)
    assert coord.diagnostics()["pending_announcements"] == 0
    await _start(hass)
    assert events == [] and calls == []
    assert NUMBER not in (await _stored(hass)).parcels


async def test_parcel_back_at_its_old_status_while_pending_is_not_announced(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, carrier = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.IN_TRANSIT))
    assert coord.store.parcels[NUMBER].unannounced_from is None
    assert coord.diagnostics()["pending_announcements"] == 0
    assert (await _stored(hass)).parcels[NUMBER].unannounced_from is None
    await _start(hass)
    assert events == [] and calls == []


async def test_a_stored_marker_equal_to_the_status_is_dropped_quietly(hass, freezer):
    """Back at the old status without a status event in between (a carrier's step back
    after 17track): nothing to tell, and the marker goes with the start."""
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _pending(hass, freezer, current=ParcelStatus.IN_TRANSIT)
    assert coord.diagnostics()["pending_announcements"] == 0
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    await _start(hass)
    assert events == [] and calls == []
    assert coord.store.parcels[NUMBER].unannounced_from is None
    assert (await _stored(hass)).parcels[NUMBER].unannounced_from is None


async def test_first_ever_result_leaves_no_marker(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.DELIVERED), first=None)
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    assert coord.store.parcels[NUMBER].status is ParcelStatus.DELIVERED
    assert coord.store.parcels[NUMBER].unannounced_from is None
    await _start(hass)
    assert events == []


async def test_no_timer_and_no_listener_left_after_unload(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    listeners = _started_listeners(hass)
    timers = _timers(hass)
    await coord.async_refresh()
    assert _timers(hass) == timers + 1
    assert _started_listeners(hass) == listeners + 1

    await coord.entry._async_process_on_unload(hass)  # what unloading the entry runs
    assert _timers(hass) == timers
    assert _started_listeners(hass) == listeners
    await _wait(hass, freezer, timedelta(seconds=120))
    await _start(hass)
    assert events == [] and calls == []
    # Kept for the next time the integration loads.
    assert (await _stored(hass)).parcels[NUMBER].unannounced_from is ParcelStatus.IN_TRANSIT


async def test_entry_unload_while_waiting_leaves_no_timer(hass, freezer):
    freezer.move_to(DAYTIME)
    with patch(FETCH) as fetch:
        entry = await _loaded_entry(hass, fetch)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        timers = _timers(hass)
        hass.set_state(CoreState.starting)
        fetch.return_value = result(ParcelStatus.OUT_FOR_DELIVERY)
        freezer.tick(timedelta(hours=5))
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert _timers(hass) == timers + 1
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert _timers(hass) == timers

"""Push notifications: sent where the status event fires, to the chosen notify entities."""

import asyncio
import gc
import logging
import warnings
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.carriers.base import Carrier, CarrierUnavailable, Match
from custom_components.parcel_tracker.const import (
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    DOMAIN,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.coordinator import (
    NOTIFY_TIMEOUT,
    ParcelCoordinator,
    _ParsedMail,
)
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME

PHONE = "notify.mobile_app_handy"
TABLET = "notify.tablet"
NUMBER = "00340434161094042557"
CODE = "847261"


def result(status, **fields):
    values = {
        "status_text": "Carrier-Text mit Ablageort Garage",
        "eta_date": None,
        "eta_from": None,
        "eta_to": None,
        "location": "Bonn",
        "pickup_point": None,
        "pickup_until": None,
        "delivered_at": None,
    }
    values.update(fields)
    return TrackingResult(status, **values)


class FakeCarrier(Carrier):
    key = "dhl"
    name = "DHL"

    def __init__(self):
        self.answer = None

    @staticmethod
    def matches(number):
        return Match.SURE

    async def fetch(self, number, postcode):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def _setup(hass, options=None, mailbox=None, targets=(PHONE, TABLET)):
    """A coordinator past its first refresh, with one parcel in transit."""
    if options is None:
        options = {CONF_NOTIFY_TARGETS: [PHONE, TABLET]}
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"}, options=options)
    entry.add_to_hass(hass)
    for entity_id in targets:
        hass.states.async_set(entity_id, "unknown")
    store = ParcelStore(hass)
    await store.async_load()
    carrier = FakeCarrier()
    coord = ParcelCoordinator(hass, entry, store, {"dhl": carrier}, mailbox)
    carrier.answer = result(ParcelStatus.IN_TRANSIT)
    parcel = await coord.async_add(NUMBER, "dhl", "Kopfhörer")
    await coord.async_refresh()  # the first refresh: nothing new
    await hass.async_block_till_done()
    return coord, carrier, parcel


async def _change(hass, coord, carrier, freezer, answer):
    carrier.answer = answer
    freezer.tick(timedelta(hours=5))
    await coord.async_refresh()
    await hass.async_block_till_done()


def _warnings(caplog) -> list[logging.LogRecord]:
    """Warnings (and worse) of the integration itself."""
    return [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and r.name.startswith("custom_components.parcel_tracker")
    ]


def _sent(calls) -> list[tuple[str, str, str]]:
    sent = []
    for call in calls:
        targets = call.data["entity_id"]
        for target in [targets] if isinstance(targets, str) else targets:
            sent.append((target, call.data.get("title"), call.data["message"]))
    return sorted(sent)


async def test_sends_once_per_change_to_every_target(hass, freezer):
    freezer.move_to(DAYTIME)
    await hass.config.async_set_time_zone("Europe/Berlin")
    coord, carrier, _ = await _setup(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    now = dt_util.now()
    await _change(
        hass, coord, carrier, freezer,
        result(
            ParcelStatus.OUT_FOR_DELIVERY,
            eta_date=now.date(),
            eta_from=now.replace(hour=18, minute=0),
            eta_to=now.replace(hour=20, minute=0),
        ),
    )
    message = "📦 Kopfhörer (DHL) ist in Zustellung – heute 18:00–20:00 Uhr"
    assert _sent(calls) == [(PHONE, "Paket Tracker", message), (TABLET, "Paket Tracker", message)]
    assert len(events) == 1
    assert (events[0].data["carrier"], events[0].data["carrier_name"]) == ("dhl", "DHL")
    for call in calls:
        assert set(call.data) == {"entity_id", "title", "message"}

    # Same status again: neither an event nor a notification.
    freezer.tick(timedelta(hours=1))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(_sent(calls)) == 2

    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert len(_sent(calls)) == 4
    assert {m for _, _, m in _sent(calls)} == {message, "✅ Kopfhörer (DHL) wurde zugestellt"}
    assert len(events) == 2


async def _restarted(hass, freezer, answer, options=None, first=ParcelStatus.IN_TRANSIT):
    """A new coordinator before its first refresh: the parcel is stored as in transit
    (``first``) and due, while the carrier now answers ``answer``."""
    if options is None:
        options = {CONF_NOTIFY_TARGETS: [PHONE]}
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"}, options=options)
    entry.add_to_hass(hass)
    hass.states.async_set(PHONE, "unknown")
    carrier = FakeCarrier()
    before = ParcelStore(hass)
    await before.async_load()
    carrier.answer = result(first) if first is not None else CarrierUnavailable("down")
    await ParcelCoordinator(hass, entry, before, {"dhl": carrier}).async_add(
        NUMBER, "dhl", "Kopfhörer"
    )
    store = ParcelStore(hass)  # what a start reads back from disk
    await store.async_load()
    assert store.parcels[NUMBER] is not before.parcels[NUMBER]
    assert store.parcels[NUMBER].status is first
    carrier.answer = answer
    freezer.tick(timedelta(hours=5))
    return ParcelCoordinator(hass, entry, store, {"dhl": carrier}), carrier


def _started_listeners(hass) -> int:
    return hass.bus.async_listeners().get(EVENT_HOMEASSISTANT_STARTED, 0)


async def _start(hass) -> None:
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()


async def test_delivered_during_a_restart_is_announced_once_after_the_start(hass, freezer):
    """Found by the first refresh, sent once Home Assistant has started (automations
    and notify targets are loaded by then)."""
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.DELIVERED))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    listeners = _started_listeners(hass)

    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.store.parcels[NUMBER].status is ParcelStatus.DELIVERED
    assert events == [] and calls == []
    assert _started_listeners(hass) == listeners + 1

    # Further refreshes while Home Assistant is still starting: still waiting, once.
    freezer.tick(timedelta(minutes=1))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert events == [] and calls == []
    assert _started_listeners(hass) == listeners + 1

    await _start(hass)
    assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
        ("in_transit", "delivered")
    ]
    assert _sent(calls) == [(PHONE, "Paket Tracker", "✅ Kopfhörer (DHL) wurde zugestellt")]
    assert _started_listeners(hass) == 0  # one-time listeners: all gone with the start

    freezer.tick(timedelta(hours=5))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1 and len(calls) == 1


async def test_several_changes_while_starting_are_one_announcement(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, carrier = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert events == [] and calls == []
    await _start(hass)
    assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
        ("in_transit", "delivered")
    ]
    assert _sent(calls) == [(PHONE, "Paket Tracker", "✅ Kopfhörer (DHL) wurde zugestellt")]


async def test_first_refresh_while_running_announces_right_away(hass, freezer):
    """A reload (e.g. after saving the options) while Home Assistant is running."""
    freezer.move_to(DAYTIME)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.DELIVERED))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    listeners = _started_listeners(hass)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1 and events[0].data["new_status"] == "delivered"
    assert _sent(calls) == [(PHONE, "Paket Tracker", "✅ Kopfhörer (DHL) wurde zugestellt")]
    assert _started_listeners(hass) == listeners
    freezer.tick(timedelta(hours=5))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1 and len(calls) == 1


async def test_first_refresh_keeps_the_rules_of_later_ones(hass, freezer):
    """Same status as stored, or a not ticked event: nothing, resp. only the event."""
    freezer.move_to(DAYTIME)
    coord, carrier = await _restarted(hass, freezer, result(ParcelStatus.IN_TRANSIT))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert events == [] and calls == []


async def test_first_refresh_does_not_announce_a_step_back_after_17track(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.IN_TRANSIT))
    # Stored: what 17track alone had shown before the carrier answered at all.
    coord.store.parcels[NUMBER].result = result(
        ParcelStatus.OUT_FOR_DELIVERY, enriched=("status",)
    )
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.store.parcels[NUMBER].status is ParcelStatus.IN_TRANSIT
    assert events == [] and calls == []


async def test_first_ever_result_on_the_first_refresh_is_not_announced(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.DELIVERED), first=None)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.store.parcels[NUMBER].status is ParcelStatus.DELIVERED
    assert events == [] and calls == []


async def test_unload_before_the_start_sends_nothing_and_leaves_no_listener(hass, freezer):
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.DELIVERED))
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    listeners = _started_listeners(hass)
    await coord.async_refresh()
    assert _started_listeners(hass) == listeners + 1

    await coord.entry._async_process_on_unload(hass)  # what unloading the entry runs
    assert _started_listeners(hass) == listeners
    await _start(hass)
    assert events == [] and calls == []


FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"


async def _loaded_entry(hass, fetch):
    """The integration set up for real, with one DHL parcel in transit."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"postcode": "10115"}, options={CONF_NOTIFY_TARGETS: [PHONE]}
    )
    entry.add_to_hass(hass)
    hass.states.async_set(PHONE, "unknown")
    fetch.return_value = result(ParcelStatus.IN_TRANSIT)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_add(NUMBER, "dhl", "Kopfhörer")
    return entry


async def test_reload_while_running_announces_what_the_first_refresh_finds(hass, freezer):
    """Saving the options reloads the integration; a parcel delivered right then must
    not get lost."""
    freezer.move_to(DAYTIME)
    with patch(FETCH) as fetch:
        entry = await _loaded_entry(hass, fetch)
        calls = async_mock_service(hass, "notify", "send_message")
        events = async_capture_events(hass, EVENT_STATUS_CHANGED)
        listeners = _started_listeners(hass)
        fetch.return_value = result(ParcelStatus.DELIVERED)
        freezer.tick(timedelta(hours=5))
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
            ("in_transit", "delivered")
        ]
        assert _sent(calls) == [
            (PHONE, "Paket Tracker", "✅ Kopfhörer (DHL) wurde zugestellt")
        ]
        assert _started_listeners(hass) == listeners
        # And not a second time with the next reload.
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert len(events) == 1 and len(calls) == 1


async def test_setup_while_starting_and_unload_leaves_no_listener(hass, freezer):
    freezer.move_to(DAYTIME)
    with patch(FETCH) as fetch:
        entry = await _loaded_entry(hass, fetch)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        calls = async_mock_service(hass, "notify", "send_message")
        events = async_capture_events(hass, EVENT_STATUS_CHANGED)
        listeners = _started_listeners(hass)

        hass.set_state(CoreState.starting)
        fetch.return_value = result(ParcelStatus.DELIVERED)
        freezer.tick(timedelta(hours=5))
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.store.parcels[NUMBER].status is ParcelStatus.DELIVERED
        assert events == [] and calls == []
        waiting = _started_listeners(hass)
        assert waiting > listeners

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert _started_listeners(hass) == waiting - 1
        await _start(hass)
        assert events == [] and calls == []


async def test_default_events_are_out_for_delivery_and_delivered(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, carrier, _ = await _setup(hass, {CONF_NOTIFY_TARGETS: [PHONE]})
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.EXCEPTION))
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.AWAITING_PICKUP))
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.AT_DELIVERY_DEPOT))
    assert len(events) == 3 and calls == []
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert [m for _, _, m in _sent(calls)] == [
        "✅ Kopfhörer (DHL) wurde zugestellt",
        "📦 Kopfhörer (DHL) ist in Zustellung",
    ]


async def test_only_the_chosen_events(hass, freezer):
    freezer.move_to(DAYTIME)
    options = {
        CONF_NOTIFY_TARGETS: [PHONE],
        CONF_NOTIFY_EVENTS: ["awaiting_pickup", "exception"],
    }
    coord, carrier, _ = await _setup(hass, options)
    calls = async_mock_service(hass, "notify", "send_message")
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    assert calls == []
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.EXCEPTION))
    await _change(
        hass, coord, carrier, freezer,
        result(ParcelStatus.AWAITING_PICKUP, pickup_point="Bonn", pickup_until=date(2026, 10, 6)),
    )
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert [m for _, _, m in _sent(calls)] == [
        "⚠️ Kopfhörer (DHL): Problem bei der Zustellung",
        "📍 Kopfhörer (DHL) liegt zur Abholung bereit – Bonn bis 06.10.",
    ]


@pytest.mark.parametrize(
    "options",
    [{}, {CONF_NOTIFY_TARGETS: []}, {CONF_NOTIFY_TARGETS: [PHONE], CONF_NOTIFY_EVENTS: []}],
    ids=["never-set", "no-targets", "no-events"],
)
async def test_off_without_targets_or_events(hass, freezer, options):
    freezer.move_to(DAYTIME)
    coord, carrier, _ = await _setup(hass, options)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert len(events) == 1 and calls == []


async def test_no_notification_for_a_step_back_when_the_carrier_takes_over(hass, freezer):
    """17track was ahead; the carrier's first own answer is older: no event, no push."""
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass, {CONF_NOTIFY_TARGETS: [PHONE]})
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    # What 17track alone had shown (and announced) before the carrier answered at all.
    parcel.result = result(ParcelStatus.OUT_FOR_DELIVERY, enriched=("status",))

    await _change(hass, coord, carrier, freezer, result(ParcelStatus.IN_TRANSIT))
    assert parcel.status is ParcelStatus.IN_TRANSIT
    assert events == [] and calls == []

    # The carrier catches up to what was already announced: not a second time.
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    assert events == [] and calls == []

    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert len(events) == 1
    assert _sent(calls) == [(PHONE, "Paket Tracker", "✅ Kopfhörer (DHL) wurde zugestellt")]


async def test_a_failing_target_disturbs_nothing(hass, freezer, caplog):
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass)
    parcel.delivery_code, parcel.delivery_code_day = CODE, dt_util.now().date()
    delivered: list[str] = []

    async def send(call: ServiceCall) -> None:
        targets = call.data["entity_id"]
        if PHONE in targets:
            raise HomeAssistantError("device not connected")
        delivered.extend([targets] if isinstance(targets, str) else targets)

    hass.services.async_register("notify", "send_message", send)
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    with caplog.at_level(logging.WARNING):
        await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert delivered == [TABLET]  # the other target still got it
    assert coord.last_update_success
    assert parcel.status is ParcelStatus.DELIVERED and len(events) == 1
    warnings = _warnings(caplog)
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    text = warnings[0].getMessage()
    assert "HomeAssistantError" in text
    for private in (NUMBER, NUMBER[-4:], "Kopfhörer", CODE, "Bonn", "Garage", PHONE, TABLET,
                    "handy", "zugestellt"):
        assert private not in text, private


async def test_missing_notify_service_is_only_a_warning(hass, freezer, caplog):
    """The notify integration is not loaded at all: the refresh still works."""
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass)
    with caplog.at_level(logging.WARNING):
        await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert coord.last_update_success and parcel.status is ParcelStatus.DELIVERED
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert NUMBER not in warnings[0].getMessage() and "Kopfhörer" not in warnings[0].getMessage()


async def test_removed_or_unavailable_targets_are_skipped(hass, freezer, caplog):
    freezer.move_to(DAYTIME)
    options = {CONF_NOTIFY_TARGETS: [PHONE, "notify.altes_handy", TABLET]}
    coord, carrier, _ = await _setup(hass, options)
    hass.states.async_set(TABLET, "unavailable")
    calls = async_mock_service(hass, "notify", "send_message")
    with caplog.at_level(logging.WARNING):
        await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert _sent(calls) == [(PHONE, "Paket Tracker", "✅ Kopfhörer (DHL) wurde zugestellt")]
    assert _warnings(caplog) == []


class FakeMailbox:
    def __init__(self):
        self.mails: list = []

    def fetch_unseen(self):
        mails, self.mails = self.mails, []
        return mails

    def finish(self, dispositions, move):
        pass


async def test_status_change_from_a_mail_is_announced_the_same_way(hass, freezer):
    freezer.move_to(DAYTIME)
    mailbox = FakeMailbox()
    coord, _, parcel = await _setup(hass, {CONF_NOTIFY_TARGETS: [PHONE]}, mailbox)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    update = MailUpdate(
        NUMBER, "dhl", ParcelStatus.DELIVERED, dt_util.now(),
        delivered_at=datetime.fromisoformat(DAYTIME), delivery_code=CODE,
    )
    parsed = [_ParsedMail(message_id="<m1@example.org>", result=MailResult(updates=[update]))]
    mailbox.mails = [("1", b"raw")]
    coord._mail_next = None
    with patch("custom_components.parcel_tracker.coordinator._parse_mails", return_value=parsed):
        await coord.async_import_mail()
    await hass.async_block_till_done()
    assert parcel.status is ParcelStatus.DELIVERED
    assert len(events) == 1
    assert _sent(calls) == [(PHONE, "Paket Tracker", "✅ Kopfhörer (DHL) wurde zugestellt")]


async def test_parcel_without_a_name_is_told_by_its_last_digits_only(hass, freezer):
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass, {CONF_NOTIFY_TARGETS: [PHONE]})
    parcel.name = None
    calls = async_mock_service(hass, "notify", "send_message")
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    (sent,) = _sent(calls)
    assert sent[2] == "✅ Paket …2557 (DHL) wurde zugestellt"
    assert NUMBER not in sent[2]


def test_parcel_model_is_unchanged():
    """Nothing about notifications is stored with a parcel."""
    now = datetime.fromisoformat(DAYTIME)
    assert not [key for key in Parcel(NUMBER, "dhl", "manual", None, now, now).to_dict()
                if "notif" in key]


@pytest.mark.parametrize(
    "options",
    [
        {CONF_NOTIFY_TARGETS: [PHONE], CONF_NOTIFY_EVENTS: None},
        {CONF_NOTIFY_TARGETS: [PHONE], CONF_NOTIFY_EVENTS: 7},
        {CONF_NOTIFY_TARGETS: 7},
    ],
    ids=["events-none", "events-odd", "targets-odd"],
)
async def test_odd_stored_settings_never_break_the_refresh(hass, freezer, options):
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass, options)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert coord.last_update_success and parcel.status is ParcelStatus.DELIVERED
    assert len(events) == 1 and calls == []


async def test_a_text_that_cannot_be_built_never_breaks_the_refresh(hass, freezer, caplog):
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    with (
        patch(
            "custom_components.parcel_tracker.coordinator.build_notification",
            side_effect=ValueError(f"oops {NUMBER}"),
        ),
        caplog.at_level(logging.WARNING),
    ):
        await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    assert coord.last_update_success and parcel.status is ParcelStatus.DELIVERED
    assert calls == []
    (warning,) = _warnings(caplog)
    assert "ValueError" in warning.getMessage() and NUMBER not in warning.getMessage()


async def test_a_task_that_cannot_be_started_never_breaks_the_refresh(hass, freezer, caplog):
    """Nothing is left un-awaited either (that would be a RuntimeWarning)."""
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    with (
        patch.object(coord.entry, "async_create_task", side_effect=RuntimeError(NUMBER)),
        caplog.at_level(logging.WARNING),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
        gc.collect()
    assert coord.last_update_success and parcel.status is ParcelStatus.DELIVERED
    assert len(events) == 1 and calls == []
    assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []
    (warning,) = _warnings(caplog)
    assert "RuntimeError" in warning.getMessage() and NUMBER not in warning.getMessage()


async def test_a_target_that_hangs_counts_as_failed(hass, freezer, caplog):
    assert NOTIFY_TIMEOUT == 30
    freezer.move_to(DAYTIME)
    coord, carrier, parcel = await _setup(hass)
    delivered: list[str] = []
    cancelled: list[str] = []

    async def send(call: ServiceCall) -> None:
        targets = call.data["entity_id"]
        if PHONE in targets:
            try:
                await asyncio.Event().wait()  # never answers
            finally:
                cancelled.append(PHONE)
        delivered.extend([targets] if isinstance(targets, str) else targets)

    hass.services.async_register("notify", "send_message", send)

    async def spin() -> None:
        for _ in range(20):
            await asyncio.sleep(0)

    with caplog.at_level(logging.WARNING):
        carrier.answer = result(ParcelStatus.DELIVERED)
        freezer.tick(timedelta(hours=5))
        await coord.async_refresh()
        await spin()
        assert delivered == [TABLET] and cancelled == []
        freezer.tick(timedelta(seconds=NOTIFY_TIMEOUT - 1))
        await spin()
        assert cancelled == [] and _warnings(caplog) == []  # still within its 30 seconds
        freezer.tick(timedelta(seconds=2))
        await hass.async_block_till_done()
    assert delivered == [TABLET] and cancelled == [PHONE]
    assert coord.last_update_success and parcel.status is ParcelStatus.DELIVERED
    (warning,) = _warnings(caplog)
    text = warning.getMessage()
    assert "1 of 2" in text and "TimeoutError" in text
    for private in (NUMBER, NUMBER[-4:], "Kopfhörer", PHONE, TABLET, "handy", "zugestellt"):
        assert private not in text, private


async def test_real_notify_send_message_accepts_the_call(hass, freezer):
    """Against Home Assistant's own ``notify.send_message`` (schema: message and title
    only) and real notify entities, one with and one without title support."""
    from homeassistant.components.notify import (
        DATA_COMPONENT,
        NotifyEntity,
        NotifyEntityFeature,
    )
    from homeassistant.setup import async_setup_component

    received: list[tuple[str, str, str | None]] = []

    class Target(NotifyEntity):
        def __init__(self, object_id: str, title: bool) -> None:
            self.entity_id = f"notify.{object_id}"
            self._attr_unique_id = object_id
            if title:
                self._attr_supported_features = NotifyEntityFeature.TITLE

        async def async_send_message(self, message: str, title: str | None = None) -> None:
            received.append((self.entity_id, message, title))

    freezer.move_to(DAYTIME)
    assert await async_setup_component(hass, "notify", {})
    await hass.async_block_till_done()
    await hass.data[DATA_COMPONENT].async_add_entities(
        [Target("mobile_app_handy", True), Target("tablet", False)]
    )
    coord, carrier, _ = await _setup(hass, targets=())
    await _change(hass, coord, carrier, freezer, result(ParcelStatus.DELIVERED))
    message = "✅ Kopfhörer (DHL) wurde zugestellt"
    assert sorted(received) == [
        (PHONE, message, "Paket Tracker"),
        (TABLET, message, "Paket Tracker"),
    ]
    # Home Assistant itself notes the time of the last notification on the entity.
    assert hass.states.get(PHONE).state not in ("unknown", "unavailable")


async def test_notify_send_message_takes_no_data(hass):
    """Why there is no dashboard path in the options: ``notify.send_message`` knows only
    ``message`` and ``title``; ``data`` (tag, url, clickAction) is rejected. Should a later
    Home Assistant accept it, this test fails and the option can be added."""
    import voluptuous as vol
    from homeassistant.components.notify import DATA_COMPONENT, NotifyEntity
    from homeassistant.setup import async_setup_component

    class Target(NotifyEntity):
        entity_id = PHONE
        _attr_unique_id = "handy"

        async def async_send_message(self, message: str, title: str | None = None) -> None:
            raise AssertionError("must not be reached")

    assert await async_setup_component(hass, "notify", {})
    await hass.async_block_till_done()
    await hass.data[DATA_COMPONENT].async_add_entities([Target()])
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": PHONE, "message": "x", "data": {"tag": "t", "url": "/lovelace"}},
            blocking=True,
        )

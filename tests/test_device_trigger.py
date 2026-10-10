"""Device triggers: the status event, offered by the automation editor."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_get_device_automations,
    async_mock_service,
)

from custom_components.parcel_tracker.const import (
    CONF_POSTCODE,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    NOTIFY_EVENTS,
)
from custom_components.parcel_tracker.device_trigger import TRIGGER_TYPES, async_get_triggers
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

from .conftest import DAYTIME

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
NOW = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
NUMBER = "00340999999999999901"
TYPES = ("out_for_delivery", "delivered", "awaiting_pickup", "exception", "status_changed")


def _result(status=ParcelStatus.IN_TRANSIT):
    return TrackingResult(status, "Text", None, None, None, "Bonn", None, None, None, [])


async def _setup(hass, hass_storage, parcels=()):
    hass_storage[DOMAIN] = {
        "version": 1,
        "minor_version": 1,
        "key": DOMAIN,
        "data": {"parcels": [p.to_dict() for p in parcels]},
    }
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_result()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return entry, device


async def _automations(hass, device_id, types=TYPES):
    """One automation per trigger type; each calls test.automation with what it saw."""
    calls = async_mock_service(hass, "test", "automation")
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "alias": kind,
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": device_id,
                        "type": kind,
                    },
                    "action": {
                        "service": "test.automation",
                        "data_template": {
                            "type": kind,
                            "platform": "{{ trigger.platform }}",
                            "name": "{{ trigger.event.data.name }}",
                            "number": "{{ trigger.event.data.number }}",
                            "carrier": "{{ trigger.event.data.carrier }}",
                            "old": "{{ trigger.event.data.old_status }}",
                            "new": "{{ trigger.event.data.new_status }}",
                        },
                    },
                }
                for kind in types
            ]
        },
    )
    await hass.async_block_till_done()
    return calls


def _event(entry_id, new, old="in_transit", assumed=False):
    """The status event as the coordinator fires it."""
    return {
        "entry_id": entry_id,
        "number": NUMBER,
        "name": "Oma",
        "carrier": "dhl",
        "carrier_name": "DHL",
        "old_status": old,
        "new_status": new,
        "eta_date": None,
        "eta_from": None,
        "eta_to": None,
        "location": "Bonn",
        "assumed": assumed,
    }


async def _fire(hass, calls, data):
    calls.clear()
    hass.bus.async_fire(EVENT_STATUS_CHANGED, data)
    await hass.async_block_till_done()
    return sorted(call.data["type"] for call in calls)


def test_trigger_types_cover_the_statuses_a_notification_can_announce():
    assert tuple(TRIGGER_TYPES) == TYPES
    assert TRIGGER_TYPES[: len(NOTIFY_EVENTS)] == NOTIFY_EVENTS


async def test_the_device_offers_the_five_triggers(hass, hass_storage):
    _entry, device = await _setup(hass, hass_storage)

    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)

    assert [t for t in triggers if t["domain"] == DOMAIN] == [
        {
            "platform": "device",
            "domain": DOMAIN,
            "device_id": device.id,
            "type": kind,
            "metadata": {},
        }
        for kind in TYPES
    ]


async def test_another_device_offers_no_trigger_of_ours(hass, hass_storage):
    await _setup(hass, hass_storage)
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "x")}
    )

    assert await async_get_triggers(hass, device.id) == []
    assert await async_get_triggers(hass, "no-such-device") == []


@pytest.mark.parametrize("status", NOTIFY_EVENTS)
async def test_a_status_fires_its_trigger_and_the_generic_one(hass, hass_storage, status):
    entry, device = await _setup(hass, hass_storage)
    calls = await _automations(hass, device.id)

    assert await _fire(hass, calls, _event(entry.entry_id, status)) == sorted(
        [status, "status_changed"]
    )
    # The event data is there for the automation: trigger.event.data.<field>.
    call = next(c for c in calls if c.data["type"] == status)
    assert call.data["platform"] == "device"
    assert call.data["name"] == "Oma"
    assert call.data["number"] == NUMBER
    assert call.data["carrier"] == "dhl"
    assert (call.data["old"], call.data["new"]) == ("in_transit", status)


@pytest.mark.parametrize("status", ["pre_transit", "in_transit", "at_delivery_depot", "unknown"])
async def test_other_statuses_fire_only_the_generic_trigger(hass, hass_storage, status):
    entry, device = await _setup(hass, hass_storage)
    calls = await _automations(hass, device.id)

    assert await _fire(hass, calls, _event(entry.entry_id, status, old="exception")) == [
        "status_changed"
    ]


async def test_assumed_delivery_does_not_fire_delivered(hass, hass_storage):
    entry, device = await _setup(hass, hass_storage)
    calls = await _automations(hass, device.id)

    assumed = _event(entry.entry_id, "delivered", assumed=True)
    assert await _fire(hass, calls, assumed) == ["status_changed"]
    assert await _fire(hass, calls, _event(entry.entry_id, "delivered")) == [
        "delivered", "status_changed"
    ]


async def test_events_of_another_entry_or_without_one_fire_nothing(hass, hass_storage):
    _entry, device = await _setup(hass, hass_storage)
    calls = await _automations(hass, device.id)

    assert await _fire(hass, calls, _event("another-entry", "delivered")) == []
    without = _event("x", "delivered")
    del without["entry_id"]
    assert await _fire(hass, calls, without) == []


async def test_a_real_status_change_fires_the_trigger(hass, hass_storage, freezer):
    """End to end: the coordinator's own event carries what the trigger filters by."""
    freezer.move_to(DAYTIME)
    parcel = Parcel(NUMBER, "dhl", "manual", "Oma", NOW, NOW, result=_result())
    entry, device = await _setup(hass, hass_storage, [parcel])
    calls = await _automations(hass, device.id)

    with patch(FETCH, return_value=_result(ParcelStatus.OUT_FOR_DELIVERY)):
        await hass.services.async_call(DOMAIN, "refresh", {"number": NUMBER}, blocking=True)
        await hass.async_block_till_done()

    assert sorted(call.data["type"] for call in calls) == ["out_for_delivery", "status_changed"]
    assert {call.data["name"] for call in calls} == {"Oma"}


async def test_the_event_names_its_config_entry(hass, hass_storage, freezer):
    freezer.move_to(DAYTIME)
    parcel = Parcel(NUMBER, "dhl", "manual", "Oma", NOW, NOW, result=_result())
    entry, _device = await _setup(hass, hass_storage, [parcel])
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)

    with patch(FETCH, return_value=_result(ParcelStatus.DELIVERED)):
        await hass.services.async_call(DOMAIN, "refresh", {"number": NUMBER}, blocking=True)
        await hass.async_block_till_done()

    # Additive: the fields of v0.3.26 are all still there, unchanged.
    assert events[0].data == _event(entry.entry_id, "delivered")


async def test_unloading_the_automation_detaches_the_trigger(hass, hass_storage):
    entry, device = await _setup(hass, hass_storage)
    calls = await _automations(hass, device.id, types=("delivered",))
    assert await _fire(hass, calls, _event(entry.entry_id, "delivered")) == ["delivered"]

    await hass.services.async_call(
        automation.DOMAIN, "turn_off", {"entity_id": "automation.delivered"}, blocking=True
    )
    assert await _fire(hass, calls, _event(entry.entry_id, "delivered")) == []

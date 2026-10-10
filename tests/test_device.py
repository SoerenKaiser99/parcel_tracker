"""The service device "Paket Tracker" (v0.3.27) and what it must not change.

One device per config entry, so the automation editor can offer device triggers. It has
no entities: entity ids, unique ids and names stay exactly those of v0.3.26, for an
installation that already has them in the entity registry and for a fresh one.
"""

from datetime import UTC, datetime
from unittest.mock import patch

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN, VERSION
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
NUMBER = "00340999999999999901"
ENTRY_ID = "0123456789abcdef0123456789abcdef"

# As v0.3.26 registered them: (entity id, unique-id suffix, name).
ENTITIES = (
    ("sensor.pakete_heute", "today", "Pakete heute"),
    ("sensor.pakete_unterwegs", "active", "Pakete unterwegs"),
    ("sensor.pakete_moeglich", "possible", "Pakete möglich"),
    ("sensor.pakete_zugestellt_heute", "delivered_today", "Pakete zugestellt heute"),
    ("sensor.pakete_abholbereit", "awaiting_pickup", "Pakete abholbereit"),
    (
        "sensor.paket_tracker_17track_kontingent",
        "track17_quota",
        "Paket Tracker 17track-Kontingent",
    ),
    (f"sensor.paket_{NUMBER}", NUMBER, "Oma"),
    ("calendar.pakete", "calendar", "Pakete"),
)


def _result():
    return TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, "Bonn", None, None, None, []
    )


def _entry(hass, hass_storage):
    hass_storage[DOMAIN] = {
        "version": 1,
        "minor_version": 1,
        "key": DOMAIN,
        "data": {
            "parcels": [
                Parcel(NUMBER, "dhl", "manual", "Oma", NOW, NOW, result=_result()).to_dict()
            ]
        },
    }
    entry = MockConfigEntry(
        domain=DOMAIN, entry_id=ENTRY_ID, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"}
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass, entry):
    with patch(FETCH, return_value=_result()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _registered(hass):
    registry = er.async_get(hass)
    found = {}
    for reg in er.async_entries_for_config_entry(registry, ENTRY_ID):
        assert reg.unique_id.startswith(f"{ENTRY_ID}_")
        state = hass.states.get(reg.entity_id)
        # 17track without a key is unavailable; its name is in the registry all the same.
        name = state.attributes["friendly_name"] if state else None
        assert reg.has_entity_name is False
        found[reg.entity_id] = (reg.unique_id.removeprefix(f"{ENTRY_ID}_"), name)
    return found


def _device(hass):
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), ENTRY_ID)
    return devices[0] if devices else None


async def test_fresh_installation_gets_the_entity_ids_of_v0_3_26(hass, hass_storage):
    await _setup(hass, _entry(hass, hass_storage))

    assert _registered(hass) == {entity_id: (suffix, name) for entity_id, suffix, name in ENTITIES}


async def test_existing_installation_keeps_ids_unique_ids_and_names(hass, hass_storage):
    entry = _entry(hass, hass_storage)
    registry = er.async_get(hass)
    # The entity registry as v0.3.26 left it: no device anywhere.
    before = {}
    for entity_id, suffix, _name in ENTITIES:
        platform, object_id = entity_id.split(".")
        reg = registry.async_get_or_create(
            platform,
            DOMAIN,
            f"{ENTRY_ID}_{suffix}",
            suggested_object_id=object_id,
            config_entry=entry,
        )
        assert reg.entity_id == entity_id and reg.device_id is None
        before[reg.id] = (reg.entity_id, reg.unique_id)
    assert dr.async_entries_for_config_entry(dr.async_get(hass), ENTRY_ID) == []

    await _setup(hass, entry)

    assert _registered(hass) == {entity_id: (suffix, name) for entity_id, suffix, name in ENTITIES}
    # The very same registry entries (history and customisations hang on them) …
    after = {
        reg.id: (reg.entity_id, reg.unique_id)
        for reg in er.async_entries_for_config_entry(registry, ENTRY_ID)
    }
    assert after == before
    # … and none of them on the device: its name would get into theirs.
    assert _device(hass) is not None
    assert {
        reg.device_id for reg in er.async_entries_for_config_entry(registry, ENTRY_ID)
    } == {None}


async def test_an_entity_id_the_user_changed_stays(hass, hass_storage):
    entry = _entry(hass, hass_storage)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor", DOMAIN, f"{ENTRY_ID}_today", suggested_object_id="meine_pakete",
        config_entry=entry,
    )

    await _setup(hass, entry)

    assert registry.async_get_entity_id("sensor", DOMAIN, f"{ENTRY_ID}_today") == (
        "sensor.meine_pakete"
    )
    assert hass.states.get("sensor.meine_pakete").attributes["friendly_name"] == "Pakete heute"
    assert hass.states.get("sensor.pakete_heute") is None


async def test_one_service_device_per_entry(hass, hass_storage):
    entry = _entry(hass, hass_storage)
    await _setup(hass, entry)

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), ENTRY_ID)
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, ENTRY_ID)}
    assert device.name == "Paket Tracker"
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.manufacturer == "Paket Tracker"
    assert device.model == "Sendungsverfolgung"
    assert device.sw_version == VERSION


async def test_removing_a_parcel_removes_its_sensor_and_keeps_the_device(hass, hass_storage):
    entry = _entry(hass, hass_storage)
    await _setup(hass, entry)
    device = _device(hass)
    registry = er.async_get(hass)
    assert registry.async_get(f"sensor.paket_{NUMBER}").device_id is None

    await hass.services.async_call(DOMAIN, "remove_parcel", {"number": NUMBER}, blocking=True)
    await hass.async_block_till_done()

    assert registry.async_get(f"sensor.paket_{NUMBER}") is None
    assert hass.states.get(f"sensor.paket_{NUMBER}") is None
    assert _device(hass).id == device.id
    assert er.async_entries_for_device(registry, device.id) == []


async def test_removing_the_entry_removes_the_device(hass, hass_storage):
    entry = _entry(hass, hass_storage)
    await _setup(hass, entry)
    assert _device(hass) is not None

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert _device(hass) is None


async def test_reload_keeps_device_and_entities(hass, hass_storage):
    entry = _entry(hass, hass_storage)
    await _setup(hass, entry)
    device = _device(hass)
    before = _registered(hass)

    with patch(FETCH, return_value=_result()):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert _device(hass).id == device.id
    assert _registered(hass) == before

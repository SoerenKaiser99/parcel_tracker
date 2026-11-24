"""Config entry 1.1 -> 1.2: the notify events of an entry that never saved them."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import (
    CONF_KEEP_DELIVERED_DAYS,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    CONF_PERSONS,
    CONF_POSTCODE,
    DEFAULT_NOTIFY_EVENTS,
    DOMAIN,
    LEGACY_NOTIFY_EVENTS,
)

SETUP = "custom_components.parcel_tracker.async_setup_entry"
PHONE = "notify.mobile_app_handy"
BASE = {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3}
ANNA = {"person": "person.anna", "addresses": ["anna@example.com"], "notify_targets": [PHONE]}


async def _set_up(hass, minor_version=1, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={**BASE, **options}, version=1,
        minor_version=minor_version,
    )
    entry.add_to_hass(hass)
    with patch(SETUP, return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


@pytest.mark.parametrize(
    "options",
    [
        {CONF_PERSONS: [ANNA]},  # the reported case: targets only under "Personen"
        {CONF_NOTIFY_TARGETS: [PHONE]},
        {CONF_NOTIFY_TARGETS: [], CONF_PERSONS: [ANNA]},
    ],
)
async def test_an_entry_with_targets_keeps_the_events_it_had(hass, options):
    """"Kommt gleich" and "Storniert" are not switched on unasked."""
    entry = await _set_up(hass, **options)
    assert entry.options[CONF_NOTIFY_EVENTS] == list(LEGACY_NOTIFY_EVENTS)
    assert "arriving_soon" not in entry.options[CONF_NOTIFY_EVENTS]
    assert "cancelled" not in entry.options[CONF_NOTIFY_EVENTS]
    assert entry.minor_version == 2
    assert {k: v for k, v in entry.options.items() if k != CONF_NOTIFY_EVENTS} == {
        **BASE, **options
    }


async def test_a_saved_choice_stays(hass):
    entry = await _set_up(hass, **{CONF_PERSONS: [ANNA], CONF_NOTIFY_EVENTS: ["delivered"]})
    assert entry.options[CONF_NOTIFY_EVENTS] == ["delivered"]
    assert entry.minor_version == 2


@pytest.mark.parametrize(
    "options",
    [
        {},
        {CONF_NOTIFY_TARGETS: []},
        {CONF_PERSONS: [{**ANNA, "notify_targets": []}]},
    ],
)
async def test_an_entry_without_targets_takes_the_default_of_the_day(hass, options):
    """Nothing was set up to keep: notifications set up later start from the default."""
    entry = await _set_up(hass, **options)
    assert CONF_NOTIFY_EVENTS not in entry.options
    assert entry.minor_version == 2
    assert dict(entry.options) == {**BASE, **options}


async def test_a_new_entry_is_not_migrated(hass):
    """An entry created by this version follows the default, "Kommt gleich" included."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3}
        )
        await hass.async_block_till_done()
    assert result["result"].minor_version == 2
    entry = await _set_up(hass, minor_version=2, **{CONF_PERSONS: [ANNA]})
    assert CONF_NOTIFY_EVENTS not in entry.options
    assert "arriving_soon" in DEFAULT_NOTIFY_EVENTS


async def test_an_entry_of_a_later_minor_version_starts_unchanged(hass):
    """Downgrade: a 1.3 entry of a later version is left as it is."""
    entry = await _set_up(hass, minor_version=3, **{CONF_PERSONS: [ANNA]})
    assert CONF_NOTIFY_EVENTS not in entry.options
    assert entry.minor_version == 3

"""Options: tick boxes that remove the saved DHL / 17track key (v0.3.48).

The tick box is only shown while a key is saved, is never stored, and wins over a new
key typed into the field above it.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.parcel_tracker
from custom_components.parcel_tracker.const import (
    CONF_DHL_API_KEY,
    CONF_DHL_API_KEY_REMOVE,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_POSTCODE,
    CONF_TRACK17_API_KEY,
    CONF_TRACK17_API_KEY_REMOVE,
    DOMAIN,
)

from .conftest import open_options

SETUP = "custom_components.parcel_tracker.async_setup_entry"
DHL_CHECK = "custom_components.parcel_tracker.config_flow.DhlCarrier.validate_key"
T17_CHECK = "custom_components.parcel_tracker.config_flow.Track17Client.getquota"

DATA = {CONF_POSTCODE: "10115", CONF_DHL_API_KEY: "dhl-key", CONF_TRACK17_API_KEY: "t17-key"}


async def _save(hass, entry, extra):
    result = await open_options(hass, entry)
    user_input = {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3, **extra}
    with (
        patch(DHL_CHECK, side_effect=AssertionError) as dhl,
        patch(T17_CHECK, side_effect=AssertionError) as t17,
        patch(SETUP, return_value=True),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    dhl.assert_not_called()
    t17.assert_not_called()
    return result


def _entry(hass, data=None):
    entry = MockConfigEntry(domain=DOMAIN, data=dict(DATA if data is None else data))
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize(
    ("key", "remove", "other"),
    [
        (CONF_DHL_API_KEY, CONF_DHL_API_KEY_REMOVE, CONF_TRACK17_API_KEY),
        (CONF_TRACK17_API_KEY, CONF_TRACK17_API_KEY_REMOVE, CONF_DHL_API_KEY),
    ],
    ids=["dhl", "track17"],
)
class TestRemoveKey:
    async def test_options_remove_key_drops_it(self, hass, key, remove, other):
        entry = _entry(hass)
        result = await _save(hass, entry, {remove: True})
        assert key not in entry.data
        assert entry.data[other] == DATA[other]
        assert remove not in result["data"]
        assert remove not in entry.options

    async def test_options_remove_wins_over_a_new_key(self, hass, key, remove, other):
        entry = _entry(hass)
        await _save(hass, entry, {remove: True, key: "new-key"})
        assert key not in entry.data

    async def test_options_empty_key_keeps_it(self, hass, key, remove, other):
        entry = _entry(hass)
        await _save(hass, entry, {key: "", remove: False})
        assert entry.data == DATA

    async def test_tick_box_only_shown_with_a_saved_key(self, hass, key, remove, other):
        result = await open_options(hass, _entry(hass))
        assert remove in result["data_schema"].schema
        entry = _entry(hass, {CONF_POSTCODE: "10115"})
        result = await open_options(hass, entry)
        assert remove not in result["data_schema"].schema


async def test_options_untouched_form_stores_no_remove_flag(hass):
    entry = _entry(hass)
    result = await open_options(hass, entry)
    defaults = {
        marker.schema: marker.default()
        for marker in result["data_schema"].schema
        if marker.default is not vol.UNDEFINED
    }
    assert defaults[CONF_DHL_API_KEY_REMOVE] is False
    assert defaults[CONF_TRACK17_API_KEY_REMOVE] is False
    result = await _save(
        hass, entry, {CONF_DHL_API_KEY_REMOVE: False, CONF_TRACK17_API_KEY_REMOVE: False}
    )
    assert entry.data == DATA
    assert not any(key.endswith("_remove") for key in result["data"])
    assert not any(key.endswith("_remove") for key in entry.options)


@pytest.mark.parametrize("name", ["strings.json", "translations/de.json", "translations/en.json"])
def test_remove_texts_are_in_the_options_settings_step(name):
    path = Path(custom_components.parcel_tracker.__file__).parent / name
    texts = json.loads(path.read_text(encoding="utf-8"))
    settings = texts["options"]["step"]["settings"]
    for part in ("data", "data_description"):
        for key in ("dhl_api_key_remove", "track17_api_key_remove"):
            assert key in settings[part], (name, part, key)
    assert "dhl_api_key_remove" not in texts["config"]["step"]["user"]["data"]

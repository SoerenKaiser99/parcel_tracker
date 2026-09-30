from unittest.mock import patch

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CARD_URL, DOMAIN, VERSION
from custom_components.parcel_tracker.lovelace_resource import (
    async_ensure_resource,
    plan_resource,
)

URL = f"{CARD_URL}?v={VERSION}"


def test_plan_resource():
    assert plan_resource([], URL) == ("create", None)
    assert plan_resource([{"id": "a", "url": "/other.js"}], URL) == ("create", None)
    assert plan_resource([{"id": "a", "url": URL}], URL) == ("none", None)
    assert plan_resource([{"id": "a", "url": f"{CARD_URL}?v=0.1.0"}], URL) == ("update", "a")
    assert plan_resource([{"id": "a", "url": CARD_URL}], URL) == ("update", "a")


def _card_items(hass):
    items = hass.data[LOVELACE_DATA].resources.async_items()
    return [i for i in items if i["url"].split("?")[0] == CARD_URL]


@pytest.fixture
async def lovelace(hass):
    assert await async_setup_component(hass, "lovelace", {})
    await hass.async_block_till_done()
    assert hass.data[LOVELACE_DATA].resource_mode == "storage"


async def test_integration_registers_resource_once(hass, lovelace):
    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    items = _card_items(hass)
    assert len(items) == 1
    assert items[0]["url"] == URL
    assert items[0]["type"] == "module"

    await async_ensure_resource(hass)
    assert len(_card_items(hass)) == 1


async def test_old_version_is_updated(hass, lovelace):
    res = hass.data[LOVELACE_DATA].resources
    await res.async_get_info()
    await res.async_create_item({"res_type": "module", "url": f"{CARD_URL}?v=0.1.0"})
    await async_ensure_resource(hass)
    items = _card_items(hass)
    assert len(items) == 1
    assert items[0]["url"] == URL


async def test_failure_only_warns(hass, lovelace, caplog):
    res = hass.data[LOVELACE_DATA].resources
    with patch.object(type(res), "async_create_item", side_effect=RuntimeError("boom")):
        await async_ensure_resource(hass)
    assert "Could not register" in caplog.text


async def test_without_lovelace_is_silent(hass, caplog):
    await async_ensure_resource(hass)
    assert "Could not register" not in caplog.text


async def test_registers_resource_when_set_up_during_startup(hass):
    from homeassistant.core import CoreState

    hass.set_state(CoreState.not_running)
    assert await async_setup_component(hass, "lovelace", {})
    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    assert _card_items(hass) == []
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    items = _card_items(hass)
    assert len(items) == 1
    assert items[0]["url"] == URL

from unittest.mock import patch

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CARD_URL, DOMAIN, LOCAL_CARD_URL, VERSION
from custom_components.parcel_tracker.lovelace_resource import (
    async_ensure_resource,
    plan_resource,
)

URL = f"{LOCAL_CARD_URL}?v={VERSION}-abcd1234"


def test_plan_resource():
    assert plan_resource([], URL) == ("create", None, [])
    assert plan_resource([{"id": "a", "url": "/other.js"}], URL) == ("create", None, [])
    assert plan_resource([{"id": "a", "url": URL}], URL) == ("none", "a", [])
    assert plan_resource([{"id": "a", "url": f"{CARD_URL}?v=0.1.4-t1"}], URL) == (
        "update",
        "a",
        [],
    )
    assert plan_resource([{"id": "a", "url": CARD_URL}], URL) == ("update", "a", [])
    dupes = [
        {"id": "a", "url": f"{CARD_URL}?v=0.1.4"},
        {"id": "b", "url": URL},
        {"id": "c", "url": f"{LOCAL_CARD_URL}?v=old"},
    ]
    assert plan_resource(dupes, URL) == ("none", "b", ["a", "c"])


def _card_items(hass):
    items = hass.data[LOVELACE_DATA].resources.async_items()
    return [i for i in items if i["url"].split("?")[0] in (CARD_URL, LOCAL_CARD_URL)]


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
    assert items[0]["url"].startswith(f"{CARD_URL}?v={VERSION}-")  # www did not exist
    assert items[0]["type"] == "module"

    await async_ensure_resource(hass, items[0]["url"])
    assert len(_card_items(hass)) == 1


async def test_old_version_is_updated(hass, lovelace):
    res = hass.data[LOVELACE_DATA].resources
    await res.async_get_info()
    await res.async_create_item({"res_type": "module", "url": f"{CARD_URL}?v=0.1.0"})
    await async_ensure_resource(hass, URL)
    items = _card_items(hass)
    assert len(items) == 1
    assert items[0]["url"] == URL


async def test_migrates_old_url_to_local(hass, lovelace):
    res = hass.data[LOVELACE_DATA].resources
    await res.async_get_info()
    await res.async_create_item({"res_type": "module", "url": f"{CARD_URL}?v=0.1.4-t1"})
    await async_ensure_resource(hass, URL)
    items = _card_items(hass)
    assert [i["url"] for i in items] == [URL]


async def test_duplicates_collapsed(hass, lovelace):
    res = hass.data[LOVELACE_DATA].resources
    await res.async_get_info()
    await res.async_create_item({"res_type": "module", "url": f"{CARD_URL}?v=0.1.4"})
    await res.async_create_item({"res_type": "module", "url": f"{LOCAL_CARD_URL}?v=x"})
    await res.async_create_item({"res_type": "module", "url": "/other.js"})
    await async_ensure_resource(hass, URL)
    assert [i["url"] for i in _card_items(hass)] == [URL]
    assert len(res.async_items()) == 2


async def test_none_creates(hass, lovelace):
    await async_ensure_resource(hass, URL)
    assert [i["url"] for i in _card_items(hass)] == [URL]


async def test_failure_only_warns(hass, lovelace, caplog):
    res = hass.data[LOVELACE_DATA].resources
    with patch.object(type(res), "async_create_item", side_effect=RuntimeError("boom")):
        await async_ensure_resource(hass, URL)
    assert "Could not register" in caplog.text


async def test_without_lovelace_is_silent(hass, caplog):
    await async_ensure_resource(hass, URL)
    assert "Could not register" not in caplog.text


async def test_registers_resource_during_startup_without_started_event(hass):
    from homeassistant.core import CoreState

    hass.set_state(CoreState.not_running)
    assert await async_setup_component(hass, "lovelace", {})
    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    items = _card_items(hass)
    assert len(items) == 1
    assert items[0]["url"].startswith(f"{CARD_URL}?v={VERSION}-")
    hass.set_state(CoreState.running)


ISSUE = "card_resource_yaml"


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


@pytest.fixture
async def yaml_lovelace(hass):
    assert await async_setup_component(hass, "lovelace", {"lovelace": {"resource_mode": "yaml"}})
    await hass.async_block_till_done()
    assert hass.data[LOVELACE_DATA].resource_mode == "yaml"


async def test_yaml_mode_raises_a_repair_with_the_url(hass, yaml_lovelace):
    await async_ensure_resource(hass, URL)
    issue = _issue(hass)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.translation_key == ISSUE
    assert issue.translation_placeholders == {"url": URL}


async def test_yaml_mode_is_quiet_once_the_resource_is_listed(hass):
    listed = {"url": f"{LOCAL_CARD_URL}?v=old", "type": "module"}
    config = {"lovelace": {"resource_mode": "yaml", "resources": [listed]}}
    assert await async_setup_component(hass, "lovelace", config)
    await hass.async_block_till_done()
    ir.async_create_issue(
        hass, DOMAIN, ISSUE, is_fixable=False, severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE, translation_placeholders={"url": URL},
    )
    await async_ensure_resource(hass, URL)
    assert _issue(hass) is None


async def test_storage_mode_clears_the_yaml_repair(hass, lovelace):
    ir.async_create_issue(
        hass, DOMAIN, ISSUE, is_fixable=False, severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE, translation_placeholders={"url": URL},
    )
    await async_ensure_resource(hass, URL)
    assert _issue(hass) is None
    assert [i["url"] for i in _card_items(hass)] == [URL]


async def test_integration_setup_raises_the_yaml_repair(hass, yaml_lovelace):
    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_placeholders["url"].startswith(f"{CARD_URL}?v={VERSION}-")


def test_yaml_repair_is_translated():
    import json
    from pathlib import Path

    base = Path(__file__).parent.parent / "custom_components" / "parcel_tracker"
    for name in ("strings.json", "translations/de.json", "translations/en.json"):
        issue = json.loads((base / name).read_text(encoding="utf-8"))["issues"][ISSUE]
        assert "{url}" in issue["description"], name
        assert "module" in issue["description"], name

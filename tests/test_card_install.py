import os
import re
from pathlib import Path
from unittest.mock import Mock, patch

from homeassistant.components.http import StaticPathConfig
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.card_install import (
    CARD_FILE,
    card_hash,
    card_url,
    remove_old_copy,
)
from custom_components.parcel_tracker.const import CARD_URL, DOMAIN, LOCAL_CARD_URL, VERSION


def test_hash_changes_with_content():
    assert card_hash(b"a") != card_hash(b"b")
    assert card_hash(b"a") == card_hash(b"a")
    assert re.fullmatch(r"[0-9a-f]{8}", card_hash(b"a"))


def test_card_url_is_always_the_integration_path():
    assert card_url("abcd1234") == f"{CARD_URL}?v={VERSION}-abcd1234"


def _old_copy(root: Path) -> Path:
    folder = root / "www" / "parcel_tracker"
    folder.mkdir(parents=True)
    card = folder / CARD_FILE
    card.write_text("old card")
    return card


def test_remove_old_copy_deletes_our_file_and_the_empty_folder(tmp_path):
    card = _old_copy(tmp_path)
    assert remove_old_copy(tmp_path / "www") is True
    assert not card.exists()
    assert not card.parent.exists()
    assert (tmp_path / "www").is_dir()


def test_remove_old_copy_keeps_foreign_files(tmp_path):
    card = _old_copy(tmp_path)
    foreign = card.parent / "notes.txt"
    foreign.write_text("mine")
    other = tmp_path / "www" / "other.js"
    other.write_text("x")
    assert remove_old_copy(tmp_path / "www") is True
    assert not card.exists()
    assert foreign.read_text() == "mine"
    assert other.read_text() == "x"


def test_remove_old_copy_does_nothing_without_a_copy(tmp_path):
    assert remove_old_copy(tmp_path / "www") is False
    (tmp_path / "www").mkdir()
    assert remove_old_copy(tmp_path / "www") is False
    assert (tmp_path / "www").is_dir()


def _card_file(hass):
    return Path(hass.config.path("www", "parcel_tracker", CARD_FILE))


async def _setup(hass):
    assert await async_setup_component(hass, "lovelace", {})
    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    return [i["url"] for i in hass.data[LOVELACE_DATA].resources.async_items()]


async def test_setup_registers_the_integration_url_and_writes_nothing_to_www(hass):
    urls = await _setup(hass)
    assert len(urls) == 1
    assert urls[0].startswith(f"{CARD_URL}?v={VERSION}-")
    assert not await hass.async_add_executor_job(Path(hass.config.path("www")).exists)


async def test_setup_ignores_a_served_local_folder(hass):
    """Even with /local being served, the card keeps the integration URL."""
    await hass.async_add_executor_job(os.mkdir, hass.config.path("www"))
    assert await async_setup_component(hass, "http", {})
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/local", hass.config.path("www"), True)]
    )
    urls = await _setup(hass)
    assert urls[0].startswith(f"{CARD_URL}?v={VERSION}-")
    assert not await hass.async_add_executor_job(_card_file(hass).exists)


async def test_setup_removes_the_copy_older_versions_left(hass):
    card = await hass.async_add_executor_job(_old_copy, Path(hass.config.config_dir))
    foreign = card.parent.parent / "mine.txt"
    await hass.async_add_executor_job(foreign.write_text, "x")
    await _setup(hass)
    assert not await hass.async_add_executor_job(card.exists)
    assert not await hass.async_add_executor_job(card.parent.exists)
    assert await hass.async_add_executor_job(foreign.is_file)


async def test_setup_does_not_register_an_extra_js_module(hass):
    """Regression (v0.3.6): the card must reach the browser only as a Lovelace resource.

    Home Assistant's index.html imports core, app and every extra module in
    parallel. app.js installs the scoped-custom-element-registry polyfill, which
    replaces window.customElements. If the small card module is evaluated first
    (cold cache, hard reload), it registers on the native registry, the polyfill
    never sees it and the dashboard shows "Custom element doesn't exist:
    parcel-tracker-card". The Lovelace resource with the same URL is not evaluated
    a second time. Resources are loaded after app.js, so they have no such race.
    """
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager

    # A loaded frontend, as far as add_extra_js_url cares (hass_frontend itself
    # is not installed in the test environment).
    manager = hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(Mock(), [])
    hass.config.components.add("frontend")

    urls = await _setup(hass)

    assert len(urls) == 1  # the Lovelace resource is the only delivery path
    assert manager.urls == frozenset()


def test_integration_does_not_import_add_extra_js_url():
    import custom_components.parcel_tracker as integration

    assert not hasattr(integration, "add_extra_js_url")


async def test_cleanup_failure_does_not_break_setup(hass, caplog):
    card = await hass.async_add_executor_job(_old_copy, Path(hass.config.config_dir))
    with patch.object(Path, "unlink", side_effect=OSError("read-only")):
        urls = await _setup(hass)
    assert len(urls) == 1
    assert "read-only" in caplog.text
    assert await hass.async_add_executor_job(card.exists)


async def test_upgrade_switches_local_resource_and_removes_the_copy(hass):
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    card = await hass.async_add_executor_job(_old_copy, Path(hass.config.config_dir))
    assert await async_setup_component(hass, "lovelace", {})
    res = hass.data[LOVELACE_DATA].resources
    await res.async_get_info()
    await res.async_create_item({"res_type": "module", "url": f"{LOCAL_CARD_URL}?v=0.3.41-x"})
    urls = await _setup(hass)
    assert len(urls) == 1
    assert urls[0].startswith(f"{CARD_URL}?v={VERSION}-")
    assert not await hass.async_add_executor_job(card.exists)
    assert not await hass.async_add_executor_job(card.parent.exists)


async def test_copy_stays_in_yaml_mode_with_a_local_entry(hass):
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    card = await hass.async_add_executor_job(_old_copy, Path(hass.config.config_dir))
    listed = {"url": f"{LOCAL_CARD_URL}?v=old", "type": "module"}
    config = {"lovelace": {"resource_mode": "yaml", "resources": [listed]}}
    assert await async_setup_component(hass, "lovelace", config)
    assert hass.data[LOVELACE_DATA].resource_mode == "yaml"
    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    assert await hass.async_add_executor_job(card.is_file)


async def test_copy_stays_when_registration_fails(hass):
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    card = await hass.async_add_executor_job(_old_copy, Path(hass.config.config_dir))
    assert await async_setup_component(hass, "lovelace", {})
    res = hass.data[LOVELACE_DATA].resources
    await res.async_get_info()
    await res.async_create_item({"res_type": "module", "url": f"{LOCAL_CARD_URL}?v=0.3.41-x"})
    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    with patch.object(type(res), "async_update_item", side_effect=RuntimeError("boom")):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    assert await hass.async_add_executor_job(card.is_file)


def test_remove_old_copy_does_not_follow_symlinks(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / CARD_FILE).write_text("keep")
    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "parcel_tracker").symlink_to(real, target_is_directory=True)
    assert remove_old_copy(tmp_path / "www") is False
    assert (real / CARD_FILE).read_text() == "keep"
    link_dir = tmp_path / "www2" / "parcel_tracker"
    link_dir.mkdir(parents=True)
    (link_dir / CARD_FILE).symlink_to(real / CARD_FILE)
    assert remove_old_copy(tmp_path / "www2") is False
    assert (real / CARD_FILE).read_text() == "keep"


def test_remove_old_copy_logs_and_returns_false_on_oserror(tmp_path, caplog):
    card = _old_copy(tmp_path)
    with patch.object(Path, "unlink", side_effect=OSError("denied")):
        assert remove_old_copy(tmp_path / "www") is False
    assert card.exists()
    assert "denied" in caplog.text

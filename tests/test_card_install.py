import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from aiohttp import web
from homeassistant.components.http import StaticPathConfig
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.card_install import (
    BUNDLED_CARD,
    card_hash,
    card_url,
    install_card,
    local_is_served,
)
from custom_components.parcel_tracker.const import CARD_URL, DOMAIN, LOCAL_CARD_URL, VERSION


def test_hash_changes_with_content():
    assert card_hash(b"a") != card_hash(b"b")
    assert card_hash(b"a") == card_hash(b"a")
    assert re.fullmatch(r"[0-9a-f]{8}", card_hash(b"a"))


def test_card_url_forms():
    assert card_url("abcd1234", True) == f"{LOCAL_CARD_URL}?v={VERSION}-abcd1234"
    assert card_url("abcd1234", False) == f"{CARD_URL}?v={VERSION}-abcd1234"


def test_install_writes_and_is_idempotent(tmp_path):
    target = tmp_path / "www" / "parcel_tracker" / "card.js"
    digest, existed, written = install_card(BUNDLED_CARD, target)
    assert (existed, written) == (False, True)
    assert target.read_bytes() == BUNDLED_CARD.read_bytes()
    os.utime(target, (1, 1))
    digest2, existed2, written2 = install_card(BUNDLED_CARD, target)
    assert (existed2, written2) == (True, False)
    assert digest2 == digest
    assert target.stat().st_mtime == 1


def test_install_rewrites_changed_file(tmp_path):
    target = tmp_path / "www" / "parcel_tracker" / "card.js"
    install_card(BUNDLED_CARD, target)
    target.write_text("old")
    assert install_card(BUNDLED_CARD, target)[2] is True
    assert target.read_bytes() == BUNDLED_CARD.read_bytes()


def _card_file(hass):
    return Path(hass.config.path("www", "parcel_tracker", "parcel-tracker-card.js"))


async def _setup(hass):
    assert await async_setup_component(hass, "lovelace", {})
    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    return [i["url"] for i in hass.data[LOVELACE_DATA].resources.async_items()]


async def _serve_local(hass):
    """What the frontend does at startup when <config>/www exists."""
    await hass.async_add_executor_job(os.mkdir, hass.config.path("www"))
    assert await async_setup_component(hass, "http", {})
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/local", hass.config.path("www"), True)]
    )


def _fake_hass(*resources):
    router = SimpleNamespace(resources=lambda: list(resources))
    return SimpleNamespace(http=SimpleNamespace(app=SimpleNamespace(router=router)))


def test_local_is_served_reads_the_router(tmp_path):
    local = web.StaticResource("/local", tmp_path)
    other = web.StaticResource("/local_other", tmp_path)
    plain = web.PlainResource("/local")
    assert local_is_served(_fake_hass(other, local)) is True
    assert local_is_served(_fake_hass(other, plain)) is False
    assert local_is_served(_fake_hass()) is False


def test_local_is_served_is_unknown_without_http():
    assert local_is_served(SimpleNamespace(http=None)) is None
    assert local_is_served(SimpleNamespace()) is None


async def test_uses_local_when_home_assistant_serves_it(hass):
    await _serve_local(hass)
    urls = await _setup(hass)
    assert len(urls) == 1
    assert urls[0].startswith(f"{LOCAL_CARD_URL}?v={VERSION}-")
    assert await hass.async_add_executor_job(_card_file(hass).is_file)


async def test_www_created_after_boot_does_not_get_a_local_url(hass, caplog):
    """HA registers /local only if <config>/www existed at startup. A folder that
    another tool created later exists on disk, but /local/... answers 404 (and HA
    lets clients cache that for 31 days), so the card keeps its own URL."""
    caplog.set_level("INFO")
    await hass.async_add_executor_job(os.mkdir, hass.config.path("www"))
    urls = await _setup(hass)
    assert len(urls) == 1
    assert urls[0].startswith(f"{CARD_URL}?v={VERSION}-")
    assert await hass.async_add_executor_job(_card_file(hass).is_file)
    assert "next Home Assistant restart" in caplog.text


async def test_falls_back_when_www_missing(hass, caplog):
    caplog.set_level("INFO")
    urls = await _setup(hass)
    assert len(urls) == 1
    assert urls[0].startswith(f"{CARD_URL}?v={VERSION}-")
    assert await hass.async_add_executor_job(_card_file(hass).is_file)
    assert "next Home Assistant restart" in caplog.text


async def test_folder_check_decides_when_http_is_unknown(hass):
    """Without hass.http (some test setups) the folder check is all there is."""
    await hass.async_add_executor_job(os.mkdir, hass.config.path("www"))
    with patch("custom_components.parcel_tracker.local_is_served", return_value=None):
        urls = await _setup(hass)
    assert urls[0].startswith(f"{LOCAL_CARD_URL}?v={VERSION}-")


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


async def test_setup_survives_copy_failure(hass):
    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    with patch(
        "custom_components.parcel_tracker.install_card", side_effect=OSError("read-only")
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()

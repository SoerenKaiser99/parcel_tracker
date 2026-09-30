import os
import re
from pathlib import Path

from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.card_install import (
    BUNDLED_CARD,
    card_hash,
    card_url,
    install_card,
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


async def test_uses_local_when_www_preexists(hass):
    await hass.async_add_executor_job(os.mkdir, hass.config.path("www"))
    urls = await _setup(hass)
    assert len(urls) == 1
    assert urls[0].startswith(f"{LOCAL_CARD_URL}?v={VERSION}-")
    assert await hass.async_add_executor_job(_card_file(hass).is_file)


async def test_falls_back_when_www_missing(hass, caplog):
    caplog.set_level("INFO")
    urls = await _setup(hass)
    assert len(urls) == 1
    assert urls[0].startswith(f"{CARD_URL}?v={VERSION}-")
    assert await hass.async_add_executor_job(_card_file(hass).is_file)
    assert "next Home Assistant restart" in caplog.text


async def test_setup_survives_copy_failure(hass):
    from unittest.mock import patch

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.parcel_tracker.const import DOMAIN

    e = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    e.add_to_hass(hass)
    with patch(
        "custom_components.parcel_tracker.install_card", side_effect=OSError("read-only")
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()

"""Geschenkmodus: the switch, who may turn it off, and the parcels it marks as gifts."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_GIFT_VIEWERS, DOMAIN
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus

SWITCH = "switch.paket_tracker_geschenkmodus"
ANNA = "person.anna"
NOW = dt_util.utcnow()
DHL = "JJD000012978217606560"


async def _setup(hass):
    hass.states.async_set(ANNA, "home", {"user_id": "uid-anna"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"dhl_api_key": "k"},
        options={"postcode": "10115", CONF_GIFT_VIEWERS: [ANNA]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _admin(hass, name):
    return await hass.auth.async_create_user(name, group_ids=["system-admin"])


async def _call(hass, service, user=None):
    context = Context(user_id=user.id) if user else Context()
    await hass.services.async_call(
        "switch", service, {"entity_id": SWITCH}, blocking=True, context=context
    )


async def test_switch_exists_with_name_and_icon(hass):
    await _setup(hass)
    state = hass.states.get(SWITCH)
    assert state.state == "off"
    assert state.attributes["icon"] == "mdi:gift"
    assert state.attributes["friendly_name"] == "Geschenkmodus"


async def test_anybody_turns_it_on_only_a_viewer_or_no_user_turns_it_off(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    anna = await hass.auth.async_create_user("Anna", group_ids=["system-admin"])
    other = await _admin(hass, "Other")
    hass.states.async_set(ANNA, "home", {"user_id": anna.id})

    await _call(hass, "turn_on", other)
    assert coordinator.gift_mode is True
    assert hass.states.get(SWITCH).state == "on"

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "turn_off", other)
    assert err.value.translation_key == "gift_mode_not_allowed"
    assert coordinator.gift_mode is True
    assert hass.states.get(SWITCH).state == "on"

    await _call(hass, "turn_off", anna)
    assert coordinator.gift_mode is False

    await _call(hass, "turn_on", anna)
    await _call(hass, "turn_off")  # an automation: no user
    assert coordinator.gift_mode is False
    assert hass.states.get(SWITCH).state == "off"


async def test_add_parcel_service_marks_gift_only_while_on(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_set_gift_mode(True, None)
    first = await coordinator.async_add(DHL, "dhl", "Lego")
    await coordinator.async_set_gift_mode(False, None)
    second = await coordinator.async_add("JJD000012978217606561", "dhl", None)
    assert first.gift is True
    assert second.gift is False
    assert coordinator.store.parcels[DHL].gift is True


def _mail_update(number, carrier="dhl", **kwargs):
    return MailUpdate(number, carrier, ParcelStatus.IN_TRANSIT, dt_util.now(), **kwargs)


async def _import(hass, coordinator, number, message):
    parsed = [_ParsedMail(message_id=message, result=MailResult([_mail_update(number)]))]
    with patch("custom_components.parcel_tracker.coordinator._parse_mails", return_value=parsed):
        await coordinator.async_import_raw_mail(b"synthetic")
    await hass.async_block_till_done()


async def test_mail_creates_gift_while_on_and_not_after(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_set_gift_mode(True, None)
    await _import(hass, coordinator, DHL, "<a@synthetic.example>")
    await coordinator.async_set_gift_mode(False, None)
    other = "JJD000012978217606562"
    await _import(hass, coordinator, other, "<b@synthetic.example>")
    assert coordinator.store.parcels[DHL].gift is True
    assert coordinator.store.parcels[other].gift is False


def test_apply_update_gift_flag_marks_new_parcels():
    parcels: dict[str, Parcel] = {}
    apply_update(parcels, _mail_update(DHL), NOW, gift=True)
    apply_update(parcels, _mail_update("JJD000012978217606563"), NOW)
    assert parcels[DHL].gift is True
    assert parcels["JJD000012978217606563"].gift is False


def _ali_order(gift):
    parcels: dict[str, Parcel] = {}
    first = MailUpdate(
        "ALI100", "aliexpress", ParcelStatus.IN_TRANSIT, NOW,
        title="Item", tracking_ref=DHL, tracking_carrier="dhl",
    )  # fmt: skip
    apply_update(parcels, first, NOW, gift=gift)
    return parcels


def test_further_box_of_a_gift_order_is_a_gift_even_when_the_mode_is_off():
    parcels = _ali_order(gift=True)
    assert parcels["ALI100"].gift is True
    second = MailUpdate(
        "ALI100", "aliexpress", ParcelStatus.IN_TRANSIT, NOW + timedelta(hours=1),
        title="Item", tracking_ref="JJD000012978217606570", tracking_carrier="dhl",
    )  # fmt: skip
    apply_update(parcels, second, NOW + timedelta(hours=1), gift=False)
    assert parcels["JJD000012978217606570"].gift is True


def test_further_box_of_a_plain_order_is_no_gift():
    parcels = _ali_order(gift=False)
    second = MailUpdate(
        "ALI100", "aliexpress", ParcelStatus.IN_TRANSIT, NOW + timedelta(hours=1),
        title="Item", tracking_ref="JJD000012978217606570", tracking_carrier="dhl",
    )  # fmt: skip
    apply_update(parcels, second, NOW + timedelta(hours=1), gift=False)
    assert parcels["JJD000012978217606570"].gift is False


async def test_mode_and_gift_survive_a_restart(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_set_gift_mode(True, None)
    await _import(hass, coordinator, DHL, "<a@synthetic.example>")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator.gift_mode is True
    assert hass.states.get(SWITCH).state == "on"
    assert coordinator.store.parcels[DHL].gift is True


async def test_old_store_without_the_mode_loads_as_off(hass, hass_storage):
    hass_storage["parcel_tracker.parcels"] = {
        "version": 1, "key": "parcel_tracker.parcels", "data": {"parcels": []},
    }  # fmt: skip
    entry = await _setup(hass)
    assert entry.runtime_data.gift_mode is False


async def test_other_carrier_added_through_17track_is_a_gift_in_the_mode(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_set_gift_mode(True, None)
    with (
        patch.object(coordinator, "_t17_client"),
        patch.object(coordinator, "_register17", return_value=123),
        patch.object(coordinator, "async_update_quota"),
    ):
        parcel = await coordinator._add_other("XY123456789", "Lego")
    assert parcel.gift is True


async def test_switch_is_not_exposed_to_voice_assistants(hass):
    assert await async_setup_component(hass, "homeassistant", {})
    await _setup(hass)
    assert async_should_expose(hass, "conversation", SWITCH) is False


async def test_non_viewer_is_refused_by_toggle_and_homeassistant_turn_off(hass):
    entry = await _setup(hass)
    other = await _admin(hass, "Other")
    await entry.runtime_data.async_set_gift_mode(True, None)
    with pytest.raises(HomeAssistantError):
        await _call(hass, "toggle", other)
    assert entry.runtime_data.gift_mode is True
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "homeassistant", "turn_off", {"entity_id": SWITCH},
            blocking=True, context=Context(user_id=other.id),
        )  # fmt: skip
    assert entry.runtime_data.gift_mode is True
    assert hass.states.get(SWITCH).state == "on"

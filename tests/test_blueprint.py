"""The notification blueprint: loads as a Home Assistant blueprint and does what it says."""

import shutil
from pathlib import Path

import pytest
from homeassistant.components.blueprint import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.setup import async_setup_component
from homeassistant.util import yaml as yaml_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.parcel_tracker.const import (
    CARRIER_NAMES,
    DEFAULT_NOTIFY_EVENTS,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.models import ParcelStatus

ROOT = Path(__file__).parent.parent
RELATIVE = "parcel_tracker/paket_benachrichtigung.yaml"
PATH = ROOT / "blueprints" / "automation" / RELATIVE
NUMBER = "00340434161094042557"
EVENT = {
    "number": NUMBER,
    "name": "Kopfhörer",
    "carrier": "dhl",
    "carrier_name": "DHL",
    "old_status": "in_transit",
    "new_status": "out_for_delivery",
    "eta_date": "2026-09-29",
    "eta_from": None,
    "eta_to": None,
    "location": "Bonn",
}


def _load() -> dict:
    return yaml_util.load_yaml(PATH)


def test_blueprint_loads_and_has_the_required_keys():
    data = _load()
    blueprint = Blueprint(data, path=RELATIVE, expected_domain="automation",
                          schema=BLUEPRINT_SCHEMA)
    assert blueprint.validate() is None
    meta = blueprint.metadata
    assert meta["name"] == "Paket Tracker: Benachrichtigung"
    assert meta["domain"] == "automation"
    assert meta["source_url"] == (
        "https://github.com/SoerenKaiser99/parcel_tracker/blob/main/blueprints/automation/"
        + RELATIVE
    )
    for key in ("blueprint", "triggers", "conditions", "actions", "mode"):
        assert key in data, key
    (trigger,) = data["triggers"]
    assert trigger["trigger"] == "event"
    assert trigger["event_type"] == EVENT_STATUS_CHANGED == "parcel_tracker_status_changed"


def test_blueprint_inputs():
    inputs = Blueprint(_load(), expected_domain="automation", schema=BLUEPRINT_SCHEMA).inputs
    assert list(inputs) == [
        "statuses", "notify_service", "title", "message", "dashboard_path",
        "replace_previous", "extra_conditions",
    ]
    statuses = inputs["statuses"]
    assert statuses["default"] == list(DEFAULT_NOTIFY_EVENTS)
    select = statuses["selector"]["select"]
    assert select["multiple"] is True
    assert [option["value"] for option in select["options"]] == [
        s.value for s in ParcelStatus if s is not ParcelStatus.UNKNOWN
    ]
    assert inputs["notify_service"]["default"] == "notify.notify"
    assert list(inputs["notify_service"]["selector"]) == ["text"]
    assert inputs["title"]["default"] == "Paket Tracker"
    assert inputs["dashboard_path"]["default"] == ""
    assert inputs["replace_previous"]["default"] is False
    assert inputs["extra_conditions"]["default"] == []
    assert list(inputs["extra_conditions"]["selector"]) == ["condition"]
    assert list(inputs["message"]["selector"]) == ["template"]
    assert inputs["message"]["default"] == "{{ text }}"
    for name in ("name", "carrier", "new_status", "old_status"):
        assert f"`{name}`" in inputs["message"]["description"], name
    for value in inputs.values():
        assert value["name"] and "description" in value


def test_blueprint_texts_follow_the_copy_rules():
    text = PATH.read_text(encoding="utf-8").lower()
    assert "bitte" not in text and "erfolgreich" not in text


def test_blueprint_takes_the_carrier_name_from_the_event():
    """No list of carriers of its own: ``carrier_name`` is what the sensor shows."""
    text = PATH.read_text(encoding="utf-8")
    assert "trigger.event.data.carrier_name" in text
    for key, name in CARRIER_NAMES.items():
        assert f"'{key}': '{name}'" not in text and f"{key}: {name}" not in text, key


async def _automation(hass, **inputs) -> None:
    await hass.async_add_executor_job(
        shutil.copytree, ROOT / "blueprints", Path(hass.config.path("blueprints"))
    )
    config = {"automation": {"use_blueprint": {"path": RELATIVE, "input": inputs}}}
    assert await async_setup_component(hass, "automation", config)
    await hass.async_block_till_done()
    assert hass.states.async_entity_ids("automation")


async def _fire(hass, **changes) -> None:
    hass.bus.async_fire(EVENT_STATUS_CHANGED, {**EVENT, **changes})
    await hass.async_block_till_done()


async def test_defaults_send_a_plain_text_without_app_data(hass):
    calls = async_mock_service(hass, "notify", "notify")
    await _automation(hass)
    await _fire(hass)
    (call,) = calls
    assert call.data == {
        "title": "Paket Tracker",
        "message": "Kopfhörer (DHL) ist in Zustellung",
    }
    await _fire(hass, new_status="delivered", old_status="out_for_delivery")
    assert calls[1].data["message"] == "Kopfhörer (DHL) wurde zugestellt"
    # Not ticked by default.
    for status in ("pre_transit", "in_transit", "at_delivery_depot", "awaiting_pickup",
                   "exception"):
        await _fire(hass, new_status=status)
    assert len(calls) == 2


async def test_every_status_has_a_default_text(hass):
    calls = async_mock_service(hass, "notify", "notify")
    statuses = [s.value for s in ParcelStatus if s is not ParcelStatus.UNKNOWN]
    await _automation(hass, statuses=statuses)
    for status in statuses:
        await _fire(hass, new_status=status, old_status="unknown")
    assert [call.data["message"] for call in calls] == [
        "Kopfhörer (DHL) ist angekündigt",
        "Kopfhörer (DHL) ist unterwegs",
        "Kopfhörer (DHL) ist im Zustelldepot",
        "Kopfhörer (DHL) ist in Zustellung",
        "Kopfhörer (DHL) liegt zur Abholung bereit",
        "Kopfhörer (DHL) wurde zugestellt",
        "Kopfhörer (DHL): Problem bei der Zustellung",
    ]


async def test_app_data_opens_the_dashboard_and_replaces_by_tag(hass):
    calls = async_mock_service(hass, "notify", "mobile_app_handy")
    await _automation(
        hass,
        notify_service="notify.mobile_app_handy",
        dashboard_path="/lovelace/pakete",
        replace_previous=True,
    )
    await _fire(hass)
    await _fire(hass, new_status="delivered", old_status="out_for_delivery")
    first, second = (call.data for call in calls)
    assert set(first) == {"title", "message", "data"}
    assert first["data"]["url"] == "/lovelace/pakete"  # iOS
    assert first["data"]["clickAction"] == "/lovelace/pakete"  # Android
    tag = first["data"]["tag"]
    assert tag.startswith("parcel_tracker_") and len(tag) == len("parcel_tracker_") + 32
    assert second["data"]["tag"] == tag  # same parcel: the later one replaces the earlier
    for digits in (NUMBER, NUMBER[-4:], NUMBER[:8]):
        assert digits not in tag
    await _fire(hass, number="09999999999902")
    assert calls[2].data["data"]["tag"] != tag


async def test_dashboard_path_alone_and_tag_alone(hass):
    calls = async_mock_service(hass, "notify", "notify")
    await _automation(hass, dashboard_path="/lovelace/pakete")
    await _fire(hass)
    assert calls[0].data["data"] == {
        "url": "/lovelace/pakete", "clickAction": "/lovelace/pakete",
    }


async def test_tag_alone(hass):
    calls = async_mock_service(hass, "notify", "notify")
    await _automation(hass, replace_previous=True)
    await _fire(hass)
    assert list(calls[0].data["data"]) == ["tag"]


async def test_own_text_with_the_variables_and_an_extra_condition(hass):
    calls = async_mock_service(hass, "notify", "notify")
    hass.states.async_set("input_boolean.zuhause", "off")
    await _automation(
        hass,
        title="Pakete",
        message="{{ name }} | {{ carrier }} | {{ old_status }} -> {{ new_status }}",
        extra_conditions=[
            {"condition": "state", "entity_id": "input_boolean.zuhause", "state": "on"}
        ],
    )
    await _fire(hass)
    assert calls == []
    hass.states.async_set("input_boolean.zuhause", "on")
    await _fire(hass)
    assert calls[0].data == {
        "title": "Pakete",
        "message": "Kopfhörer | DHL | in_transit -> out_for_delivery",
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": None}, "Paket …2557 (DHL) ist in Zustellung"),
        ({"name": None, "number": "AMZ30212345671234567", "carrier": "amazon",
          "carrier_name": "Amazon"},
         "Paket …4567 (Amazon) ist in Zustellung"),
        # A carrier without own connection: the one 17track recognised, as on the sensor.
        ({"carrier": "other", "carrier_name": "GLS"}, "Kopfhörer (GLS) ist in Zustellung"),
        ({"carrier": "other", "carrier_name": "17track"},
         "Kopfhörer (17track) ist in Zustellung"),
        ({"carrier": None, "carrier_name": None}, "Kopfhörer ist in Zustellung"),
    ],
    ids=["no-name", "shop-order", "other-carrier", "other-unknown", "no-carrier"],
)
async def test_default_text_names_the_parcel_without_its_number(hass, changes, message):
    calls = async_mock_service(hass, "notify", "notify")
    await _automation(hass)
    await _fire(hass, **changes)
    assert calls[0].data["message"] == message
    assert NUMBER not in calls[0].data["message"]


async def test_an_assumed_delivery_is_not_announced(hass):
    """v0.3.20: an order closed without a delivery mail fires the event with
    ``assumed: true``; nothing arrived just now, so the blueprint stays quiet."""
    calls = async_mock_service(hass, "notify", "notify")
    await _automation(hass)
    await _fire(hass, new_status="delivered", assumed=True)
    assert calls == []
    await _fire(hass, new_status="delivered", assumed=False)
    assert len(calls) == 1
    # An event of an older version of the integration carries no such field.
    await _fire(hass, new_status="delivered")
    assert len(calls) == 2

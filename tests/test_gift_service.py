"""Geschenkmodus: the service set_gift and the WebSocket commands for gift viewers."""

from unittest.mock import patch

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_GIFT_VIEWERS, DOMAIN
from custom_components.parcel_tracker.links import tracking_url
from custom_components.parcel_tracker.models import TrackingResult

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
ANNA = "person.anna"
OPEN1 = "JJD000012978217606560"
OPEN2 = "JJD000012978217606561"
DONE = "JJD000012978217606562"
NAME_OPEN1 = {"type": "parcel_tracker/gift_name", "number": OPEN1}
VIEWER = {"type": "parcel_tracker/gift_viewer"}


async def _setup(hass, viewers=(ANNA,)):
    options = {"postcode": "10115"}
    if viewers:
        options[CONF_GIFT_VIEWERS] = list(viewers)
    entry = MockConfigEntry(domain=DOMAIN, data={"dhl_api_key": "k"}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    in_transit = TrackingResult.from_dict({"status": "in_transit", "events": []})
    for number, name in ((OPEN1, "Lego"), (OPEN2, None), (DONE, "Buch")):
        with patch(FETCH, return_value=in_transit):
            parcel = await coordinator.async_add(number, "dhl", name)
        parcel.mail_title = f"Titel {number[-1]}"
    coordinator.store.parcels[DONE].result = TrackingResult.from_dict(
        {"status": "delivered", "events": []}
    )
    return entry


async def _user(hass, name, person=None):
    user = await hass.auth.async_create_user(name, group_ids=["system-admin"])
    if person:
        hass.states.async_set(person, "home", {"user_id": user.id})
    return user


async def _set_gift(hass, data, user=None):
    context = Context(user_id=user.id) if user else Context()
    await hass.services.async_call(DOMAIN, "set_gift", data, blocking=True, context=context)


async def test_open_parcels_marks_all_not_delivered_but_no_delivered(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    kid = await _user(hass, "Kid")
    await _set_gift(hass, {"open_parcels": True, "gift": True}, kid)
    assert parcels[OPEN1].gift and parcels[OPEN2].gift
    assert not parcels[DONE].gift


async def test_open_parcels_leaves_a_cancelled_order_alone(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    parcels[OPEN2].result = TrackingResult.from_dict({"status": "cancelled", "events": []})
    await _set_gift(hass, {"open_parcels": True, "gift": True})
    assert parcels[OPEN1].gift
    assert not parcels[OPEN2].gift and not parcels[DONE].gift


async def test_single_number_and_unknown_number(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    await _set_gift(hass, {"number": OPEN1, "gift": True})
    assert parcels[OPEN1].gift and not parcels[OPEN2].gift
    with pytest.raises(ServiceValidationError) as err:
        await _set_gift(hass, {"number": "JJD999999999999999999", "gift": True})
    assert err.value.translation_key == "not_tracked"


async def test_number_xor_open_parcels(hass):
    await _setup(hass)
    for data in ({"gift": True}, {"number": OPEN1, "open_parcels": True, "gift": True}):
        with pytest.raises(ServiceValidationError) as err:
            await _set_gift(hass, data)
        assert err.value.translation_key == "gift_target"


async def test_only_a_viewer_or_no_user_takes_a_gift_back(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    anna = await _user(hass, "Anna", ANNA)
    kid = await _user(hass, "Kid")
    await _set_gift(hass, {"number": OPEN1, "gift": True}, kid)
    with pytest.raises(HomeAssistantError) as err:
        await _set_gift(hass, {"number": OPEN1, "gift": False}, kid)
    assert err.value.translation_key == "gift_not_allowed"
    assert parcels[OPEN1].gift is True
    await _set_gift(hass, {"number": OPEN1, "gift": False}, anna)
    assert parcels[OPEN1].gift is False
    await _set_gift(hass, {"number": OPEN1, "gift": True}, kid)
    await _set_gift(hass, {"number": OPEN1, "gift": False})  # automation
    assert parcels[OPEN1].gift is False


async def test_sensor_follows_the_change(hass):
    await _setup(hass)
    await _set_gift(hass, {"number": OPEN1, "gift": True})
    await hass.async_block_till_done()
    states = [s for s in hass.states.async_all("sensor") if s.attributes.get("gift") is True]
    assert len(states) == 1


async def _token(hass, user):
    refresh = await hass.auth.async_create_refresh_token(user, "https://example.test")
    return hass.auth.async_create_access_token(refresh)


async def _ask(hass, hass_ws_client, user, message):
    client = await hass_ws_client(hass, access_token=await _token(hass, user))
    await client.send_json({"id": 1, **message})
    return await client.receive_json()


async def test_gift_name_for_a_viewer(hass, hass_ws_client):
    entry = await _setup(hass)
    anna = await _user(hass, "Anna", ANNA)
    parcel = entry.runtime_data.store.parcels[OPEN1]
    await _set_gift(hass, {"number": OPEN1, "gift": True})
    reply = await _ask(hass, hass_ws_client, anna, NAME_OPEN1)
    assert reply["success"] is True
    assert reply["result"] == {
        "name": "Lego",
        "mail_title": f"Titel {OPEN1[-1]}",
        "tracking_url": tracking_url(parcel),
    }
    assert reply["result"]["tracking_url"]
    missing = {"type": "parcel_tracker/gift_name", "number": "NOPE123456"}
    reply = await _ask(hass, hass_ws_client, anna, missing)
    assert reply["error"]["code"] == "not_found"


async def test_gift_name_denied_to_non_viewer_and_admin_without_list(hass, hass_ws_client):
    await _setup(hass)
    await _user(hass, "Anna", ANNA)
    kid = await _user(hass, "Kid")  # an admin, but not a viewer
    reply = await _ask(hass, hass_ws_client, kid, NAME_OPEN1)
    assert reply["success"] is False
    assert reply["error"]["code"] == "not_allowed"
    assert "Lego" not in str(reply)


async def test_gift_name_denied_without_any_viewer_list(hass, hass_ws_client):
    await _setup(hass, viewers=())
    someone = await _user(hass, "Someone")
    reply = await _ask(hass, hass_ws_client, someone, NAME_OPEN1)
    assert reply["error"]["code"] == "not_allowed"
    assert "Lego" not in str(reply)


async def test_gift_viewer_command(hass, hass_ws_client):
    await _setup(hass)
    anna = await _user(hass, "Anna", ANNA)
    kid = await _user(hass, "Kid")
    assert (await _ask(hass, hass_ws_client, anna, VIEWER))["result"] == {"viewer": True}
    assert (await _ask(hass, hass_ws_client, kid, VIEWER))["result"] == {"viewer": False}


async def _child(hass):
    """A plain user: no admin group."""
    return await hass.auth.async_create_user("Child", group_ids=["system-users"])


async def _call(hass, service, data, user=None):
    context = Context(user_id=user.id) if user else Context()
    await hass.services.async_call(DOMAIN, service, data, blocking=True, context=context)


async def test_plain_user_cannot_untake_remove_or_rename_a_gift(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    child = await _child(hass)
    await _call(hass, "set_gift", {"number": OPEN1, "gift": True}, child)
    for service, data, key in (
        ("set_gift", {"number": OPEN1, "gift": False}, "gift_not_allowed"),
        ("remove_parcel", {"number": OPEN1}, "gift_remove_not_allowed"),
        ("rename_parcel", {"number": OPEN1, "name": "Bagger"}, "gift_rename_not_allowed"),
    ):
        with pytest.raises(HomeAssistantError) as err:
            await _call(hass, service, data, child)
        assert err.value.translation_key == key
    assert parcels[OPEN1].gift is True
    assert parcels[OPEN1].name == "Lego"
    # a parcel that is no gift stays open to the plain user
    await _call(hass, "rename_parcel", {"number": OPEN2, "name": "Bagger"}, child)
    assert parcels[OPEN2].name == "Bagger"
    await _call(hass, "remove_parcel", {"number": OPEN2}, child)
    assert OPEN2 not in parcels


async def test_viewer_and_no_user_may_rename_and_remove_a_gift(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    anna = await _user(hass, "Anna", ANNA)
    await _call(hass, "set_gift", {"open_parcels": True, "gift": True})
    await _call(hass, "rename_parcel", {"number": OPEN1, "name": "Bagger"}, anna)
    assert parcels[OPEN1].name == "Bagger"
    await _call(hass, "remove_parcel", {"number": OPEN1}, anna)
    assert OPEN1 not in parcels
    await _call(hass, "rename_parcel", {"number": OPEN2, "name": "Auto"})
    await _call(hass, "remove_parcel", {"number": OPEN2})
    assert OPEN2 not in parcels


async def test_plain_user_gets_not_allowed_also_for_an_unknown_number(hass, hass_ws_client):
    await _setup(hass)
    await _user(hass, "Anna", ANNA)
    child = await _child(hass)
    unknown = {"type": "parcel_tracker/gift_name", "number": "NOPE123456"}
    reply = await _ask(hass, hass_ws_client, child, unknown)
    assert reply["error"]["code"] == "not_allowed"
    reply = await _ask(hass, hass_ws_client, child, NAME_OPEN1)
    assert reply["error"]["code"] == "not_allowed"
    assert "Lego" not in str(reply)

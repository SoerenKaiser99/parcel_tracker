"""The delivery code (one-time password) is never an attribute: the card asks for it through
the WebSocket command parcel_tracker/delivery_code (HACS review, point 2)."""

from datetime import timedelta

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_READ_OTP, DOMAIN
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.sensor import ParcelSensor

AMZ = "AMZ99905626221455530"
OLD = "AMZ99991565342587125"
GIFT = "AMZ99990000000000041"
NONE = "AMZ99990000000000052"
CODE = "482915"
CODE_OLD = "731602"
CODE_GIFT = "590274"


def _result():
    return TrackingResult.from_dict({"status": ParcelStatus.OUT_FOR_DELIVERY.value, "events": []})


async def _setup(hass, read_otp=True):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"dhl_api_key": "k"},
        options={"postcode": "10115", CONF_READ_OTP: read_otp},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    now = dt_util.utcnow()
    today = dt_util.now().date()
    for number, code, day, gift in (
        (AMZ, CODE, today, False),
        (OLD, CODE_OLD, today - timedelta(days=1), False),
        (GIFT, CODE_GIFT, today, True),
        (NONE, None, None, False),
    ):
        coordinator.store.add(
            Parcel(
                number, "amazon", "mail", None, now, now, result=_result(),
                delivery_code=code, delivery_code_day=day, gift=gift,
            )
        )
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()
    return entry


async def _user(hass, name, admin=False):
    groups = ["system-admin"] if admin else ["system-users"]
    return await hass.auth.async_create_user(name, group_ids=groups)


async def _ask(hass, hass_ws_client, user, number):
    refresh = await hass.auth.async_create_refresh_token(user, "https://example.test")
    client = await hass_ws_client(hass, access_token=hass.auth.async_create_access_token(refresh))
    await client.send_json({"id": 1, "type": "parcel_tracker/delivery_code", "number": number})
    return await client.receive_json()


def _all_attributes(hass) -> str:
    return repr([(s.entity_id, dict(s.attributes)) for s in hass.states.async_all()])


async def test_no_attribute_holds_the_code(hass):
    await _setup(hass)
    text = _all_attributes(hass)
    for code in (CODE, CODE_OLD, CODE_GIFT):
        assert code not in text
    for number in (AMZ, OLD, GIFT, NONE):
        attrs = hass.states.get(f"sensor.paket_{number.lower()}").attributes
        assert "delivery_code" not in attrs
        assert type(attrs["has_delivery_code"]) is bool
    assert hass.states.get(f"sensor.paket_{AMZ.lower()}").attributes["has_delivery_code"] is True
    assert hass.states.get(f"sensor.paket_{GIFT.lower()}").attributes["has_delivery_code"] is True
    assert hass.states.get(f"sensor.paket_{OLD.lower()}").attributes["has_delivery_code"] is False
    assert hass.states.get(f"sensor.paket_{NONE.lower()}").attributes["has_delivery_code"] is False
    assert "delivery_code" not in ParcelSensor._unrecorded_attributes


async def test_has_delivery_code_is_false_with_the_option_off(hass):
    await _setup(hass, read_otp=False)
    for number in (AMZ, GIFT):
        attrs = hass.states.get(f"sensor.paket_{number.lower()}").attributes
        assert attrs["has_delivery_code"] is False


async def test_the_command_gives_the_active_code(hass, hass_ws_client):
    await _setup(hass)
    user = await _user(hass, "Max Mustermann")
    reply = await _ask(hass, hass_ws_client, user, AMZ)
    assert reply["success"] is True
    assert reply["result"] == {"code": CODE}
    # The number as typed (lower case, spaces) is found as well.
    reply = await _ask(hass, hass_ws_client, user, " " + AMZ.lower())
    assert reply["result"] == {"code": CODE}


async def test_a_gift_still_gives_its_code(hass, hass_ws_client):
    # The code is needed at the door; a gift hides only what is inside.
    await _setup(hass)
    user = await _user(hass, "Max Mustermann")
    assert (await _ask(hass, hass_ws_client, user, GIFT))["result"] == {"code": CODE_GIFT}


async def test_no_code_for_an_expired_missing_or_unknown_parcel(hass, hass_ws_client):
    await _setup(hass)
    user = await _user(hass, "Max Mustermann")
    for number in (OLD, NONE, "AMZ00000000000000000"):
        reply = await _ask(hass, hass_ws_client, user, number)
        assert reply["success"] is True
        assert reply["result"] == {"code": None}


async def test_no_code_with_the_option_off(hass, hass_ws_client):
    await _setup(hass, read_otp=False)
    user = await _user(hass, "Max Mustermann", admin=True)
    assert (await _ask(hass, hass_ws_client, user, AMZ))["result"] == {"code": None}


async def test_no_code_without_a_loaded_entry(hass, hass_ws_client):
    entry = await _setup(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    user = await _user(hass, "Max Mustermann")
    reply = await _ask(hass, hass_ws_client, user, AMZ)
    assert reply["result"] == {"code": None}

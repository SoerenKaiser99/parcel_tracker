"""``gift_for``: the persons a gift is for (wish from issue #64).

A gift with ``gift_for`` is hidden from those persons like from somebody who may not see
gifts, also when they are gift viewers: no real name, no change, no push to their targets.
Who a gift is for is only stored and told to the card per user (WebSocket), never in a
state, an event, the diagnostics or the log. Without ``gift_for`` nothing changes.
"""

import logging
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import yaml
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.card_install import BUNDLED_CARD
from custom_components.parcel_tracker.const import (
    CONF_GIFT_VIEWERS,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    CONF_PERSONS,
    DOMAIN,
    EVENT_PARCEL_ADDED,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.diagnostics import async_get_config_entry_diagnostics
from custom_components.parcel_tracker.mail.apply import _fold, apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
ANNA = "person.anna"  # gift viewer, gives the gift
BEN = "person.ben"  # gift viewer, gets the gift
CARA = "person.cara"  # gets a gift as well, no viewer
DORA = "person.dora"  # not set up in the integration
GENERAL = "notify.general"
ANNA_PHONE = "notify.anna_phone"
BEN_PHONE = "notify.ben_phone"
NUMBER = "JJD000012978217606560"
OTHER = "JJD000012978217606561"
IN_TRANSIT = TrackingResult.from_dict({"status": "in_transit", "events": []})
BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=BERLIN)


async def _setup(hass, general=(GENERAL,), extra=None):
    options = {
        "postcode": "10115",
        CONF_NOTIFY_TARGETS: list(general),
        CONF_NOTIFY_EVENTS: ["delivered"],
        CONF_GIFT_VIEWERS: [ANNA, BEN],
        CONF_PERSONS: [
            {"person": ANNA, "addresses": ["anna@example.org"], "notify_targets": [ANNA_PHONE]},
            {"person": BEN, "addresses": ["ben@example.org"], "notify_targets": [BEN_PHONE]},
            {"person": CARA, "addresses": ["cara@example.org"], "notify_targets": []},
        ],
        **(extra or {}),
    }
    entry = MockConfigEntry(domain=DOMAIN, data={"dhl_api_key": "k"}, options=options)
    entry.add_to_hass(hass)
    for entity in (GENERAL, ANNA_PHONE, BEN_PHONE, ANNA, BEN, CARA):
        hass.states.async_set(entity, "unknown")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    for number, name in ((NUMBER, "Lego"), (OTHER, "Buch")):
        with patch(FETCH, return_value=IN_TRANSIT):
            await coordinator.async_add(number, "dhl", name)
    return entry


async def _user(hass, name, person=None):
    user = await hass.auth.async_create_user(name, group_ids=["system-admin"])
    if person:
        hass.states.async_set(person, "home", {"user_id": user.id})
    return user


async def _call(hass, service, data, user=None):
    context = Context(user_id=user.id) if user else Context()
    await hass.services.async_call(DOMAIN, service, data, blocking=True, context=context)


async def _gift_for(hass, persons, number=NUMBER, user=None):
    await _call(hass, "set_gift", {"number": number, "gift": True, "gift_for": persons}, user)


async def _token(hass, user):
    refresh = await hass.auth.async_create_refresh_token(user, "https://example.test")
    return hass.auth.async_create_access_token(refresh)


async def _ask(hass, hass_ws_client, user, message):
    client = await hass_ws_client(hass, access_token=await _token(hass, user))
    await client.send_json({"id": 1, **message})
    return await client.receive_json()


# ----- model -----
def _parcel(**fields) -> Parcel:
    return Parcel(NUMBER, "dhl", "mail", "Lego", NOW, NOW, **fields)


def test_gift_for_round_trip_and_old_store():
    p = _parcel(gift=True, gift_for=[BEN, CARA])
    data = p.to_dict()
    assert Parcel.from_dict(data).gift_for == [BEN, CARA]
    del data["gift_for"]
    assert Parcel.from_dict(data).gift_for == []
    assert Parcel.from_dict({**data, "gift_for": "person.ben"}).gift_for == []
    assert Parcel.from_dict({**data, "gift_for": [BEN, 3, "light.x", None]}).gift_for == [BEN]
    assert _parcel().gift_for == []


# ----- service set_gift -----
async def test_automation_sets_gift_for_and_makes_it_a_gift(hass):
    entry = await _setup(hass)
    parcel = entry.runtime_data.store.parcels[NUMBER]
    seen = []
    entry.runtime_data.async_add_listener(lambda: seen.append(1))
    await _gift_for(hass, [BEN, BEN])  # no user: the push answer flow of issue #64
    assert parcel.gift is True
    assert parcel.gift_for == [BEN]
    assert seen
    # gift: true without gift_for leaves the list alone
    await _call(hass, "set_gift", {"number": NUMBER, "gift": True})
    assert parcel.gift_for == [BEN]
    # gift_for: [] empties only the list
    await _gift_for(hass, [])
    assert (parcel.gift, parcel.gift_for) == (True, [])
    # gift: false empties the list as well
    await _gift_for(hass, [CARA])
    await _call(hass, "set_gift", {"number": NUMBER, "gift": False})
    assert (parcel.gift, parcel.gift_for) == (False, [])


async def test_gift_for_a_single_person_as_text(hass):
    entry = await _setup(hass)
    await _call(hass, "set_gift", {"number": NUMBER, "gift": True, "gift_for": BEN})
    assert entry.runtime_data.store.parcels[NUMBER].gift_for == [BEN]


async def test_unknown_person_and_no_person_are_refused(hass):
    entry = await _setup(hass)
    parcel = entry.runtime_data.store.parcels[NUMBER]
    with pytest.raises(ServiceValidationError) as err:
        await _gift_for(hass, [BEN, "person.nobody"])
    assert err.value.translation_key == "gift_for_unknown"
    assert (parcel.gift, parcel.gift_for) == (False, [])
    with pytest.raises(Exception):  # noqa: B017 - the schema refuses it
        await _gift_for(hass, ["light.x"])
    hass.states.async_set("light.x", "on")
    with pytest.raises(ServiceValidationError) as err:
        await entry.runtime_data.async_set_gift(NUMBER, False, True, None, ["light.x"])
    assert err.value.translation_key == "gift_for_unknown"


async def test_gift_false_with_persons_is_refused(hass):
    entry = await _setup(hass)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "set_gift", {"number": NUMBER, "gift": False, "gift_for": [BEN]})
    assert err.value.translation_key == "gift_for_no_gift"
    assert entry.runtime_data.store.parcels[NUMBER].gift is False


async def test_open_parcels_with_gift_for(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    await _call(hass, "set_gift", {"open_parcels": True, "gift": True, "gift_for": [CARA]})
    assert parcels[NUMBER].gift_for == parcels[OTHER].gift_for == [CARA]


async def test_gift_for_survives_a_restart(hass):
    entry = await _setup(hass)
    await _gift_for(hass, [BEN])
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.parcels[NUMBER].gift_for == [BEN]


# ----- rights -----
async def test_the_recipient_may_change_nothing_the_giver_everything(hass):
    entry = await _setup(hass)
    parcel = entry.runtime_data.store.parcels[NUMBER]
    anna = await _user(hass, "Anna", ANNA)
    ben = await _user(hass, "Ben", BEN)
    await _gift_for(hass, [BEN], user=anna)
    assert parcel.gift_for == [BEN]
    for service, data, key in (
        ("set_gift", {"number": NUMBER, "gift": False}, "gift_not_allowed"),
        ("set_gift", {"number": NUMBER, "gift": True, "gift_for": []}, "gift_not_allowed"),
        ("set_gift", {"number": NUMBER, "gift": True, "gift_for": [CARA]}, "gift_not_allowed"),
        ("remove_parcel", {"number": NUMBER}, "gift_remove_not_allowed"),
        ("rename_parcel", {"number": NUMBER, "name": "Bagger"}, "gift_rename_not_allowed"),
        ("set_owner", {"number": NUMBER, "person": BEN}, "gift_owner_not_allowed"),
    ):
        with pytest.raises(HomeAssistantError) as err:
            await _call(hass, service, data, ben)
        assert err.value.translation_key == key, service
    assert (parcel.gift, parcel.gift_for, parcel.name, parcel.owner) == (True, [BEN], "Lego", None)
    # Marking it as a gift again changes nothing and is no secret: allowed.
    await _call(hass, "set_gift", {"number": NUMBER, "gift": True}, ben)
    # Anna (viewer, not in gift_for) may do everything as before.
    await _call(hass, "set_owner", {"number": NUMBER, "person": ANNA}, anna)
    await _call(hass, "rename_parcel", {"number": NUMBER, "name": "Bagger"}, anna)
    await _gift_for(hass, [CARA], user=anna)
    assert (parcel.owner, parcel.name, parcel.gift_for) == (ANNA, "Bagger", [CARA])
    await _call(hass, "set_gift", {"number": NUMBER, "gift": False}, anna)
    assert (parcel.gift, parcel.gift_for) == (False, [])
    await _gift_for(hass, [BEN], user=anna)
    await _call(hass, "remove_parcel", {"number": NUMBER}, anna)
    assert NUMBER not in entry.runtime_data.store.parcels


async def test_ben_keeps_his_rights_on_other_gifts(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    ben = await _user(hass, "Ben", BEN)
    await _gift_for(hass, [CARA], number=OTHER)
    await _call(hass, "rename_parcel", {"number": OTHER, "name": "Ball"}, ben)
    await _call(hass, "set_gift", {"number": OTHER, "gift": False}, ben)
    assert (parcels[OTHER].name, parcels[OTHER].gift) == ("Ball", False)


async def test_a_non_viewer_may_not_set_gift_for(hass):
    entry = await _setup(hass)
    kid = await _user(hass, "Kid")
    with pytest.raises(HomeAssistantError) as err:
        await _gift_for(hass, [CARA], user=kid)
    assert err.value.translation_key == "gift_not_allowed"
    assert entry.runtime_data.store.parcels[NUMBER].gift is False


async def test_open_parcels_skip_the_recipients_gifts_without_a_word(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    ben = await _user(hass, "Ben", BEN)
    await _gift_for(hass, [BEN])
    await _call(hass, "set_gift", {"number": OTHER, "gift": True})
    await _call(hass, "set_gift", {"open_parcels": True, "gift": False}, ben)
    assert (parcels[NUMBER].gift, parcels[NUMBER].gift_for) == (True, [BEN])
    assert parcels[OTHER].gift is False
    await _call(hass, "set_gift", {"open_parcels": True, "gift": True, "gift_for": [CARA]}, ben)
    assert parcels[NUMBER].gift_for == [BEN]
    assert parcels[OTHER].gift_for == [CARA]


async def test_set_owner_of_a_box_skips_the_recipients_gift(hass):
    entry = await _setup(hass)
    parcels = entry.runtime_data.store.parcels
    ben = await _user(hass, "Ben", BEN)
    for parcel in parcels.values():
        parcel.tracking_carrier, parcel.tracking_ref = "dhl", "JJD000012978217606599"
    await _gift_for(hass, [BEN], number=OTHER)
    await _call(hass, "set_owner", {"number": NUMBER, "person": BEN}, ben)
    assert parcels[NUMBER].owner == BEN
    assert parcels[OTHER].owner is None


# ----- WebSocket -----
async def test_gift_viewer_names_the_hidden_gifts_and_gift_name_refuses_them(
    hass, hass_ws_client
):
    await _setup(hass)
    anna = await _user(hass, "Anna", ANNA)
    ben = await _user(hass, "Ben", BEN)
    kid = await _user(hass, "Kid", CARA)
    viewer = {"type": "parcel_tracker/gift_viewer"}
    name = {"type": "parcel_tracker/gift_name", "number": NUMBER}
    # Without gift_for: as before (plus an empty list).
    await _call(hass, "set_gift", {"number": NUMBER, "gift": True})
    assert (await _ask(hass, hass_ws_client, ben, viewer))["result"] == {
        "viewer": True, "hidden": []
    }
    assert (await _ask(hass, hass_ws_client, ben, name))["result"]["name"] == "Lego"
    await _gift_for(hass, [BEN, CARA])
    assert (await _ask(hass, hass_ws_client, anna, viewer))["result"] == {
        "viewer": True, "hidden": []
    }
    assert (await _ask(hass, hass_ws_client, ben, viewer))["result"] == {
        "viewer": True, "hidden": [NUMBER]
    }
    # A non-viewer is shown no gift anyway: no list (it would tell who a gift is for).
    assert (await _ask(hass, hass_ws_client, kid, viewer))["result"] == {
        "viewer": False, "hidden": []
    }
    reply = await _ask(hass, hass_ws_client, ben, name)
    assert reply["error"]["code"] == "not_allowed"
    assert "Lego" not in str(reply)
    assert (await _ask(hass, hass_ws_client, anna, name))["result"]["name"] == "Lego"


async def test_a_parcel_that_is_no_gift_any_more_is_not_hidden(hass, hass_ws_client):
    entry = await _setup(hass)
    ben = await _user(hass, "Ben", BEN)
    await _gift_for(hass, [BEN])
    entry.runtime_data.store.parcels[NUMBER].gift = False  # (as a mail could never do)
    reply = await _ask(hass, hass_ws_client, ben, {"type": "parcel_tracker/gift_viewer"})
    assert reply["result"]["hidden"] == []


# ----- notifications -----
async def _delivered_push(hass, coordinator, number=NUMBER):
    calls = async_mock_service(hass, "notify", "send_message")
    parcel = coordinator.store.parcels[number]
    old = parcel.status
    parcel.result = TrackingResult.from_dict({"status": "delivered", "events": []})
    pushed = coordinator._notify(parcel, old)
    await hass.async_block_till_done()
    targets = []
    for call in calls:
        value = call.data["entity_id"]
        targets += [value] if isinstance(value, str) else list(value)
    return pushed, sorted(targets)


async def test_no_push_to_the_targets_of_the_persons_a_gift_is_for(hass):
    entry = await _setup(hass, general=(GENERAL, BEN_PHONE, ANNA_PHONE))
    coordinator = entry.runtime_data
    await _gift_for(hass, [BEN])
    # everybody's parcel: the general targets without Ben's
    assert await _delivered_push(hass, coordinator) == (True, [ANNA_PHONE, GENERAL])


async def test_a_gift_owned_by_its_recipient_is_pushed_to_nobody(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator.store.parcels[NUMBER].owner = BEN
    await _gift_for(hass, [BEN])
    assert await _delivered_push(hass, coordinator) == (False, [])


async def test_a_gift_for_others_goes_to_the_owner_as_before(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator.store.parcels[NUMBER].owner = ANNA
    await _gift_for(hass, [BEN])
    assert await _delivered_push(hass, coordinator) == (True, [ANNA_PHONE])


async def test_without_gift_for_the_push_is_unchanged(hass):
    entry = await _setup(hass, general=(GENERAL, BEN_PHONE))
    coordinator = entry.runtime_data
    await _call(hass, "set_gift", {"number": NUMBER, "gift": True})
    assert await _delivered_push(hass, coordinator) == (True, [BEN_PHONE, GENERAL])


# ----- status event -----
async def test_status_event_carries_gift(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    parcel = coordinator.store.parcels[NUMBER]
    parcel.result = TrackingResult.from_dict({"status": "delivered", "events": []})
    coordinator._announce(parcel, ParcelStatus.IN_TRANSIT)
    await _gift_for(hass, [CARA])
    coordinator._announce(parcel, ParcelStatus.IN_TRANSIT)
    await hass.async_block_till_done()
    assert [e.data["gift"] for e in events] == [False, True]
    assert "gift_for" not in events[1].data
    assert CARA not in str(events[1].data)


# ----- never told -----
async def test_gift_for_is_in_no_state_event_diagnostics_or_log(hass, caplog):
    caplog.set_level(logging.DEBUG)
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    # (a person only a gift names: the integration's own person list is no secret)
    hass.states.async_set(DORA, "home")
    status = async_capture_events(hass, EVENT_STATUS_CHANGED)
    added = async_capture_events(hass, EVENT_PARCEL_ADDED)
    await _gift_for(hass, [DORA])
    await _call(hass, "set_gift", {"open_parcels": True, "gift": True, "gift_for": [DORA]})
    with patch(FETCH, return_value=TrackingResult.from_dict({"status": "delivered", "events": []})):
        await coordinator.async_refresh_parcels(NUMBER)
    await hass.async_block_till_done()
    assert status  # the change was announced
    states = [
        s for s in hass.states.async_all()
        if s.entity_id.startswith(("sensor.", "calendar.", "switch.")) and "paket" in s.entity_id
    ]
    assert states
    for state in states:
        assert DORA not in str(state.attributes), state.entity_id
        assert "gift_for" not in str(state.attributes), state.entity_id
    for event in (*status, *added):
        assert DORA not in str(event.data)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "gift_for" not in str(diagnostics)
    assert DORA not in str(diagnostics)
    # (the test helper's own storage mock logs the stored data; Home Assistant does not)
    logged = "\n".join(
        r.getMessage() for r in caplog.records
        if not r.name.startswith("pytest_homeassistant_custom_component")
    )
    assert "parcel_tracker" in logged
    assert "gift_for" not in logged
    assert DORA not in logged


# ----- mails: further boxes and folding take gift_for along -----
def test_fold_takes_gift_for_along():
    order = Parcel("AMZ99999999999994321", "amazon", "mail", None, NOW, NOW, gift=True,
                   gift_for=[BEN])
    parcel = _parcel(gift=True, gift_for=[CARA, BEN])
    parcels = {order.number: order, NUMBER: parcel}
    _fold(parcels, parcel, order)
    assert order.gift_for == [BEN, CARA]
    plain = Parcel("AMZ99999999999994322", "amazon", "mail", None, NOW, NOW)
    parcels = {plain.number: plain, NUMBER: _parcel(gift=True, gift_for=[CARA])}
    _fold(parcels, parcels[NUMBER], plain)
    assert (plain.gift, plain.gift_for) == (True, [CARA])


def test_further_carrier_box_of_a_gift_order_takes_gift_for():
    parcels: dict[str, Parcel] = {}
    first = MailUpdate(
        "ALI100", "aliexpress", ParcelStatus.IN_TRANSIT, NOW,
        title="Item", tracking_ref=NUMBER, tracking_carrier="dhl",
    )  # fmt: skip
    apply_update(parcels, first, NOW, gift=True)
    parcels["ALI100"].gift_for = [BEN]
    second = MailUpdate(
        "ALI100", "aliexpress", ParcelStatus.IN_TRANSIT, NOW + timedelta(hours=1),
        title="Item", tracking_ref=OTHER, tracking_carrier="dhl",
    )  # fmt: skip
    apply_update(parcels, second, NOW + timedelta(hours=1))
    assert (parcels[OTHER].gift, parcels[OTHER].gift_for) == (True, [BEN])
    assert parcels["ALI100"].gift_for == [BEN]


def test_further_shop_box_of_a_gift_order_takes_gift_for():
    order = "AMZ99991565342587125"
    parcels: dict[str, Parcel] = {}
    apply_update(parcels, MailUpdate(
        order, "amazon", ParcelStatus.IN_TRANSIT, NOW, title="Alphamarke Trinkflasche",
        shipment_id="TAbCdE9fG",
    ), NOW)  # fmt: skip
    parcels[order].gift, parcels[order].gift_for = True, [CARA]
    apply_update(parcels, MailUpdate(
        order, "amazon", ParcelStatus.IN_TRANSIT, NOW + timedelta(days=1),
        title="Alphamarke Trinkflasche", shipment_id="UhIjKl9mN",
    ), NOW + timedelta(days=1))  # fmt: skip
    further = parcels[f"{order}P2"]
    assert (further.gift, further.gift_for) == (True, [CARA])
    further.gift_for.append(BEN)
    assert parcels[order].gift_for == [CARA]  # a list of its own


def test_services_yaml_offers_gift_for_as_persons():
    services = yaml.safe_load((BUNDLED_CARD.parents[1] / "services.yaml").read_text("utf-8"))
    field = services["set_gift"]["fields"]["gift_for"]
    assert field["selector"] == {"entity": {"domain": "person", "multiple": True}}
    assert not field.get("required")

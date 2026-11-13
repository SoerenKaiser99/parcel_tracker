"""Personen-Zuordnung: pushes go to the owner's targets, and the service set_owner."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.const import (
    CONF_DEFAULT_OWNER,
    CONF_GIFT_VIEWERS,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    CONF_PERSONS,
    DOMAIN,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.sensor import TodaySensor

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
ANNA = "person.anna"
BEN = "person.ben"
CARA = "person.cara"
GENERAL = "notify.general"
ANNA_PHONE = "notify.anna_phone"
BEN_PHONE = "notify.ben_phone"
NUMBER = "JJD000012978217606560"
IN_TRANSIT = TrackingResult.from_dict({"status": "in_transit", "events": []})


async def _setup(hass, extra=None):
    options = {
        "postcode": "10115",
        CONF_NOTIFY_TARGETS: [GENERAL],
        CONF_NOTIFY_EVENTS: ["delivered"],
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
    with patch(FETCH, return_value=IN_TRANSIT):
        await coordinator.async_add(NUMBER, "dhl", "Lego")
    return coordinator


async def _delivered_push(hass, coordinator):
    """Deliver the parcel and return the notify entities that were pushed to."""
    calls = async_mock_service(hass, "notify", "send_message")
    parcel = coordinator.store.parcels[NUMBER]
    old = parcel.status
    parcel.result = TrackingResult.from_dict({"status": "delivered", "events": []})
    assert coordinator._notify(parcel, old)
    await hass.async_block_till_done()
    targets = []
    for call in calls:
        value = call.data["entity_id"]
        targets += [value] if isinstance(value, str) else list(value)
    return sorted(targets)


async def _set_owner(hass, person, number=NUMBER, user=None):
    context = Context(user_id=user.id) if user else Context()
    await hass.services.async_call(
        DOMAIN, "set_owner", {"number": number, "person": person}, blocking=True, context=context
    )


async def test_push_goes_only_to_the_owners_targets(hass):
    coordinator = await _setup(hass)
    coordinator.store.parcels[NUMBER].owner = ANNA
    assert await _delivered_push(hass, coordinator) == [ANNA_PHONE]


async def test_owner_without_targets_gets_the_general_ones(hass):
    coordinator = await _setup(hass)
    coordinator.store.parcels[NUMBER].owner = CARA
    assert await _delivered_push(hass, coordinator) == [GENERAL]


async def test_parcel_without_owner_gets_the_general_targets(hass):
    coordinator = await _setup(hass)
    assert await _delivered_push(hass, coordinator) == [GENERAL]


async def test_default_person_receives_the_push_without_being_stored(hass):
    coordinator = await _setup(hass, {CONF_DEFAULT_OWNER: BEN})
    parcel = coordinator.store.parcels[NUMBER]
    assert parcel.owner is None
    assert await _delivered_push(hass, coordinator) == [BEN_PHONE]
    assert parcel.owner is None


async def test_parcel_set_to_all_by_hand_gets_general_targets_despite_default(hass):
    coordinator = await _setup(hass, {CONF_DEFAULT_OWNER: BEN})
    await _set_owner(hass, "all")
    parcel = coordinator.store.parcels[NUMBER]
    assert (parcel.owner, parcel.owner_manual) == (None, True)
    assert await _delivered_push(hass, coordinator) == [GENERAL]


async def test_set_owner_sets_person_and_manual_mark(hass):
    coordinator = await _setup(hass)
    seen = []
    coordinator.async_add_listener(lambda: seen.append(1))
    await _set_owner(hass, BEN)
    parcel = coordinator.store.parcels[NUMBER]
    assert (parcel.owner, parcel.owner_manual) == (BEN, True)
    assert seen
    assert await _delivered_push(hass, coordinator) == [BEN_PHONE]


async def test_unknown_person_is_refused(hass):
    coordinator = await _setup(hass)
    with pytest.raises(ServiceValidationError) as err:
        await _set_owner(hass, "person.nobody")
    assert err.value.translation_key == "owner_unknown"
    assert coordinator.store.parcels[NUMBER].owner is None


async def test_unknown_number_is_not_tracked(hass):
    await _setup(hass)
    with pytest.raises(ServiceValidationError) as err:
        await _set_owner(hass, ANNA, number="JJD999999999999999999")
    assert err.value.translation_key == "not_tracked"


async def test_later_mail_does_not_reset_a_manual_owner(hass):
    coordinator = await _setup(hass)
    await _set_owner(hass, BEN)
    parcel = coordinator.store.parcels[NUMBER]
    now = datetime(2026, 10, 1, tzinfo=UTC)
    update = MailUpdate(number=NUMBER, carrier="dhl", status=ParcelStatus.IN_TRANSIT, sent_at=now)
    apply_update(coordinator.store.parcels, update, now, False, ANNA)
    assert (parcel.owner, parcel.owner_manual) == (BEN, True)


async def _gift_setup(hass):
    coordinator = await _setup(hass, {CONF_GIFT_VIEWERS: [ANNA]})
    coordinator.store.parcels[NUMBER].gift = True
    return coordinator


async def _user(hass, name, person=None):
    user = await hass.auth.async_create_user(name, group_ids=["system-admin"])
    if person:
        hass.states.async_set(person, "home", {"user_id": user.id})
    return user


async def test_gift_owner_cannot_be_changed_by_a_non_viewer(hass):
    coordinator = await _gift_setup(hass)
    kid = await _user(hass, "Kid", BEN)
    with pytest.raises(HomeAssistantError) as err:
        await _set_owner(hass, BEN, user=kid)
    assert err.value.translation_key == "gift_owner_not_allowed"
    assert coordinator.store.parcels[NUMBER].owner is None


async def test_gift_owner_can_be_changed_by_a_viewer_or_without_user(hass):
    coordinator = await _gift_setup(hass)
    viewer = await _user(hass, "Anna", ANNA)
    await _set_owner(hass, BEN, user=viewer)
    assert coordinator.store.parcels[NUMBER].owner == BEN
    await _set_owner(hass, CARA)
    assert coordinator.store.parcels[NUMBER].owner == CARA


async def test_add_parcel_with_owner(hass):
    coordinator = await _setup(hass)
    other = "JJD000012978217606561"
    with patch(FETCH, return_value=IN_TRANSIT):
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": other, "carrier": "dhl", "owner": ANNA}, blocking=True
        )
        await hass.services.async_call(
            DOMAIN, "add_parcel",
            {"number": "JJD000012978217606562", "carrier": "dhl", "owner": "all"}, blocking=True,
        )
    parcels = coordinator.store.parcels
    assert (parcels[other].owner, parcels[other].owner_manual) == (ANNA, True)
    everybody = parcels["JJD000012978217606562"]
    assert (everybody.owner, everybody.owner_manual) == (None, True)


async def test_add_parcel_with_unknown_owner_is_refused_and_adds_nothing(hass):
    coordinator = await _setup(hass)
    other = "JJD000012978217606561"
    with patch(FETCH, return_value=IN_TRANSIT), pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "add_parcel",
            {"number": other, "carrier": "dhl", "owner": "person.nobody"}, blocking=True,
        )
    assert err.value.translation_key == "owner_unknown"
    assert other not in coordinator.store.parcels


async def test_non_person_entity_is_refused(hass):
    coordinator = await _setup(hass)
    hass.states.async_set("light.x", "on")
    with pytest.raises(ServiceValidationError) as err:
        await coordinator.async_set_owner(NUMBER, "light.x")  # the schema stops it earlier
    assert err.value.translation_key == "owner_unknown"
    assert coordinator.store.parcels[NUMBER].owner is None


async def test_schema_rejects_a_non_person_id(hass):
    await _setup(hass)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_owner", {"number": NUMBER, "person": "light.x"}, blocking=True
        )


async def test_status_event_carries_the_owner(hass):
    coordinator = await _setup(hass, {CONF_DEFAULT_OWNER: BEN})
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    parcel = coordinator.store.parcels[NUMBER]
    parcel.result = TrackingResult.from_dict({"status": "delivered", "events": []})
    coordinator._announce(parcel, ParcelStatus.IN_TRANSIT)
    parcel.owner = ANNA
    coordinator._announce(parcel, ParcelStatus.IN_TRANSIT)
    await hass.async_block_till_done()
    assert [e.data["owner"] for e in events] == [BEN, ANNA]


async def test_without_persons_everything_goes_to_the_general_targets(hass):
    options = {
        "postcode": "10115",
        CONF_NOTIFY_TARGETS: [GENERAL],
        CONF_NOTIFY_EVENTS: ["delivered"],
    }
    entry = MockConfigEntry(domain=DOMAIN, data={"dhl_api_key": "k"}, options=options)
    entry.add_to_hass(hass)
    hass.states.async_set(GENERAL, "unknown")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    with patch(FETCH, return_value=IN_TRANSIT):
        await coordinator.async_add(NUMBER, "dhl", "Lego")
    assert coordinator.effective_owner(coordinator.store.parcels[NUMBER]) is None
    assert await _delivered_push(hass, coordinator) == [GENERAL]


async def _box(hass, coordinator, gift_second=False):
    """Two shop orders that share one carrier box (same tracking_carrier and ref)."""
    now = datetime(2026, 10, 1, tzinfo=UTC)
    for number in ("AMZ111", "AMZ222"):
        coordinator.store.add(
            Parcel(
                number=number, carrier="amazon", carrier_mode="manual", name=number,
                added_at=now, last_change_at=now, tracking_carrier="dhl", tracking_ref="BOX1",
                gift=gift_second and number == "AMZ222",
            )
        )
    return coordinator.store.parcels["AMZ111"], coordinator.store.parcels["AMZ222"]


async def test_set_owner_moves_the_whole_box_and_pushes_once_to_the_owner(hass):
    coordinator = await _setup(hass)
    first, second = await _box(hass, coordinator)
    await _set_owner(hass, BEN, number="AMZ111")
    assert (first.owner, first.owner_manual) == (BEN, True)
    assert (second.owner, second.owner_manual) == (BEN, True)
    calls = async_mock_service(hass, "notify", "send_message")
    coordinator._announcing = True
    for parcel in (second, first):
        parcel.result = TrackingResult.from_dict({"status": "delivered", "events": []})
        coordinator._announce(parcel, ParcelStatus.IN_TRANSIT)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in calls] == [BEN_PHONE]


async def test_box_with_a_gift_skips_the_gift_for_a_non_viewer(hass):
    """A non-viewer changing a visible order of a box that holds a gift: the order
    changes, the gift stays as it is, and nothing tells that there is a gift."""
    coordinator = await _setup(hass, {CONF_GIFT_VIEWERS: [ANNA]})
    first, second = await _box(hass, coordinator, gift_second=True)
    kid = await _user(hass, "Kid", BEN)
    await _set_owner(hass, BEN, number="AMZ111", user=kid)
    assert (first.owner, first.owner_manual) == (BEN, True)
    assert (second.owner, second.owner_manual) == (None, False)


async def test_gift_of_a_box_is_refused_for_a_non_viewer(hass):
    coordinator = await _setup(hass, {CONF_GIFT_VIEWERS: [ANNA]})
    first, second = await _box(hass, coordinator, gift_second=True)
    kid = await _user(hass, "Kid", BEN)
    with pytest.raises(HomeAssistantError) as err:
        await _set_owner(hass, BEN, number="AMZ222", user=kid)
    assert err.value.translation_key == "gift_owner_not_allowed"
    assert first.owner is None and second.owner is None


async def test_box_with_a_gift_moves_whole_for_a_viewer(hass):
    coordinator = await _setup(hass, {CONF_GIFT_VIEWERS: [ANNA]})
    first, second = await _box(hass, coordinator, gift_second=True)
    viewer = await _user(hass, "Anna", ANNA)
    await _set_owner(hass, BEN, number="AMZ111", user=viewer)
    assert first.owner == BEN and second.owner == BEN


async def test_box_of_two_owners_pushes_once_to_each_owner(hass):
    coordinator = await _setup(hass)
    first, second = await _box(hass, coordinator)
    third = Parcel(
        number="AMZ333", carrier="amazon", carrier_mode="manual", name="AMZ333",
        added_at=first.added_at, last_change_at=first.last_change_at,
        tracking_carrier="dhl", tracking_ref="BOX1",
    )  # fmt: skip
    coordinator.store.add(third)
    first.owner, second.owner, third.owner = ANNA, BEN, BEN
    calls = async_mock_service(hass, "notify", "send_message")
    coordinator._announcing = True
    for parcel in (first, second, third):
        parcel.result = TrackingResult.from_dict({"status": "delivered", "events": []})
        coordinator._announce(parcel, ParcelStatus.IN_TRANSIT)
    await hass.async_block_till_done()
    # Each owner of the shared box hears of it once; the same owner not twice.
    assert [c.data["entity_id"] for c in calls] == [ANNA_PHONE, BEN_PHONE]


async def test_owner_that_is_no_configured_person_counts_as_unassigned(hass):
    coordinator = await _setup(hass, {CONF_DEFAULT_OWNER: BEN})
    hass.states.async_set("person.gone", "home")
    parcel = coordinator.store.parcels[NUMBER]
    for manual in (False, True):
        parcel.owner, parcel.owner_manual = "person.gone", manual
        # Read time only: the default person applies, nothing stored changes.
        assert coordinator.effective_owner(parcel) == BEN
        assert parcel.owner == "person.gone"
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()
    attrs = hass.states.get(f"sensor.paket_{NUMBER.lower()}").attributes
    # Shown as the default person's, not as an owner of its own.
    assert (attrs["owner"], attrs["owner_detected"]) == (BEN, False)
    assert await _delivered_push(hass, coordinator) == [BEN_PHONE]
    coordinator.hass.config_entries.async_update_entry(
        coordinator.entry, options={**coordinator.entry.options, CONF_DEFAULT_OWNER: "all"}
    )
    assert coordinator.effective_owner(parcel) is None


async def test_today_sensor_names_the_configured_persons_and_the_default(hass):
    coordinator = await _setup(hass, {CONF_DEFAULT_OWNER: BEN})
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    attrs = hass.states.get("sensor.pakete_heute").attributes
    # Entity ids only: no address, no notify target.
    assert attrs["persons"] == [ANNA, BEN, CARA]
    assert attrs["default_owner"] == BEN
    assert {"persons", "default_owner"} <= TodaySensor._unrecorded_attributes


async def test_today_sensor_without_persons_names_none(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"dhl_api_key": "k"}, options={"postcode": "10115"}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    attrs = hass.states.get("sensor.pakete_heute").attributes
    assert attrs["persons"] == []
    assert attrs["default_owner"] is None


async def test_person_not_set_up_in_the_integration_is_refused(hass):
    coordinator = await _setup(hass)
    hass.states.async_set("person.guest", "home")
    with pytest.raises(ServiceValidationError) as err:
        await _set_owner(hass, "person.guest")
    assert err.value.translation_key == "owner_unknown"
    assert coordinator.store.parcels[NUMBER].owner is None


async def test_box_of_two_owners_without_targets_pushes_general_targets_once(hass):
    coordinator = await _setup(hass)
    first, second = await _box(hass, coordinator)
    first.owner, second.owner = CARA, None  # both end at the general targets
    calls = async_mock_service(hass, "notify", "send_message")
    coordinator._announcing = True
    for parcel in (first, second):
        parcel.result = TrackingResult.from_dict({"status": "delivered", "events": []})
        coordinator._announce(parcel, ParcelStatus.IN_TRANSIT)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in calls] == [GENERAL]

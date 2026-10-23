"""Event ``parcel_tracker_parcel_added``: fired once for every entry that is new in the store."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.parcel_tracker.const import (
    CONF_DEFAULT_OWNER,
    CONF_GIFT_VIEWERS,
    CONF_PERSONS,
    DOMAIN,
    EVENT_PARCEL_ADDED,
)
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import ParcelStatus
from custom_components.parcel_tracker.store import DuplicateParcel

ANNA = "person.anna"
DHL = "JJD000012978217606560"
DHL2 = "JJD000012978217606561"
SECRET = "Geheimes Lego-Set"


def test_event_name():
    assert EVENT_PARCEL_ADDED == "parcel_tracker_parcel_added"


async def _setup(hass, options=None):
    hass.states.async_set(ANNA, "home", {"user_id": "uid-anna"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"dhl_api_key": "k"},
        options={"postcode": "10115", CONF_GIFT_VIEWERS: [ANNA], **(options or {})},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _update(number, carrier="dhl", status=ParcelStatus.IN_TRANSIT, **kwargs):
    return MailUpdate(number, carrier, status, dt_util.now(), **kwargs)


async def _import(hass, coordinator, updates, message, owner=None):
    parsed = [_ParsedMail(message_id=message, result=MailResult(list(updates)), owner=owner)]
    with patch("custom_components.parcel_tracker.coordinator._parse_mails", return_value=parsed):
        await coordinator.async_import_raw_mail(b"synthetic")
    await hass.async_block_till_done()


async def test_mail_creating_a_parcel_fires_once_with_its_data(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    await _import(hass, coordinator, [_update(DHL, title="Shop GmbH")], "<a@synthetic.example>")
    assert len(events) == 1
    data = events[0].data
    assert data["number"] == DHL
    assert data["name"] == coordinator.display_name(coordinator.store.parcels[DHL])
    assert data["carrier"] == "dhl"
    assert data["owner"] is None
    assert data["gift"] is False
    assert data["entry_id"] == entry.entry_id


async def test_a_second_mail_about_the_same_parcel_fires_nothing(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await _import(hass, coordinator, [_update(DHL)], "<a@synthetic.example>")
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    later = _update(DHL, status=ParcelStatus.OUT_FOR_DELIVERY)
    await _import(hass, coordinator, [later], "<b@synthetic.example>")
    assert events == []


async def test_a_mail_read_twice_fires_once(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    await _import(hass, coordinator, [_update(DHL)], "<a@synthetic.example>")
    await _import(hass, coordinator, [_update(DHL)], "<a@synthetic.example>")
    assert len(events) == 1


async def test_each_new_parcel_of_one_mail_fires_once(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    await _import(hass, coordinator, [_update(DHL), _update(DHL2)], "<a@synthetic.example>")
    assert sorted(e.data["number"] for e in events) == [DHL, DHL2]


async def test_a_further_box_of_an_order_fires_once(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    first = _update(
        "ALI100", "aliexpress", title="Item", tracking_ref=DHL, tracking_carrier="dhl"
    )
    await _import(hass, coordinator, [first], "<a@synthetic.example>")
    assert [e.data["number"] for e in events] == ["ALI100"]
    second = _update(
        "ALI100", "aliexpress", title="Item", tracking_ref=DHL2, tracking_carrier="dhl"
    )
    await _import(hass, coordinator, [second], "<b@synthetic.example>")
    assert [e.data["number"] for e in events] == ["ALI100", DHL2]
    assert events[1].data["carrier"] == "dhl"


async def test_a_carrier_mail_merged_into_an_order_fires_nothing(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    order = _update("ALI100", "aliexpress", title="Item")
    await _import(hass, coordinator, [order], "<a@synthetic.example>")
    # The carrier's own parcel of that number exists first ...
    await _import(hass, coordinator, [_update(DHL)], "<b@synthetic.example>")
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    # ... and the shop mail folds it into the order: one entry is left, nothing new.
    shipped = _update(
        "ALI100", "aliexpress", title="Item", tracking_ref=DHL, tracking_carrier="dhl"
    )
    await _import(hass, coordinator, [shipped], "<c@synthetic.example>")
    assert DHL not in coordinator.store.parcels
    assert coordinator.store.parcels["ALI100"].tracking_ref == DHL
    assert events == []


async def test_a_carrier_mail_matched_to_an_order_on_arrival_fires_nothing(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    order = _update("ALI100", "aliexpress", title="Item")
    await _import(hass, coordinator, [order], "<a@synthetic.example>")
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    with patch(
        "custom_components.parcel_tracker.mail.apply._merge_candidate",
        side_effect=lambda parcels, *_: parcels["ALI100"],
    ):
        await _import(hass, coordinator, [_update(DHL, shop="aliexpress")], "<b@synthetic.example>")
    assert DHL not in coordinator.store.parcels
    assert events == []


async def test_a_parcel_created_and_folded_in_the_same_import_fires_nothing(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    order = _update("ALI100", "aliexpress", title="Item")
    await _import(hass, coordinator, [order], "<a@synthetic.example>")
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    # One mail: the carrier's parcel is created, then the shop's words fold it into the
    # order (the real ``_take_shop_facts`` / ``_fold``): nothing new is left.
    shipped = _update(
        "ALI100", "aliexpress", title="Item", tracking_ref=DHL, tracking_carrier="dhl"
    )
    await _import(hass, coordinator, [_update(DHL), shipped], "<b@synthetic.example>")
    assert DHL not in coordinator.store.parcels
    assert coordinator.store.parcels["ALI100"].tracking_ref == DHL
    assert events == []


async def test_an_order_that_takes_in_an_announced_parcel_fires_nothing(hass):
    """Carrier mail first, then the shop mail that creates the order and absorbs it: one
    box, one event (the carrier parcel's)."""
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    await _import(hass, coordinator, [_update(DHL)], "<a@synthetic.example>")
    shipped = _update(
        "ALI100", "aliexpress", title="Item", tracking_ref=DHL, tracking_carrier="dhl"
    )
    await _import(hass, coordinator, [shipped], "<b@synthetic.example>")
    assert list(coordinator.store.parcels) == ["ALI100"]
    assert coordinator.store.parcels["ALI100"].tracking_ref == DHL
    assert [e.data["number"] for e in events] == [DHL]


async def test_the_shop_mail_first_and_the_carrier_mail_after_fire_once(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    shipped = _update(
        "ALI100", "aliexpress", title="Item", tracking_ref=DHL, tracking_carrier="dhl"
    )
    await _import(hass, coordinator, [shipped], "<a@synthetic.example>")
    await _import(hass, coordinator, [_update(DHL)], "<b@synthetic.example>")
    assert list(coordinator.store.parcels) == ["ALI100"]
    assert [e.data["number"] for e in events] == ["ALI100"]


async def test_imap_import_fires_after_the_sensors_know_the_parcel(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    seen = []

    @callback
    def _added(event):
        seen.append((event.data["number"], DHL in coordinator.data))

    hass.bus.async_listen(EVENT_PARCEL_ADDED, _added)

    class Mailbox:
        def fetch_unseen(self):
            return [("1", b"synthetic")]

        def finish(self, dispositions, move):
            pass

    parsed = [_ParsedMail(message_id="<i@synthetic.example>",
                          result=MailResult([_update(DHL)]))]
    with patch(
        "custom_components.parcel_tracker.coordinator._parse_mails", return_value=parsed
    ):
        await coordinator._import_mail(Mailbox(), dt_util.utcnow())
    await hass.async_block_till_done()
    assert seen == [(DHL, True)]


async def test_add_parcel_fires_once_and_not_for_a_duplicate(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    await hass.services.async_call(
        DOMAIN, "add_parcel", {"number": DHL, "carrier": "dhl", "name": "Buch"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["number"] == DHL
    assert events[0].data["name"] == "Buch"
    assert events[0].data["carrier"] == "dhl"
    assert events[0].data["gift"] is False
    with pytest.raises(DuplicateParcel):
        await coordinator.async_add(DHL, "dhl", None)
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_other_carrier_added_through_17track_fires_once(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    with (
        patch.object(coordinator, "_t17_client"),
        patch.object(coordinator, "_register17", return_value=123),
        patch.object(coordinator, "async_update_quota"),
    ):
        await coordinator._add_other("XY123456789", "Lego")
    await hass.async_block_till_done()
    assert [e.data["number"] for e in events] == ["XY123456789"]
    assert events[0].data["carrier"] == "other"


async def test_owner_is_the_effective_owner(hass):
    hass.states.async_set("person.ben", "home")
    options = {
        CONF_PERSONS: [{"person": ANNA, "addresses": []}, {"person": "person.ben"}],
        CONF_DEFAULT_OWNER: "person.ben",
    }
    entry = await _setup(hass, options)
    coordinator = entry.runtime_data
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    await _import(hass, coordinator, [_update(DHL)], "<a@synthetic.example>")
    await coordinator.async_add(DHL2, "dhl", None, owner=ANNA)
    await hass.async_block_till_done()
    owners = {e.data["number"]: e.data["owner"] for e in events}
    parcels = coordinator.store.parcels
    assert owners == {
        DHL: coordinator.effective_owner(parcels[DHL]),
        DHL2: coordinator.effective_owner(parcels[DHL2]),
    }
    assert owners[DHL2] == ANNA


async def test_a_gift_never_tells_its_real_name(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_set_gift_mode(True, None)
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    await _import(hass, coordinator, [_update(DHL, title=SECRET)], "<a@synthetic.example>")
    await coordinator.async_add(DHL2, "dhl", SECRET)
    order = _update("AMZ99991565342587125", "amazon", title=SECRET)
    await _import(hass, coordinator, [order], "<b@synthetic.example>")
    await hass.async_block_till_done()
    assert len(events) == 3
    for event in events:
        assert event.data["gift"] is True
        assert event.data["name"].startswith("Geschenk · ")
        assert "Lego" not in repr(event.data)
        assert set(event.data) == {"entry_id", "number", "name", "carrier", "owner", "gift"}


async def test_nothing_fires_when_the_stored_parcels_load_again(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await _import(hass, coordinator, [_update(DHL)], "<a@synthetic.example>")
    await coordinator.async_add(DHL2, "dhl", None)
    events = async_capture_events(hass, EVENT_PARCEL_ADDED)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    coordinator._mail_next = dt_util.utcnow() - timedelta(minutes=1)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert set(coordinator.store.parcels) == {DHL, DHL2}
    assert events == []

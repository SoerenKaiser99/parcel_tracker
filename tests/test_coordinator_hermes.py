"""Hermes parcel redirected to a PaketShop (issue #18): "Abholbereit" is announced
once, the collection afterwards is "Zugestellt"."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.carriers import hermes as hermes_module
from custom_components.parcel_tracker.carriers.hermes import HermesCarrier, parse_hermes
from custom_components.parcel_tracker.const import (
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    NOTIFY_EVENTS,
)
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.models import ParcelStatus
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME
from .test_hermes import DELIVERED_FLAG, _shop_history

PHONE = "notify.mobile_app_handy"
NUMBER = "H9999999999999999901"


class AnsweringHermes(HermesCarrier):
    """The real parser behind a canned answer (no network)."""

    def __init__(self):
        self.payload: list = []

    async def fetch(self, number, postcode):
        return parse_hermes(self.payload)


@pytest.mark.parametrize(
    ("waiting", "collected", "flag"),
    [
        ("SHOP_CODE_NOBODY_KNOWS", "COLLECTION_CODE_NOBODY_KNOWS", None),
        ("DELIVERED_PARCELSHOP", "PICKED_UP_BY_RECIPIENT", None),
        ("DELIVERED_PARCELSHOP", "DELIVERED_PARCELSHOP", DELIVERED_FLAG),
        ("PARCELSHOP_ITEMS_FOR_COLLECTION", "COLLECTED", DELIVERED_FLAG),
    ],
    ids=["unknown", "delivered-shop", "delivered-shop-with-flag", "known-with-flag"],
)
async def test_shop_parcel_is_announced_as_ready_once_and_then_as_delivered(
    hass, freezer, waiting, collected, flag
):
    hermes_module._WARNED.clear()
    freezer.move_to(DAYTIME)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"postcode": "10115"},
        options={CONF_NOTIFY_TARGETS: [PHONE], CONF_NOTIFY_EVENTS: list(NOTIFY_EVENTS)},
    )
    entry.add_to_hass(hass)
    hass.states.async_set(PHONE, "unknown")
    store = ParcelStore(hass)
    await store.async_load()
    carrier = AnsweringHermes()
    coord = ParcelCoordinator(hass, entry, store, {"hermes": carrier})
    carrier.payload = _shop_history("DELIVERY_TOUR_STARTED")
    parcel = await coord.async_add(NUMBER, "hermes", "Schuhe")
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert parcel.status is ParcelStatus.OUT_FOR_DELIVERY
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)

    async def poll(payload):
        carrier.payload = payload
        freezer.tick(timedelta(minutes=10))
        await coord.async_refresh()
        await hass.async_block_till_done()

    for _ in range(3):  # the step is seen on several polls, told once
        await poll(_shop_history("DELIVERY_TOUR_STARTED", waiting, attributes=flag))
    assert parcel.status is ParcelStatus.AWAITING_PICKUP
    assert [e.data["new_status"] for e in events] == ["awaiting_pickup"]
    assert [c.data["message"] for c in calls] == ["📍 Schuhe (Hermes) liegt zur Abholung bereit"]

    for _ in range(2):
        await poll(_shop_history("DELIVERY_TOUR_STARTED", waiting, collected, flag))
    assert parcel.status is ParcelStatus.DELIVERED
    assert [e.data["new_status"] for e in events] == ["awaiting_pickup", "delivered"]
    assert [c.data["message"] for c in calls] == [
        "📍 Schuhe (Hermes) liegt zur Abholung bereit",
        "✅ Schuhe (Hermes) wurde zugestellt",
    ]

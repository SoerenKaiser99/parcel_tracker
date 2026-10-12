"""v0.3.31: corrections after a code review - "Erhalten" (the hand mark)."""

from datetime import timedelta

from homeassistant.helpers import issue_registry as ir

from custom_components.parcel_tracker.carriers.base import BERLIN, CarrierUnavailable
from custom_components.parcel_tracker.const import DOMAIN
from custom_components.parcel_tracker.mail.apply import (
    ASSUMED_TEXT,
    MANUAL_TEXT,
    close_unconfirmed,
    mark_received,
)
from custom_components.parcel_tracker.models import ParcelStatus
from custom_components.parcel_tracker.schedule import delivered_today, should_remove, summarize

from .test_coordinator import result, setup  # noqa: F401 - the fixture
from .test_coordinator_notify import _start
from .test_order_closing import (
    NOW,
    ORDER,
    TODAY,
    _coordinator,
    _days,
    _order,
    _prepared,
    _refresh,
)


# ----- B2: "Erhalten" on an order closed on its own only confirms it -----
def test_erhalten_on_a_closed_order_changes_flag_and_words_only():
    order = _order(first=TODAY - _days(6), changed=NOW - _days(8))
    closed = NOW - timedelta(hours=3)  # today
    close_unconfirmed(order, closed)
    mark_received(order, NOW)
    assert (order.assumed_delivered, order.manual_delivered) == (False, True)
    assert order.result.status_text == MANUAL_TEXT
    assert [e.text for e in order.result.events][:2] == [MANUAL_TEXT, ASSUMED_TEXT]
    # Nobody knows when it came: no time of delivery, and it never counts for today.
    assert order.result.delivered_at is None
    assert not delivered_today(order, TODAY, BERLIN)
    assert summarize([order], TODAY, BERLIN).delivered_today == []
    # The days it is kept go on counting from the closing.
    assert order.last_change_at == closed
    assert not should_remove(order, closed + _days(3), 3)
    assert should_remove(order, closed + _days(3) + timedelta(minutes=1), 3)


async def test_erhalten_on_a_closed_order_fires_no_event(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(6), changed=NOW - _days(8))
    close_unconfirmed(order, NOW - _days(1))
    coord = await _coordinator(hass, hass_storage, [order])
    await _refresh(hass, coord)
    await _start(hass)
    await coord.async_mark_delivered(ORDER)
    await hass.async_block_till_done()
    order = coord.store.parcels[ORDER]
    assert (order.status, order.manual_delivered) == (ParcelStatus.DELIVERED, True)
    assert order.last_change_at == NOW - _days(1)
    assert events == [] and calls == []
    assert not delivered_today(order, TODAY, BERLIN)
    await coord.async_shutdown()


# ----- B3: a carrier nobody asks any more has no repair issue -----
async def _broken(hass, coord, fake, freezer):
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    await coord.async_add("123", "fake", None)
    fake.answers = [CarrierUnavailable("down")]
    for _ in range(30):
        freezer.tick(timedelta(hours=1))
        await coord.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "carrier_broken_fake") is not None


async def test_marking_the_last_parcel_of_a_broken_carrier_clears_the_issue(
    hass, setup, freezer  # noqa: F811
):
    coord, fake = setup
    await _broken(hass, coord, fake, freezer)
    await coord.async_mark_delivered("123")
    assert ir.async_get(hass).async_get_issue(DOMAIN, "carrier_broken_fake") is None
    assert "fake" not in coord._first_fail


async def test_removing_the_last_parcel_of_a_broken_carrier_clears_the_issue(
    hass, setup, freezer  # noqa: F811
):
    coord, fake = setup
    await _broken(hass, coord, fake, freezer)
    await coord.async_remove("123")
    assert ir.async_get(hass).async_get_issue(DOMAIN, "carrier_broken_fake") is None
    assert "fake" not in coord._first_fail


async def test_the_issue_stays_while_another_parcel_of_the_carrier_is_asked(
    hass, setup, freezer  # noqa: F811
):
    coord, fake = setup
    await _broken(hass, coord, fake, freezer)
    await coord.async_add("456", "fake", None)
    await coord.async_mark_delivered("123")
    assert ir.async_get(hass).async_get_issue(DOMAIN, "carrier_broken_fake") is not None
    assert "fake" in coord._first_fail
    await coord.async_remove("456")
    assert ir.async_get(hass).async_get_issue(DOMAIN, "carrier_broken_fake") is None

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.parcel_tracker.carriers.base import (
    AuthError,
    Carrier,
    CarrierUnavailable,
    Match,
    MissingCredentials,
    NotFound,
    RateLimited,
)
from custom_components.parcel_tracker.const import DOMAIN, EVENT_STATUS_CHANGED
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.detect import UnsupportedNumber
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.store import DuplicateParcel, ParcelStore

from .conftest import DAYTIME


def result(status, eta=None, delivered_at=None):
    return TrackingResult(status, "txt", eta, None, None, "Bonn", None, None, delivered_at, [])


class FakeCarrier(Carrier):
    key = "fake"
    name = "Fake"

    def __init__(self):
        self.answers: list = []
        self.calls = 0

    @staticmethod
    def matches(number):
        return Match.POSSIBLE if number.isdigit() else Match.NO

    async def fetch(self, number, postcode):
        self.calls += 1
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeCarrierA(FakeCarrier):
    """Second candidate carrier used to test 'first hit wins' ordering."""

    key = "fake1"
    name = "FakeA"


class FakeCarrierB(FakeCarrier):
    """Second candidate carrier used to test 'first hit wins' ordering."""

    key = "fake2"
    name = "FakeB"


class FakeDhlCarrier(FakeCarrier):
    """Stands in for DhlCarrier so the "dhl" key/reauth path can be tested."""

    key = "dhl"
    name = "DHL"


@pytest.fixture
async def setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"}, options={})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    fake = FakeCarrier()
    coord = ParcelCoordinator(hass, entry, store, {"fake": fake})
    return coord, fake


async def _new_coordinator(hass, carriers):
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"}, options={})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    return ParcelCoordinator(hass, entry, store, carriers)


async def test_add_polls_immediately(hass, setup):
    coord, fake = setup
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    parcel = await coord.async_add("0147 5194", "auto", "Test")
    assert parcel.number == "01475194"
    assert parcel.carrier == "fake"
    assert parcel.status is ParcelStatus.IN_TRANSIT
    with pytest.raises(DuplicateParcel):
        await coord.async_add("01475194", "auto", None)
    with pytest.raises(UnsupportedNumber):
        await coord.async_add("TBA1", "auto", None)
    with pytest.raises(ValueError):
        await coord.async_add("123", "nope", None)


async def test_not_found_everywhere(hass, setup):
    coord, fake = setup
    fake.answers = [NotFound("x")]
    parcel = await coord.async_add("123", "auto", None)
    assert parcel.carrier is None
    assert parcel.last_error == "not_found"


async def test_events_suppressed_on_first_refresh(hass, setup, freezer: FrozenDateTimeFactory):
    freezer.move_to(DAYTIME)
    coord, fake = setup
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    await coord.async_add("123", "fake", None)

    # Status changes before the first scheduled refresh -> still no event.
    fake.answers = [result(ParcelStatus.OUT_FOR_DELIVERY, eta=date(2026, 9, 29))]
    freezer.tick(timedelta(minutes=31))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 0

    # Second refresh is not the "first" one any more -> event fires.
    fake.answers = [result(ParcelStatus.DELIVERED, delivered_at=datetime.now(UTC))]
    freezer.tick(timedelta(minutes=31))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["old_status"] == "out_for_delivery"
    assert events[0].data["new_status"] == "delivered"


async def test_unavailable_keeps_last_result_and_backs_off(hass, setup, freezer):
    freezer.move_to(DAYTIME)
    coord, fake = setup
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    await coord.async_add("123", "fake", None)
    fake.answers = [CarrierUnavailable("down")]
    freezer.tick(timedelta(minutes=31))
    await coord.async_refresh()
    parcel = coord.store.get("123")
    assert parcel.status is ParcelStatus.IN_TRANSIT
    assert parcel.last_error == "unavailable"
    assert parcel.error_streak == 1
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(minutes=5)


async def test_carrier_broken_issue_after_24h(hass, setup, freezer):
    coord, fake = setup
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    await coord.async_add("123", "fake", None)
    fake.answers = [CarrierUnavailable("down")]
    for _ in range(30):
        freezer.tick(timedelta(hours=1))
        await coord.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "carrier_broken_fake") is not None
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    freezer.tick(timedelta(hours=2))
    await coord.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "carrier_broken_fake") is None


async def test_auth_error_on_non_dhl_creates_no_issue(hass, setup):
    coord, fake = setup
    fake.answers = [AuthError("bad")]
    parcel = await coord.async_add("123", "fake", None)
    assert parcel.last_error == "auth"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "dhl_auth") is None  # only for dhl


async def test_auth_error_creates_dhl_issue_and_starts_reauth(hass):
    dhl_like = FakeDhlCarrier()
    dhl_like.answers = [AuthError("bad key")]
    coord = await _new_coordinator(hass, {"dhl": dhl_like})
    with patch.object(coord.entry, "async_start_reauth") as reauth:
        parcel = await coord.async_add("123", "auto", None)
    reauth.assert_called_once()
    assert parcel.last_error == "auth"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "dhl_auth") is not None


async def test_missing_key_sets_last_error_without_issue_or_reauth(hass):
    dhl_like = FakeDhlCarrier()
    dhl_like.answers = [MissingCredentials("no key")]
    coord = await _new_coordinator(hass, {"dhl": dhl_like})
    with patch.object(coord.entry, "async_start_reauth") as reauth:
        parcel = await coord.async_add("123", "auto", None)
    reauth.assert_not_called()
    assert parcel.last_error == "missing_key"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "dhl_auth") is None


async def test_missing_key_falls_through_to_next_candidate(hass):
    dhl_like = FakeDhlCarrier()
    dhl_like.answers = [MissingCredentials("no key")]
    fallback = FakeCarrierB()
    fallback.answers = [result(ParcelStatus.IN_TRANSIT)]
    coord = await _new_coordinator(hass, {"dhl": dhl_like, "fake2": fallback})
    with patch.object(coord.entry, "async_start_reauth") as reauth:
        parcel = await coord.async_add("123", "auto", None)
    reauth.assert_not_called()
    assert parcel.carrier == "fake2"
    assert parcel.last_error is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, "dhl_auth") is None


async def test_cleanup_delivered(hass, setup, freezer):
    coord, fake = setup
    now = datetime.now(UTC)
    fake.answers = [result(ParcelStatus.DELIVERED, delivered_at=now)]
    await coord.async_add("123", "fake", None)
    freezer.tick(timedelta(days=3, hours=1))
    await coord.async_refresh()
    assert coord.store.get("123") is None


async def test_stale_not_delivered_removed_after_30_days(hass, setup, freezer):
    coord, fake = setup
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    await coord.async_add("123", "fake", None)
    freezer.tick(timedelta(days=31))
    await coord.async_refresh()
    assert coord.store.get("123") is None


async def test_rename_and_remove(hass, setup):
    coord, fake = setup
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    await coord.async_add("123", "fake", None)
    await coord.async_rename("123", "Neu")
    assert coord.store.get("123").name == "Neu"
    await coord.async_remove("123")
    assert coord.store.get("123") is None
    with pytest.raises(KeyError):
        await coord.async_remove("123")


async def test_rate_limited_sets_next_poll_from_retry_after(hass, setup, freezer):
    freezer.move_to(DAYTIME)
    coord, fake = setup
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    await coord.async_add("123", "fake", None)
    fake.answers = [RateLimited(retry_after=120)]
    freezer.tick(timedelta(minutes=31))
    await coord.async_refresh()
    parcel = coord.store.get("123")
    assert parcel.last_error == "rate_limited"
    assert parcel.next_poll_at - parcel.last_poll_at == timedelta(seconds=120)


async def test_first_matching_candidate_wins(hass):
    first = FakeCarrierA()
    first.answers = [NotFound("x")]
    second = FakeCarrierB()
    second.answers = [result(ParcelStatus.IN_TRANSIT)]
    coord = await _new_coordinator(hass, {"fake1": first, "fake2": second})
    parcel = await coord.async_add("123", "auto", None)
    assert parcel.carrier == "fake2"
    assert first.calls == 1
    assert second.calls == 1


async def test_unexpected_error_does_not_block_other_parcels(hass, setup, freezer):
    freezer.move_to(DAYTIME)
    coord, fake = setup
    fake.answers = [result(ParcelStatus.IN_TRANSIT)]
    await coord.async_add("111", "fake", None)
    await coord.async_add("222", "fake", None)
    freezer.tick(timedelta(minutes=31))
    fake.answers = [RuntimeError("boom"), result(ParcelStatus.IN_TRANSIT)]
    await coord.async_refresh()
    first = coord.store.get("111")
    second = coord.store.get("222")
    assert first.last_error == "unavailable"
    assert first.error_streak == 1
    assert first.next_poll_at - first.last_poll_at == timedelta(minutes=5)
    assert second.last_error is None
    assert second.status is ParcelStatus.IN_TRANSIT


async def test_unknown_stored_carrier_is_carrier_not_found(hass, setup):
    coord, fake = setup
    now = dt_util.utcnow()
    parcel = Parcel(
        number="999",
        carrier="ghost",
        carrier_mode="manual",
        name=None,
        added_at=now,
        last_change_at=now,
    )
    coord.store.add(parcel)
    await coord.async_refresh()
    stored = coord.store.get("999")
    assert stored.last_error == "carrier_not_found"
    assert stored.next_poll_at - stored.last_poll_at == timedelta(hours=1)


class RecordingDhl(FakeDhlCarrier):
    """Remembers which numbers were asked for."""

    def __init__(self):
        super().__init__()
        self.numbers: list[str] = []

    async def fetch(self, number, postcode):
        self.numbers.append(number)
        return await super().fetch(number, postcode)


def _mail_parcel(number, carrier, **kwargs) -> Parcel:
    now = dt_util.utcnow()
    return Parcel(number, carrier, "mail", None, now, now, **kwargs)


async def test_mail_only_parcels_are_never_polled(hass):
    dhl = RecordingDhl()
    dhl.answers = [result(ParcelStatus.IN_TRANSIT)]
    coord = await _new_coordinator(hass, {"dhl": dhl})
    coord.store.add(_mail_parcel("AMZ99991565342587125", "amazon"))
    coord.store.add(_mail_parcel("1Z999AA11026832876", "ups"))
    await coord.async_refresh()
    assert dhl.numbers == []
    assert coord.store.get("AMZ99991565342587125").last_poll_at is None


async def test_parcel_with_tracking_ref_is_polled_by_that_number(hass):
    dhl = RecordingDhl()
    dhl.answers = [result(ParcelStatus.OUT_FOR_DELIVERY)]
    coord = await _new_coordinator(hass, {"dhl": dhl})
    coord.store.add(
        _mail_parcel(
            "AMZ99991565342587125",
            "amazon",
            tracking_ref="JJD000012978217606560",
            tracking_carrier="dhl",
        )
    )
    await coord.async_refresh()
    assert dhl.numbers == ["JJD000012978217606560"]
    parcel = coord.store.get("AMZ99991565342587125")
    assert parcel.carrier == "amazon"
    assert parcel.status is ParcelStatus.OUT_FOR_DELIVERY


async def test_expired_delivery_code_is_dropped(hass, freezer):
    freezer.move_to("2026-08-21 10:00:00+00:00")
    coord = await _new_coordinator(hass, {})
    old = _mail_parcel("AMZ1", "amazon", delivery_code="123", delivery_code_day=date(2026, 8, 20))
    today = _mail_parcel("AMZ2", "amazon", delivery_code="654", delivery_code_day=date(2026, 8, 21))
    coord.store.add(old)
    coord.store.add(today)
    await coord.async_refresh()
    assert old.delivery_code is None and old.delivery_code_day is None
    assert today.delivery_code == "654"

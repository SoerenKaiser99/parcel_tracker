""""Kommt gleich" (DHL "wird gleich zugestellt"): its own event and push, once a day."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.const import (
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    EVENT_ARRIVING_SOON,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import DAYTIME
from .test_coordinator_notify import (
    NUMBER,
    PHONE,
    FakeMailbox,
    _restarted,
    _sent,
    _setup,
    _start,
    result,
)

SOON = "Wird gleich zugestellt"


def _soon(minutes: int = 15) -> MailUpdate:
    """The mail as the parser makes it: sent now, in delivery, the window from now on."""
    sent = dt_util.now().replace(second=0, microsecond=0)
    return MailUpdate(
        NUMBER, "dhl", ParcelStatus.OUT_FOR_DELIVERY, sent, eta_date=sent.date(),
        eta_from=sent, eta_to=sent + timedelta(minutes=minutes), status_text=SOON,
    )


async def _mail(hass, coord, update: MailUpdate, message_id: str) -> None:
    coord.mailbox.mails = [("1", b"raw")]
    coord._mail_next = None
    parsed = [_ParsedMail(message_id=message_id, result=MailResult(updates=[update]))]
    with patch("custom_components.parcel_tracker.coordinator._parse_mails", return_value=parsed):
        await coord.async_import_mail()
    await hass.async_block_till_done()


async def _in_delivery(hass, freezer, options=None):
    """A coordinator with the parcel in delivery (by a lookup), and the captures."""
    freezer.move_to(DAYTIME)
    await hass.config.async_set_time_zone("Europe/Berlin")
    coord, carrier, parcel = await _setup(
        hass, options or {CONF_NOTIFY_TARGETS: [PHONE]}, FakeMailbox(), targets=(PHONE,)
    )
    carrier.answer = result(ParcelStatus.OUT_FOR_DELIVERY, eta_date=dt_util.now().date())
    freezer.tick(timedelta(hours=1))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert parcel.status is ParcelStatus.OUT_FOR_DELIVERY
    calls = async_mock_service(hass, "notify", "send_message")
    soon = async_capture_events(hass, EVENT_ARRIVING_SOON)
    status = async_capture_events(hass, EVENT_STATUS_CHANGED)
    return coord, carrier, parcel, calls, soon, status


async def test_a_soon_mail_fires_its_event_and_pushes_once_a_day(hass, freezer):
    coord, _, parcel, calls, soon, status = await _in_delivery(hass, freezer)

    await _mail(hass, coord, _soon(), "<s1@example.org>")

    # 10:00 UTC plus the hour of _in_delivery: 13:00 in Berlin.
    assert _sent(calls) == [
        (PHONE, "Paket Tracker", "🔔 Kopfhörer (DHL) wird gleich zugestellt – bis 13:15 Uhr")
    ]
    (event,) = soon
    assert event.data["entry_id"] == coord.entry.entry_id
    assert (event.data["number"], event.data["name"]) == (NUMBER, "Kopfhörer")
    assert (event.data["carrier"], event.data["carrier_name"]) == ("dhl", "DHL")
    assert event.data["event"] == "arriving_soon"
    assert event.data["eta_to"] == parcel.result.eta_to.isoformat()
    assert (event.data["owner"], event.data["gift"], event.data["outgoing"]) == (
        None, False, False
    )
    # No status change: the parcel stays in delivery.
    assert status == []

    # DHL's second mail minutes later: the window moves on, nobody is told again.
    freezer.tick(timedelta(minutes=6))
    await _mail(hass, coord, _soon(), "<s2@example.org>")
    assert len(soon) == 1 and len(calls) == 1
    assert f"{parcel.result.eta_to:%H:%M}" == "13:21"


async def test_soon_is_pushed_only_when_chosen_but_always_fires_its_event(hass, freezer):
    options = {CONF_NOTIFY_TARGETS: [PHONE], CONF_NOTIFY_EVENTS: ["delivered"]}
    coord, _, _, calls, soon, _ = await _in_delivery(hass, freezer, options)

    await _mail(hass, coord, _soon(), "<s1@example.org>")

    assert len(soon) == 1 and calls == []


async def test_a_soon_mail_read_too_late_tells_nothing(hass, freezer):
    coord, _, parcel, calls, soon, _ = await _in_delivery(hass, freezer)
    late = _soon()
    freezer.tick(timedelta(minutes=20))

    await _mail(hass, coord, late, "<s1@example.org>")

    assert soon == [] and calls == []
    assert parcel.result.status_text == SOON  # (the history line, no window)
    assert parcel.result.eta_from is None


async def test_a_lookup_keeps_the_window_until_it_is_over(hass, freezer):
    coord, carrier, parcel, _, _, _ = await _in_delivery(hass, freezer)
    await _mail(hass, coord, _soon(), "<s1@example.org>")
    window = (parcel.result.eta_from, parcel.result.eta_to)
    today = dt_util.now().date()
    later = dt_util.now().replace(hour=16, minute=0, second=0, microsecond=0)
    carrier.answer = result(
        ParcelStatus.OUT_FOR_DELIVERY, eta_date=today,
        eta_from=later, eta_to=later + timedelta(hours=2),
    )

    freezer.tick(timedelta(minutes=5))
    parcel.next_poll_at = None
    await coord.async_refresh()
    assert (parcel.result.eta_from, parcel.result.eta_to) == window

    freezer.tick(timedelta(minutes=15))
    parcel.next_poll_at = None
    await coord.async_refresh()
    assert (parcel.result.eta_from, parcel.result.eta_to) == (later, later + timedelta(hours=2))


async def test_soon_while_starting_is_told_once_started_if_still_running(hass, freezer):
    freezer.move_to(DAYTIME)
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.set_state(CoreState.starting)
    coord, _ = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    coord.mailbox = FakeMailbox()
    calls = async_mock_service(hass, "notify", "send_message")
    soon = async_capture_events(hass, EVENT_ARRIVING_SOON)
    await coord.async_refresh()
    await hass.async_block_till_done()

    await _mail(hass, coord, _soon(), "<s1@example.org>")
    assert soon == []

    await _start(hass)
    assert len(soon) == 1
    # The change to "in delivery" waited as well: one push, the closer one.
    assert [sent[2] for sent in _sent(calls)] == [
        "🔔 Kopfhörer (DHL) wird gleich zugestellt – bis 17:15 Uhr",
    ]


async def _waiting_soon(hass, freezer):
    """Home Assistant starts; the parcel went to "in delivery" and its soon mail came."""
    freezer.move_to(DAYTIME)
    hass.set_state(CoreState.starting)
    coord, carrier = await _restarted(hass, freezer, result(ParcelStatus.OUT_FOR_DELIVERY))
    coord.mailbox = FakeMailbox()
    calls = async_mock_service(hass, "notify", "send_message")
    soon = async_capture_events(hass, EVENT_ARRIVING_SOON)
    await coord.async_refresh()
    await hass.async_block_till_done()
    await _mail(hass, coord, _soon(), "<s1@example.org>")
    return coord, carrier, calls, soon


async def test_soon_while_starting_is_dropped_once_its_window_is_over(hass, freezer):
    _coord, _, calls, soon = await _waiting_soon(hass, freezer)

    freezer.tick(timedelta(minutes=16))
    await _start(hass)

    assert soon == []
    # The change to "in delivery" is pushed as usual then.
    (sent,) = _sent(calls)
    assert sent[2].startswith("📦 Kopfhörer (DHL) ist in Zustellung")


async def test_soon_while_starting_is_dropped_once_the_parcel_is_delivered(hass, freezer):
    coord, carrier, calls, soon = await _waiting_soon(hass, freezer)
    carrier.answer = result(ParcelStatus.DELIVERED)
    freezer.tick(timedelta(minutes=5))
    coord.store.parcels[NUMBER].next_poll_at = None
    await coord.async_refresh()
    await hass.async_block_till_done()

    await _start(hass)

    assert soon == []
    assert [sent[2] for sent in _sent(calls)] == ["✅ Kopfhörer (DHL) wurde zugestellt"]


async def test_a_soon_mail_that_brings_the_parcel_into_delivery_is_one_push(hass, freezer):
    freezer.move_to(DAYTIME)
    await hass.config.async_set_time_zone("Europe/Berlin")
    coord, _, parcel = await _setup(
        hass, {CONF_NOTIFY_TARGETS: [PHONE]}, FakeMailbox(), targets=(PHONE,)
    )
    assert parcel.status is ParcelStatus.IN_TRANSIT
    calls = async_mock_service(hass, "notify", "send_message")
    status = async_capture_events(hass, EVENT_STATUS_CHANGED)

    await _mail(hass, coord, _soon(), "<s1@example.org>")

    # The status event fires as always; the push is "Kommt gleich" alone.
    assert [e.data["new_status"] for e in status] == ["out_for_delivery"]
    assert [sent[2] for sent in _sent(calls)] == [
        "🔔 Kopfhörer (DHL) wird gleich zugestellt – bis 12:15 Uhr"
    ]


async def test_without_kommt_gleich_chosen_the_change_is_pushed(hass, freezer):
    freezer.move_to(DAYTIME)
    options = {CONF_NOTIFY_TARGETS: [PHONE], CONF_NOTIFY_EVENTS: ["out_for_delivery"]}
    coord, _, _ = await _setup(hass, options, FakeMailbox(), targets=(PHONE,))
    calls = async_mock_service(hass, "notify", "send_message")

    await _mail(hass, coord, _soon(), "<s1@example.org>")

    (sent,) = _sent(calls)
    assert sent[2].startswith("📦 Kopfhörer (DHL) ist in Zustellung")


async def test_an_error_while_announcing_soon_leaves_the_mail_recognised(hass, freezer, caplog):
    coord, _, parcel, calls, soon, _ = await _in_delivery(hass, freezer)
    with patch.object(type(coord), "display_name", side_effect=RuntimeError("odd")):
        await _mail(hass, coord, _soon(), "<s1@example.org>")
    assert soon == [] and calls == []
    assert parcel.soon_until is not None  # applied all the same
    assert coord._mail_unrecognized == 0
    assert "Could not announce an arriving parcel (RuntimeError)" in caplog.text

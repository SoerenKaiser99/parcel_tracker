"""The import_mail endpoint: one raw mail handed in over HTTP, without a mailbox."""

from datetime import timedelta
from email.utils import format_datetime
from unittest.mock import patch

import pytest
from aiohttp import FormData
from homeassistant.const import EVENT_CALL_SERVICE, MATCH_ALL
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import ParcelStatus

from .test_coordinator_mail import _coordinator, dated_mail
from .test_order_closing import (
    BRAND,
    DHL,
    NOW,
    ORDER,
    TODAY,
    _carrier_parcel,
    _days,
    _order,
    _prepared,
    _refresh,
)
from .test_order_closing import _coordinator as _stored_coordinator

URL = "/api/parcel_tracker/import_mail"
FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
TODAY_MAIL = "Wed, 30 Sep 2026 08:00:00 +0000"


def no_number(date: str) -> bytes:
    return (
        "From: Shop <shop@example.org>\r\nMessage-ID: <n@example.org>\r\n"
        f"Subject: Danke\r\nDate: {date}\r\n\r\nDanke\r\n"
    ).encode()


def advertising(date: str) -> bytes:
    return (
        "From: Prime Video <no-reply@primevideo.com>\r\nMessage-ID: <p@example.org>\r\n"
        f"Subject: Neu\r\nDate: {date}\r\n\r\nFilm\r\n"
    ).encode()


def number(i: int) -> str:
    return f"0034099999999999991{i}"


def _date(days_ago: int = 0) -> str:
    """Date header relative to the real clock (see ``entry``)."""
    return format_datetime(dt_util.utcnow() - timedelta(days=days_ago, hours=1))


@pytest.fixture
async def entry(hass):
    # Real clock: the access token of the test client is not valid in a frozen past.
    e = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    e.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    return e


async def _post(client, raw: bytes) -> tuple[int, dict]:
    response = await client.post(URL, data=raw)
    return response.status, await response.json()


async def test_mail_creates_a_parcel_and_is_applied_once(hass, entry, hass_client):
    client = await hass_client()
    mail = dated_mail(1, _date())
    assert await _post(client, mail) == (200, {"result": "recognized", "parcels": [number(1)]})
    assert entry.runtime_data.store.get(number(1)).carrier == "dhl"
    assert await _post(client, mail) == (200, {"result": "duplicate", "parcels": []})


async def test_old_mail_is_not_read(hass, entry, hass_client):
    client = await hass_client()
    old = dated_mail(1, _date(days_ago=15))
    assert await _post(client, old) == (200, {"result": "stale", "parcels": []})
    assert entry.runtime_data.store.get(number(1)) is None


async def test_mails_without_a_parcel(hass, entry, hass_client):
    client = await hass_client()
    answer = await _post(client, no_number(_date()))
    assert answer == (200, {"result": "unrecognized", "parcels": []})
    answer = await _post(client, advertising(_date()))
    assert answer == (200, {"result": "ignored", "parcels": []})
    assert entry.runtime_data.store.parcels == {}


async def test_mail_stays_off_the_event_bus(hass, entry, hass_client):
    """Why this is no service: a service call would carry the whole mail as an event."""
    client = await hass_client()
    events = async_capture_events(hass, MATCH_ALL)
    mail = dated_mail(1, _date()) + b"Ablageort: Gartenhaus\r\n"
    assert (await _post(client, mail))[1]["result"] == "recognized"
    await hass.async_block_till_done()
    assert not [event for event in events if event.event_type == EVENT_CALL_SERVICE]
    assert all("Gartenhaus" not in str(event.data) for event in events)


async def test_needs_a_login(hass, entry, hass_client_no_auth):
    client = await hass_client_no_auth()
    response = await client.post(URL, data=dated_mail(1, _date()))
    assert response.status == 401
    assert entry.runtime_data.store.parcels == {}


@pytest.mark.parametrize("body", [b"", b" \r\n"])
async def test_empty_body_is_rejected(hass, entry, hass_client, body):
    client = await hass_client()
    assert await _post(client, body) == (400, {"message": "The request body is empty."})


@pytest.mark.parametrize("prefix", [b"\xef\xbb\xbf", b"\r\n\r\n"])
async def test_byte_order_mark_or_blank_lines_in_front_do_not_hide_the_mail(
    hass, entry, hass_client, prefix
):
    client = await hass_client()
    answer = await _post(client, prefix + dated_mail(1, _date()))
    assert answer == (200, {"result": "recognized", "parcels": [number(1)]})


async def test_form_upload_is_rejected(hass, entry, hass_client):
    client = await hass_client()
    form = FormData()
    form.add_field("file", dated_mail(1, _date()), filename="mail.eml")
    response = await client.post(URL, data=form)
    assert response.status == 415
    assert entry.runtime_data.store.parcels == {}


async def test_answer_names_the_integration_when_it_is_not_loaded(hass, entry, hass_client):
    client = await hass_client()
    assert await hass.config_entries.async_unload(entry.entry_id)
    status, answer = await _post(client, dated_mail(1, _date()))
    assert (status, answer) == (503, {"message": "Parcel Tracker is not set up or not loaded."})


async def test_parcel_folded_into_an_order_is_reported_as_the_order(hass, hass_storage, freezer):
    await _prepared(hass, freezer)
    order = _order(first=TODAY - _days(1), last=TODAY + _days(1), changed=NOW - _days(3))
    parcel = _carrier_parcel(status=ParcelStatus.OUT_FOR_DELIVERY, delivered_at=None)
    parcel.next_poll_at = NOW + _days(1)
    coord = await _stored_coordinator(hass, hass_storage, [order, parcel])
    await _refresh(hass, coord)
    assert set(coord.store.parcels) == {ORDER, DHL}

    mail = MailUpdate(DHL, "dhl", ParcelStatus.DELIVERED, dt_util.now(), title=BRAND)
    parsed = [_ParsedMail(message_id="<1@synthetic.example>", result=MailResult([mail]))]
    with patch("custom_components.parcel_tracker.coordinator._parse_mails", return_value=parsed):
        answer = await coord.async_import_raw_mail(b"synthetic")
    await hass.async_block_till_done()
    assert answer == {"result": "recognized", "parcels": [ORDER]}
    assert list(coord.store.parcels) == [ORDER]
    assert coord.store.parcels[ORDER].tracking_ref == DHL


async def test_mail_that_changes_nothing_leaves_the_sensors_alone(hass, freezer):
    freezer.move_to("2026-09-30 10:00:00+00:00")
    coord = await _coordinator(hass, None)
    mail = dated_mail(1, TODAY_MAIL)
    with patch.object(coord, "async_set_updated_data") as updated:
        assert (await coord.async_import_raw_mail(mail))["result"] == "recognized"
        assert updated.call_count == 1
        assert (await coord.async_import_raw_mail(mail))["result"] == "duplicate"
        answer = await coord.async_import_raw_mail(advertising(TODAY_MAIL))
        assert answer["result"] == "ignored"
        answer = await coord.async_import_raw_mail(no_number(TODAY_MAIL))
        assert answer["result"] == "unrecognized"
    assert updated.call_count == 1


async def test_unloaded_coordinator_applies_nothing(hass, freezer):
    """A reload while the mail is parsed: the old coordinator must not write its store."""
    freezer.move_to("2026-09-30 10:00:00+00:00")
    coord = await _coordinator(hass, None)
    await coord.async_shutdown()
    assert await coord.async_import_raw_mail(dated_mail(1, TODAY_MAIL)) is None
    assert coord.store.parcels == {}
    assert coord.store.message_ids == []

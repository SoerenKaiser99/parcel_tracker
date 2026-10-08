"""The import_mail service: one raw mail handed in by a service call, without a mailbox."""

import base64
from unittest.mock import patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker import decode_raw_mail
from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import ParcelStatus

from .test_coordinator_mail import _coordinator, dated_mail, unknown_amazon_mail
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

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
TODAY_MAIL = "Wed, 30 Sep 2026 08:00:00 +0000"
OLD_MAIL = "Tue, 15 Sep 2026 09:00:00 +0000"  # 15 days before the frozen time
NO_NUMBER = (
    b"From: Shop <shop@example.org>\r\nMessage-ID: <n@example.org>\r\n"
    b"Subject: Danke\r\nDate: Wed, 30 Sep 2026 08:00:00 +0000\r\n\r\nDanke\r\n"
)
ADVERTISING = (
    b"From: Prime Video <no-reply@primevideo.com>\r\nMessage-ID: <p@example.org>\r\n"
    b"Subject: Neu\r\nDate: Wed, 30 Sep 2026 08:00:00 +0000\r\n\r\nFilm\r\n"
)


def number(i: int) -> str:
    return f"0034099999999999991{i}"


@pytest.fixture
async def entry(hass, freezer):
    freezer.move_to("2026-09-30 10:00:00+00:00")
    e = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    e.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    return e


async def _call(hass, raw: bytes) -> dict:
    return await hass.services.async_call(
        DOMAIN,
        "import_mail",
        {"raw": base64.b64encode(raw).decode()},
        blocking=True,
        return_response=True,
    )


def test_decode_accepts_the_usual_base64_spellings():
    raw = b"\xfb\xff\xfe a mail"
    standard = base64.b64encode(raw).decode()
    assert "+" in standard and "/" in standard
    assert decode_raw_mail(standard) == raw
    assert decode_raw_mail(base64.urlsafe_b64encode(raw).decode().rstrip("=")) == raw
    assert decode_raw_mail(f"{standard[:4]}\r\n {standard[4:]}\n") == raw


@pytest.mark.parametrize("data", ["!!!", "a", base64.b64encode(b" \r\n").decode()])
def test_decode_rejects_what_is_no_mail(data):
    with pytest.raises(ServiceValidationError) as err:
        decode_raw_mail(data)
    assert err.value.translation_key == "invalid_mail"


async def test_mail_creates_a_parcel_and_is_applied_once(hass, entry):
    mail = dated_mail(1, TODAY_MAIL)
    assert await _call(hass, mail) == {"result": "recognized", "parcels": [number(1)]}
    assert entry.runtime_data.store.get(number(1)).carrier == "dhl"
    assert await _call(hass, mail) == {"result": "duplicate", "parcels": []}


async def test_call_without_a_response_applies_the_mail(hass, entry):
    answer = await hass.services.async_call(
        DOMAIN,
        "import_mail",
        {"raw": base64.b64encode(dated_mail(1, TODAY_MAIL)).decode()},
        blocking=True,
    )
    assert answer is None
    assert entry.runtime_data.store.get(number(1)) is not None


async def test_old_mail_is_not_read(hass, entry):
    assert await _call(hass, dated_mail(1, OLD_MAIL)) == {"result": "stale", "parcels": []}
    assert entry.runtime_data.store.get(number(1)) is None


async def test_mails_without_a_parcel(hass, entry):
    assert await _call(hass, NO_NUMBER) == {"result": "unrecognized", "parcels": []}
    assert await _call(hass, ADVERTISING) == {"result": "ignored", "parcels": []}
    assert entry.runtime_data.store.parcels == {}


async def test_error_names_the_integration_when_it_is_not_loaded(hass, entry):
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, dated_mail(1, TODAY_MAIL))
    assert err.value.translation_key == "not_loaded"


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
        assert (await coord.async_import_raw_mail(ADVERTISING))["result"] == "ignored"
        assert (await coord.async_import_raw_mail(NO_NUMBER))["result"] == "unrecognized"
    assert updated.call_count == 1


async def test_amazon_mails_by_service_raise_no_repair_issue(hass, freezer):
    """The issue points to the mailbox folder; a mail from a service call lies in none."""
    freezer.move_to("2026-09-30 10:00:00+00:00")
    coord = await _coordinator(hass, None)
    for i in range(6):
        answer = await coord.async_import_raw_mail(unknown_amazon_mail(i))
        assert answer["result"] == "unrecognized"
    assert coord._amazon_misses == 0
    assert ir.async_get(hass).async_get_issue(DOMAIN, "amazon_unrecognized") is None
    assert coord._mail_unrecognized == 6  # still counted for the diagnostics

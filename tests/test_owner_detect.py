"""Personen-Zuordnung: the owner of a parcel taken from the headers of its mail."""

from datetime import datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import format_datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import (
    CONF_DEFAULT_OWNER,
    CONF_PERSONS,
    CONF_POSTCODE,
    CONF_SHARED_ADDRESSES,
    DOMAIN,
)
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.mail.owner import owner_from_message
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, PersonConfig

from .test_coordinator_mail import FakeMailbox, _coordinator

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=BERLIN)
ANNA = "person.anna"
BEN = "person.ben"
SHARED = "pakete@example.org"  # the mailbox Home Assistant reads
PERSONS = (
    PersonConfig(ANNA, ("anna@example.org", "pakete+anna@example.org"), ()),
    PersonConfig(BEN, ("ben@example.org",), ()),
    PersonConfig("person.carla", (), ()),  # no addresses: never matches
)
DHL = "00340999999999992557"
URL = "/api/parcel_tracker/import_mail"
FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"


def _mail(headers: list[tuple[str, str]], sender: str = "shop@example.com") -> EmailMessage:
    lines = [f"From: Shop <{sender}>", "Subject: Versandbestaetigung"]
    lines += [f"{name}: {value}" for name, value in headers]
    raw = "\r\n".join(lines) + "\r\n\r\nDHL-Sendungsnummer: 00340999999999992557\r\n"
    return message_from_bytes(raw.encode(), policy=policy.default)


def _owner(headers, sender="shop@example.com", persons=PERSONS):
    return owner_from_message(_mail(headers, sender), persons)


def test_forwarded_mail_with_own_address_as_older_delivered_to():
    # Real shape: the newest station (the shared mailbox) on top, the person's own below.
    headers = [("Delivered-To", SHARED), ("Delivered-To", "anna@example.org")]
    assert _owner(headers) == ANNA


def test_own_address_in_x_original_to_with_other_delivered_to():
    assert _owner([("Delivered-To", SHARED), ("X-Original-To", "ben@example.org")]) == BEN


def test_plus_address_in_delivered_to():
    assert _owner([("Delivered-To", "pakete+anna@example.org")]) == ANNA


def test_x_original_to_alone():
    assert _owner([("X-Original-To", "ben@example.org")]) == BEN


@pytest.mark.parametrize("header", ["X-Forwarded-To", "X-Forwarded-For"])
def test_gmail_forward_headers(header):
    assert _owner([("Delivered-To", SHARED), (header, "anna@example.org")]) == ANNA


def test_gmail_forwarded_for_with_two_addresses():
    # Gmail writes "X-Forwarded-For: original@… forwardee@…".
    value = "anna@example.org pakete@example.org"
    assert _owner([("Delivered-To", SHARED), ("X-Forwarded-For", value)]) == ANNA


@pytest.mark.parametrize("header", ["Resent-From", "Resent-To", "To", "Cc"])
def test_other_headers(header):
    assert _owner([("Delivered-To", SHARED), (header, "Ben <ben@example.org>")]) == BEN


def test_case_does_not_matter():
    assert _owner([("Delivered-To", "Anna@Example.ORG")]) == ANNA


def test_two_persons_match_is_unclear():
    headers = [("To", "anna@example.org"), ("Cc", "ben@example.org")]
    assert _owner(headers) is None


def test_no_person_matches_is_unclear():
    assert _owner([("Delivered-To", SHARED), ("To", "someone@example.org")]) is None


def test_plus_address_compared_exactly():
    persons = (PersonConfig(ANNA, (SHARED,), ()),)
    assert _owner([("Delivered-To", "pakete+soeren@example.org")], persons=persons) is None
    persons = (PersonConfig(ANNA, ("pakete+soeren@example.org",), ()),)
    assert _owner([("Delivered-To", SHARED)], persons=persons) is None


def test_person_without_addresses_and_no_persons_never_match():
    assert _owner([("To", "carla@example.org")]) is None
    assert _owner([("To", "anna@example.org")], persons=()) is None


def test_address_in_a_display_name_or_other_header_is_no_match():
    assert _owner([("To", '"anna@example.org" <someone@example.org>')]) is None
    assert _owner([("Reply-To", "anna@example.org")]) is None


def test_shop_sender_never_counts():
    # The From of a mail nobody forwarded is the shop, not a person.
    persons = (PersonConfig(ANNA, ("shop@example.com",), ()),)
    assert _owner([("Delivered-To", SHARED)], persons=persons) is None


def _hand_forward(sender: str) -> EmailMessage:
    raw = (
        f"From: Anna <{sender}>\r\n"
        f"To: {SHARED}\r\n"
        "Subject: WG: Ihr Paket kommt\r\n"
        "Date: Tue, 20 Oct 2026 10:00:00 +0200\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Schau mal\r\n\r\n"
        "---------- Weitergeleitete Nachricht ----------\r\n"
        "Von: DHL Paket <noreply@dhl.de>\r\n"
        "Datum: Mo., 19. Okt. 2026 um 09:00 Uhr\r\n"
        "Betreff: Ihr Paket kommt\r\n"
        "An: anna@example.org\r\n\r\n"
        "Sendungsnummer 00340999999999992557\r\n"
    ).encode()
    return message_from_bytes(raw, policy=policy.default)


def test_hand_forward_counts_the_forwarders_address():
    assert owner_from_message(_hand_forward("anna@example.org"), PERSONS) == ANNA
    assert owner_from_message(_hand_forward("someone@example.org"), PERSONS) is None


def test_odd_headers_are_unclear_not_an_error():
    assert _owner([("To", "undisclosed-recipients:;"), ("Delivered-To", "<<>>")]) is None


# ---- apply_update ------------------------------------------------------------------


def _dhl(at=NOW, status=ParcelStatus.IN_TRANSIT) -> MailUpdate:
    return MailUpdate(DHL, "dhl", status, at)


def test_new_parcel_gets_the_owner():
    parcels: dict[str, Parcel] = {}
    apply_update(parcels, _dhl(), NOW, owner=ANNA)
    assert (parcels[DHL].owner, parcels[DHL].owner_manual) == (ANNA, False)


def test_later_mail_fills_a_missing_owner_only():
    parcels: dict[str, Parcel] = {}
    apply_update(parcels, _dhl(), NOW)
    assert parcels[DHL].owner is None
    later = NOW + timedelta(hours=1)
    apply_update(parcels, _dhl(later, ParcelStatus.OUT_FOR_DELIVERY), later, owner=ANNA)
    assert parcels[DHL].owner == ANNA
    # First owner wins: a mail naming somebody else does not move the parcel.
    apply_update(parcels, _dhl(later, ParcelStatus.DELIVERED), later, owner=BEN)
    assert parcels[DHL].owner == ANNA


def test_mail_never_touches_a_manual_owner():
    parcels = {DHL: Parcel(DHL, "dhl", "mail", None, NOW, NOW, owner=None, owner_manual=True)}
    apply_update(parcels, _dhl(), NOW, owner=ANNA)
    assert (parcels[DHL].owner, parcels[DHL].owner_manual) == (None, True)
    parcels[DHL].owner = BEN
    apply_update(parcels, _dhl(), NOW, owner=ANNA)
    assert parcels[DHL].owner == BEN


def test_order_gets_the_owner_and_later_mail_fills_it():
    order = "AMZ99999999999994321"
    update = MailUpdate(order, "amazon", ParcelStatus.PRE_TRANSIT, NOW, title="Fahrrad")
    parcels: dict[str, Parcel] = {}
    apply_update(parcels, update, NOW, owner=BEN)
    assert parcels[order].owner == BEN
    parcels = {}
    apply_update(parcels, update, NOW)
    later = NOW + timedelta(hours=1)
    shipped = MailUpdate(
        order, "amazon", ParcelStatus.IN_TRANSIT, later, title="Fahrrad", tracking_ref=DHL,
        tracking_carrier="dhl",
    )  # fmt: skip
    apply_update(parcels, shipped, later, owner=ANNA)
    assert parcels[order].owner == ANNA


# ---- coordinator: IMAP import and HTTP endpoint --------------------------------------


OPTIONS = {
    CONF_PERSONS: [
        {"person": ANNA, "addresses": ["anna@example.org"], "notify_targets": []},
        {"person": BEN, "addresses": ["ben@example.org"], "notify_targets": []},
    ]
}


def _raw(i: int, delivered_to: str, date: str = "Wed, 30 Sep 2026 08:00:00 +0000") -> bytes:
    return (
        "From: Shop <shop@example.com>\r\n"
        f"Delivered-To: {SHARED}\r\n"
        f"Delivered-To: {delivered_to}\r\n"
        f"Message-ID: <owner{i}@example.org>\r\n"
        "Subject: Versandbestaetigung\r\n"
        f"Date: {date}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"DHL-Sendungsnummer: 0034099999999999991{i}\r\n"
    ).encode()


@pytest.fixture(autouse=True)
def accept_old_mails():
    with patch(
        "custom_components.parcel_tracker.coordinator.MAIL_MAX_AGE", timedelta(days=36500)
    ):
        yield


async def test_imap_import_sets_the_detected_owner(hass):
    mailbox = FakeMailbox([("1", _raw(1, "ben@example.org"))])
    coord = await _coordinator(hass, mailbox, OPTIONS)
    await coord.async_import_mail()
    assert coord.store.get("00340999999999999911").owner == BEN


async def test_default_owner_is_not_stored_but_effective_while_the_person_exists(hass):
    options = {**OPTIONS, CONF_DEFAULT_OWNER: ANNA}
    mails = [("1", _raw(1, "someone@example.org")), ("2", _raw(2, "ben@example.org"))]
    coord = await _coordinator(hass, FakeMailbox(mails), options)
    hass.states.async_set(ANNA, "home")
    await coord.async_import_mail()
    unclear = coord.store.get("00340999999999999911")
    detected = coord.store.get("00340999999999999912")
    # Only the detected owner is stored; the default person is added when read.
    assert (unclear.owner, coord.effective_owner(unclear)) == (None, ANNA)
    assert (detected.owner, coord.effective_owner(detected)) == (BEN, BEN)
    # A later mail that names a person still claims the parcel the default had.
    coord.mailbox = FakeMailbox([("3", _raw(1, "ben@example.org").replace(b"owner1", b"x1"))])
    coord._mail_next = None
    await coord.async_import_mail()
    assert unclear.owner == BEN


async def test_changed_default_applies_to_open_parcels_and_removed_person_is_all(hass):
    hass.states.async_set(ANNA, "home")
    hass.states.async_set(BEN, "home")
    coord = await _coordinator(
        hass, FakeMailbox([("1", _raw(1, "someone@example.org"))]), OPTIONS
    )
    await coord.async_import_mail()
    parcel = coord.store.get("00340999999999999911")
    assert coord.effective_owner(parcel) is None  # default "all"
    hass.config_entries.async_update_entry(
        coord.entry, options={**OPTIONS, CONF_DEFAULT_OWNER: BEN}
    )
    assert coord.effective_owner(parcel) == BEN
    hass.config_entries.async_update_entry(
        coord.entry, options={**OPTIONS, CONF_DEFAULT_OWNER: ANNA}
    )
    assert coord.effective_owner(parcel) == ANNA
    hass.states.async_remove(ANNA)  # the person is gone from Home Assistant
    assert coord.effective_owner(parcel) is None
    assert parcel.owner is None


async def test_without_persons_nobody_owns_anything(hass):
    coord = await _coordinator(hass, FakeMailbox([("1", _raw(1, "ben@example.org"))]))
    await coord.async_import_mail()
    assert coord.store.get("00340999999999999911").owner is None


async def test_http_import_sets_the_owner(hass, hass_client):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"}, options=OPTIONS)
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    client = await hass_client()
    date = format_datetime(dt_util.utcnow() - timedelta(hours=1))
    response = await client.post(URL, data=_raw(4, "anna@example.org", date))
    assert response.status == 200
    assert (await response.json())["parcels"] == ["00340999999999999914"]
    parcel = entry.runtime_data.store.get("00340999999999999914")
    assert parcel.owner == ANNA


# ---- review fixes: shared addresses, replies, further apply paths, sensor ------------


def test_shared_address_makes_the_mail_unclear():
    headers = [("X-Original-To", "familie@example.org"), ("Delivered-To", "anna@example.org")]
    assert _owner(headers) == ANNA
    mail = _mail(headers)
    assert owner_from_message(mail, PERSONS, ("familie@example.org",)) is None
    # A shared address the mail does not name changes nothing.
    assert owner_from_message(mail, PERSONS, ("andere@example.org",)) == ANNA


def _from_anna(subject: str) -> EmailMessage:
    raw = (
        "From: Anna <anna@example.org>\r\n"
        f"To: {SHARED}\r\n"
        f"Subject: {subject}\r\n"
        "Date: Tue, 20 Oct 2026 10:00:00 +0200\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Sendungsnummer 00340999999999992557\r\n"
    ).encode()
    return message_from_bytes(raw, policy=policy.default)


@pytest.mark.parametrize("subject", ["AW: Ihr Paket kommt", "Re: Ihr Paket kommt"])
def test_reply_does_not_count_the_senders_address(subject):
    assert owner_from_message(_from_anna(subject), PERSONS) is None


@pytest.mark.parametrize("subject", ["WG: Ihr Paket kommt", "Fwd: Ihr Paket kommt", "FW: x"])
def test_forward_subject_counts_the_senders_address(subject):
    assert owner_from_message(_from_anna(subject), PERSONS) == ANNA


def _order_in_transit(parcels, number, carrier, at=NOW):
    update = MailUpdate(number, carrier, ParcelStatus.IN_TRANSIT, at, title="Fahrrad")
    apply_update(parcels, update, at)
    assert parcels[number].tracking_ref is None
    return parcels[number]


def test_orderless_shop_mail_fills_the_owner():
    parcels: dict[str, Parcel] = {}
    order = _order_in_transit(parcels, "ALI8100000000000001", "aliexpress")
    later = NOW + timedelta(hours=1)
    update = MailUpdate(
        "", "aliexpress", ParcelStatus.OUT_FOR_DELIVERY, later, shop="aliexpress"
    )
    assert apply_update(parcels, update, later, owner=ANNA) is not None
    assert order.owner == ANNA


def test_carrier_mail_merged_into_an_order_fills_the_owner():
    parcels: dict[str, Parcel] = {}
    order = _order_in_transit(parcels, "AMZ99999999999994321", "amazon")
    later = NOW + timedelta(hours=1)
    update = MailUpdate(DHL, "dhl", ParcelStatus.IN_TRANSIT, later, shop="amazon")
    apply_update(parcels, update, later, owner=BEN)
    assert DHL not in parcels and order.tracking_ref == DHL
    assert order.owner == BEN


def _second_box(parcels, owner):
    later = NOW + timedelta(hours=2)
    update = MailUpdate(
        "AMZ99999999999994321", "amazon", ParcelStatus.IN_TRANSIT, later, title="Helm"
    )
    apply_update(parcels, update, later, owner=owner)
    assert len(parcels) == 2
    return next(p for n, p in parcels.items() if n != "AMZ99999999999994321")


@pytest.mark.parametrize(
    ("first", "manual", "expected"),
    [(ANNA, False, ANNA), (ANNA, True, ANNA), (None, False, BEN), (None, True, None)],
)
def test_new_box_inherits_the_orders_owner(first, manual, expected):
    parcels: dict[str, Parcel] = {}
    order = _order_in_transit(parcels, "AMZ99999999999994321", "amazon")
    order.owner, order.owner_manual = first, manual
    box = _second_box(parcels, BEN)
    # A detected or hand-set owner of the order, else the mail's; "everybody" set by
    # hand on the order keeps the box for everybody too.
    assert box.owner == expected
    # The hand mark goes along with the order's owner (also "everybody" set by hand).
    assert box.owner_manual is manual


@pytest.mark.parametrize("owner", [None, BEN])
def test_cancellation_mail_leaves_the_owner(owner):
    parcels: dict[str, Parcel] = {}
    number = "AMZ99999999999994321"
    apply_update(parcels, MailUpdate(number, "amazon", ParcelStatus.PRE_TRANSIT, NOW), NOW)
    parcels[number].owner = owner
    later = NOW + timedelta(hours=1)
    apply_update(parcels, MailUpdate(number, "amazon", ParcelStatus.CANCELLED, later), later,
                 owner=ANNA)  # fmt: skip
    assert parcels[number].status is ParcelStatus.CANCELLED
    assert parcels[number].owner == owner


async def test_imap_import_honours_shared_addresses(hass):
    options = {**OPTIONS, CONF_SHARED_ADDRESSES: [SHARED]}
    coord = await _coordinator(hass, FakeMailbox([("1", _raw(1, "ben@example.org"))]), options)
    await coord.async_import_mail()
    assert coord.store.get("00340999999999999911").owner is None


async def test_sensor_shows_effective_owner_and_whether_it_was_detected(hass, hass_client):
    hass.states.async_set(BEN, "home")
    options = {**OPTIONS, CONF_DEFAULT_OWNER: BEN}
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"}, options=options)
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    client = await hass_client()
    date = format_datetime(dt_util.utcnow() - timedelta(hours=1))
    for i, to in ((5, "anna@example.org"), (6, "someone@example.org")):
        response = await client.post(URL, data=_raw(i, to, date))
        assert response.status == 200
    await hass.async_block_till_done()
    seen = {
        state.attributes["number"]: (
            state.attributes["owner"], state.attributes["owner_detected"]
        )
        for state in hass.states.async_all("sensor")
        if "owner_detected" in state.attributes
    }  # fmt: skip
    assert seen == {
        "00340999999999999915": (ANNA, True),
        "00340999999999999916": (BEN, False),
    }


async def test_parcel_set_to_everybody_by_hand_gets_no_default_person(hass):
    hass.states.async_set(ANNA, "home")
    coord = await _coordinator(hass, FakeMailbox(), {**OPTIONS, CONF_DEFAULT_OWNER: ANNA})
    by_hand = Parcel(DHL, "dhl", "mail", None, NOW, NOW, owner=None, owner_manual=True)
    open_ = Parcel(DHL, "dhl", "mail", None, NOW, NOW)
    manual_ben = Parcel(DHL, "dhl", "mail", None, NOW, NOW, owner=BEN, owner_manual=True)
    assert coord.effective_owner(by_hand) is None
    assert coord.effective_owner(open_) == ANNA
    assert coord.effective_owner(manual_ben) == BEN

"""v0.3.36: Amazon's pickup mail ("Paket zur Abholung bereit", issue #33).

Amazon writes from ``pickup-point@amazon.de`` when an order waits at a pickup point (a
Hermes PaketShop, an Amazon Locker or Counter, another partner shop). The order is then
"Abholbereit", with the pickup point and the day the mail names.
"""

import os
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.carriers.base import BERLIN, Carrier, Match
from custom_components.parcel_tracker.const import (
    CONF_NOTIFY_TARGETS,
    DEFAULT_NOTIFY_EVENTS,
    DOMAIN,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.mail import (
    AMAZON_SENDERS,
    KNOWN_MAIL_DOMAINS,
    known_sender_domain,
    parse_mail,
)
from custom_components.parcel_tracker.mail.amazon import PICKUP_SENDER
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import ParcelStatus, TrackingResult
from custom_components.parcel_tracker.notification import build_notification
from custom_components.parcel_tracker.schedule import summarize
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import FIXTURES, load_mail

PICKUP = "177_pickup_point_paket_zur_abholung_bereit.eml"
ORDER = "AMZ99999999999999999"
ITEM = "Beispiel Kaffeebohnen, 1KG"
PLACE = "Hermes PaketShop - Beispielkiosk Musterweg 1"
# (a notification names a place with at most 40 characters)
SHORT_PLACE = "Hermes PaketShop - Beispielkiosk Muster…"
SENT = datetime(2026, 10, 16, 9, 12, 44, tzinfo=BERLIN)
HERMES = "H1009999999999999999"
PHONE = "notify.mobile_app_handy"


def _raw() -> bytes:
    return (FIXTURES / "mail" / PICKUP).read_bytes()


def _mail(raw: bytes):
    return BytesParser(policy=policy.default).parsebytes(raw)


def _variant(*swaps: tuple[str, str], date_header: str | None = None):
    """The fixture with parts of its text replaced (subject, body, date)."""
    text = _raw().decode("utf-8")
    for old, new in swaps:
        assert old in text, old
        text = text.replace(old, new)
    if date_header:
        text = re.sub(r"^Date: .*$", f"Date: {date_header}", text, count=1, flags=re.M)
    return _mail(text.encode("utf-8"))


def _update(**fields) -> MailUpdate:
    values = {
        "number": ORDER,
        "carrier": "amazon",
        "status": ParcelStatus.IN_TRANSIT,
        "sent_at": SENT - timedelta(days=2),
        "title": ITEM,
    }
    values.update(fields)
    return MailUpdate(**values)


def _pickup_update() -> MailUpdate:
    [update] = parse_mail(load_mail(PICKUP)).updates
    return update


# ----- the sender -----
def test_the_sender_is_an_amazon_sender_the_import_knows():
    assert PICKUP_SENDER == "pickup-point@amazon.de"
    assert PICKUP_SENDER in AMAZON_SENDERS
    assert "amazon.de" in KNOWN_MAIL_DOMAINS
    assert known_sender_domain(PICKUP_SENDER) == "amazon.de"


# ----- what the mail tells -----
def test_pickup_mail_sets_the_order_awaiting_pickup():
    result = parse_mail(load_mail(PICKUP))
    assert result.amazon is True
    [u] = result.updates
    assert (u.number, u.carrier, u.status) == (ORDER, "amazon", ParcelStatus.AWAITING_PICKUP)
    assert u.title == ITEM
    assert u.pickup_point == PLACE
    assert u.pickup_until == date(2026, 10, 24)
    assert u.sent_at == SENT
    # A pickup point is no delivery day, no delivery and no postponement.
    assert (u.eta_date, u.eta_latest, u.eta_from, u.eta_to) == (None,) * 4
    assert (u.delivered_at, u.delivery_code, u.tracking_ref) == (None,) * 3
    assert u.postponed is False and u.status_text is None


def test_pickup_mail_takes_no_price_no_shop_id_and_no_postcode():
    dump = repr([asdict(u) for u in parse_mail(load_mail(PICKUP)).updates])
    for secret in ("19.99", "EUR", "Menge", "HPS", "909090", "Musterstadt", "Max", "example"):
        assert secret not in dump, secret
    assert "99999 " not in dump and ", 99999" not in dump


def test_pickup_mail_never_takes_a_name_from_the_greeting():
    msg = _variant(
        (
            "<tr><td><h2>Das Paket",
            "<tr><td>Hallo Erika Beispielfrau,</td></tr>\n<tr><td><h2>Das Paket",
        ),
    )
    [u] = parse_mail(msg).updates
    assert (u.pickup_point, u.title) == (PLACE, ITEM)
    dump = repr(asdict(u))
    assert "Erika" not in dump and "Beispielfrau" not in dump


def test_a_line_below_the_day_the_subject_does_not_name_is_never_the_place():
    msg = _variant(
        ("<tr><td>Hermes PaketShop - Beispielkiosk Musterweg 1 HPS#909090 , 99999</td></tr>",
         "<tr><td>Erika Beispielfrau</td></tr>"),
    )
    [u] = parse_mail(msg).updates
    assert u.pickup_point == PLACE
    assert "Erika" not in repr(asdict(u))


def test_item_without_a_list_mark_is_the_line_above_its_quantity():
    msg = _variant(("<ul><li>* Beispiel Kaffeebohnen, 1KG</li></ul>", "Beispiel Kaffeebohnen, 1KG"))
    [u] = parse_mail(msg).updates
    assert u.title == ITEM


def test_a_day_of_the_mail_itself_is_no_last_pickup_day():
    """"Abholung am <the mail's own day>" tells when it got there, no last day."""
    msg = _variant(
        ("Abholung am 24. Oktober", "Abholung am 16. Oktober"),
        ("Musterstadt_24._Oktober", "Musterstadt_16._Oktober"),
    )
    [u] = parse_mail(msg).updates
    assert u.status is ParcelStatus.AWAITING_PICKUP
    assert u.pickup_until is None and u.pickup_point == PLACE


def test_the_last_pickup_day_may_lie_in_the_next_year():
    msg = _variant(
        ("Abholung am 24. Oktober", "Abholung am 4. Januar"),
        ("Musterstadt_24._Oktober", "Musterstadt_4._Januar"),
        date_header="Mon, 28 Dec 2026 08:00:00 +0000",
    )
    [u] = parse_mail(msg).updates
    assert u.pickup_until == date(2027, 1, 4)


def test_without_the_body_line_the_place_comes_from_the_subject():
    msg = _variant(
        ("<tr><td>Hermes PaketShop - Beispielkiosk Musterweg 1 HPS#909090 , 99999</td></tr>\n", ""),
        ("<tr><td><b>Abholung am 24. Oktober</b></td></tr>\n", ""),
    )
    [u] = parse_mail(msg).updates
    assert u.pickup_point == PLACE
    assert u.pickup_until == date(2026, 10, 24)


@pytest.mark.parametrize(
    ("subject", "place"),
    [
        ("Amazon Locker - Beispiel 24. Oktober", "Amazon Locker - Beispiel"),
        ("Amazon Counter - Beispielladen Musterweg 9, 99999 Musterstadt 24. Oktober",
         "Amazon Counter - Beispielladen Musterweg 9"),
        ("Amazon Counter - Beispielladen Musterweg 9 99999 Musterstadt 24. Oktober",
         "Amazon Counter - Beispielladen Musterweg 9"),
        ("Amazon Locker - Beispiel 99999 Musterstadt", "Amazon Locker - Beispiel"),
        ("Amazon Counter - Beispielladen Musterweg 9 99999 Musterstadt",
         "Amazon Counter - Beispielladen Musterweg 9"),
    ],
)
def test_other_pickup_points_from_the_subject(subject, place):
    msg = _variant(
        ("<tr><td>Hermes PaketShop - Beispielkiosk Musterweg 1 HPS#909090 , 99999</td></tr>\n", ""),
        (
            "_Hermes_PaketShop_-_Beispielkiosk_Mu?=\n"
            " =?UTF-8?Q?sterweg_1_HPS#909090_,_99999_Musterstadt_24._Oktober?=",
            subject.replace(" ", "_") + "?=",
        ),
    )
    [u] = parse_mail(msg).updates
    assert u.pickup_point == place


@pytest.mark.parametrize(
    "line",
    [
        "Amazon Counter - Beispielladen Musterweg 9 99999 Musterstadt",
        "Amazon Counter - Beispielladen Musterweg 9 99999",
        "Amazon Counter - Beispielladen Musterweg 9, 99999 Musterstadt 24. Oktober",
        "Amazon Counter - Beispielladen Musterweg 9 99999 Musterstadt 24. Oktober",
    ],
)
def test_body_line_without_a_comma_loses_postcode_town_and_day(line):
    msg = _variant(
        ("Hermes PaketShop - Beispielkiosk Musterweg 1 HPS#909090 , 99999</td>", f"{line}</td>"),
        (
            "_Hermes_PaketShop_-_Beispielkiosk_Mu?=\n"
            " =?UTF-8?Q?sterweg_1_HPS#909090_,_99999_Musterstadt_24._Oktober?=",
            "_Amazon_Counter_-_Beispielladen_Musterweg_9_99999_Musterstadt_24._Oktober?=",
        ),
    )
    [u] = parse_mail(msg).updates
    assert u.pickup_point == "Amazon Counter - Beispielladen Musterweg 9"
    assert u.pickup_until == date(2026, 10, 24)


def test_a_subject_with_only_the_day_names_no_place():
    msg = _variant(
        ("<tr><td>Hermes PaketShop - Beispielkiosk Musterweg 1 HPS#909090 , 99999</td></tr>\n", ""),
        ("<tr><td><b>Abholung am 24. Oktober</b></td></tr>\n", ""),
        (
            "_Hermes_PaketShop_-_Beispielkiosk_Mu?=\n"
            " =?UTF-8?Q?sterweg_1_HPS#909090_,_99999_Musterstadt_24._Oktober?=",
            "_24._Oktober?=",
        ),
    )
    [u] = parse_mail(msg).updates
    assert u.status is ParcelStatus.AWAITING_PICKUP
    assert u.pickup_point is None
    assert u.pickup_until == date(2026, 10, 24)


def test_a_forwarded_pickup_mail_is_read_by_its_subject():
    msg = _variant(
        ('"Amazon.de" <pickup-point@amazon.de>', "Max <max@example.org>"),
        ("Subject: =?UTF-8?Q?Paket", "Subject: =?UTF-8?Q?WG:_Paket"),
    )
    result = parse_mail(msg)
    [u] = result.updates
    assert (u.number, u.status, u.pickup_point) == (ORDER, ParcelStatus.AWAITING_PICKUP, PLACE)
    assert result.amazon is False


# ----- applying it -----
def test_shipped_order_becomes_awaiting_pickup_with_place_and_last_day():
    parcels = {}
    apply_update(parcels, _update(), SENT - timedelta(days=2))
    order = parcels[ORDER]
    assert order.status is ParcelStatus.IN_TRANSIT
    change = apply_update(parcels, _pickup_update(), SENT)
    assert change is not None and change.parcel is order and not change.created
    assert change.old_status is ParcelStatus.IN_TRANSIT
    result = order.result
    assert (result.status, result.status_text) == (ParcelStatus.AWAITING_PICKUP, "Abholbereit")
    assert (result.pickup_point, result.pickup_until) == (PLACE, date(2026, 10, 24))
    assert result.events[0].text == "Abholbereit"
    assert order.name == ITEM and list(parcels) == [ORDER]
    # It waits at the pickup point: listed there, and it still counts as on its way.
    summary = summarize(parcels.values(), date(2026, 10, 16))
    assert summary.awaiting_pickup == [order] and summary.active == [order]


def test_the_order_keeps_its_name():
    parcels = {}
    apply_update(parcels, _update(title="Beispiel Kaffeebohnen, 1KG, ganze Bohne…"), SENT)
    parcels[ORDER].name = "Kaffee"
    apply_update(parcels, _pickup_update(), SENT)
    assert parcels[ORDER].name == "Kaffee"
    assert parcels[ORDER].status is ParcelStatus.AWAITING_PICKUP


def test_pickup_mail_for_an_unknown_order_creates_it():
    parcels = {}
    change = apply_update(parcels, _pickup_update(), SENT)
    assert change is not None and change.created
    order = parcels[ORDER]
    assert (order.carrier, order.carrier_mode, order.name) == ("amazon", "mail", ITEM)
    assert order.status is ParcelStatus.AWAITING_PICKUP
    assert (order.result.pickup_point, order.result.pickup_until) == (PLACE, date(2026, 10, 24))


def test_a_repeated_pickup_mail_without_the_place_keeps_it():
    parcels = {}
    apply_update(parcels, _pickup_update(), SENT)
    again = _update(status=ParcelStatus.AWAITING_PICKUP, sent_at=SENT + timedelta(days=1))
    assert apply_update(parcels, again, SENT + timedelta(days=1)) is None
    result = parcels[ORDER].result
    assert (result.pickup_point, result.pickup_until) == (PLACE, date(2026, 10, 24))


def test_amazons_delivered_mail_closes_the_order_and_drops_the_place():
    parcels = {}
    apply_update(parcels, _update(), SENT - timedelta(days=2))
    apply_update(parcels, _pickup_update(), SENT)
    later = SENT + timedelta(days=2)
    change = apply_update(
        parcels, _update(status=ParcelStatus.DELIVERED, sent_at=later, delivered_at=later), later
    )
    assert change is not None and change.old_status is ParcelStatus.AWAITING_PICKUP
    result = parcels[ORDER].result
    assert result.status is ParcelStatus.DELIVERED and result.delivered_at == later
    assert (result.pickup_point, result.pickup_until) == (None, None)


def test_the_carriers_delivered_mail_closes_the_order():
    parcels = {}
    apply_update(parcels, _update(tracking_ref=HERMES, tracking_carrier="hermes"), SENT)
    assert parcels[ORDER].tracking_ref == HERMES
    apply_update(parcels, _pickup_update(), SENT)
    assert parcels[ORDER].status is ParcelStatus.AWAITING_PICKUP
    later = SENT + timedelta(days=1)
    delivered = MailUpdate(HERMES, "hermes", ParcelStatus.DELIVERED, later, delivered_at=later)
    change = apply_update(parcels, delivered, later)
    assert change is not None and change.parcel is parcels[ORDER]
    assert parcels[ORDER].status is ParcelStatus.DELIVERED
    assert list(parcels) == [ORDER]


def test_an_older_shipping_mail_read_late_never_takes_it_back():
    parcels = {}
    apply_update(parcels, _pickup_update(), SENT)
    assert apply_update(parcels, _update(), SENT) is None
    assert parcels[ORDER].status is ParcelStatus.AWAITING_PICKUP


def test_notification_names_the_place_and_the_last_day():
    """The place shows on the card, in the attributes and in the notification."""
    parcels = {}
    apply_update(parcels, _update(), SENT - timedelta(days=2))
    apply_update(parcels, _pickup_update(), SENT)
    assert "awaiting_pickup" in DEFAULT_NOTIFY_EVENTS
    title, message = build_notification(parcels[ORDER], ParcelStatus.IN_TRANSIT, SENT)
    assert message == f"📍 {ITEM} (Amazon) liegt zur Abholung bereit – {SHORT_PLACE} bis 24.10."


# ----- the anonymiser (tester mode) -----
def test_anonymiser_scrubs_the_recipient_and_the_mail_still_reads(tmp_path):
    """A tester's own pickup mail: name, address, town and postcode go; the shop's place
    (public) stays, so the anonymised mail is still read the same way."""
    text = _raw().decode("utf-8")
    text = text.replace(
        "<tr><td><h2>Das Paket",
        "<tr><td>Hallo Erika Beispielfrau,</td></tr>\n<tr><td><h2>Das Paket",
    )
    text = text.replace("To: max@example.org", "To: Erika Beispielfrau <erika@privatpost.example>")
    text = text.replace("_99999_Musterstadt_", "_98765_Beispielhausen_")
    text = text.replace(", 99999<", ", 98765<")
    (tmp_path / "mail.eml").write_text(text, encoding="utf-8")
    script = Path(__file__).parent.parent / "scripts" / "anonymize_mail.py"
    done = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "mail.eml"), "--name", "Erika Beispielfrau",
         "--email", "erika@privatpost.example", "--postcode", "98765", "--city", "Beispielhausen"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert done.returncode == 0, done.stderr
    assert "ACHTUNG" not in done.stdout + done.stderr
    [written] = (tmp_path / "anonymisiert").glob("*.eml")
    raw = written.read_bytes()
    for secret in (b"Erika", b"Beispielfrau", b"privatpost", b"Beispielhausen", b"98765",
                   b"9999999-9999999"):
        assert secret not in raw, secret
    [u] = parse_mail(_mail(raw)).updates
    assert (u.status, u.title, u.pickup_point) == (ParcelStatus.AWAITING_PICKUP, ITEM, PLACE)
    assert u.pickup_until == date(2026, 10, 24)


# ----- end to end: mailbox, event, notification -----
class _Mailbox:
    def __init__(self):
        self.mails = []

    def fetch_unseen(self):
        mails, self.mails = self.mails, []
        return mails

    def finish(self, dispositions, move):
        pass


def _shipped_mail() -> bytes:
    return (
        b"From: Amazon.de <shipment-tracking@amazon.de>\r\n"
        b"Message-ID: <shipped-177@example.org>\r\n"
        b"Subject: =?UTF-8?Q?Versendet:_=E2=80=9EBeispiel_Kaffeebohnen,_1KG=E2=80=9C?=\r\n"
        b"Date: Wed, 14 Oct 2026 08:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Bestellnr.\r\n999-9999999-9999999\r\n* Beispiel Kaffeebohnen, 1KG\r\n"
    )


async def test_import_fires_the_event_and_the_default_notification(hass, freezer):
    freezer.move_to("2026-10-16 10:00:00+00:00")
    await hass.config.async_set_time_zone("Europe/Berlin")
    mailbox = _Mailbox()
    entry = MockConfigEntry(
        domain=DOMAIN, data={"postcode": "10115"}, options={CONF_NOTIFY_TARGETS: [PHONE]}
    )
    entry.add_to_hass(hass)
    hass.states.async_set(PHONE, "unknown")
    store = ParcelStore(hass)
    await store.async_load()
    coord = ParcelCoordinator(hass, entry, store, {}, mailbox)
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()  # the first refresh: no mail import
    mailbox.mails = [("1", _shipped_mail())]
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.store.get(ORDER).status is ParcelStatus.IN_TRANSIT
    assert events == [] and calls == []  # a new order is no news

    mailbox.mails = [("2", _raw())]
    coord._mail_next = None
    await coord.async_refresh()
    await hass.async_block_till_done()
    order = coord.store.get(ORDER)
    assert order.status is ParcelStatus.AWAITING_PICKUP
    assert order.result.pickup_point == PLACE
    assert len(events) == 1
    assert (events[0].data["old_status"], events[0].data["new_status"]) == (
        "in_transit", "awaiting_pickup",
    )
    assert [call.data["message"] for call in calls] == [
        f"📍 {ITEM} (Amazon) liegt zur Abholung bereit – {SHORT_PLACE} bis 24.10."
    ]


# ----- the carrier's lookup after the pickup mail -----
class _Carrier(Carrier):
    key = "hermes"
    name = "Hermes"

    def __init__(self):
        self.answer = None

    @staticmethod
    def matches(number):
        return Match.SURE

    async def fetch(self, number, postcode):
        return self.answer


def _answer(status, **fields) -> TrackingResult:
    values = {
        "status_text": "Die Sendung liegt im PaketShop zur Abholung bereit.",
        "eta_date": None, "eta_from": None, "eta_to": None, "location": None,
        "pickup_point": None, "pickup_until": None, "delivered_at": None,
    }
    values.update(fields)
    return TrackingResult(status, **values)


async def _polled(hass, freezer, *answers):
    """An Amazon order with a Hermes number that got the pickup mail, then polled once
    per answer; the stored order after the last one."""
    freezer.move_to("2026-10-16 10:00:00+00:00")
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    parcels = {}
    apply_update(parcels, _update(tracking_ref=HERMES, tracking_carrier="hermes"), SENT)
    apply_update(parcels, _pickup_update(), SENT)
    store.parcels.update(parcels)
    carrier = _Carrier()
    coord = ParcelCoordinator(hass, entry, store, {"hermes": carrier})
    for answer in answers:
        carrier.answer = answer
        store.parcels[ORDER].next_poll_at = None
        freezer.tick(timedelta(minutes=10))
        await coord.async_refresh()
        await hass.async_block_till_done()
    return store.parcels[ORDER]


async def test_a_carrier_poll_still_awaiting_pickup_keeps_the_mails_place(hass, freezer):
    order = await _polled(hass, freezer, _answer(ParcelStatus.AWAITING_PICKUP))
    assert order.status is ParcelStatus.AWAITING_PICKUP
    assert order.result.status_text.startswith("Die Sendung liegt im PaketShop")
    assert (order.result.pickup_point, order.result.pickup_until) == (PLACE, date(2026, 10, 24))


async def test_the_carriers_own_place_and_day_win(hass, freezer):
    order = await _polled(
        hass, freezer,
        _answer(ParcelStatus.AWAITING_PICKUP, pickup_point="Beispielstadt"),
    )
    assert (order.result.pickup_point, order.result.pickup_until) == (
        "Beispielstadt", date(2026, 10, 24),
    )
    order = await _polled(
        hass, freezer,
        _answer(ParcelStatus.AWAITING_PICKUP, pickup_until=date(2026, 10, 30)),
    )
    assert (order.result.pickup_point, order.result.pickup_until) == (PLACE, date(2026, 10, 30))


async def test_any_other_status_from_the_carrier_drops_the_place(hass, freezer):
    order = await _polled(
        hass, freezer,
        _answer(ParcelStatus.AWAITING_PICKUP),
        _answer(ParcelStatus.IN_TRANSIT),
    )
    assert (order.result.pickup_point, order.result.pickup_until) == (None, None)
    # (back at a pickup point later: the old place is not taken up again)
    order = await _polled(
        hass, freezer,
        _answer(ParcelStatus.IN_TRANSIT),
        _answer(ParcelStatus.AWAITING_PICKUP),
    )
    assert order.status is ParcelStatus.AWAITING_PICKUP
    assert (order.result.pickup_point, order.result.pickup_until) == (None, None)


async def test_the_carriers_delivery_drops_the_place(hass, freezer):
    order = await _polled(
        hass, freezer,
        _answer(ParcelStatus.DELIVERED, delivered_at=SENT + timedelta(hours=1)),
    )
    assert order.status is ParcelStatus.DELIVERED
    assert (order.result.pickup_point, order.result.pickup_until) == (None, None)

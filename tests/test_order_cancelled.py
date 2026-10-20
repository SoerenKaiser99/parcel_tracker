"""A shop cancels an order: the status "Storniert" (Amazon, eBay, AliExpress)."""

import json
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.card_install import BUNDLED_CARD
from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.const import DOMAIN
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.diagnostics import async_get_config_entry_diagnostics
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.aliexpress import CONFIRMED_TEXT
from custom_components.parcel_tracker.mail.apply import (
    ASSUMED_TEXT,
    CANCELLED_TEXT,
    apply_update,
    close_unconfirmed,
)
from custom_components.parcel_tracker.mail.base import READY_TEXT, MailResult, MailUpdate
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)
from custom_components.parcel_tracker.notification import build_notification
from custom_components.parcel_tracker.schedule import (
    delivered_today,
    order_overdue,
    should_remove,
    summarize,
)

from .conftest import load_mail
from .test_order_closing import _coordinator, _prepared, _refresh

# "Artikel erfolgreich storniert: …": the item in the subject.
AMAZON = "154_order_update_artikel_erfolgreich_stornie.eml"
# Other wordings: no item in the subject, the order number twice in the text. The first
# one is about the whole order, the second about items of it (named in the text).
AMAZON_ORDER = "155_order_update_ihre_bestellung_wurde_storn.eml"
AMAZON_ITEMS = "156_order_update_erfolgreiche_stornierung_vo.eml"
# German, sent along with "is closed": the order number stands only in the text.
ALIEXPRESS_OVERDUE = "157_aliexpress_stornierte_bestellung_wegen_b.eml"
# Tells no reason: also after a dispute or a refund of an order that arrived long ago.
ALIEXPRESS_CLOSED = "142_aliexpress_your_order_is_closed.eml"
# eBay, a real sequence: ordered, the buyer asks to break the purchase off (only read: the
# seller may say no), the seller agrees.
EBAY_ORDERED = "192_ebay_bestellung_bestaetigt_baustrahler.eml"
EBAY_REQUEST = "193_ebay_ok_sie_moechten_den_kauf_abbrechen.eml"
EBAY_BROKEN_OFF = "194_ebay_kauf_wurde_abgebrochen.eml"
# Amazon's order mail naming the items of each day under the order number again.
AMAZON_SEVERAL = "189_bestellbestaetigung_bestellt.eml"
# Amazon's order mail about two orders, the first of two items (a saw blade, a charger).
AMAZON_ORDERS = "124_bestellbestaetigung_bestellt.eml"

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
TODAY = NOW.astimezone(BERLIN).date()
SENT = (NOW - timedelta(hours=1)).astimezone(BERLIN)
ORDER = "AMZ99974120133366279"
TITLE = "Beispiel-Sirup Himbeer 1 Liter (Glas…"
ROBOT = "Beispiel-Saugroboter mit Wischfunktion, Hindernisüberwindun…"
SANDING = "Beispiel-Schleifnetz… und 4 weitere Artikel"
BEAM = "Beispiel-Akku-Baustrahler 5000 Hybrid Blau"
NODE = shutil.which("node")


def _order(number=ORDER, carrier="amazon", status=ParcelStatus.PRE_TRANSIT, title=TITLE, **fields):
    result = TrackingResult(status, "Bestellt", TODAY, None, None, None, None, None, None)
    return Parcel(number, carrier, "mail", title, NOW, NOW, result=result, mail_title=title,
                  **fields)


def _cancel(number=ORDER, carrier="amazon", title=None) -> MailUpdate:
    return MailUpdate(number, carrier, ParcelStatus.CANCELLED, SENT, title=title)


# ----- the parsers, on the anonymised mails -----


@pytest.mark.parametrize(
    ("name", "number", "carrier", "title"),
    [
        (AMAZON, ORDER, "amazon", TITLE),
        (AMAZON_ORDER, "AMZ99938310205529571", "amazon", None),  # (None: the whole order)
        (AMAZON_ITEMS, "AMZ99936398346041064", "amazon", ROBOT),
        (EBAY_BROKEN_OFF, "EBAY999090900990", "ebay", BEAM),
        (ALIEXPRESS_OVERDUE, "ALI9999999999990001", "aliexpress", None),
    ],
)
def test_cancellation_mails_name_the_order_and_the_status(name, number, carrier, title):
    result = parse_mail(load_mail(name))
    [update] = result.updates
    assert (update.number, update.carrier, update.title) == (number, carrier, title)
    assert update.status is ParcelStatus.CANCELLED
    assert not result.ignored
    assert result.amazon is (carrier == "amazon")  # counts as an Amazon mail we know


def test_an_item_cancellation_without_an_item_tells_nothing():
    msg = load_mail(AMAZON_ITEMS)
    body = msg.get_content().replace("Aufgegeben am 4. Juli 2025", "")
    msg.set_content(body)
    assert parse_mail(msg).updates == []


def test_closed_tells_no_reason_and_is_only_read():
    result = parse_mail(load_mail(ALIEXPRESS_CLOSED))
    assert result.ignored and not result.updates


def test_the_request_to_break_off_an_ebay_purchase_is_only_read():
    result = parse_mail(load_mail(EBAY_REQUEST))
    assert result.ignored and not result.updates


def test_an_amazon_order_mail_naming_its_items_one_by_one_is_one_order_of_them_all():
    updates = parse_mail(load_mail(AMAZON_SEVERAL)).updates
    assert {u.title for u in updates} == {"Fasgear 240W… und 3 weitere Artikel"}


def test_other_mails_are_never_a_cancellation():
    for name in ("104_ebay_ihre_sendung_ist_jetzt_beim_versand.eml",
                 "129_aliexpress_bestellung_wurde_versandt.eml",
                 "102_versandbestaetigung_ihre_amazon_de_beste.eml"):
        [update] = parse_mail(load_mail(name)).updates
        assert update.status is not ParcelStatus.CANCELLED


def test_a_cancellation_forwarded_by_hand_is_read_like_amazons_own_mail():
    msg = load_mail(AMAZON)
    msg.replace_header("From", "Max Mustermann <max@example.org>")
    msg.replace_header("Subject", "WG: " + str(msg["Subject"]))
    result = parse_mail(msg)
    [update] = result.updates
    assert (update.number, update.status) == (ORDER, ParcelStatus.CANCELLED)
    assert result.amazon is False


# ----- closing the order -----


@pytest.mark.parametrize(
    ("name", "number", "carrier", "title"),
    [
        (AMAZON, ORDER, "amazon", TITLE),
        (AMAZON_ORDER, "AMZ99938310205529571", "amazon", SANDING),  # (also with further items)
        (AMAZON_ITEMS, "AMZ99936398346041064", "amazon", "Beispiel-Saugroboter mit Wischfunk…"),
        (EBAY_BROKEN_OFF, "EBAY999090900990", "ebay", "Beispiel-Akku-Baustrahler"),
        (ALIEXPRESS_OVERDUE, "ALI9999999999990001", "aliexpress", None),
    ],
)
def test_the_mail_closes_the_open_order_as_cancelled(name, number, carrier, title):
    order = _order(number, carrier, title=title)
    parcels = {number: order}
    mail = load_mail(name)
    [change] = [apply_update(parcels, u, NOW) for u in parse_mail(mail).updates]
    assert (change.parcel, change.old_status, change.created) == (
        order, ParcelStatus.PRE_TRANSIT, False
    )
    assert order.assumed_delivered is False
    result = order.result
    assert (result.status, result.status_text) == (ParcelStatus.CANCELLED, "Storniert")
    assert (result.delivered_at, result.eta_date) == (None, None)  # nothing comes
    # The line in the history carries the time of the mail, the change is now.
    [event] = result.events
    assert (event.text, event.timestamp) == (CANCELLED_TEXT, parse_mail(mail).updates[0].sent_at)
    assert order.last_change_at == NOW
    assert len(parcels) == 1


def _replay(*names):
    parcels = {}
    for name in names:
        for update in parse_mail(load_mail(name)).updates:
            apply_update(parcels, update, update.sent_at)
    return parcels


def test_an_ebay_purchase_broken_off_after_the_request_is_cancelled():
    [order] = _replay(EBAY_ORDERED, EBAY_REQUEST, EBAY_BROKEN_OFF).values()
    assert (order.number, order.status) == ("EBAY999090900990", ParcelStatus.CANCELLED)
    assert [e.text for e in order.result.events] == [CANCELLED_TEXT, "Bestellt"]


def test_an_ebay_purchase_of_more_items_stays_when_one_is_broken_off():
    number = "EBAY999090900990"
    order = _order(number, "ebay", title=f"{BEAM} und 1 weiterer Artikel")
    [update] = parse_mail(load_mail(EBAY_BROKEN_OFF)).updates
    assert apply_update({number: order}, update, NOW) is None  # the other item still comes
    assert order.status is ParcelStatus.PRE_TRANSIT


def test_an_ebay_purchase_broken_off_without_its_item_in_the_text_is_all_of_it():
    msg = load_mail(EBAY_BROKEN_OFF)
    msg.set_content(msg.get_content().replace(f"<p>{BEAM}</p>", ""), subtype="html")
    [update] = parse_mail(msg).updates
    assert (update.number, update.title) == ("EBAY999090900990", None)


def test_a_cancelled_order_is_done_but_never_delivered():
    order = _order()
    apply_update({ORDER: order}, _cancel(), NOW)
    assert build_notification(order, ParcelStatus.PRE_TRANSIT, NOW) is None
    assert not delivered_today(order, TODAY, BERLIN)
    summary = summarize([order], TODAY, BERLIN)
    assert summary.active == [] and summary.delivered_today == [] and summary.sure == []
    assert not order_overdue(order, TODAY + timedelta(days=30), BERLIN)
    # Tidied up like every delivered parcel, counted from the day the mail was read.
    assert not should_remove(order, NOW + timedelta(days=3), 3)
    assert should_remove(order, NOW + timedelta(days=3, minutes=1), 3)


def test_nothing_is_created_for_an_order_nobody_knows():
    parcels = {"AMZ99999999999999902": _order("AMZ99999999999999902")}
    assert apply_update(parcels, _cancel(), NOW) is None
    assert list(parcels) == ["AMZ99999999999999902"]
    assert parcels["AMZ99999999999999902"].status is ParcelStatus.PRE_TRANSIT


@pytest.mark.parametrize(
    "status",
    [s for s in ParcelStatus if s not in (ParcelStatus.PRE_TRANSIT, ParcelStatus.CANCELLED)],
)
def test_only_an_order_that_is_not_shipped_yet_is_cancelled(status):
    order = _order(status=status)
    before = order.to_dict()
    assert apply_update({ORDER: order}, _cancel(), NOW) is None
    assert order.to_dict() == before


def test_an_order_the_carrier_tells_about_stays():
    order = _order(tracking_ref="00340999999999999901", tracking_carrier="dhl")
    assert apply_update({ORDER: order}, _cancel(), NOW) is None
    assert order.status is ParcelStatus.PRE_TRANSIT


def test_a_cancellation_read_after_the_shipping_mail_closes_nothing():
    order = _order()
    parcels = {ORDER: order}
    shipped = MailUpdate(ORDER, "amazon", ParcelStatus.IN_TRANSIT, SENT + timedelta(minutes=30),
                         title=TITLE)
    apply_update(parcels, shipped, NOW)
    before = order.to_dict()
    assert apply_update(parcels, _cancel(), NOW) is None  # sent before "Versendet"
    assert order.to_dict() == before


def _history(order, *texts):
    """Give ``order`` the history of the mails ``texts`` (oldest first)."""
    events = [TrackingEvent(SENT - timedelta(days=9 - i), t, None) for i, t in enumerate(texts)]
    order.result = replace(order.result, events=events[::-1])
    return order


# (closed on its own, but nothing had left: the shop's cancellation tells why no mail came)
@pytest.mark.parametrize("texts", [("Bestellt",), ("Bestellt", READY_TEXT)])
def test_an_order_closed_without_a_delivery_mail_that_never_left_becomes_cancelled(texts):
    order = _history(_order(), *texts)
    close_unconfirmed(order, NOW - timedelta(days=1))
    change = apply_update({ORDER: order}, _cancel(), NOW)
    assert (change.old_status, order.status) == (ParcelStatus.DELIVERED, ParcelStatus.CANCELLED)
    assert order.assumed_delivered is False
    assert [e.text for e in order.result.events] == [CANCELLED_TEXT, ASSUMED_TEXT, *texts[::-1]]


# Part of it was shipped and may well have come; the cancellation is about the rest.
def test_an_order_closed_without_a_delivery_mail_after_it_was_shipped_stays():
    order = _history(_order(status=ParcelStatus.IN_TRANSIT), "Bestellt", "Versendet")
    close_unconfirmed(order, NOW - timedelta(days=1))
    before = order.to_dict()
    assert apply_update({ORDER: order}, _cancel(), NOW) is None
    assert order.to_dict() == before


def test_an_order_the_shop_confirmed_as_delivered_stays():
    order = _history(_order(carrier="aliexpress", number="ALI9999999999990001"), "Bestellt")
    close_unconfirmed(order, NOW - timedelta(days=1), CONFIRMED_TEXT, SENT - timedelta(days=1))
    before = order.to_dict()
    assert apply_update({order.number: order}, _cancel(order.number, "aliexpress"), NOW) is None
    assert order.to_dict() == before


# ----- a cancellation of items: only an order of that one item -----


@pytest.mark.parametrize(
    "title",
    [
        f"{TITLE} und 1 weiterer Artikel",  # the other item still comes
        "Beispiel-Netzteil 65 W",  # another item of the order
        None,  # nobody knows what the order holds
    ],
)
def test_an_item_cancellation_leaves_an_order_with_more_or_other_items(title):
    order = _order(title=title)
    before = order.to_dict()
    assert apply_update({ORDER: order}, _cancel(title=TITLE), NOW) is None
    assert order.to_dict() == before


def test_an_item_cut_short_in_the_subject_still_names_the_order():
    order = _order(title="Beispiel-Lautsprecher Bluetooth")
    assert apply_update({ORDER: order}, _cancel(title="Beispiel…"), NOW).parcel is order
    assert order.status is ParcelStatus.CANCELLED


def test_an_item_cancellation_leaves_an_order_whose_mail_named_its_items_one_by_one():
    [order] = _replay(AMAZON_SEVERAL).values()
    item = MailUpdate(order.number, "amazon", ParcelStatus.CANCELLED, NOW,
                      title="Midori 15 cm Aluminium Lineal – schwarz")
    before = order.to_dict()
    assert apply_update({order.number: order}, item, NOW) is None  # three more still come
    assert order.to_dict() == before
    assert apply_update({order.number: order}, replace(item, title=None), NOW).parcel is order
    assert order.status is ParcelStatus.CANCELLED


def test_an_item_cancellation_leaves_an_order_of_more_items_in_a_mail_about_several():
    parcels = _replay(AMAZON_ORDERS)
    blade, saw = parcels["AMZ99927581034893895"], parcels["AMZ99900481738659171"]
    sent = blade.result.events[0].timestamp + timedelta(hours=1)
    item = MailUpdate(blade.number, "amazon", ParcelStatus.CANCELLED, sent,
                      title="Bosch Professional 1x Expert…")
    assert apply_update(parcels, item, sent) is None  # the charger still comes
    assert blade.status is ParcelStatus.PRE_TRANSIT
    item = replace(item, number=saw.number, title="Bosch PRO 18V System Akku…")
    assert apply_update(parcels, item, sent).parcel is saw  # the only item of its order
    assert saw.status is ParcelStatus.CANCELLED


def test_the_cancellation_of_the_whole_order_closes_it_with_all_its_items():
    order = _order(title=f"{TITLE} und 1 weiterer Artikel")
    assert apply_update({ORDER: order}, _cancel(), NOW).parcel is order
    assert order.status is ParcelStatus.CANCELLED


def test_the_same_mail_twice_changes_nothing():
    order = _order()
    parcels = {ORDER: order}
    apply_update(parcels, _cancel(), NOW)
    before = order.to_dict()
    assert apply_update(parcels, _cancel(), NOW + timedelta(hours=1)) is None
    assert order.to_dict() == before


def test_of_two_shipments_only_the_one_that_still_waits_is_closed():
    first = _order(status=ParcelStatus.DELIVERED, title="Netzteil 65 W")
    second = _order(f"{ORDER}P2")
    parcels = {first.number: first, second.number: second}
    change = apply_update(parcels, _cancel(title=TITLE), NOW)
    assert change.parcel is second
    assert (first.status, second.status) == (ParcelStatus.DELIVERED, ParcelStatus.CANCELLED)


def test_of_two_waiting_shipments_the_item_mail_takes_the_one_it_names():
    first, second = _order(title="Netzteil 65 W"), _order(f"{ORDER}P2")
    parcels = {first.number: first, second.number: second}
    assert apply_update(parcels, _cancel(title=TITLE), NOW).parcel is second
    assert (first.status, second.status) == (ParcelStatus.PRE_TRANSIT, ParcelStatus.CANCELLED)


def test_two_waiting_shipments_are_one_too_many_to_pick_from():
    first, second = _order(title="Netzteil 65 W"), _order(f"{ORDER}P2")
    parcels = {first.number: first, second.number: second}
    assert apply_update(parcels, _cancel(), NOW) is None
    assert (first.status, second.status) == (ParcelStatus.PRE_TRANSIT, ParcelStatus.PRE_TRANSIT)


@pytest.mark.parametrize("title", [TITLE, "Netzteil 65 W"])
def test_a_later_mail_of_the_shop_opens_the_order_again(title):
    order = _order()
    parcels = {ORDER: order}
    apply_update(parcels, _cancel(), NOW)
    shipped = MailUpdate(ORDER, "amazon", ParcelStatus.IN_TRANSIT, SENT + timedelta(hours=1),
                         title=title)
    change = apply_update(parcels, shipped, NOW)
    assert (change.parcel, change.old_status, change.created) == (
        order, ParcelStatus.CANCELLED, False
    )
    assert (order.status, order.result.status_text) == (ParcelStatus.IN_TRANSIT, "Versendet")
    assert order.assumed_delivered is False
    assert [e.text for e in order.result.events] == ["Versendet", CANCELLED_TEXT]
    assert len(parcels) == 1  # also with another title: no further shipment


@pytest.mark.parametrize("sent", [SENT - timedelta(hours=1), SENT])
@pytest.mark.parametrize("title", [TITLE, "Netzteil 65 W"])
def test_a_mail_sent_before_the_cancellation_does_not_open_the_order(sent, title):
    order = _order()
    parcels = {ORDER: order}
    apply_update(parcels, _cancel(), NOW)
    before = order.to_dict()
    ordered = MailUpdate(ORDER, "amazon", ParcelStatus.PRE_TRANSIT, sent, title=title)
    assert apply_update(parcels, ordered, NOW) is None  # read late, e.g. forwarded by hand
    assert order.to_dict() == before and len(parcels) == 1


def test_a_new_box_goes_to_the_open_entry_not_to_the_cancelled_one():
    # Neither entry knows a shipment yet; the mail names one and no item.
    cancelled = _order()
    shipped = _order(f"{ORDER}P2", status=ParcelStatus.IN_TRANSIT, title="Beispiel-Netzteil 65 W")
    parcels = {cancelled.number: cancelled, shipped.number: shipped}
    apply_update(parcels, _cancel(), NOW)
    box = MailUpdate(ORDER, "amazon", ParcelStatus.OUT_FOR_DELIVERY, SENT + timedelta(hours=2),
                     shipment_id="TNeu12345")
    assert apply_update(parcels, box, NOW).parcel is shipped
    assert (cancelled.status, shipped.shipment_ids) == (ParcelStatus.CANCELLED, ["TNeu12345"])


def test_an_open_shipment_comes_before_the_cancelled_one():
    first, second = _order(title="Netzteil 65 W"), _order(f"{ORDER}P2", title="Kabel")
    parcels = {first.number: first}
    apply_update(parcels, _cancel(), NOW)
    parcels[second.number] = second
    shipped = MailUpdate(ORDER, "amazon", ParcelStatus.IN_TRANSIT, SENT + timedelta(hours=1),
                         title="Tasche")
    assert apply_update(parcels, shipped, NOW).parcel is second
    assert (first.status, second.status) == (ParcelStatus.CANCELLED, ParcelStatus.IN_TRANSIT)


def test_the_status_is_stored_and_nothing_else_marks_the_order():
    order = _order()
    apply_update({ORDER: order}, _cancel(), NOW)
    data = order.to_dict()
    assert data["result"]["status"] == "cancelled" and "cancelled" not in data
    assert Parcel.from_dict(data).status is ParcelStatus.CANCELLED


# ----- the coordinator, the sensor and the diagnostics -----


def _closed_on_its_own():
    order = _order()
    close_unconfirmed(order, NOW - timedelta(days=1))
    return order


@pytest.mark.parametrize(
    ("order", "old"), [(_order, "pre_transit"), (_closed_on_its_own, "delivered")]
)
async def test_cancelling_fires_the_event_and_sends_no_notification(
    hass, hass_storage, freezer, order, old
):
    calls, events = await _prepared(hass, freezer)
    coord = await _coordinator(hass, hass_storage, [order()])
    await _refresh(hass, coord)
    item = _ParsedMail(message_id="<1@synthetic.example>",
                       result=MailResult([_cancel(title=TITLE)]))
    async with coord._lock:
        assert coord._handle_mail(item, NOW) is not None
    await hass.async_block_till_done()
    [event] = events
    assert (event.data["old_status"], event.data["new_status"]) == (old, "cancelled")
    assert event.data["assumed"] is False and "cancelled" not in event.data
    assert calls == []
    await coord.async_shutdown()


async def test_sensor_and_diagnostics_show_the_cancelled_order(hass, hass_storage, freezer):
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("Europe/Berlin")
    cancelled, open_ = _order(), _order("AMZ99999999999999902", title="Kopfhörer")
    apply_update({ORDER: cancelled}, _cancel(), NOW)
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {"parcels": [cancelled.to_dict(), open_.to_dict()], "message_ids": []},
    }
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(f"sensor.paket_{ORDER.lower()}")
    assert state.state == "cancelled"
    attributes = state.attributes
    assert attributes["assumed_delivered"] is False and "cancelled" not in attributes
    assert (attributes["status_text"], attributes["progress"]) == ("Storniert", 0)
    assert (attributes["eta_date"], attributes["days_until"]) == (None, None)
    other = hass.states.get("sensor.paket_amz99999999999999902").attributes
    assert other["progress"] == 1
    assert hass.states.get("sensor.pakete_unterwegs").state == "1"
    assert hass.states.get("sensor.pakete_zugestellt_heute").state == "0"

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert [p["status"] for p in diagnostics["parcels"]] == ["cancelled", "pre_transit"]


# ----- the card (run in Node) -----

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
const sandbox = {
  HTMLElement: class {},
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {},
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(process.argv[1], "utf8")
    + "\n;globalThis.__label = stateLabel; globalThis.__eta = etaText;"
    + "globalThis.__sub = subText; globalThis.__order = ORDER;"
    + "globalThis.__received = canMarkReceived;",
  sandbox,
);
const st = (state, attributes) => ({ state, attributes });
const cancelled = { carrier: "amazon", carrier_name: "Amazon", assumed_delivered: false,
  delivered_at: null, days_until: null, eta_date: null, progress: 0 };
const label = sandbox.__label(st("cancelled", cancelled));
console.log(JSON.stringify({
  label,
  eta: sandbox.__eta("cancelled", cancelled),
  sub: sandbox.__sub(label, cancelled, "cancelled"),
  order: [sandbox.__order("delivered", cancelled), sandbox.__order("cancelled", cancelled)],
  assumed: sandbox.__eta("delivered", { ...cancelled, assumed_delivered: true }),
  received: ["cancelled", "pre_transit"].map((s) => sandbox.__received(cancelled, s)),
}));
"""


def test_card_shows_a_cancelled_order_as_storniert():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    card = json.loads(done.stdout)
    assert (card["label"], card["eta"]) == ("Storniert", "Storniert")
    assert card["sub"] == "Amazon · Storniert"
    assert card["order"] == [5, 5]  # at the end of the list, with the delivered ones
    assert card["assumed"] == "Abgeschlossen (ohne Zustellbestätigung)"
    # "Erhalten" would make it delivered today: a cancelled order is not offered it.
    assert card["received"] == [False, True]

"""Amazon's refund of a box the carrier brings back ("Erstattung veranlasst für …").

The mail comes from rueckgabe@amazon.de, whose other mails (the user's own returns) are
ignored. It tells that the carrier sends the box back to Amazon and that Amazon refunds its
items: the box will not come, also once it was shipped. All values are invented, those of
fixture 234 by the anonymiser and by hand.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from email import policy
from email.message import EmailMessage

from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.const import EVENT_STATUS_CHANGED
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update, close_unconfirmed
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import OrderItem, ParcelStatus, TrackingEvent

from .conftest import load_mail
from .test_coordinator_notify import _start
from .test_mail_amazon_items import NUMBER, ORDER, _page
from .test_mail_amazon_split import (
    CABLE,
    CANCELLED,
    DAY,
    NOW,
    ORDERED,
    P2,
    SHIPPED,
    TAPE,
    TITLES,
    _box,
    _ordered,
    _read,
    _state,
)
from .test_order_closing import (
    _coordinator,
    _refresh,
)

RETURNED = "Zurück an Amazon"
DHL = "00340434161234567890"
OUT_FOR_DELIVERY = ParcelStatus.OUT_FOR_DELIVERY
SENTENCE = (
    "Es tut uns leid, dir mitteilen zu müssen, dass dein Paket vom Transportdienstleister an"
    " uns zurückgesandt wird und nicht zugestellt werden konnte. Wir haben eine Erstattung"
    " veranlasst."
)


def _refund(*articles: tuple[str, int], when: int = 3, sentence: str = SENTENCE,
            html: bool = True) -> EmailMessage:
    """Amazon's refund: the order as "Bestellnummer …", each item refunded with the link to
    its page and "Anzahl: …" (in the HTML part; the text part links nowhere)."""
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "rueckgabe@amazon.de <rueckgabe@amazon.de>"
    msg["Subject"] = f"Erstattung veranlasst für {TITLES[articles[0][0]][:30]}...."
    msg["Date"] = DAY[when]
    listed = "".join(f"{TITLES[a][:24]}... ( https://www.amazon.de/… )\nAnzahl: {n}\n"
                     for a, n in articles)
    msg.set_content(f"Hallo Max, {sentence}\n\nBestellnummer {ORDER}\n\nArtikel erstattet\n"
                    f"{listed}")
    if html:
        rows = "".join(
            f'<tr><td><a href="{_page(a)}"><img src="x.jpg" alt="{TITLES[a]}"></a></td></tr>'
            f'<tr><td><a href="{_page(a)}">{TITLES[a][:24]}...</a></td></tr>'
            f"<tr><td>Anzahl: {n}</td></tr>"
            for a, n in articles
        )
        msg.add_alternative(
            f"<html><body><p>Hallo Max, {sentence}</p><table><tr><td>Bestellnummer {ORDER}"
            f"</td></tr><tr><td>Artikel erstattet</td></tr>{rows}</table></body></html>",
            subtype="html",
        )
    return msg


# ----- reading the mail -----
def test_the_refund_of_a_box_the_carrier_brings_back_is_read():
    [update] = parse_mail(load_mail("234_rueckgabe_erstattung_paket_zurueck.eml")).updates
    assert (update.number, update.carrier, update.status) == (
        "AMZ99918875815392608", "amazon", CANCELLED
    )
    assert update.returned and update.status_text == RETURNED
    # (the text part links no item's page: no article number, the subject names it, cut
    # short as it is)
    assert update.title == "Beispiel-Flüssigkleber Holz 50 ml…"
    assert update.items == (OrderItem(None, 1, None),)


def test_the_html_part_tells_the_refunded_items_by_article_number():
    [update] = parse_mail(_refund((CABLE, 1), (TAPE, 2))).updates
    assert update.items == (OrderItem(CABLE, 1, TITLES[CABLE]), OrderItem(TAPE, 2, TITLES[TAPE]))
    assert update.title == TITLES[CABLE]


def test_any_other_mail_of_the_returns_sender_is_still_ignored():
    # (a return the user sent: refunded once Amazon has it, nothing for the tracker)
    result = parse_mail(_refund((CABLE, 1), sentence="Wir haben deine Rücksendung erhalten."))
    assert result.ignored and result.updates == []


def test_a_mail_about_a_return_the_user_sent_is_none_the_carrier_brings_back():
    # (the same words about the carrier, but no box that could not be delivered, or no
    # refund's subject)
    own = _refund((CABLE, 1), sentence="Sobald dein Paket vom Transportdienstleister an uns"
                  " zurückgesandt wurde, erstatten wir den Betrag.")
    other_subject = _refund((CABLE, 1))
    other_subject.replace_header("Subject", "Deine Rücksendung ist unterwegs")
    for msg in (own, other_subject):
        result = parse_mail(msg)
        assert result.ignored and result.updates == []


def test_a_refund_without_an_order_or_without_its_item_is_ignored():
    # Neither counted as an Amazon mail not recognised, nor a cancellation of the whole
    # order: what was refunded is not known.
    no_order = _refund((CABLE, 1))
    for part in no_order.iter_parts():
        text = part.get_content().replace("Bestellnummer", "Bestellung vom")
        part.set_content(text, subtype=part.get_content_subtype())
    nameless = _refund((CABLE, 1), html=False)
    nameless.replace_header("Subject", "Erstattung veranlasst")
    for msg in (no_order, nameless):
        result = parse_mail(msg)
        assert result.ignored and result.updates == []


# ----- what becomes of the box -----
def test_a_box_on_its_way_the_carrier_brings_back_is_closed():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment="TAbCdE9fG"),
          _box((CABLE, 1), shipment="TBbCdE9fG", when=2))
    [update] = parse_mail(_refund((CABLE, 1))).updates
    change = apply_update(parcels, update, NOW)
    assert change is not None and change.parcel is parcels[P2] and change.old_status is SHIPPED
    assert _state(parcels) == {NUMBER: (SHIPPED, [(TAPE, 1)]), P2: (CANCELLED, [(CABLE, 1)])}
    assert parcels[P2].result.status_text == RETURNED
    assert parcels[P2].result.events[0].text == RETURNED
    assert parcels[P2].result.eta_date is None


def test_a_copy_of_the_refund_changes_nothing():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1),), _box((TAPE, 1), shipment="TAbCdE9fG"), _refund((TAPE, 1)))
    [update] = parse_mail(_refund((TAPE, 1))).updates
    assert apply_update(parcels, update, NOW) is None
    assert parcels[NUMBER].status is CANCELLED


def test_a_box_delivered_for_real_is_none_the_carrier_brings_back():
    # (what arrived and went back is the user's own return)
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1),), _box((TAPE, 1), shipment="TAbCdE9fG"),
          _box((TAPE, 1), shipment="TAbCdE9fG", when=2, subject="Zugestellt: „Beispiel…“"))
    [update] = parse_mail(_refund((TAPE, 1))).updates
    assert apply_update(parcels, update, NOW) is None
    assert parcels[NUMBER].status is ParcelStatus.DELIVERED


def test_without_article_numbers_the_title_tells_the_box():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment="TAbCdE9fG"),
          _box((CABLE, 1), shipment="TBbCdE9fG", when=2), _refund((CABLE, 1), html=False))
    assert _state(parcels)[P2] == (CANCELLED, [(CABLE, 1)])
    assert parcels[NUMBER].status is SHIPPED


def test_a_box_that_knows_no_article_numbers_is_told_by_its_items_name():
    # (an entry of an older version, or one whose mails had no HTML part)
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1),), _box((TAPE, 1), shipment="TAbCdE9fG"))
    parcels[NUMBER].items = [OrderItem(None, 1, TITLES[TAPE])]
    _read(parcels, _refund((TAPE, 1)))
    assert parcels[NUMBER].status is CANCELLED


def test_an_order_with_a_carriers_number_is_brought_back_though_still_ordered():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1),))
    parcels[NUMBER].tracking_ref, parcels[NUMBER].tracking_carrier = DHL, "dhl"
    _read(parcels, _refund((TAPE, 1)))
    assert parcels[NUMBER].status is CANCELLED
    assert parcels[NUMBER].result.status_text == RETURNED


def test_when_the_rest_holds_the_same_item_nothing_is_told_back():
    # "Menge: 2" in two boxes, the second not shipped yet: which one went back is not told.
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 2),), _box((TAPE, 1), shipment="TAbCdE9fG"))
    [update] = parse_mail(_refund((TAPE, 1))).updates
    assert apply_update(parcels, update, NOW) is None
    assert _state(parcels) == {NUMBER: (SHIPPED, [(TAPE, 1)]), P2: (ORDERED, [(TAPE, 1)])}


def test_the_duty_of_a_box_brought_back_is_no_longer_due():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1),), _box((TAPE, 1), shipment="TAbCdE9fG"))
    box = parcels[NUMBER]
    box.customs_amount, box.customs_currency, box.customs_cash = 12.5, "EUR", True
    box.last_error, box.error_streak = "Zeitüberschreitung", 3
    _read(parcels, _refund((TAPE, 1)))
    assert (box.customs_amount, box.customs_currency, box.customs_cash) == (None, None, False)
    assert (box.last_error, box.error_streak) == (None, 0)


# ----- a box brought back is so for good -----
def _brought_back() -> dict:
    """An order of two boxes, each with Amazon's id; the second one (CABLE, "…P2") with a
    carrier's number as well, brought back."""
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment="TAbCdE9fG"),
          _box((CABLE, 1), shipment="TBbCdE9fG", when=2))
    parcels[P2].tracking_ref, parcels[P2].tracking_carrier = DHL, "dhl"
    _read(parcels, _refund((CABLE, 1)))
    assert parcels[P2].status is CANCELLED
    return parcels


def test_a_carriers_mail_never_opens_a_box_brought_back_again():
    # (older or newer: "zugestellt" then is the delivery to the shop)
    for status, sent in ((OUT_FOR_DELIVERY, NOW - timedelta(days=2)),
                         (ParcelStatus.DELIVERED, NOW + timedelta(days=3))):
        parcels = _brought_back()
        mail = MailUpdate(DHL, "dhl", status, sent, shop="amazon")
        assert apply_update(parcels, mail, NOW) is None
        assert parcels[P2].status is CANCELLED and DHL not in parcels


def test_a_mail_with_the_id_of_a_box_brought_back_makes_no_further_box():
    # A "Zustellversuch" with the box's id, no items: no phantom "…P3", and no other box
    # of the order takes it.
    parcels = _brought_back()
    attempt = MailUpdate(NUMBER, "amazon", SHIPPED, NOW - timedelta(days=1), postponed=True,
                         status_text="Zustellung versucht", shipment_id="TBbCdE9fG")
    assert apply_update(parcels, attempt, NOW) is None
    assert _state(parcels) == {NUMBER: (SHIPPED, [(TAPE, 1)]), P2: (CANCELLED, [(CABLE, 1)])}


def test_a_box_brought_back_without_an_id_still_takes_its_own_mails():
    # (its mails go by its items: none goes to another box of the order)
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment=None),
          _box((CABLE, 1), shipment=None, when=2), _refund((CABLE, 1)))
    assert parcels[P2].status is CANCELLED
    # ("Zugestellt" after the refund is the delivery to the shop)
    delivered = MailUpdate(NUMBER, "amazon", ParcelStatus.DELIVERED, NOW + timedelta(days=3),
                           items=(OrderItem(CABLE, 1, TITLES[CABLE]),))
    assert apply_update(parcels, delivered, NOW) is None
    assert _state(parcels) == {NUMBER: (SHIPPED, [(TAPE, 1)]), P2: (CANCELLED, [(CABLE, 1)])}


# ----- only a box that is known and holds nothing else -----
def test_a_refund_read_before_the_boxs_mails_changes_nothing():
    # The refund comes for a box that was shipped: one not known yet is none it closes,
    # and what is still ordered is no cancellation. The box comes as usual (a known limit).
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)))
    [update] = parse_mail(_refund((CABLE, 1))).updates
    assert apply_update(parcels, update, NOW) is None
    _read(parcels, _box((CABLE, 1), shipment="TBbCdE9fG", when=2))
    assert _state(parcels) == {NUMBER: (SHIPPED, [(CABLE, 1)]), P2: (ORDERED, [(TAPE, 1)])}


def test_by_name_only_a_box_of_one_item_and_the_same_quantity_is_brought_back():
    # Without article numbers: a box whose title tells further items, or one that holds
    # two pieces where the refund names one, is not the one told.
    more: dict = {}
    _read(more, _ordered((TAPE, 1),), _box((TAPE, 1), shipment="TAbCdE9fG"))
    more[NUMBER].items = []
    more[NUMBER].mail_title = f"{TITLES[TAPE]} und 2 weitere Artikel"
    two: dict = {}
    _read(two, _ordered((TAPE, 2),), _box((TAPE, 2), shipment="TAbCdE9fG"))
    two[NUMBER].items = [OrderItem(None, 2, TITLES[TAPE])]
    for parcels in (more, two):
        [update] = parse_mail(_refund((TAPE, 1), html=False)).updates
        assert apply_update(parcels, update, NOW) is None
        assert parcels[NUMBER].status is SHIPPED


def test_a_box_closed_without_a_delivery_mail_is_brought_back():
    # ("Abgeschlossen ohne Zustellbestätigung": nobody saw it arrive)
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1),), _box((TAPE, 1), shipment="TAbCdE9fG"))
    close_unconfirmed(parcels[NUMBER], NOW)
    _read(parcels, _refund((TAPE, 1)))
    assert parcels[NUMBER].status is CANCELLED and not parcels[NUMBER].assumed_delivered


def test_a_long_history_of_a_box_brought_back_stays():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1),), _box((TAPE, 1), shipment="TAbCdE9fG"))
    box = parcels[NUMBER]
    lines = [TrackingEvent(NOW - timedelta(hours=n), f"Zeile {n}", None) for n in range(20)]
    box.result = replace(box.result, events=lines)
    _read(parcels, _refund((TAPE, 1)))
    assert len(box.result.events) == 20 and box.result.events[0].text == RETURNED


def test_a_box_that_holds_more_than_the_refund_names_is_none_brought_back():
    # A box goes back whole: one that holds another item as well is not the one told,
    # also while it is "Bestellt" with a carrier's number.
    shipped: dict = {}
    _read(shipped, _ordered((TAPE, 1), (CABLE, 1)),
          _box((TAPE, 1), (CABLE, 1), shipment="TAbCdE9fG"))
    ordered: dict = {}
    _read(ordered, _ordered((TAPE, 1), (CABLE, 1)))
    ordered[NUMBER].tracking_ref, ordered[NUMBER].tracking_carrier = DHL, "dhl"
    for parcels, status in ((shipped, SHIPPED), (ordered, ORDERED)):
        [update] = parse_mail(_refund((CABLE, 1))).updates
        assert apply_update(parcels, update, NOW) is None
        assert parcels[NUMBER].status is status


# ----- told -----
async def test_a_box_brought_back_tells_its_status_and_pushes_cancelled(hass, hass_storage, freezer):
    # "Storniert" is a default push since #91; automations hear of it too.
    freezer.move_to(datetime(2026, 10, 12, 9, 0, tzinfo=BERLIN))
    await hass.config.async_set_time_zone("Europe/Berlin")
    calls = async_mock_service(hass, "notify", "send_message")
    changed = async_capture_events(hass, EVENT_STATUS_CHANGED)
    coord = await _coordinator(hass, hass_storage, [])
    await _refresh(hass, coord)
    await _start(hass)
    mails = (_ordered((TAPE, 1),), _box((TAPE, 1), shipment="TAbCdE9fG"), _refund((TAPE, 1)))
    for n, msg in enumerate(mails):
        msg["Message-ID"] = f"<return{n}@example.org>"
        assert (await coord.async_import_raw_mail(msg.as_bytes()))["result"] == "recognized"
    await hass.async_block_till_done()
    await coord.async_shutdown()
    assert coord.store.parcels[NUMBER].status is CANCELLED
    assert [(e.data["number"], e.data["new_status"]) for e in changed][-1:] == [
        (NUMBER, "cancelled")
    ]
    assert len(calls) == 1
    assert "storniert" in calls[0].data["message"]

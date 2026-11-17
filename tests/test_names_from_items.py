"""An entry's name comes from its items, the further items stand behind it as "(+2)".

Amazon's subject cuts an item's name short ("Versendet: „Beispiel-Maßband 5 m mi…“") and
names the order's first item for every box. The items of the newest mail tell the name in
full and what the box holds. No entry carries the number of the entry in its name any more
("… (2)"): the number tells the entries apart. All values here are invented.
"""

from datetime import datetime
from email import policy
from email.message import EmailMessage

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import (
    OrderItem,
    Parcel,
    ParcelStatus,
    TrackingResult,
    display_name,
    name_parts,
)
from custom_components.parcel_tracker.notification import build_notification

from .conftest import DAYTIME, load_mail

ORDER = "999-9156534-2587125"
NUMBER = "AMZ99991565342587125"
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=BERLIN)
LATER = datetime(2026, 10, 12, 9, 0, tzinfo=BERLIN)
TAPE = OrderItem("B0BEISPIEL", 1, "Beispiel-Maßband 5 m mit Feststellknopf und Gürtelclip")
CABLE = OrderItem("B0MUSTER01", 2, "Beispiel-Kabel 2 m")
SUBJECT = "Beispiel-Maßband 5 m mi…"  # (as Amazon's subject cuts it)


def _mail(status, *items, sent=NOW, **fields) -> MailUpdate:
    return MailUpdate(NUMBER, "amazon", status, sent, title=SUBJECT, items=items, **fields)


def _ordered(parcels: dict) -> Parcel:
    apply_update(parcels, _mail(ParcelStatus.PRE_TRANSIT, TAPE, CABLE), NOW)
    return parcels[NUMBER]


# ----- the name from the items -----
def test_an_order_is_named_after_its_first_item_in_full_and_shows_how_many_more():
    order = _ordered({})
    assert order.name == TAPE.title
    assert order.mail_title == SUBJECT  # (later mails find it by the subject, as before)
    assert display_name(order, False) == f"{TAPE.title} (+1)"


def test_a_box_is_named_after_what_it_holds():
    # The box holds the second item only; the subject names the order's first one.
    parcels: dict = {}
    _ordered(parcels)
    apply_update(parcels, _mail(ParcelStatus.IN_TRANSIT, CABLE, sent=LATER), LATER)
    assert display_name(parcels[NUMBER], False) == CABLE.title


def test_a_name_the_user_typed_in_stays():
    parcels: dict = {}
    order = _ordered(parcels)
    order.name, order.name_manual = "Werkzeug für Papa", True
    apply_update(parcels, _mail(ParcelStatus.IN_TRANSIT, CABLE, sent=LATER), LATER)
    assert display_name(order, False) == "Werkzeug für Papa"


def test_a_later_mail_without_titles_leaves_the_name():
    # (a mail without HTML part: no title, no article number)
    parcels: dict = {}
    order = _ordered(parcels)
    apply_update(parcels, _mail(ParcelStatus.IN_TRANSIT, OrderItem(None, 1), sent=LATER), LATER)
    assert order.items == [OrderItem(None, 1)] and order.name == TAPE.title


def test_a_further_box_without_item_is_named_after_the_shop_also_next_to_a_parcel():
    # The order's own number is a carrier's parcel here: no entry of the order, but the box
    # is a further one ("…P2") all the same, named after the shop.
    parcels = {NUMBER: Parcel(NUMBER, "dhl", "mail", "Beispielversender", NOW, NOW)}
    box = MailUpdate(NUMBER, "amazon", ParcelStatus.IN_TRANSIT, NOW, shipment_id="DAbCdE9fG")
    change = apply_update(parcels, box, NOW)
    assert change.parcel.number == f"{NUMBER}P2" and change.parcel.name == "Amazon-Sendung"


def test_without_titles_the_subject_names_the_entry_as_before():
    parcels: dict = {}
    apply_update(parcels, _mail(ParcelStatus.PRE_TRANSIT, OrderItem(None, 1)), NOW)
    assert parcels[NUMBER].name == SUBJECT


def test_titles_are_stored_and_read_back():
    order = _ordered({})
    assert Parcel.from_dict(order.to_dict()).items == [TAPE, CABLE]


# ----- how a name is shown -----
def _parcel(number: str = NUMBER, name: str | None = None, **fields) -> Parcel:
    return Parcel(number, "amazon", "mail", name, NOW, NOW, **fields)


@pytest.mark.parametrize(
    ("number", "name", "shown"),
    [
        # Older versions put the entry's number behind the name of a further one.
        (f"{NUMBER}P2", "Beispiel-Kabel… (2)", "Beispiel-Kabel…"),
        (f"{NUMBER}P2", "Amazon-Sendung (2)", "Amazon-Sendung"),
        (f"{NUMBER}P12", "Beispiel-Kabel (12)", "Beispiel-Kabel"),
        # ... only the entry's own number: a name may end in a number in brackets.
        (NUMBER, "Beispiel-Set (2)", "Beispiel-Set (2)"),
        (f"{NUMBER}P3", "Beispiel-Set (2)", "Beispiel-Set (2)"),
        # Amazon's subject tells the further items in words.
        (NUMBER, "Beispiel-Kabel… und 2 weitere Artikel", "Beispiel-Kabel… (+2)"),
        (f"{NUMBER}P2", "Beispiel-Kabel… und 1 weiterer Artikel (2)", "Beispiel-Kabel… (+1)"),
    ],
)
def test_a_name_from_an_older_version_is_shown_the_new_way(number, name, shown):
    assert display_name(_parcel(number, name), False) == shown


def test_the_items_tell_how_many_more_only_for_a_name_from_them():
    assert name_parts(_parcel(name=CABLE.title, items=[CABLE, TAPE])) == (CABLE.title, 1)
    # A name from a subject (a later mail without HTML part named the box) says it in words:
    # the items may be the order's.
    parcel = _parcel(name="Beispiel-Kabel…", items=[TAPE, CABLE])
    assert name_parts(parcel) == ("Beispiel-Kabel…", 0)
    parcel.name = "Beispiel-Kabel… und 2 weitere Artikel"
    assert name_parts(parcel) == ("Beispiel-Kabel…", 2)


def test_a_title_that_ends_in_the_entrys_number_stays_whole():
    adapter = OrderItem("B0BEISPIEL", 1, "Beispiel-Adapter USB-C (2)")
    parcel = _parcel(f"{NUMBER}P2", adapter.title, items=[adapter])
    assert display_name(parcel, False) == "Beispiel-Adapter USB-C (2)"


def test_a_name_typed_in_is_shown_as_it_is():
    parcel = _parcel(f"{NUMBER}P2", "Kabel (2) und 2 weitere Artikel", name_manual=True,
                     items=[CABLE, TAPE])
    assert display_name(parcel, False) == "Kabel (2) und 2 weitere Artikel"


def test_hidden_names_and_gifts_stay_as_they_were():
    parcel = _parcel(name=TAPE.title, items=[TAPE, CABLE])
    assert display_name(parcel, True) == "Amazon-Bestellung …7125"
    parcel.gift = True
    assert display_name(parcel, False) == "Geschenk · Amazon-Bestellung …7125"


def test_a_notification_cuts_the_name_but_never_the_further_items():
    parcel = _parcel(name=TAPE.title, items=[TAPE, CABLE], result=TrackingResult(
        ParcelStatus.DELIVERED, "Zugestellt", None, None, None, None, None, None, NOW, []
    ))
    _, message = build_notification(parcel, ParcelStatus.IN_TRANSIT, NOW)
    shown = "Beispiel-Maßband 5 m mit Feststellknopf… (+1)"
    assert message == f"✅ {shown} (Amazon) wurde zugestellt"


# ----- reading the title -----
def _html(*rows: str) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "Amazon.de <versandbestaetigung@amazon.de>"
    msg["Subject"] = f"Versendet: „{SUBJECT}“"
    msg["Date"] = "Sun, 11 Oct 2026 08:00:00 +0200"
    msg.set_content(f"Bestellnr. {ORDER}\n* {SUBJECT}\n")
    cells = "".join(f"<tr><td>{row}</td></tr>" for row in (f"Bestellnr. {ORDER}", *rows))
    msg.add_alternative(f"<html><body><table>{cells}</table></body></html>", subtype="html")
    return msg


PAGE = "https://www.amazon.de/dp/B0BEISPIEL"


def test_the_pictures_name_wins_over_the_links_text_wherever_it_stands():
    # The name's link before the picture's: the name in full all the same.
    msg = _html(f'<a href="{PAGE}">Beispiel-Maßband 5 m mi...</a>',
                f'<a href="{PAGE}"><img src="x.jpg" alt="{TAPE.title}"></a>', "Menge: 1")
    [update] = parse_mail(msg).updates
    assert update.items == (OrderItem(TAPE.article_id, 1, TAPE.title),)


def test_only_a_links_own_text_is_a_title():
    # A picture without name and no link with text: the seller below is no title.
    msg = _html(f'<a href="{PAGE}"><img src="x.jpg" alt=""></a>',
                "Verkauf durch Beispielhandel e.K.", "Menge: 1")
    [update] = parse_mail(msg).updates
    assert update.items == (OrderItem(TAPE.article_id, 1),)


@pytest.mark.parametrize(
    "alt", ["Produktbild", "Jetzt 20 % sparen – Beispiel-Angebot der Woche", "Amazon Logo"]
)
def test_an_alt_text_that_is_not_the_items_name_gives_way_to_the_links_text(alt):
    msg = _html(f'<a href="{PAGE}"><img src="x.jpg" alt="{alt}"></a>',
                f'<a href="{PAGE}">Beispiel-Maßband 5 m mi...</a>', "Menge: 1")
    [update] = parse_mail(msg).updates
    assert update.items == (OrderItem(TAPE.article_id, 1, "Beispiel-Maßband 5 m mi..."),)


@pytest.mark.parametrize("button", ["Erneut kaufen", "ARTIKEL ANSEHEN"])
def test_a_buttons_text_is_no_title(button):
    # A picture without name, then a button to the item's page: no title, the subject names
    # the entry as before.
    msg = _html(f'<a href="{PAGE}"><img src="x.jpg" alt=""></a>',
                f'<a href="{PAGE}">{button}</a>', "Menge: 1")
    [update] = parse_mail(msg).updates
    assert update.items == (OrderItem(TAPE.article_id, 1),)


def test_a_link_left_open_takes_no_name_from_a_later_picture():
    # The name's link is never closed; a logo further down is no item's name.
    msg = _html(f'<a href="{PAGE}">Beispiel-Maßband 5 m mi...', "Menge: 1",
                '<img src="logo.png" alt="Amazon Logo">')
    [update] = parse_mail(msg).updates
    assert update.items == (OrderItem(TAPE.article_id, 1),)


def test_a_short_links_text_takes_the_alt_text_that_begins_with_it():
    msg = _html(f'<a href="{PAGE}"><img src="x.jpg" alt="Beispiel-Kabel 2 m USB-C auf USB-A"></a>',
                f'<a href="{PAGE}">Beispiel-Kabel...</a>', "Menge: 1")
    [update] = parse_mail(msg).updates
    assert update.items[0].title == "Beispiel-Kabel 2 m USB-C auf USB-A"


# ----- two mails in Amazon's own HTML (fixtures 212 and 213) -----
# The markup of the order's block is Amazon's as it is (MJML tables, the picture's link and
# the name's link per item); every value in them is invented.
ORDERED = "212_bestellbestaetigung_bestellt_artikelliste.eml"
SHIPPED = "213_versandbestaetigung_versendet_artikelliste.eml"
KIT = OrderItem("B0BEISPIEL", 1, "Beispiel-Werkzeugset 12-teilig mit Koffer und Bit-Halter")
TIES = OrderItem("B0MUSTER01", 1, "Musterfirma Kabelbinder 200 Stück schwarz UV-beständig")
REAL = "AMZ99921255579900212"


def test_amazons_order_mail_names_each_item_in_full():
    [update] = parse_mail(load_mail(ORDERED)).updates
    assert (update.status, update.items) == (ParcelStatus.PRE_TRANSIT, (KIT, TIES))


def test_amazons_box_mail_names_the_item_in_the_box():
    [update] = parse_mail(load_mail(SHIPPED)).updates
    assert (update.status, update.shipment_id) == (ParcelStatus.IN_TRANSIT, "TBeiSpiel1")
    assert update.items == (TIES,)


def test_the_box_is_named_after_what_it_holds_not_after_the_order():
    parcels: dict = {}
    for name in (ORDERED, SHIPPED):
        for update in parse_mail(load_mail(name)).updates:
            apply_update(parcels, update, update.sent_at)
            if name == ORDERED:
                assert display_name(parcels[REAL], False) == f"{KIT.title} (+1)"
    assert display_name(parcels[REAL], False) == TIES.title


# ----- with Home Assistant -----
async def _setup(hass, hass_storage, freezer, *parcels: Parcel):
    freezer.move_to(DAYTIME)
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {"parcels": [p.to_dict() for p in parcels], "message_ids": []},
    }
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_the_sensor_has_the_name_and_the_further_items_apart(hass, hass_storage, freezer):
    await _setup(hass, hass_storage, freezer, _parcel(name=TAPE.title, items=[TAPE, CABLE]))
    state = hass.states.get(f"sensor.paket_{NUMBER.lower()}")
    assert (state.attributes["name"], state.attributes["more_items"]) == (TAPE.title, 1)
    # The entity's own name is one text, as in notifications and the calendar.
    assert state.name == f"{TAPE.title} (+1)"


@pytest.mark.parametrize("given", [TAPE.title, f"{TAPE.title} (+1)"])
async def test_saving_the_offered_name_untouched_changes_nothing(
    hass, hass_storage, freezer, given
):
    # The card offers the name without "(+1)"; the sensor shows it with.
    entry = await _setup(hass, hass_storage, freezer, _parcel(name=TAPE.title, items=[TAPE, CABLE]))
    await hass.services.async_call(
        DOMAIN, "rename_parcel", {"number": NUMBER, "name": given}, blocking=True
    )
    parcel = entry.runtime_data.store.parcels[NUMBER]
    assert (parcel.name, parcel.name_manual) == (TAPE.title, False)

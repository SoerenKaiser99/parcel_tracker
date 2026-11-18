"""An Amazon order split into its boxes by article number and quantity.

The order's mail lists every item of the order, a box's mail the items in that box (see
test_mail_amazon_items.py). The order's first box keeps the order's own entry ("AMZ…"),
so a sensor never changes its number; what the box does not hold stays "Bestellt" in an
entry of its own ("…P2"), which the next box takes over in turn. All values are invented.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta

from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.const import EVENT_PARCEL_ADDED, EVENT_STATUS_CHANGED
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import (
    apply_update,
    close_unconfirmed,
    fold_delivered,
)
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import OrderItem, Parcel, ParcelStatus, name_parts

from .test_coordinator_notify import _start
from .test_mail_amazon_items import NUMBER, ORDER, _item, _msg, _redirect
from .test_order_closing import _coordinator, _refresh

CABLE, LAMP, TAPE = "B0KABEL001", "B0LAMPE001", "B0MASSBAND"
TITLES = {
    TAPE: "Beispiel-Maßband 5 m mit Feststellknopf",
    CABLE: "Beispiel-Kabel 2 m geflochten",
    LAMP: "Beispiel-Lampe mit Klemme",
}
P2, P3 = f"{NUMBER}P2", f"{NUMBER}P3"
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=BERLIN)
DAY = {n: f"{d} Oct 2026 08:00:00 +0200" for n, d in enumerate(("Fri, 09", "Sat, 10",
                                                               "Sun, 11", "Mon, 12"))}


def _items(*articles: tuple[str, int]) -> tuple[str, ...]:
    return tuple(_item(a, n, TITLES[a]) for a, n in articles)


def _ordered(*articles: tuple[str, int], when: int = 0):
    return _msg((ORDER, _items(*articles)), subject="Bestellt: „Beispiel…“", when=DAY[when])


def _box(*articles: tuple[str, int], shipment: str | None, when: int = 1,
         subject: str = "Versendet: „Beispiel…“", html: bool = True):
    links = ()
    if shipment:
        page = f"https://www.amazon.de/progress-tracker/package?orderId={ORDER}"
        links = (_redirect(f"{page}&shipmentId={shipment}"),)
    return _msg((ORDER, _items(*articles)), subject=subject, links=links, when=DAY[when],
                html=html)


def _read(parcels: dict, *mails) -> None:
    for msg in mails:
        for update in parse_mail(msg).updates:
            apply_update(parcels, update, NOW)


def _state(parcels: dict) -> dict:
    """Per entry: status and the items it holds, (article, quantity)."""
    return {
        number: (p.status, [(i.article_id, i.quantity) for i in p.items])
        for number, p in sorted(parcels.items())
    }


ORDERED, SHIPPED = ParcelStatus.PRE_TRANSIT, ParcelStatus.IN_TRANSIT


# ----- what a box leaves stays ordered -----
def test_the_first_box_keeps_the_order_and_the_rest_stays_ordered():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)))
    order_day = parcels[NUMBER].result.eta_date
    _read(parcels, _box((TAPE, 1), shipment="TAbCdE9fG"))
    assert _state(parcels) == {
        NUMBER: (SHIPPED, [(TAPE, 1)]),
        P2: (ORDERED, [(CABLE, 1), (LAMP, 1)]),
    }
    # Each is named after what it really holds, with how many more there are.
    assert name_parts(parcels[NUMBER]) == (TITLES[TAPE], 0)
    assert name_parts(parcels[P2]) == (TITLES[CABLE], 1)
    rest = parcels[P2]
    # (what the order was: its history, its day, its seller)
    assert [e.text for e in rest.result.events] == ["Bestellt"]
    assert rest.result.eta_date == order_day
    assert rest.sellers == parcels[NUMBER].sellers[:1]
    assert rest.shipment_ids == [] and rest.tracking_ref is None


def test_the_next_box_takes_the_rest_over_and_leaves_what_it_does_not_hold():
    parcels: dict = {}
    _read(
        parcels,
        _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
        _box((TAPE, 1), shipment="TAbCdE9fG"),
        _box((CABLE, 1), shipment="TBbCdE9fG", when=2),
    )
    assert _state(parcels) == {
        NUMBER: (SHIPPED, [(TAPE, 1)]),
        P2: (SHIPPED, [(CABLE, 1)]),
        P3: (ORDERED, [(LAMP, 1)]),
    }
    _read(parcels, _box((LAMP, 1), shipment="TCbCdE9fG", when=3))
    assert _state(parcels)[P3] == (SHIPPED, [(LAMP, 1)])
    assert len(parcels) == 3


def test_a_quantity_split_over_two_boxes_is_taken_away_piece_by_piece():
    # "Menge: 2" sent as 1 + 1: the rest holds the second piece.
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 2), (CABLE, 1)), _box((TAPE, 1), shipment="TAbCdE9fG"))
    assert _state(parcels)[P2] == (ORDERED, [(TAPE, 1), (CABLE, 1)])
    _read(parcels, _box((TAPE, 1), (CABLE, 1), shipment="TBbCdE9fG", when=2))
    assert _state(parcels) == {
        NUMBER: (SHIPPED, [(TAPE, 1)]),
        P2: (SHIPPED, [(TAPE, 1), (CABLE, 1)]),
    }


def test_a_box_with_everything_leaves_nothing():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 2), (CABLE, 1)),
          _box((CABLE, 1), (TAPE, 2), shipment="TAbCdE9fG"))
    assert list(parcels) == [NUMBER]


def test_without_article_numbers_nothing_is_split():
    # A box's mail without HTML part: what the box holds is not known for sure.
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment=None, html=False))
    assert list(parcels) == [NUMBER]


def test_a_box_that_holds_none_of_the_orders_articles_leaves_nothing():
    # (it is not this order's box: Amazon put another order's items under this number)
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((LAMP, 1), shipment="TAbCdE9fG"))
    assert list(parcels) == [NUMBER]


def test_the_rest_belongs_to_whom_the_order_belongs_and_is_a_gift_if_it_is():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)))
    order = parcels[NUMBER]
    order.owner, order.owner_manual = "person.anna", True
    order.gift, order.gift_for = True, ["person.ben"]
    _read(parcels, _box((TAPE, 1), shipment="TAbCdE9fG"))
    rest = parcels[P2]
    assert (rest.owner, rest.owner_manual, rest.gift, rest.gift_for) == (
        "person.anna", True, True, ["person.ben"]
    )


def test_making_the_rest_is_no_change_of_its_own():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)))
    [update] = parse_mail(_box((TAPE, 1), shipment="TAbCdE9fG")).updates
    change = apply_update(parcels, update, NOW)
    assert (change.parcel.number, change.old_status, change.created) == (NUMBER, ORDERED, False)
    assert not change.announce


# ----- the order of the mails -----
def test_the_orders_mail_read_after_the_box_leaves_the_same_rest():
    in_order: dict = {}
    _read(in_order, _ordered((TAPE, 1), (CABLE, 2)), _box((TAPE, 1), shipment="TAbCdE9fG"))
    late: dict = {}
    _read(late, _box((TAPE, 1), shipment="TAbCdE9fG"), _ordered((TAPE, 1), (CABLE, 2)))
    assert _state(late) == _state(in_order) == {
        NUMBER: (SHIPPED, [(TAPE, 1)]),
        P2: (ORDERED, [(CABLE, 2)]),
    }
    assert name_parts(late[P2]) == (TITLES[CABLE], 0)


def test_the_orders_mail_read_after_all_boxes_leaves_nothing():
    parcels: dict = {}
    _read(
        parcels,
        _box((TAPE, 1), shipment="TAbCdE9fG"),
        _box((CABLE, 1), shipment="TBbCdE9fG", when=2),
        _ordered((TAPE, 1), (CABLE, 1)),
    )
    assert _state(parcels) == {NUMBER: (SHIPPED, [(TAPE, 1)]), P2: (SHIPPED, [(CABLE, 1)])}


def test_the_orders_mail_read_late_makes_no_rest_while_a_box_holds_no_items():
    # The first box's mail had no HTML part: what it holds is not known.
    parcels: dict = {}
    _read(parcels, _box((TAPE, 1), shipment=None, html=False), _ordered((TAPE, 1), (CABLE, 1)))
    assert list(parcels) == [NUMBER]


# ----- mails without Amazon's id -----
def test_shipped_without_id_goes_to_the_rest_by_its_articles():
    parcels: dict = {}
    _read(
        parcels,
        _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
        _box((TAPE, 1), shipment="TAbCdE9fG"),
        _box((LAMP, 1), shipment=None, when=2),
    )
    assert _state(parcels) == {
        NUMBER: (SHIPPED, [(TAPE, 1)]),
        P2: (SHIPPED, [(LAMP, 1)]),
        P3: (ORDERED, [(CABLE, 1)]),
    }


def test_a_later_mail_without_id_goes_to_the_box_with_its_articles():
    parcels: dict = {}
    _read(
        parcels,
        _ordered((TAPE, 1), (CABLE, 1)),
        _box((TAPE, 1), shipment="TAbCdE9fG"),
        _box((TAPE, 1), shipment=None, when=2, subject="Zugestellt: „Beispiel…“"),
    )
    assert _state(parcels) == {
        NUMBER: (ParcelStatus.DELIVERED, [(TAPE, 1)]),
        P2: (ORDERED, [(CABLE, 1)]),
    }


def test_shipped_without_id_and_items_goes_to_the_rest():
    # (no further box "…P3" next to a rest that waits for exactly this box)
    parcels: dict = {}
    _read(
        parcels,
        _ordered((TAPE, 1), (CABLE, 1)),
        _box((TAPE, 1), shipment="TAbCdE9fG"),
        _box((CABLE, 1), shipment=None, when=2, html=False,
             subject="Versendet: „Beispiel-Kabel…“"),
    )
    assert [(n, p.status) for n, p in sorted(parcels.items())] == [
        (NUMBER, SHIPPED), (P2, SHIPPED)
    ]


# ----- carriers' mails -----
def _carrier_mail(day: date | None, status=SHIPPED, sent: datetime = NOW) -> MailUpdate:
    return MailUpdate("00340434161234567890", "dhl", status, sent, eta_date=day, shop="amazon")


def _split_order(parcels: dict) -> None:
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment="TAbCdE9fG"))
    # (the order's mail named the same day as the box's: common for both)
    parcels[P2].result = replace(parcels[P2].result, eta_date=parcels[NUMBER].result.eta_date)


def test_a_carriers_mail_goes_to_the_box_not_to_the_rest_of_the_same_day():
    parcels: dict = {}
    _split_order(parcels)
    day = parcels[NUMBER].result.eta_date
    apply_update(parcels, _carrier_mail(day), NOW)
    assert parcels[NUMBER].tracking_ref == "00340434161234567890"
    assert parcels[P2].tracking_ref is None and parcels[P2].status is ORDERED


def test_a_carriers_mail_for_the_rests_day_alone_is_a_parcel_of_its_own():
    # A carrier carries a box: what is not shipped yet never takes its mail.
    parcels: dict = {}
    _split_order(parcels)
    later = parcels[NUMBER].result.eta_date + timedelta(days=5)
    parcels[P2].result = replace(parcels[P2].result, eta_date=later)
    apply_update(parcels, _carrier_mail(later), NOW)
    assert "00340434161234567890" in parcels
    assert parcels[P2].tracking_ref is None


def test_a_delivered_carrier_parcel_is_folded_into_the_box_not_the_rest():
    parcels: dict = {}
    _split_order(parcels)
    day = parcels[NUMBER].result.eta_date
    delivered = datetime.combine(day, datetime.min.time(), BERLIN) + timedelta(hours=14)
    mail = _carrier_mail(None, ParcelStatus.DELIVERED, delivered)
    # (made before Amazon's box was known: a parcel of its own)
    parcels["00340434161234567890"] = Parcel(
        "00340434161234567890", "dhl", "mail", "Amazon", delivered, delivered
    )
    apply_update(parcels, mail, delivered)
    order = fold_delivered(parcels, parcels["00340434161234567890"], delivered)
    assert order is parcels[NUMBER]
    assert parcels[P2].status is ORDERED


# ----- cancelling -----
def _cancel(title: str) -> MailUpdate:
    """A cancellation of items whose mail names no article number (no HTML part)."""
    return MailUpdate(NUMBER, "amazon", ParcelStatus.CANCELLED, NOW, title=title)


def _cancelled(*articles: tuple[str, int], when: int = 2, html_head: str = ""):
    """Amazon's mail "Artikel erfolgreich storniert": the subject names the first item, the
    HTML part lists each one with its article number and quantity."""
    first, count = articles[0]
    msg = _msg((ORDER, _items(*articles)), when=DAY[when], html_head=html_head,
               subject=f"Artikel erfolgreich storniert: {count} „{TITLES[first][:20]}…“")
    msg.replace_header("From", "Amazon.de <order-update@amazon.de>")
    return msg


def test_a_cancellation_lists_the_items_it_cancels():
    [update] = parse_mail(_cancelled((CABLE, 1), (LAMP, 2))).updates
    assert update.status is ParcelStatus.CANCELLED
    assert [(i.article_id, i.quantity) for i in update.items] == [(CABLE, 1), (LAMP, 2)]


def test_cancelling_one_item_of_the_rest_leaves_the_others():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
          _box((TAPE, 1), shipment="TAbCdE9fG"))
    [update] = parse_mail(_cancelled((CABLE, 1))).updates
    change = apply_update(parcels, update, NOW)
    # Still "Bestellt", named after what is left: no status, so no news.
    assert (change.parcel, change.old_status) == (parcels[P2], ORDERED)
    assert _state(parcels)[P2] == (ORDERED, [(LAMP, 1)])
    assert name_parts(parcels[P2]) == (TITLES[LAMP], 0)


def test_an_item_cancelled_before_the_first_box_is_in_no_rest():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)))
    [update] = parse_mail(_cancelled((CABLE, 1), when=1)).updates
    apply_update(parcels, update, NOW)
    assert name_parts(parcels[NUMBER]) == (TITLES[TAPE], 1)
    _read(parcels, _box((TAPE, 1), shipment="TAbCdE9fG"),
          _box((LAMP, 1), shipment="TBbCdE9fG", when=3))
    # (no "…P3" waiting for the cable that never comes)
    assert _state(parcels) == {NUMBER: (SHIPPED, [(TAPE, 1)]), P2: (SHIPPED, [(LAMP, 1)])}


def test_a_cancelled_quantity_is_taken_away_piece_by_piece():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 3)), _box((TAPE, 1), shipment="TAbCdE9fG"))
    [update] = parse_mail(_cancelled((CABLE, 2))).updates
    apply_update(parcels, update, NOW)
    assert _state(parcels)[P2] == (ORDERED, [(CABLE, 1)])


def test_cancelling_all_the_rest_holds_cancels_it():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
          _box((TAPE, 1), shipment="TAbCdE9fG"))
    [update] = parse_mail(_cancelled((CABLE, 1), (LAMP, 1))).updates
    change = apply_update(parcels, update, NOW)
    assert (change.parcel, change.old_status) == (parcels[P2], ORDERED)
    assert parcels[P2].status is ParcelStatus.CANCELLED
    assert parcels[NUMBER].status is SHIPPED


def test_a_cancellation_of_what_is_shipped_changes_nothing():
    # (what is on its way comes anyway)
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment="TAbCdE9fG"))
    [update] = parse_mail(_cancelled((TAPE, 1))).updates
    assert apply_update(parcels, update, NOW) is None
    assert _state(parcels) == {NUMBER: (SHIPPED, [(TAPE, 1)]), P2: (ORDERED, [(CABLE, 1)])}


def test_the_same_cancellation_twice_changes_nothing_more():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 2), (LAMP, 1)),
          _box((TAPE, 1), shipment="TAbCdE9fG"))
    [update] = parse_mail(_cancelled((LAMP, 1))).updates
    apply_update(parcels, update, NOW)
    assert apply_update(parcels, update, NOW) is None
    assert _state(parcels)[P2] == (ORDERED, [(CABLE, 2)])


def test_without_article_numbers_the_title_names_the_item_cancelled():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
          _box((TAPE, 1), shipment="TAbCdE9fG"))
    change = apply_update(parcels, _cancel(TITLES[CABLE][:20] + "…"), NOW)
    assert change.parcel is parcels[P2]
    assert _state(parcels)[P2] == (ORDERED, [(LAMP, 1)])


def test_without_article_numbers_a_title_of_more_items_cancels_nothing():
    # Which further items are cancelled is not told.
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
          _box((TAPE, 1), shipment="TAbCdE9fG"))
    assert apply_update(parcels, _cancel(f"{TITLES[CABLE]} und 1 weiterer Artikel"), NOW) is None
    assert _state(parcels)[P2] == (ORDERED, [(CABLE, 1), (LAMP, 1)])


def test_without_article_numbers_a_title_two_items_begin_with_cancels_nothing():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
          _box((TAPE, 1), shipment="TAbCdE9fG"))
    assert apply_update(parcels, _cancel("Beispiel-…"), NOW) is None
    assert parcels[P2].status is ORDERED


def test_cancelling_the_one_item_of_the_rest_by_its_title_cancels_it():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment="TAbCdE9fG"))
    change = apply_update(parcels, _cancel(TITLES[CABLE]), NOW)
    assert change.parcel is parcels[P2]
    assert parcels[P2].status is ParcelStatus.CANCELLED
    assert parcels[NUMBER].status is SHIPPED


def test_a_copy_of_a_cancellation_of_some_pieces_takes_nothing_more():
    # (a copy forwarded by hand: another message id, the same mail)
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 2)), _box((TAPE, 1), shipment="TAbCdE9fG"))
    [update] = parse_mail(_cancelled((CABLE, 1))).updates
    apply_update(parcels, update, NOW)
    assert apply_update(parcels, update, NOW) is None
    assert _state(parcels)[P2] == (ORDERED, [(CABLE, 1)])


def test_a_box_sent_before_a_cancellation_read_after_it_holds_its_own_items():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)), _cancelled((CABLE, 1), when=2),
          _box((TAPE, 1), shipment="TAbCdE9fG", when=1))
    assert _state(parcels) == {NUMBER: (SHIPPED, [(TAPE, 1)]), P2: (ORDERED, [(LAMP, 1)])}


def test_a_copy_of_the_orders_mail_read_late_brings_back_nothing_cancelled():
    parcels: dict = {}
    _read(
        parcels,
        _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
        _cancelled((CABLE, 1), when=1),
        _box((TAPE, 1), shipment="TAbCdE9fG", when=2),
        _box((LAMP, 1), shipment="TBbCdE9fG", when=3),
        _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
    )
    assert _state(parcels) == {NUMBER: (SHIPPED, [(TAPE, 1)]), P2: (SHIPPED, [(LAMP, 1)])}


def test_a_cancellation_naming_the_order_twice_lists_no_items():
    # The same items may be listed under each mention: the title tells the item.
    msg = _cancelled((CABLE, 1))
    twice = _msg((ORDER, _items((CABLE, 1))), (ORDER, _items((CABLE, 1))), when=DAY[2],
                 subject=msg["Subject"])
    twice.replace_header("From", msg["From"])
    [update] = parse_mail(twice).updates
    assert update.items == () and update.title


def test_a_cancellation_naming_the_order_in_its_head_lists_the_items_below():
    msg = _cancelled((CABLE, 1), html_head=f"<p>Bestellnr. {ORDER}</p>")
    [update] = parse_mail(msg).updates
    assert [(i.article_id, i.quantity) for i in update.items] == [(CABLE, 1)]


# ----- what a box holds -----
def test_a_box_with_an_article_the_order_does_not_list_leaves_nothing():
    # (the two mails do not tell the articles alike: what is left is not known for sure)
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)),
          _box((TAPE, 1), (LAMP, 1), shipment="TAbCdE9fG"))
    assert list(parcels) == [NUMBER]


def test_an_order_a_carriers_number_was_told_for_is_split_by_its_first_box():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)))
    day = parcels[NUMBER].result.eta_date
    apply_update(parcels, _carrier_mail(day, ParcelStatus.PRE_TRANSIT), NOW)
    assert parcels[NUMBER].tracking_ref == "00340434161234567890"
    _read(parcels, _box((TAPE, 1), shipment="TAbCdE9fG"))
    rest = parcels[P2]
    assert _state(parcels)[P2] == (ORDERED, [(CABLE, 1)])
    # (the carrier's number and what it told are the box's)
    assert rest.tracking_ref is None
    assert [e.text for e in rest.result.events] == ["Bestellt"]


def test_the_orders_mail_read_late_in_gift_mode_leaves_a_gift():
    parcels: dict = {}
    _read(parcels, _box((TAPE, 1), shipment="TAbCdE9fG"))
    for update in parse_mail(_ordered((TAPE, 1), (CABLE, 1))).updates:
        apply_update(parcels, update, NOW, gift=True)
    assert parcels[P2].gift


def test_a_delivery_without_id_never_goes_to_the_rest():
    # Two boxes of one article and a rest of it: the delivery is one of the boxes', which
    # one is not told. What is not shipped yet is never delivered.
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 3)), _box((TAPE, 1), shipment="TAbCdE9fG"),
          _box((TAPE, 1), shipment="TBbCdE9fG", when=2))
    assert _state(parcels)[P3] == (ORDERED, [(TAPE, 1)])
    _read(parcels, _box((TAPE, 1), shipment=None, when=3, subject="Zugestellt: „Anderes…“"))
    assert parcels[P3].status is ORDERED


def test_a_box_is_named_after_its_first_item_with_a_name():
    parcels: dict = {}
    items = (OrderItem(TAPE, 1), OrderItem(CABLE, 1, "Kabel"))
    apply_update(parcels, MailUpdate(NUMBER, "amazon", SHIPPED, NOW, title="Beispiel…",
                                     items=items), NOW)
    assert parcels[NUMBER].name == "Kabel"


# ----- a postponed delivery, a closed rest, an item without a name -----
def _postponed(*articles: OrderItem) -> MailUpdate:
    """Amazon's "Versuchte Zustellung" without its id: it is about a box on its way."""
    return MailUpdate(NUMBER, "amazon", SHIPPED, NOW, title="Anderer Artikel", postponed=True,
                      status_text="Zustellung versucht", items=articles)


def test_a_postponed_delivery_without_id_stays_with_the_box_not_the_rest():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment="TAbCdE9fG"))
    apply_update(parcels, _postponed(), NOW)
    assert parcels[NUMBER].result.status_text == "Zustellung versucht"
    assert parcels[P2].status is ORDERED


def test_a_postponed_delivery_of_a_piece_goes_to_the_box_of_that_article():
    # "Menge: 2" as 1 + 1: the box and the rest both hold the article.
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 2),), _box((TAPE, 1), shipment="TAbCdE9fG"))
    apply_update(parcels, _postponed(OrderItem(TAPE, 1, TITLES[TAPE])), NOW)
    assert parcels[NUMBER].result.status_text == "Zustellung versucht"
    assert parcels[P2].status is ORDERED


def test_a_rest_closed_without_a_delivery_mail_is_split_by_its_next_box():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1), (LAMP, 1)),
          _box((TAPE, 1), shipment="TAbCdE9fG"))
    close_unconfirmed(parcels[P2], NOW)
    _read(parcels, _box((CABLE, 1), shipment="TBbCdE9fG", when=3))
    assert _state(parcels)[P2] == (SHIPPED, [(CABLE, 1)])
    # (what is left stays closed as it was: nothing tells it came, nor that it did not)
    assert _state(parcels)[P3] == (ParcelStatus.DELIVERED, [(LAMP, 1)])
    assert parcels[P3].assumed_delivered


def test_the_rest_is_named_after_its_first_item_with_a_name():
    parcels: dict = {}
    items = (OrderItem(TAPE, 1, TITLES[TAPE]), OrderItem(CABLE, 1), OrderItem(LAMP, 1, "Lampe"))
    ordered = MailUpdate(NUMBER, "amazon", ORDERED, NOW - timedelta(days=1), items=items)
    box = MailUpdate(NUMBER, "amazon", SHIPPED, NOW, title="Beispiel…", shipment_id="TAbCdE9fG",
                     items=items[:1])
    for update in (ordered, box):
        apply_update(parcels, update, NOW)
    assert parcels[P2].name == "Lampe"
    nameless = (OrderItem(TAPE, 1, TITLES[TAPE]), OrderItem(CABLE, 1))
    parcels = {}
    for update in (replace(ordered, items=nameless), replace(box, items=nameless[:1])):
        apply_update(parcels, update, NOW)
    assert parcels[P2].name == "Amazon-Sendung"


# ----- stored and told -----
def test_the_rest_is_stored_and_read_back():
    parcels: dict = {}
    _read(parcels, _ordered((TAPE, 1), (CABLE, 1)), _box((TAPE, 1), shipment="TAbCdE9fG"))
    rest = parcels[P2]
    again = Parcel.from_dict(rest.to_dict())
    assert again.items == [OrderItem(CABLE, 1, TITLES[CABLE])]
    assert again.status is ORDERED


async def test_the_rest_is_added_without_a_push(hass, hass_storage, freezer):
    freezer.move_to(datetime(2026, 10, 10, 9, 0, tzinfo=BERLIN))
    await hass.config.async_set_time_zone("Europe/Berlin")
    calls = async_mock_service(hass, "notify", "send_message")
    changed = async_capture_events(hass, EVENT_STATUS_CHANGED)
    added = async_capture_events(hass, EVENT_PARCEL_ADDED)
    coord = await _coordinator(hass, hass_storage, [])
    await _refresh(hass, coord)
    await _start(hass)
    # (the box's first mail is its delivery: a status that is pushed)
    delivered = _box((TAPE, 1), shipment="TAbCdE9fG", subject="Zugestellt: „Beispiel…“")
    for n, msg in enumerate((_ordered((TAPE, 1), (CABLE, 1)), delivered)):
        msg["Message-ID"] = f"<split{n}@example.org>"
        assert (await coord.async_import_raw_mail(msg.as_bytes()))["result"] == "recognized"
    await hass.async_block_till_done()
    await coord.async_shutdown()
    # One box, one push. The rest is new, so it is added, but "Bestellt" is its first
    # status and no news.
    assert [(e.data["number"], e.data["new_status"]) for e in changed] == [
        (NUMBER, "delivered")
    ]
    assert len(calls) == 1
    assert [e.data["number"] for e in added] == [NUMBER, P2]

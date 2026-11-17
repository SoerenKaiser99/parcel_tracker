"""The items of an Amazon order: article number and quantity, kept per entry.

Amazon's mails from "Bestellt" to "In Zustellung" list each item in their HTML part: a
picture and the name, both linked to the item's page (behind Amazon's redirect,
…/dp/<article number>), and its quantity ("Menge: 1"). The text part names no article
number. An entry keeps the items of the newest mail that listed some; what it does with
them comes later. All values here are invented.
"""

from datetime import datetime
from email import policy
from email.message import EmailMessage
from urllib.parse import quote

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.const import MAX_ORDER_ITEMS
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.models import OrderItem, Parcel

ORDER = "999-9156534-2587125"
OTHER_ORDER = "999-1234567-7654321"
NUMBER = "AMZ99991565342587125"
FIRST, SECOND = "B0BEISPIEL", "B0MUSTER01"
TITLE = "Beispiel-Maßband 5 m mit Feststellknopf und Gürtelclip"
SELLER = "Verkauf durch Beispielhandel e.K., Händler & Versand aus Deutschland"
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=BERLIN)


def _redirect(target: str) -> str:
    return f"https://www.amazon.de/gp/r.html?C=X&amp;U={quote(target, safe='')}&amp;H=X"


def _page(asin: str) -> str:
    return _redirect(f"https://www.amazon.de/dp/{asin}?ref_=pe_999_{asin}_i_fed_asin_title")


def _item(asin: str | None, quantity: int = 1, title: str = TITLE, seller: str | None = SELLER,
          picture: bool = True, href: str | None = None) -> str:
    """One item as Amazon's HTML part lists it."""
    link = href or (_page(asin) if asin else "https://www.amazon.de/…")
    shown = f"{title[:24]}..."
    return (
        (f'<tr><td><a href="{link}"><img src="x.jpg" alt="{title}"></a></td></tr>'
         if picture else "")
        + f'<tr><td><a href="{link}">{shown}</a></td></tr>'
        + (f"<tr><td>{seller}</td></tr>" if seller else "")
        + "<tr><td>Zustand: Neu</td></tr>"
        + f"<tr><td>Menge: {quantity}</td></tr><tr><td>9,99 €</td></tr>"
    )


def _msg(*blocks: tuple[str, tuple[str, ...]], html: bool = True,
         subject: str = "Versendet: „Beispiel-Maßband 5 m...“", text_items: str = "",
         links: tuple[str, ...] = (), when: str = "Sun, 11 Oct 2026 08:00:00 +0200",
         html_head: str = "") -> EmailMessage:
    """An Amazon mail: per block an order and the HTML of its items; ``html_head`` stands
    above them in the HTML part only."""
    blocks = blocks or ((ORDER, (_item(FIRST),)),)
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "Amazon.de <versandbestaetigung@amazon.de>"
    msg["Subject"] = subject
    msg["Date"] = when
    text = "\n".join(f"Bestellnr. {order}\n* {TITLE}\n{text_items}" for order, _ in blocks)
    msg.set_content(f"Hallo Max,\n\nAnkunft morgen\n\n{text}")
    if html:
        rows = "".join(
            f"<tr><td>Bestellnr. &#x202B;{order}</td></tr>" + "".join(items)
            for order, items in blocks
        )
        tracking = "".join(f'<a href="{href}">Lieferung verfolgen</a>' for href in links)
        msg.add_alternative(
            f"<html><body><p>Hallo Max,</p>{tracking}{html_head}<table>{rows}</table>"
            "</body></html>",
            subtype="html",
        )
    return msg


def _items(msg: EmailMessage) -> list[tuple[OrderItem, ...]]:
    return [u.items for u in parse_mail(msg).updates]


# ----- reading the items -----
def test_an_item_with_its_article_number_quantity_and_full_title():
    assert _items(_msg()) == [(OrderItem(FIRST, 1, TITLE),)]


def test_each_item_of_a_box_with_its_own_quantity_and_title():
    # (its picture and its name both link to its page: one item, not two)
    msg = _msg((ORDER, (_item(FIRST, 2), _item(SECOND, 1, "Beispiel-Kabel 2 m", None))))
    assert _items(msg) == [(OrderItem(FIRST, 2, TITLE), OrderItem(SECOND, 1, "Beispiel-Kabel 2 m"))]


def test_without_a_picture_the_title_is_the_links_text():
    # (Amazon cuts it short: the name of the picture is the one in full)
    [[item]] = _items(_msg((ORDER, (_item(FIRST, picture=False),))))
    assert item.title == f"{TITLE[:24]}..."


def test_a_long_title_is_cut_like_every_title():
    long = "Beispiel-Werkzeugkoffer " + "mit Zubehör " * 10
    [[item]] = _items(_msg((ORDER, (_item(FIRST, title=long),))))
    assert len(item.title) == 60 and item.title.endswith("…")


@pytest.mark.parametrize(
    "path",
    ["/dp/B0BEISPIEL", "/Beispiel-Massband/dp/B0BEISPIEL/ref=x", "/-/en/dp/B0BEISPIEL",
     "/gp/product/B0BEISPIEL"],
)
def test_the_article_number_behind_other_parts_of_the_path(path):
    href = _redirect(f"https://www.amazon.de{path}")
    [[item]] = _items(_msg((ORDER, (_item(None, href=href),))))
    assert item.article_id == FIRST


@pytest.mark.parametrize(
    "href",
    [
        "http://www.amazon.de/dp/B0BEISPIEL",  # not https
        "https://www.example.org/dp/B0BEISPIEL",  # not Amazon
        "https://www.amazon.de/gp/r.html?U=" + quote(_page(FIRST), safe=""),  # redirect twice
        "https://www.amazon.de/dp/B0BEISPIEL123",  # no article number
        "https://www.amazon.de/a/b/c/d/dp/B0BEISPIEL",  # more than three parts in front
        "https://www.amazon.de/gp/your-account/order-history",
    ],
)
def test_only_a_link_to_an_items_page_at_amazon_names_its_article_number(href):
    [[item]] = _items(_msg((ORDER, (_item(None, href=href),))))
    assert item.article_id is None and item.quantity == 1


def test_an_item_of_quantity_zero_is_none():
    msg = _msg((ORDER, (_item(FIRST, 0), _item(SECOND))))
    assert _items(msg) == [(OrderItem(SECOND, 1, TITLE),)]


def test_a_quantity_of_more_than_four_digits_is_none_and_the_mail_still_counts():
    # (``int`` refuses more than 4300 digits: the mail must not fail on it)
    msg = _msg((ORDER, (_item(FIRST), _item(SECOND, "1" * 5000))))
    [update] = parse_mail(msg).updates
    assert update.items == (OrderItem(FIRST, 1, TITLE),)


def test_only_an_asin_is_an_article_number():
    # A line that begins with the mark but is no ASIN (here in a mail without HTML part).
    msg = _msg(html=False, text_items="\ue000Beispielweg 12\nMenge: 1\n")
    assert _items(msg) == [(OrderItem(None, 1),)]


def test_a_mention_without_items_adds_none():
    # The HTML part names the order once more in its head, without items: the text part
    # names it once, so the mentions are taken by the order, and the head adds nothing.
    msg = _msg(html_head=f"<p>Bestellnr. {ORDER}</p>")
    assert _items(msg) == [(OrderItem(FIRST, 1, TITLE),)]


def test_each_order_of_a_mail_has_its_own_items():
    msg = _msg((ORDER, (_item(FIRST),)), (OTHER_ORDER, (_item(SECOND),)))
    assert [[i.article_id for i in items] for items in _items(msg)] == [[FIRST], [SECOND]]


def test_the_orders_mail_gives_every_day_all_items_of_the_order():
    # The order's mail names the order once per day: all of it is one entry.
    msg = _msg((ORDER, (_item(FIRST),)), (ORDER, (_item(SECOND),)),
               subject="Bestellt: „Beispiel-Maßband 5 m...“")
    assert [[i.article_id for i in items] for items in _items(msg)] == [[FIRST, SECOND]] * 2


def test_a_mail_without_html_part_has_items_without_article_number():
    msg = _msg(html=False, text_items=f"{SELLER}\nMenge: 3\n")
    assert _items(msg) == [(OrderItem(None, 3),)]


def test_an_order_that_came_along_in_another_orders_box_takes_none_of_its_items():
    tracking = _redirect(
        f"https://www.amazon.de/progress-tracker/package?orderId={OTHER_ORDER}"
        "&shipmentId=TAbCdE9fG"
    )
    updates = parse_mail(_msg(links=(tracking,))).updates
    assert [(u.along, len(u.items)) for u in updates] == [(False, 1), (True, 0)]


def test_a_box_mail_naming_an_order_twice_in_another_order_gives_no_items():
    # Two boxes of one order, and the HTML part names one order more than the text part:
    # which items are whose box is not told, so neither takes any.
    msg = _msg((ORDER, (_item(FIRST),)), (ORDER, (_item(SECOND),)),
               html_head=f"<p>Bestellnr. {OTHER_ORDER}</p>")
    assert _items(msg) == [(), ()]


def test_at_most_max_order_items():
    items = tuple(_item(f"B0{n:08d}") for n in range(MAX_ORDER_ITEMS + 5))
    assert len(_items(_msg((ORDER, items)))[0]) == MAX_ORDER_ITEMS


# ----- keeping them -----
def test_an_entry_keeps_the_items_of_the_newest_mail_that_lists_some():
    parcels: dict = {}
    ordered = _msg((ORDER, (_item(FIRST), _item(SECOND))), subject="Bestellt: „Beispiel…“")
    for update in parse_mail(ordered).updates:
        apply_update(parcels, update, NOW)
    assert [i.article_id for i in parcels[NUMBER].items] == [FIRST, SECOND]
    # The box's mail names the box's items: they hold from now on.
    for update in parse_mail(_msg()).updates:
        apply_update(parcels, update, NOW)
    assert [i.article_id for i in parcels[NUMBER].items] == [FIRST]
    # A mail that lists none ("Zugestellt") leaves them as they are.
    for update in parse_mail(_msg((ORDER, ()), subject="Zugestellt: „Beispiel…“")).updates:
        apply_update(parcels, update, NOW)
    assert [i.article_id for i in parcels[NUMBER].items] == [FIRST]


def test_a_mail_sent_before_the_items_were_told_changes_nothing():
    # The order's mail read after the box's: the box must not get the items of the order.
    parcels: dict = {}
    box = _msg(when="Mon, 12 Oct 2026 08:00:00 +0200")
    ordered = _msg((ORDER, (_item(FIRST), _item(SECOND))), subject="Bestellt: „Beispiel…“",
                   when="Fri, 09 Oct 2026 08:00:00 +0200")
    for update in (*parse_mail(box).updates, *parse_mail(ordered).updates):
        apply_update(parcels, update, NOW)
    entry = parcels[NUMBER]
    assert [i.article_id for i in entry.items] == [FIRST]
    assert entry.items_at == datetime(2026, 10, 12, 8, 0, tzinfo=BERLIN)
    assert Parcel.from_dict(entry.to_dict()).items_at == entry.items_at


def test_a_later_mail_about_the_whole_order_leaves_a_boxs_items():
    # The box (with its id) holds FIRST; a mail about the whole order sent after it lists
    # FIRST and SECOND: the box must not take the items of the order.
    tracking = _redirect(
        f"https://www.amazon.de/progress-tracker/package?orderId={ORDER}&shipmentId=DAbCdE9fG"
    )
    parcels: dict = {}
    for update in parse_mail(_msg(links=(tracking,))).updates:
        apply_update(parcels, update, NOW)
    ordered = _msg((ORDER, (_item(FIRST), _item(SECOND))), subject="Bestellt: „Beispiel…“",
                   when="Mon, 12 Oct 2026 08:00:00 +0200")
    for update in parse_mail(ordered).updates:
        apply_update(parcels, update, NOW)
    assert parcels[NUMBER].shipment_ids == ["DAbCdE9fG"]
    assert [i.article_id for i in parcels[NUMBER].items] == [FIRST]


def test_keeping_items_alone_is_no_change():
    parcels: dict = {}
    for update in parse_mail(_msg()).updates:
        apply_update(parcels, update, NOW)
    again = parse_mail(_msg((ORDER, (_item(SECOND),)))).updates[0]
    assert apply_update(parcels, again, NOW) is None
    assert [i.article_id for i in parcels[NUMBER].items] == [SECOND]


def test_items_are_stored_and_read_back():
    parcel = Parcel(NUMBER, "amazon", "mail", None, NOW, NOW,
                    items=[OrderItem(FIRST, 2, TITLE), OrderItem(None, 1)])
    assert Parcel.from_dict(parcel.to_dict()).items == parcel.items


def test_an_entry_stored_by_an_older_version_has_no_items():
    data = Parcel(NUMBER, "amazon", "mail", None, NOW, NOW).to_dict()
    del data["items"], data["items_at"]
    parcel = Parcel.from_dict(data)
    assert parcel.items == [] and parcel.items_at is None


def test_unreadable_stored_items_are_dropped():
    data = Parcel(NUMBER, "amazon", "mail", None, NOW, NOW).to_dict()
    data["items"] = [
        {"article_id": FIRST, "quantity": 1},
        {"article_id": SECOND, "quantity": 0},
        {"article_id": SECOND, "quantity": "2"},
        {"article_id": 7, "quantity": 1, "title": ["x"]},
        "B0BEISPIEL",
        *({"article_id": None, "quantity": 1} for _ in range(MAX_ORDER_ITEMS)),
    ]
    items = Parcel.from_dict(data).items
    # (an unreadable value is dropped from its item: the quantity of the fourth holds)
    assert items[:2] == [OrderItem(FIRST, 1), OrderItem(None, 1)]
    # Of the first MAX_ORDER_ITEMS stored, three are unreadable.
    assert len(items) == MAX_ORDER_ITEMS - 3

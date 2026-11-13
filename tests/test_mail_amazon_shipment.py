"""Amazon's shipment id: read from the link to the tracking page and kept with the order.

Amazon's mails from "Versendet" on link to the shipment's tracking page
(https://www.amazon.de/progress-tracker/package?orderId=…&shipmentId=…), behind Amazon's
own redirect: since about March 2025, in the plain layout of "In Zustellung" since about
August 2025. The id is the same in every mail about that box: it tells which entry of an
order a mail goes to. Most mails are built here; the fixtures 181-191 are real sequences
whose links the anonymiser kept as invented ones (the same id for the same box).
"""

from datetime import datetime, timedelta
from email import policy
from email.message import EmailMessage
from urllib.parse import quote

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import (
    MANUAL_TEXT,
    apply_update,
    close_unconfirmed,
    mark_received,
)
from custom_components.parcel_tracker.mail.base import ATTEMPT_TEXT, MailUpdate
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import FIXTURES, load_mail

ORDER = "999-9156534-2587125"
OTHER_ORDER = "999-1234567-7654321"
NUMBER = "AMZ99991565342587125"
SHIPMENT = "TAbCdE9fG"
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=BERLIN)


def _page(order: str = ORDER, shipment: str = SHIPMENT) -> str:
    return (
        "https://www.amazon.de/progress-tracker/package?_encoding=UTF8"
        f"&orderId={order}&shipmentId={shipment}&packageIndex=0&vt=NOTIFICATIONS"
    )


def _redirect(target: str) -> str:
    return f"https://www.amazon.de/gp/r.html?C=X&amp;T=C&amp;U={quote(target, safe='')}&amp;H=X"


def _msg(
    *hrefs: str,
    subject: str = "Versendet: „Beispiel-Maßband 5...“",
    orders: tuple[str, ...] = (ORDER,),
    sender: str = "versandbestaetigung@amazon.de",
    when: str = "Sun, 11 Oct 2026 08:00:00 +0200",
    items: tuple[str, ...] = (),
) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"Amazon.de <{sender}>"
    msg["Subject"] = subject
    msg["Date"] = when
    items = items or ("Beispiel-Maßband 5 m",) * len(orders)
    lines = [f"Bestellnr. {order}\n* {item}\n" for order, item in zip(orders, items, strict=True)]
    msg.set_content("Hallo Max,\n\n" + "\n".join(lines))
    links = "".join(f'<a href="{href}">Paket verfolgen</a>' for href in hrefs)
    msg.add_alternative(f"<html><body><p>Hallo Max,</p>{links}</body></html>", subtype="html")
    return msg


def _updates(msg: EmailMessage):
    return parse_mail(msg).updates


def test_the_shipment_id_is_read_from_amazons_redirect():
    [update] = _updates(_msg(_redirect(_page())))
    assert update.number == NUMBER
    assert update.status is ParcelStatus.IN_TRANSIT
    assert update.shipment_id == SHIPMENT


def test_a_direct_link_to_the_tracking_page_counts_as_well():
    [update] = _updates(_msg(_page().replace("&", "&amp;")))
    assert update.shipment_id == SHIPMENT


def test_a_mail_without_the_link_has_no_shipment_id():
    [update] = _updates(_msg())
    assert update.shipment_id is None


@pytest.mark.parametrize(
    "href",
    [
        _redirect(_page()).replace("https://", "http://", 1),
        _redirect(_page().replace("https://", "http://")),
        _redirect(_page()).replace("www.amazon.de", "www.amazon.de.example.com", 1),
        _redirect(_page().replace("www.amazon.de", "www.amazon.com")),
        _redirect(_page().replace("/progress-tracker/package", "/gp/your-account/order-details")),
        _redirect(_redirect(_page()).replace("&amp;", "&")),
        _redirect(_page(shipment="TAb-dE9fG")),
        _redirect(_page(shipment="TAb")),
        _redirect(_page(order="999-9156534")),
        _redirect(_page(order=OTHER_ORDER)),
    ],
    ids=[
        "redirect-over-http",
        "page-over-http",
        "other-host",
        "other-amazon",
        "other-page",
        "redirect-in-redirect",
        "id-with-other-characters",
        "id-too-short",
        "order-cut",
        "order-the-mail-does-not-name",
    ],
)
def test_no_other_link_gives_a_shipment_id(href):
    [update] = _updates(_msg(href))
    assert update.shipment_id is None


def test_each_order_of_a_mail_takes_the_id_its_link_names():
    msg = _msg(
        _redirect(_page(OTHER_ORDER, "UhIjKl9mN")),
        _redirect(_page()),
        orders=(ORDER, OTHER_ORDER),
    )
    assert {u.number: u.shipment_id for u in _updates(msg)} == {
        NUMBER: SHIPMENT,
        "AMZ99912345677654321": "UhIjKl9mN",
    }


def test_the_first_id_of_an_order_counts():
    [update] = _updates(_msg(_redirect(_page()), _redirect(_page(shipment="UhIjKl9mN"))))
    assert update.shipment_id == SHIPMENT


def test_an_order_named_as_two_shipments_of_one_mail_takes_no_id():
    # Which of the two links is whose is not told: the items tell the two boxes apart.
    msg = _msg(
        _redirect(_page()),
        _redirect(_page(shipment="UhIjKl9mN")),
        _redirect(_page(OTHER_ORDER, "VwXyZa9bC")),
        orders=(ORDER, ORDER, OTHER_ORDER),
        items=("Alphamarke Trinkflasche 750 ml", "Betamarke Kabel 2 m", "Gammamarke Seife"),
    )
    updates = _updates(msg)
    assert [(u.number, u.title, u.shipment_id) for u in updates] == [
        (NUMBER, "Alphamarke Trinkflasche 750 ml", None),
        (NUMBER, "Betamarke Kabel 2 m", None),
        ("AMZ99912345677654321", "Gammamarke Seife", "VwXyZa9bC"),
    ]
    parcels: dict = {}
    for update in updates:
        apply_update(parcels, update, NOW)
    assert parcels[NUMBER].name == "Alphamarke Trinkflasche 750 ml"
    assert parcels[f"{NUMBER}P2"].name == "Betamarke Kabel 2 m (2)"


def _apply(parcels: dict, msg: EmailMessage):
    return [apply_update(parcels, update, NOW) for update in _updates(msg)]


def test_the_order_keeps_the_id_once_through_all_its_mails():
    parcels: dict = {}
    _apply(parcels, _msg(_redirect(_page())))
    _apply(
        parcels,
        _msg(
            _redirect(_page()),
            subject="In Zustellung: „Beispiel-Maßband 5...“",
            sender="shipment-tracking@amazon.de",
        ),
    )
    _apply(
        parcels,
        _msg(
            _redirect(_page()),
            subject="Zugestellt: „Beispiel-Maßband 5...“",
            sender="order-update@amazon.de",
        ),
    )
    assert parcels[NUMBER].status is ParcelStatus.DELIVERED
    assert parcels[NUMBER].shipment_ids == [SHIPMENT]


def test_an_order_without_the_link_keeps_no_id():
    parcels: dict = {}
    _apply(parcels, _msg())
    assert parcels[NUMBER].shipment_ids == []


def test_a_further_id_of_the_same_item_is_a_further_shipment():
    # ("2 x …": one item, sent in two boxes on two days)
    parcels: dict = {}
    _apply(parcels, _msg(_redirect(_page())))
    later = _msg(_redirect(_page(shipment="UhIjKl9mN")), when="Wed, 14 Oct 2026 10:00:00 +0200")
    [change] = _apply(parcels, later)
    assert change.created and change.parcel.number == f"{NUMBER}P2"
    assert parcels[NUMBER].shipment_ids == [SHIPMENT]
    assert parcels[f"{NUMBER}P2"].shipment_ids == ["UhIjKl9mN"]


# ----- one entry per shipment: the id decides, the title only without one -----
FIRST, SECOND, THIRD, FOURTH = "TAbCdE9fG", "TuVwXy9zA", "TbCdEf9gH", "TcDeFg9hI"
ORDERED = ParcelStatus.PRE_TRANSIT
SHIPPED = ParcelStatus.IN_TRANSIT
OUT = ParcelStatus.OUT_FOR_DELIVERY
DELIVERED = ParcelStatus.DELIVERED
# Made-up items; within its first 15 characters (``title_key``) each is its own.
ALPHA = "Alphamarke Trinkflasche 750 ml"
BETA = "Betamarke Kabel 2 m"
GAMMA = "Gammamarke Seife"
DELTA = "Deltamarke Notizblock"


def _mail(
    status, title: str | None, shipment: str | None = None, hour: int = 9, **more
) -> MailUpdate:
    return MailUpdate(
        NUMBER, "amazon", status, NOW.replace(hour=hour), title=title, shipment_id=shipment, **more
    )


def _run(*updates: MailUpdate, parcels: dict | None = None) -> dict:
    parcels = {} if parcels is None else parcels
    for update in updates:
        apply_update(parcels, update, NOW)
    return parcels


def _boxes(parcels: dict) -> dict:
    return {n: (p.name, p.status, p.shipment_ids) for n, p in parcels.items()}


def test_two_boxes_of_one_item_stay_apart_through_all_their_mails():
    parcels = _run(
        _mail(ORDERED, f"{ALPHA}…"),
        _mail(SHIPPED, f"{ALPHA}…", FIRST, 10),
        _mail(SHIPPED, f"{ALPHA}…", SECOND, 11),
        _mail(OUT, f"{ALPHA}…", SECOND, 12),
        _mail(DELIVERED, f"{ALPHA}…", SECOND, 13),
    )
    assert _boxes(parcels) == {
        NUMBER: (f"{ALPHA}…", SHIPPED, [FIRST]),
        f"{NUMBER}P2": (f"{ALPHA}… (2)", DELIVERED, [SECOND]),
    }


def test_the_first_box_takes_over_the_ordered_entry_and_its_name():
    # The order's mail names its first item; the box that comes first holds another.
    parcels = _run(
        _mail(ORDERED, ALPHA),
        _mail(SHIPPED, "Betamarke Kab… und 1 weiterer Artikel", FIRST, 10),
        _mail(SHIPPED, "Alphamarke Tri…", SECOND, 11),
        _mail(DELIVERED, "Betamarke Kab… und 1 weiterer Artikel", FIRST, 12),
    )
    assert _boxes(parcels) == {
        NUMBER: ("Betamarke Kab… und 1 weiterer Artikel", DELIVERED, [FIRST]),
        f"{NUMBER}P2": ("Alphamarke Tri… (2)", SHIPPED, [SECOND]),
    }


@pytest.mark.parametrize("shipped", ["Alphamarke Trink…", "Alphamarke…"])
def test_the_ordered_entry_keeps_its_name_for_a_box_of_its_item(shipped):
    # (the subject may cut the title after its first word)
    parcels = _run(_mail(ORDERED, f"{ALPHA}, Modell Z9"), _mail(SHIPPED, shipped, FIRST, 10))
    assert parcels[NUMBER].name == f"{ALPHA}, Modell Z9"


def test_a_further_box_whose_mail_names_no_item_is_named_after_the_shop():
    parcels = _run(_mail(SHIPPED, ALPHA, FIRST), _mail(DELIVERED, None, SECOND, 10))
    assert parcels[f"{NUMBER}P2"].name == "Amazon-Sendung (2)"
    assert parcels[NUMBER].status is SHIPPED


def test_the_shop_name_gives_way_once_a_mail_names_the_item():
    # (the box's "Versendet" mail is read after its "Zugestellt" mail)
    parcels = _run(
        _mail(SHIPPED, ALPHA, FIRST),
        _mail(DELIVERED, None, SECOND, 10),
        _mail(SHIPPED, BETA, SECOND, 8),
    )
    assert _boxes(parcels)[f"{NUMBER}P2"] == (f"{BETA} (2)", DELIVERED, [SECOND])


def test_a_name_typed_in_for_a_box_without_item_stays():
    parcels = _run(_mail(SHIPPED, ALPHA, FIRST), _mail(DELIVERED, None, SECOND, 10))
    box = parcels[f"{NUMBER}P2"]
    box.name, box.name_manual = "Mein Paket", True
    _run(_mail(SHIPPED, BETA, SECOND, 8), parcels=parcels)
    assert box.name == "Mein Paket"
    assert box.mail_title == BETA


def test_a_name_typed_in_stays_when_the_first_box_takes_over():
    parcels = _run(_mail(ORDERED, ALPHA))
    parcels[NUMBER].name, parcels[NUMBER].name_manual = "Mein Paket", True
    _run(_mail(SHIPPED, BETA, FIRST, 10), parcels=parcels)
    assert parcels[NUMBER].name == "Mein Paket"
    assert parcels[NUMBER].mail_title == BETA


def test_a_box_whose_title_changes_stays_one_entry():
    # Without the id a "Versendet" mail of another item would be a further shipment.
    parcels = _run(
        _mail(SHIPPED, "Alphamarke Tri… und 1 weiterer Artikel", FIRST),
        _mail(SHIPPED, "Betamarke Kab… und 2 weitere Artikel", FIRST, 10),
    )
    assert _boxes(parcels) == {
        NUMBER: ("Alphamarke Tri… und 1 weiterer Artikel", SHIPPED, [FIRST]),
    }


def test_an_attempted_delivery_of_a_new_box_is_an_entry_of_its_own():
    # (without the id, a postponed delivery is never a further shipment)
    parcels = _run(
        _mail(SHIPPED, ALPHA, FIRST),
        _mail(OUT, ALPHA, FIRST, 10),
        _mail(SHIPPED, BETA, SECOND, 11, postponed=True, status_text=ATTEMPT_TEXT),
    )
    assert _boxes(parcels) == {
        NUMBER: (ALPHA, OUT, [FIRST]),
        f"{NUMBER}P2": (f"{BETA} (2)", SHIPPED, [SECOND]),
    }
    assert parcels[f"{NUMBER}P2"].result.status_text == ATTEMPT_TEXT


def test_a_mail_without_a_title_finds_its_box_by_the_id():
    # (an old "Zugestellt" mail names no item: it went to the first open entry)
    parcels = _run(
        _mail(SHIPPED, ALPHA, FIRST),
        _mail(SHIPPED, BETA, SECOND, 10),
        _mail(DELIVERED, None, SECOND, 11),
    )
    assert parcels[NUMBER].status is SHIPPED
    assert parcels[f"{NUMBER}P2"].status is DELIVERED


@pytest.mark.parametrize(
    ("without_id", "with_id"),
    [(ALPHA, "Alphamarke…"), ("Alphamarke…", ALPHA)],
    ids=["mail-cuts-the-title", "entry-has-it-cut"],
)
def test_a_new_id_takes_the_entry_a_mail_without_id_made_for_its_item(without_id, with_id):
    # The two titles differ in their first 15 characters: one only begins the other.
    parcels = _run(_mail(SHIPPED, without_id), _mail(OUT, with_id, FIRST, 10))
    assert _boxes(parcels) == {NUMBER: (without_id, OUT, [FIRST])}


def test_a_new_id_without_a_title_takes_the_open_entry_no_box_was_told_for():
    parcels = _run(
        _mail(SHIPPED, ALPHA, FIRST),
        _mail(SHIPPED, BETA, None, 10),
        _mail(DELIVERED, None, SECOND, 11),
    )
    assert _boxes(parcels) == {
        NUMBER: (ALPHA, SHIPPED, [FIRST]),
        f"{NUMBER}P2": (f"{BETA} (2)", DELIVERED, [SECOND]),
    }


def test_a_further_box_is_its_own_entry_whatever_its_status():
    # (its "Versendet" mail was never read)
    parcels = _run(_mail(SHIPPED, ALPHA, FIRST), _mail(OUT, ALPHA, SECOND, 10))
    assert _boxes(parcels) == {
        NUMBER: (ALPHA, SHIPPED, [FIRST]),
        f"{NUMBER}P2": (f"{ALPHA} (2)", OUT, [SECOND]),
    }


def test_without_ids_the_first_box_takes_over_the_ordered_entry_as_well():
    parcels = _run(
        _mail(ORDERED, ALPHA),
        _mail(SHIPPED, "Betamarke Kab…", None, 10),
        _mail(SHIPPED, "Alphamarke Tri…", None, 11),
    )
    assert _boxes(parcels) == {
        NUMBER: ("Betamarke Kab…", SHIPPED, []),
        f"{NUMBER}P2": ("Alphamarke Tri… (2)", SHIPPED, []),
    }


# ----- a new id while an entry has none (its mails were read without the link) -----
def test_a_new_id_naming_another_item_of_the_box_takes_the_entry_without_id():
    parcels = _run(_mail(SHIPPED, ALPHA), _mail(DELIVERED, BETA, FIRST, 10))
    assert _boxes(parcels) == {NUMBER: (ALPHA, DELIVERED, [FIRST])}


def test_a_new_id_delivers_an_entry_without_id_closed_without_a_delivery_mail():
    parcels = _run(_mail(SHIPPED, ALPHA))
    close_unconfirmed(parcels[NUMBER], NOW)
    _run(_mail(DELIVERED, None, FIRST, 10), parcels=parcels)
    assert _boxes(parcels) == {NUMBER: (ALPHA, DELIVERED, [FIRST])}
    assert not parcels[NUMBER].assumed_delivered


def test_a_new_id_leaves_an_entry_without_id_marked_as_received_as_it_is():
    parcels = _run(_mail(SHIPPED, ALPHA))
    mark_received(parcels[NUMBER], NOW)
    assert apply_update(parcels, _mail(DELIVERED, None, FIRST, 10), NOW) is None
    assert list(parcels) == [NUMBER]
    assert parcels[NUMBER].result.status_text == MANUAL_TEXT


def test_a_new_id_shipping_another_item_is_still_a_further_box():
    parcels = _run(_mail(SHIPPED, ALPHA), _mail(SHIPPED, BETA, FIRST, 10))
    assert _boxes(parcels) == {
        NUMBER: (ALPHA, SHIPPED, []),
        f"{NUMBER}P2": (f"{BETA} (2)", SHIPPED, [FIRST]),
    }


def test_a_new_id_skips_an_entry_with_another_id():
    # The second box's "Versendet" mail came in the old layout, without the link.
    parcels = _run(
        _mail(ORDERED, ALPHA),
        _mail(SHIPPED, "Betamarke Kab…", FIRST, 10),
        _mail(SHIPPED, "Alphamarke…", None, 11),
        _mail(DELIVERED, None, SECOND, 12),
    )
    assert _boxes(parcels) == {
        NUMBER: ("Betamarke Kab…", SHIPPED, [FIRST]),
        f"{NUMBER}P2": ("Alphamarke… (2)", DELIVERED, [SECOND]),
    }


# ----- the number of a further entry -----
@pytest.mark.parametrize("ids", [True, False], ids=["with-ids", "without-ids"])
def test_a_further_box_after_a_removed_entry_in_between_takes_a_free_number(ids):
    first, second, third, fourth = (FIRST, SECOND, THIRD, FOURTH) if ids else (None,) * 4
    parcels = _run(
        _mail(SHIPPED, ALPHA, first),
        _mail(SHIPPED, BETA, second, 10),
        _mail(SHIPPED, GAMMA, third, 11),
    )
    del parcels[f"{NUMBER}P2"]
    _run(_mail(SHIPPED, DELTA, fourth, 12), parcels=parcels)
    assert {n: p.name for n, p in parcels.items()} == {
        NUMBER: ALPHA,
        f"{NUMBER}P3": f"{GAMMA} (3)",
        f"{NUMBER}P4": f"{DELTA} (4)",
    }


@pytest.mark.parametrize("ids", [True, False], ids=["with-ids", "without-ids"])
def test_a_further_box_after_the_removed_first_entry_takes_a_free_number(ids):
    first, second, third = (FIRST, SECOND, THIRD) if ids else (None, None, None)
    parcels = _run(_mail(SHIPPED, ALPHA, first), _mail(SHIPPED, BETA, second, 10))
    del parcels[NUMBER]
    _run(_mail(SHIPPED, GAMMA, third, 11), parcels=parcels)
    assert {n: p.name for n, p in parcels.items()} == {
        f"{NUMBER}P2": f"{BETA} (2)",
        f"{NUMBER}P3": f"{GAMMA} (3)",
    }


def test_an_order_without_entries_left_starts_with_its_own_number_again():
    parcels = _run(_mail(SHIPPED, ALPHA, FIRST))
    del parcels[NUMBER]
    _run(_mail(SHIPPED, BETA, SECOND, 10), parcels=parcels)
    assert {n: p.name for n, p in parcels.items()} == {NUMBER: BETA}


# ----- entries closed by hand or on their own -----
def test_a_box_marked_as_received_keeps_its_id_and_its_later_mails():
    parcels = _run(_mail(ORDERED, ALPHA))
    mark_received(parcels[NUMBER], NOW)
    changed_at = parcels[NUMBER].last_change_at
    changes = [
        apply_update(parcels, update, NOW)
        for update in (_mail(SHIPPED, ALPHA, FIRST, 10), _mail(DELIVERED, None, FIRST, 11))
    ]
    assert changes == [None, None]
    assert list(parcels) == [NUMBER]
    parcel = parcels[NUMBER]
    assert parcel.shipment_ids == [FIRST]
    # (the hand mark stays as it is: the id is no news, the mails change nothing)
    assert parcel.manual_delivered
    assert parcel.result.status_text == MANUAL_TEXT
    assert parcel.last_change_at == changed_at


def test_a_box_marked_as_received_after_its_id_finds_its_later_mails():
    parcels = _run(_mail(SHIPPED, ALPHA, FIRST), _mail(SHIPPED, BETA, SECOND, 10))
    mark_received(parcels[f"{NUMBER}P2"], NOW)
    _run(_mail(DELIVERED, None, SECOND, 11), parcels=parcels)
    assert list(parcels) == [NUMBER, f"{NUMBER}P2"]
    assert parcels[NUMBER].status is SHIPPED
    assert parcels[f"{NUMBER}P2"].result.status_text == MANUAL_TEXT


@pytest.mark.parametrize("title", [BETA, None], ids=["names-its-item", "names-no-item"])
def test_a_new_box_takes_over_an_order_closed_without_a_delivery_mail(title):
    parcels = _run(_mail(ORDERED, ALPHA))
    close_unconfirmed(parcels[NUMBER], NOW)
    change = apply_update(parcels, _mail(DELIVERED, title, FIRST, 10), NOW)
    assert _boxes(parcels) == {NUMBER: (title or ALPHA, DELIVERED, [FIRST])}
    assert not parcels[NUMBER].assumed_delivered
    assert change is not None and not change.created


def test_an_entry_shipped_before_it_was_closed_is_no_order_to_take_over():
    parcels = _run(_mail(SHIPPED, ALPHA))
    close_unconfirmed(parcels[NUMBER], NOW)
    _run(_mail(SHIPPED, BETA, FIRST, 10), parcels=parcels)
    assert _boxes(parcels) == {
        NUMBER: (ALPHA, DELIVERED, []),
        f"{NUMBER}P2": (f"{BETA} (2)", SHIPPED, [FIRST]),
    }


def test_of_two_entries_with_the_same_id_the_one_with_its_item_takes_the_mail():
    # An older version kept every id with the entry its mail went to.
    parcels = _run(_mail(SHIPPED, ALPHA, FIRST), _mail(SHIPPED, BETA, SECOND, 10))
    parcels[NUMBER].shipment_ids.append(SECOND)
    _run(_mail(OUT, BETA, SECOND, 11), parcels=parcels)
    assert parcels[NUMBER].status is SHIPPED
    assert parcels[f"{NUMBER}P2"].status is OUT


# ----- telling the delivery of a further box -----
def test_a_further_box_delivered_as_soon_as_it_is_known_is_announced():
    parcels = _run(_mail(SHIPPED, ALPHA, FIRST, 8))
    change = apply_update(parcels, _mail(DELIVERED, BETA, SECOND), NOW)
    assert change.created and change.announce


def test_the_first_entry_of_an_order_delivered_right_away_is_not_announced():
    change = apply_update({}, _mail(DELIVERED, ALPHA, FIRST), NOW)
    assert change.created and not change.announce


def test_a_further_box_delivered_long_ago_is_not_announced():
    parcels = _run(_mail(SHIPPED, ALPHA, FIRST, 8))
    late = MailUpdate(
        NUMBER, "amazon", DELIVERED, NOW - timedelta(days=2), title=BETA, shipment_id=SECOND
    )
    change = apply_update(parcels, late, NOW)
    assert change.created and not change.announce


# ----- real sequences: every mail of an order, in the order they were sent -----
def _replay(first: int, last: int) -> list:
    names = sorted(p.name for p in (FIXTURES / "mail").glob("1[89][0-9]_*.eml"))
    names = [n for n in names if first <= int(n[:3]) <= last]
    updates = [u for name in names for u in parse_mail(load_mail(name)).updates]
    parcels: dict = {}
    for update in sorted(updates, key=lambda u: u.sent_at):
        apply_update(parcels, update, update.sent_at)
    return sorted(parcels.values(), key=lambda p: (len(p.number), p.number))


def test_three_boxes_of_one_day_stay_apart_though_two_have_the_same_title():
    # Ordered with four items; three "Versendet" mails on one day, two of them „Gardena…“.
    # The first box never got a delivery mail: it stays shipped.
    first, second, third = _replay(181, 188)
    assert [(p.status, p.shipment_ids) for p in (first, second, third)] == [
        (SHIPPED, ["TidmkrlPA"]),
        (DELIVERED, ["TWsgUCqnI"]),
        (DELIVERED, ["TdHFU2zAu"]),
    ]
    assert (second.name, third.name) == ("Gardena… (2)", "Gardena… und 1 weiterer Artikel (3)")


def test_the_order_named_after_its_first_item_takes_the_name_of_the_first_box():
    # The order's mail names each of its four items under the order number; the first box
    # holds another one, the second box the first item and one more.
    assert [(p.name, p.status, p.shipment_ids) for p in _replay(189, 191)] == [
        ("OVNSHVN…", SHIPPED, ["T6DlR8pGJ"]),
        ("Fasgear 240W… und 1 weiterer Artikel (2)", SHIPPED, ["TXAnNg2hP"]),
    ]

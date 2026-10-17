"""v0.3.31: corrections after a code review - the AliExpress parser (invented mails; the
fixtures show the layouts)."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.aliexpress import (
    CONFIRMED_TEXT,
    HANDED_OVER_TEXT,
    _item_names,
    _lines,
    _link_orders,
)
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.models import ParcelStatus
from custom_components.parcel_tracker.notification import build_notification
from custom_components.parcel_tracker.schedule import delivered_today

from .conftest import load_mail
from .test_mail_aliexpress import DELIVERY_CONFIRMED, DHL, HANDED_OVER, LINK, _apply, _msg

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
ORDER = "9999999999990901"
OTHER = "9999999999990906"
SURVEY = f"Bestellung {ORDER}: wie ist es gelaufen?"


def _survey(number: str = ORDER) -> str:
    return (
        "Lieferung bestätigt\nHallo Max Mustermann,\n"
        f"Wir haben die Lieferung Ihrer Bestellung {number} bestätigt.Wenn Sie Fragen haben, "
        "sind wir für Sie da.\nBestellung prüfen\n"
        "Wenn Sie den Artikel immer noch nicht erhalten haben, öffnen Sie einen Streitfall.\n"
    )


# ----- C4: the survey confirms on AliExpress's word only, and only its own order -----
def test_survey_about_another_order_confirms_nothing():
    result = parse_mail(_msg(SURVEY, _survey(OTHER)))
    assert result.ignored and result.updates == []


def test_survey_confirms_only_the_order_of_its_subject():
    body = _survey() + f"Bestelldetails\nBestell-Nr.\n{ORDER}\nBestell-Nr.\n{OTHER}\n"
    [u] = parse_mail(_msg(SURVEY, body)).updates
    assert (u.number, u.status, u.confirmation) == (f"ALI{ORDER}", ParcelStatus.DELIVERED, True)
    assert u.status_text == CONFIRMED_TEXT == "Lieferung bestätigt (laut AliExpress)"
    # Nobody saw it arrive: the mail tells no time of delivery.
    assert u.delivered_at is None


def test_confirmation_closes_an_open_order_as_assumed_only():
    """The same mail says "Wenn Sie den Artikel immer noch nicht erhalten haben": it proves
    no arrival. Closed like an order without a delivery mail: no push, not "today"."""
    parcels: dict = {}
    _apply(parcels, _msg(f"Bestellung {ORDER}: Bestellung versandt"), NOW - timedelta(days=5))
    [change] = _apply(parcels, _msg(SURVEY, _survey()), NOW)
    [order] = parcels.values()
    assert (change.old_status, order.status) == (ParcelStatus.IN_TRANSIT, ParcelStatus.DELIVERED)
    assert order.assumed_delivered is True
    assert order.result.status_text == CONFIRMED_TEXT
    assert order.result.events[0].text == CONFIRMED_TEXT
    assert order.result.delivered_at is None
    assert not delivered_today(order, NOW.astimezone(BERLIN).date(), BERLIN)
    assert build_notification(order, ParcelStatus.IN_TRANSIT, NOW) is None


def test_the_real_survey_mail_still_confirms_its_order():
    [u] = parse_mail(load_mail(DELIVERY_CONFIRMED)).updates
    assert (u.number, u.confirmation, u.delivered_at) == ("ALI9999999999990021", True, None)


# ----- C5: no pattern is quadratic on a long run of brackets -----
@pytest.mark.parametrize("char", ["(", "[", "<"])
def test_a_long_run_of_brackets_is_read_in_linear_time(char):
    text = "Hallo\n" + char * 200_000 + "\nx1\n"
    start = time.perf_counter()
    lines = _lines(text)
    result = parse_mail(_msg(f"Bestellung {ORDER}: Bestellung versandt", text))
    assert time.perf_counter() - start < 5
    assert lines == ["Hallo", char * 200_000, "x1"]
    assert [u.status for u in result.updates] == [ParcelStatus.IN_TRANSIT]


def test_links_are_still_cut_out_of_the_lines():
    text = "Lieferung verfolgen <https://www.aliexpress.com/x?a=1>\n((https://a.example/b)\nx1\n"
    assert _lines(text) == ["Lieferung verfolgen", "x1"]


# ----- C6: order numbers only from the links of AliExpress itself -----
def _parcel_html(*anchors: str, text: str = "") -> str:
    return f"<html><body><p>Hallo Max Mustermann,</p>{text}{''.join(anchors)}</body></html>"


def _link(href: str) -> str:
    return f'<a href="{href}">Lieferung verfolgen</a>'


def _orders(html: str) -> list[str]:
    return _link_orders(_msg(f"Packstück {DHL}: Vom Kurier abgeholt", html=html))


def test_orders_are_read_from_links_of_aliexpress():
    html = _parcel_html(
        _link(f"{LINK}{ORDER}&amp;x=1"),
        _link(f"https://m.aliexpress.com/ssr/1?o_ids={OTHER},9999999999990907&amp;x=1"),
        _link(f"https://aliexpress.com/p?orderId={ORDER}"),
        _link("https://www.aliexpress.com/p?o_ids=9999999999990908%2C9999999999990909"),
    )
    assert _orders(html) == [
        ORDER, OTHER, "9999999999990907", "9999999999990908", "9999999999990909",
    ]


@pytest.mark.parametrize(
    "html",
    [
        # another host, also one that only looks like AliExpress
        _parcel_html(_link(f"https://evil.example/p?tradeOrderId={ORDER}")),
        _parcel_html(_link(f"https://aliexpress.com.evil.example/p?tradeOrderId={ORDER}")),
        _parcel_html(_link(f"https://notaliexpress.com/p?tradeOrderId={ORDER}")),
        # not a link: text, an image, another attribute
        _parcel_html(text=f"<p>https://www.aliexpress.com/p?tradeOrderId={ORDER}</p>"),
        _parcel_html(f'<img src="{LINK}{ORDER}">'),
        _parcel_html(f'<a title="{LINK}{ORDER}" href="https://www.aliexpress.com/">x</a>'),
        # a link inside a link is not followed
        _parcel_html(_link(
            "https://www.aliexpress.com/redirect?url=https%3A%2F%2Fwww.aliexpress.com%2Fp"
            f"%3FtradeOrderId%3D{ORDER}"
        )),
        _parcel_html(_link(f"https://evil.example/r?u={LINK}{ORDER}")),
        # not the shape of an order number: nothing is cut out of a longer run
        _parcel_html(_link(f"{LINK}{'9' * 40}")),
        _parcel_html(_link(f"{LINK}{ORDER}abc")),
        _parcel_html(_link(f"{LINK}12345")),
    ],
)
def test_no_order_from_anything_else(html):
    assert _orders(html) == []


def test_one_bad_value_does_not_hide_the_good_ones():
    html = _parcel_html(_link(f"https://www.aliexpress.com/p?o_ids={ORDER},{'9' * 40},12"))
    assert _orders(html) == [ORDER]


def test_too_many_orders_in_one_mail_count_as_none():
    numbers = [f"99999999999{n:05d}" for n in range(21)]
    html = _parcel_html(*(_link(f"{LINK}{number}") for number in numbers))
    assert _orders(html) == []
    assert _orders(_parcel_html(*(_link(f"{LINK}{n}") for n in numbers[:20]))) == numbers[:20]
    # Told like a mail without an order: one carrier's parcel, no order is made.
    [u] = parse_mail(_msg(f"Packstück {DHL}: Vom Kurier abgeholt", html=html)).updates
    assert (u.number, u.carrier, u.shop) == (DHL, "dhl", "aliexpress")


def test_links_of_a_text_mail_are_still_read():
    body = f"Hallo Max Mustermann,\nLieferung verfolgen <{LINK}{ORDER}>\n"
    [u] = parse_mail(_msg(f"Packstück {DHL}: Vom Kurier abgeholt", body)).updates
    assert (u.number, u.tracking_ref) == (f"ALI{ORDER}", DHL)
    other = f"Hallo,\nLieferung verfolgen <https://evil.example/p?tradeOrderId={ORDER}>\n"
    [u] = parse_mail(_msg(f"Packstück {DHL}: Vom Kurier abgeholt", other)).updates
    assert u.number == DHL


# ----- C8: "Wird zugestellt" is never the last mile -----
def test_wird_zugestellt_is_on_its_way_whatever_the_text_says():
    [u] = parse_mail(_msg(f"Bestellung {ORDER}: Wird zugestellt")).updates
    assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, None)
    body = "Hallo Max Mustermann,\nIhre Bestellung wird heute zugestellt.\n"
    [u] = parse_mail(_msg(f"Bestellung {ORDER}: Wird zugestellt", body)).updates
    assert u.status is ParcelStatus.IN_TRANSIT
    u = parse_mail(load_mail(HANDED_OVER)).updates[0]
    assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, HANDED_OVER_TEXT)


# ----- C9: an item's name only from where the layouts put it -----
ITEM = "Beispiel-Kabel USB-C auf USB-A geflo..."
NAME = "Beispiel-Kabel USB-C auf USB-A geflo…"


@pytest.mark.parametrize(
    "lines",
    [
        ["Paketinfos", ITEM, "Variante A", "x1"],
        ["Paketinfos", ITEM, "x1"],
        ["Paketinfos", ITEM, "Variante A x2"],
        ["Aufgegeben am Jan 01,2026, 12:00", "Beispiel Store", ITEM, "Variante A", "€ 1,99x1"],
        ["Bestellung 19999999999990001", ITEM, "Variante A", "x1"],
        ["Bestätigt", "Versandt", "Zugestellt", ITEM, "Variante A", "x1"],
        ["Paketinfos", "Anderer Artikel...", "x1", ITEM, "Variante A", "x1"],
        ["Paketinfos", "Hi-Fi Kopfhörer kabellos...", "x1", ITEM, "x1"],
    ],
)
def test_item_names_of_the_known_layouts(lines):
    assert _item_names(lines)[-1] == NAME


@pytest.mark.parametrize(
    "lines",
    [
        # nothing the layouts know stands above the item
        ["Hallo Max Mustermann,", "x1"],
        ["Hallo Max Mustermann,", "Variante A", "x1"],
        ["Ein Satz über die Lieferung.", ITEM, "Variante A", "x1"],
        # a second line of the variant: which line is the name?
        ["Paketinfos", ITEM, "Farbe: Türkis", "Größe: L", "x1"],
        # lines that are no item, wherever they stand
        ["Paketinfos", "Hallo Max Mustermann,", "x1"],
        ["Paketinfos", "Hi Max", "Variante A", "x1"],
        ["Paketinfos", "Max Mustermann (+49) 0000000000", "x1"],
        ["Paketinfos", "Max Mustermann +49 151 0000000", "Variante A", "x1"],
        ["Paketinfos", "30/08/2024", "x1"],
        ["Bestelldetails", "Aufgegeben am Jan 01,2026, 12:00", "x1"],
        ["Paketinfos", "Voraussichtliche Zustellzeit", "x1"],
        ["Paketinfos", "Versand nach", "Musterstraße 1, Musterstadt", "x1"],
        ["Bestelldetails", "Aufgegeben am Jan 01,2026, 12:00", "Beispiel Store", "x1"],
        ["Bestelldetails", "Aufgegeben am Jan 01,2026, 12:00", "Beispiel Store", "Variante A x1"],
    ],
)
def test_no_item_name_without_the_anchor_of_a_layout(lines):
    """No title is better than a wrong one: never a greeting, a name or an address."""
    assert _item_names(lines) == []


def test_update_of_a_mail_with_an_odd_layout_has_no_title():
    body = "Hallo Max Mustermann,\nMax Mustermann (+49) 0000000000\nx1\n"
    [u] = parse_mail(_msg(f"Bestellung {ORDER}: Bestellung versandt", body)).updates
    assert u.title is None
    parcels: dict = {}
    apply_update(parcels, u, NOW)
    assert parcels[f"ALI{ORDER}"].name is None

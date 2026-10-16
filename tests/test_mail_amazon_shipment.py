"""Amazon's shipment id: read from the link to the tracking page and kept with the order.

Since autumn 2025 every Amazon mail from "Versendet" on links to the shipment's tracking page
(https://www.amazon.de/progress-tracker/package?orderId=…&shipmentId=…), behind Amazon's
own redirect. The id is the same in every mail about that box. It is only kept for now.
The anonymised fixtures cut every link, so these mails are built here.
"""

from datetime import datetime
from email import policy
from email.message import EmailMessage
from urllib.parse import quote

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update, mark_received
from custom_components.parcel_tracker.models import ParcelStatus

ORDER = "999-9156534-2587125"
OTHER_ORDER = "999-4240915-8849919"
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
) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"Amazon.de <{sender}>"
    msg["Subject"] = subject
    msg["Date"] = when
    lines = [f"Bestellnr. {order}\n* Beispiel-Maßband 5 m\n" for order in orders]
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
        "AMZ99942409158849919": "UhIjKl9mN",
    }


def test_the_first_id_of_an_order_counts():
    [update] = _updates(_msg(_redirect(_page()), _redirect(_page(shipment="UhIjKl9mN"))))
    assert update.shipment_id == SHIPMENT


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


def test_a_further_id_is_kept_after_the_first_and_is_no_change_of_its_own():
    parcels: dict = {}
    _apply(parcels, _msg(_redirect(_page())))
    changed_at = parcels[NUMBER].last_change_at
    later = _msg(_redirect(_page(shipment="UhIjKl9mN")), when="Sun, 11 Oct 2026 10:00:00 +0200")
    assert _apply(parcels, later) == [None]
    assert parcels[NUMBER].shipment_ids == [SHIPMENT, "UhIjKl9mN"]
    assert parcels[NUMBER].last_change_at == changed_at


def test_an_order_marked_as_received_takes_no_further_id():
    parcels: dict = {}
    _apply(parcels, _msg(_redirect(_page())))
    mark_received(parcels[NUMBER], NOW)
    _apply(parcels, _msg(_redirect(_page(shipment="UhIjKl9mN"))))
    assert parcels[NUMBER].shipment_ids == [SHIPMENT]

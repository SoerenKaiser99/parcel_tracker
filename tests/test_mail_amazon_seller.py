"""Amazon's marketplace seller: read from the order's mails and matched with a carrier's mail.

A seller that sends the box itself hands it to a carrier of its own, and that carrier's
mail names the seller ("Ihre Beispiel GmbH Sendung ist unterwegs"), never Amazon. Amazon's
mails name the seller of each item in their HTML part only ("Verkauf durch …"). A seller
that sells its own make is found by the title already; this is for one that sells others'.
"""

from datetime import datetime, timedelta
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update, fold_delivered
from custom_components.parcel_tracker.mail.base import MailUpdate, is_seller
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

from .conftest import load_mail

ORDER = "999-9156534-2587125"
OTHER_ORDER = "999-1234567-7654321"
NUMBER = "AMZ99991565342587125"
OTHER_NUMBER = "AMZ99912345677654321"
DHL = "999999990901"
ITEM = "Musterfirma Akku-Ladegerät 18V"
SELLER = "Verkauf durch Beispielhandel e.K., Händler & Versand aus Deutschland"
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=BERLIN)
TODAY = NOW.date()


def _item(line: str | None) -> str:
    """An item as the mail lists it: its seller line (None: the mail names none), quantity."""
    return (f"{line}\n" if line else "") + "Menge: 1\n"


def _msg(
    *blocks: tuple[str, tuple[str | None, ...]],
    html: bool = True,
    when: str = "Sun, 11 Oct 2026 08:00:00 +0200",
    subject: str = "Versendet: „Musterfirma Akku-Ladegerät...“",
    html_head: str = "",
) -> EmailMessage:
    """An Amazon mail: per block an order and its items, one per seller line.

    The current layout names the sellers in the HTML part only; without one (``html``
    False) the text part names them, as the older layout of the order's mail did.
    """
    blocks = blocks or ((ORDER, (SELLER,)),)
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "Amazon.de <versandbestaetigung@amazon.de>"
    msg["Subject"] = subject
    msg["Date"] = when
    text = "\n".join(
        f"Bestellnr. {order}\n* {ITEM}\n" + ("" if html else "".join(map(_item, lines)))
        for order, lines in blocks
    )
    msg.set_content(f"Hallo Max,\n\nAnkunft morgen\n\n{text}")
    if html:
        rows = "".join(
            f"<tr><td>Bestellnr. &#x202B;{order}</td></tr><tr><td>{ITEM}</td></tr>"
            + "".join(
                (f"<tr><td>{line}</td></tr>" if line else "") + "<tr><td>Menge: 1</td></tr>"
                for line in lines
            )
            for order, lines in blocks
        )
        msg.add_alternative(
            f"<html><body><p>Hallo Max,</p>{html_head}<table>{rows}</table></body></html>",
            subtype="html",
        )
    return msg


def _sellers(msg: EmailMessage) -> list[str | None]:
    return [u.seller for u in parse_mail(msg).updates]


# ----- the order's mails -----
def test_the_seller_is_read_without_amazons_note():
    assert _sellers(_msg()) == ["Beispielhandel e.K."]


@pytest.mark.parametrize(
    "line",
    [
        "Verkauf durch Amazon.de",
        "Verkauf durch einen Drittanbieter und Versand durch Amazon.",
        "Verkauf durch Amazon EU S.à r.l.",
    ],
)
def test_amazon_is_no_seller(line):
    assert _sellers(_msg((ORDER, (line,)))) == [None]


def test_a_seller_of_every_item_counts_and_each_order_has_its_own():
    msg = _msg(
        (ORDER, (SELLER, "Verkauf durch ⭐⭐⭐ Beispielhandel e.K.")),
        (OTHER_ORDER, ("Verkauf durch Amazon.de",)),
    )
    assert _sellers(msg) == ["Beispielhandel e.K.", None]


@pytest.mark.parametrize(
    "line",
    [
        "Verkauf durch Erika Musterfrau",
        "Verkauf durch Musterladen",
        "Verkauf durch Erika Musterfrau, Händler & Versand aus Deutschland",
    ],
)
def test_a_seller_without_legal_form_is_never_kept(line):
    # The name a seller gives itself may be a person's: only a company is taken from a mail.
    assert _sellers(_msg((ORDER, (line,)))) == [None]


@pytest.mark.parametrize(
    "lines",
    [
        (SELLER, "Verkauf durch Musterladen"),  # two sellers, one of them without legal form
        (SELLER, "Verkauf durch Musterladen GmbH"),
        (SELLER, "Verkauf durch Amazon.de"),  # a seller and Amazon
        (SELLER, "Verkauf durch einen Drittanbieter und Versand durch Amazon."),
    ],
)
def test_an_order_of_items_of_several_sellers_has_none(lines):
    # Which of them sends which box is not told: a carrier's mail of one of them must never
    # go to a box with another's item.
    assert _sellers(_msg((ORDER, lines))) == [None]


def test_an_item_whose_seller_is_not_named_leaves_the_order_without_one():
    # Amazon does not name the seller of every item: what is not named may be another's.
    assert _sellers(_msg((ORDER, (None, SELLER)))) == [None]


@pytest.mark.parametrize(
    ("line", "seller"),
    [
        # Amazon's note behind the comma is never the seller
        ("Verkauf durch Musterladen, Versand durch Amazon EU S.à r.l.", None),
        ("Verkauf durch Erika Musterfrau, Beispiel GmbH", None),
        # a shop we know or "eBay" is no company with its legal form
        ("Verkauf durch Thomann", None),
        ("Verkauf durch ebay-shop24", None),
        # "Amazon" only as a word of its own
        ("Verkauf durch Amazonas Naturkost GmbH", "Amazonas Naturkost GmbH"),
    ],
)
def test_only_the_name_in_front_of_the_comma_and_only_a_company_is_kept(line, seller):
    assert _sellers(_msg((ORDER, (line,)))) == [seller]


@pytest.mark.parametrize(
    ("second", "seller"),
    [
        (SELLER, "Beispielhandel e.K."),
        ("Verkauf durch Amazon.de", None),
        ("Verkauf durch Musterladen GmbH", None),
    ],
)
def test_the_orders_mail_takes_the_seller_of_all_its_days(second, seller):
    # The order's mail names an order once per day it comes: all of it is one entry, so a
    # seller counts only if it sells the items of every day.
    msg = _msg(
        (ORDER, (SELLER,)), (ORDER, (second,)), subject="Bestellt: „Musterfirma Akku-Ladegerät...“"
    )
    assert _sellers(msg) == [seller, seller]  # (one update per day, both for the one entry)


def test_a_mention_without_items_tells_nothing():
    # The HTML part names the order once more in its head, without items: the text part
    # names it once, so the mentions are taken by the order, and the head does not count.
    msg = _msg(html_head=f"<p>Bestellnr. {ORDER}</p>")
    assert _sellers(msg) == ["Beispielhandel e.K."]


def test_a_mail_without_html_part_reads_the_seller_from_its_text():
    assert _sellers(_msg(html=False)) == ["Beispielhandel e.K."]
    assert _sellers(_msg((ORDER, (None,)), html=False)) == [None]


def test_the_seller_is_kept_with_the_order_and_stored():
    parcels: dict = {}
    for update in parse_mail(_msg()).updates:
        apply_update(parcels, update, NOW)
    order = parcels[NUMBER]
    assert order.sellers == ["Beispielhandel e.K."]
    assert Parcel.from_dict(order.to_dict()).sellers == ["Beispielhandel e.K."]
    # A later mail that names the seller again keeps it once and tells nothing new.
    again = MailUpdate(
        NUMBER, "amazon", ParcelStatus.IN_TRANSIT, NOW, title=ITEM, seller="Beispielhandel e.K."
    )
    assert apply_update(parcels, again, NOW) is None
    assert order.sellers == ["Beispielhandel e.K."]
    # Two are kept at most: a second one already says the entry has no single seller.
    for seller in ("Musterladen GmbH", "Dritthandel GmbH"):
        apply_update(parcels, MailUpdate(
            NUMBER, "amazon", ParcelStatus.IN_TRANSIT, NOW, title=ITEM, seller=seller
        ), NOW)
    assert order.sellers == ["Beispielhandel e.K.", "Musterladen GmbH"]


def test_an_order_stored_by_an_older_version_has_no_seller():
    data = _order(NUMBER).to_dict()
    del data["sellers"]
    assert Parcel.from_dict(data).sellers == []


# ----- the carrier's mail -----
def _order(number: str = NUMBER, sellers=("Beispielhandel e.K.",), day=TODAY) -> Parcel:
    result = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Versendet", day, None, None, None, None, None, None, []
    )
    return Parcel(
        number, "amazon", "mail", ITEM, NOW, NOW,
        result=result, mail_title=ITEM, sellers=list(sellers),
    )


def _dhl(title: str = "Beispielhandel e.K.", status=ParcelStatus.OUT_FOR_DELIVERY) -> MailUpdate:
    return MailUpdate(DHL, "dhl", status, NOW, title=title, eta_date=TODAY)


def test_a_carrier_mail_naming_the_seller_joins_its_order():
    parcels = {NUMBER: _order()}
    change = apply_update(parcels, _dhl(), NOW)
    assert not change.created and change.parcel is parcels[NUMBER]
    assert set(parcels) == {NUMBER}
    order = parcels[NUMBER]
    assert (order.tracking_ref, order.tracking_carrier) == (DHL, "dhl")
    assert order.name == ITEM
    assert order.status is ParcelStatus.OUT_FOR_DELIVERY


@pytest.mark.parametrize(
    ("seller", "title", "joined"),
    [
        ("Beispielhandel e.K.", "Beispielhandel e.K.", True),
        ("BEISPIELHANDEL UG", "Beispielhandel GmbH", True),  # any case, any legal form
        ("Beispiel Handel GmbH & Co. KG", "Beispiel Handel GmbH", True),
        ("Beispielhandel Nord GmbH", "Beispielhandel GmbH", False),  # another seller
        ("Beispielhandel GmbH", "Beispielhandel Nord GmbH", False),
        ("Beispielhandel GmbH", "Beispielhandel", False),  # no company: the mail names no brand
        ("Abcd GmbH", "Abcd GmbH", False),  # a brand too short to tell an order by
    ],
)
def test_the_seller_must_be_the_brand_word_for_word(seller, title, joined):
    parcels = {NUMBER: _order(sellers=(seller,))}
    change = apply_update(parcels, _dhl(title), NOW)
    assert change.created is not joined
    assert (parcels[NUMBER].tracking_ref == DHL) is joined


def test_an_entry_told_of_two_sellers_is_found_by_neither():
    parcels = {NUMBER: _order(sellers=("Beispielhandel e.K.", "Musterladen GmbH"))}
    change = apply_update(parcels, _dhl(), NOW)
    assert change.created and parcels[NUMBER].tracking_ref is None


def test_the_box_of_a_mixed_order_is_found_by_its_own_seller_only():
    # One order, one item sold by Amazon and one by the seller: the order's mail names no
    # seller. Amazon's own box comes first and takes the order's entry; the seller's box is
    # a further entry, and only that one is found by the seller's carrier mail.
    def mail(status, when, lines, shipment=None, item=ITEM):
        return MailUpdate(
            NUMBER, "amazon", status, when, title=item, eta_date=TODAY,
            shipment_id=shipment,
            seller=_sellers(_msg((ORDER, lines)))[0],
        )

    ordered = mail(ParcelStatus.PRE_TRANSIT, NOW - timedelta(days=2),
                   (SELLER, "Verkauf durch Amazon.de"))
    amazon_box = mail(ParcelStatus.IN_TRANSIT, NOW - timedelta(days=1),
                      ("Verkauf durch Amazon.de",), "TAmazon01")
    parcels: dict = {}
    for update in (ordered, amazon_box):
        apply_update(parcels, update, update.sent_at)
    # The seller's carrier mail before Amazon's mail about the seller's box: no entry is
    # the seller's yet, so it becomes a parcel of its own.
    early = apply_update(parcels, _dhl(status=ParcelStatus.IN_TRANSIT), NOW)
    assert early.created and parcels[NUMBER].tracking_ref is None
    del parcels[DHL]
    seller_box = mail(ParcelStatus.IN_TRANSIT, NOW, (SELLER,), "DSeller01",
                      item="Beispiel Zubehör")
    apply_update(parcels, seller_box, NOW)
    change = apply_update(parcels, _dhl(), NOW)
    assert not change.created and change.parcel.number == f"{NUMBER}P2"
    assert parcels[NUMBER].tracking_ref is None


def test_amazons_box_never_takes_the_seller_of_an_order_of_two_days():
    # The order's mail: the seller's item on one day, Amazon's on the other. Amazon's box
    # comes first and takes the order's entry: the seller's carrier mail must not find it.
    ordered = _msg(
        (ORDER, (SELLER,)), (ORDER, ("Verkauf durch Amazon.de",)),
        subject="Bestellt: „Musterfirma Akku-Ladegerät...“",
        when="Fri, 09 Oct 2026 08:00:00 +0200",
    )
    parcels: dict = {}
    for update in parse_mail(ordered).updates:
        apply_update(parcels, update, update.sent_at)
    box = MailUpdate(NUMBER, "amazon", ParcelStatus.IN_TRANSIT, NOW - timedelta(hours=2),
                     title=ITEM, eta_date=TODAY, shipment_id="TAmazon01")
    apply_update(parcels, box, box.sent_at)
    assert parcels[NUMBER].sellers == []
    change = apply_update(parcels, _dhl(), NOW)
    assert change.created and parcels[NUMBER].tracking_ref is None


def test_two_orders_of_the_seller_are_never_joined():
    parcels = {NUMBER: _order(), OTHER_NUMBER: _order(OTHER_NUMBER)}
    change = apply_update(parcels, _dhl(), NOW)
    assert change.created and DHL in parcels
    assert all(parcels[n].tracking_ref is None for n in (NUMBER, OTHER_NUMBER))


def test_the_seller_needs_a_day_that_fits():
    parcels = {NUMBER: _order(day=TODAY + timedelta(days=5))}
    change = apply_update(parcels, _dhl(), NOW)
    assert change.created and parcels[NUMBER].tracking_ref is None


def test_a_delivered_parcel_of_the_seller_is_folded_into_its_order_afterwards():
    parcels = {NUMBER: _order()}
    parcel = Parcel(DHL, "dhl", "mail", "Beispielhandel e.K.", NOW, NOW)
    parcel.result = TrackingResult(
        ParcelStatus.DELIVERED, "Zugestellt", None, None, None, None, None, None, NOW, []
    )
    parcels[DHL] = parcel
    order = fold_delivered(parcels, parcel, NOW + timedelta(hours=1))
    assert order is parcels[NUMBER] and DHL not in parcels
    assert order.tracking_ref == DHL and order.status is ParcelStatus.DELIVERED


def test_is_seller():
    assert is_seller("Beispielhandel", "beispielhandel e.K.")
    assert is_seller("Beispiel Handel", "Beispiel  Handel UG")
    assert not is_seller("Beispielhandel", "Beispielhandel Nord")


# ----- the whole way, with a real DHL mail -----
def test_the_dhl_mail_of_a_seller_goes_to_the_amazon_order():
    # The DHL mail "Ihre Beispiel GmbH Sendung ist unterwegs" (no day) came after Amazon's
    # "Versendet" of an order sold by that seller, an item of another make.
    amazon = _msg(
        (ORDER, ("Verkauf durch Beispiel GmbH, Händler & Versand aus Deutschland",)),
        when="Fri, 21 Aug 2026 08:00:00 +0200",
    )
    updates = [*parse_mail(amazon).updates, *parse_mail(load_mail(
        "118_dhl_international_unterwegs.eml")).updates]
    parcels: dict = {}
    for update in sorted(updates, key=lambda u: u.sent_at):
        apply_update(parcels, update, update.sent_at)
    [order] = parcels.values()
    assert order.number == NUMBER and order.name.startswith("Musterfirma")
    assert order.tracking_carrier == "dhl" and order.status is ParcelStatus.IN_TRANSIT

"""v0.3.53: Amazon's mail about an item it could not get (#77), AliExpress in English (#76)."""

from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.mail import is_ignored, parse_mail
from custom_components.parcel_tracker.mail.aliexpress import ALIEXPRESS_SENDER
from custom_components.parcel_tracker.mail.apply import CANCELLED_TEXT, apply_update
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

NOW = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
AMAZON_ORDER = "999-1234567-7654321"
CANCEL_SUBJECT = f"Artikel für deine Amazon.de Bestellung #{AMAZON_ORDER} wurde storniert"
ITEM = "Beispiel-Laubsammler 18 V | 55 cm Arbeitsbreite | ohne Akku"


def _amazon(subject: str, body: str, sender_: str = "no-reply@amazon.de") -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f'"Amazon.de" <{sender_}>'
    msg["Subject"] = subject
    msg["Date"] = "Mon, 16 Nov 2026 06:08:05 +0000"
    msg.set_content(body)
    return msg


def _cancel_body(*items: str) -> str:
    listed = "\n".join(f"* {item}\nMenge: 1\n9.99 EUR\n" for item in items)
    return (
        "Dein Artikel wurde storniert\n"
        "Aufgrund fehlender Verfügbarkeit können wir den folgenden Artikel aus deiner "
        "Bestellung leider nicht beschaffen.\n\n"
        "Max – Musterstadt\n\nBestellnr.\n"
        f"{AMAZON_ORDER}\n\n\nBestelldetails anzeigen\nhttps://www.amazon.de/…\n\n"
        f"{listed}\n"
    )


# ----- Amazon: "Artikel für deine Amazon.de Bestellung #… wurde storniert" (#77) -----


def test_the_mail_about_an_item_amazon_could_not_get_cancels_it():
    result = parse_mail(_amazon(CANCEL_SUBJECT, _cancel_body(ITEM)))
    [u] = result.updates
    assert (u.number, u.carrier, u.status) == (
        "AMZ99912345677654321", "amazon", ParcelStatus.CANCELLED,
    )
    assert u.title is not None and u.title.startswith("Beispiel-Laubsammler")
    assert not result.ignored and result.amazon


def test_several_items_cancelled_name_how_many_more():
    [u] = parse_mail(_amazon(CANCEL_SUBJECT, _cancel_body(ITEM, "Beispiel-Akku 4 Ah"))).updates
    assert u.title is not None and u.title.endswith("und 1 weiterer Artikel")


def test_without_a_listed_item_the_mail_tells_nothing():
    body = _cancel_body(ITEM).replace(f"* {ITEM}", ITEM)
    result = parse_mail(_amazon(CANCEL_SUBJECT, body))
    assert result.updates == []


def test_the_cancellation_never_goes_to_the_generic_parser():
    # (review: a body without "Bestellnr." but with a carrier's number)
    body = "Bestellnummer 999-1234567-7654321\nSendung JJD000390012345678901\n"
    result = parse_mail(_amazon(CANCEL_SUBJECT, body))
    assert result.updates == [] and result.amazon


def test_the_cancellation_behind_apples_relay_is_read():
    relay = "no_reply_at_amazon_de_0a1b2c3d4e_0a1b2c3d@privaterelay.appleid.com"
    [u] = parse_mail(_amazon(CANCEL_SUBJECT, _cancel_body(ITEM), sender_=relay)).updates
    assert u.status is ParcelStatus.CANCELLED


def test_other_mails_of_no_reply_stay_ignored():
    assert is_ignored("no-reply@amazon.de")
    result = parse_mail(_amazon("Dein Amazon-Konto: neue Anmeldung", "Bestellnr.\n" + AMAZON_ORDER))
    assert result.ignored and not result.updates


def test_the_subject_alone_from_another_sender_is_no_amazon_mail():
    result = parse_mail(_amazon(CANCEL_SUBJECT, "nichts", sender_="max@example.org"))
    assert not result.updates


def test_the_cancellation_closes_the_order_of_that_one_item():
    order = "AMZ99912345677654321"
    result = TrackingResult(
        ParcelStatus.PRE_TRANSIT, "Bestellt", None, None, None, None, None, None, None
    )
    parcels = {
        order: Parcel(order, "amazon", "mail", ITEM, NOW, NOW, result=result, mail_title=ITEM)
    }
    [u] = parse_mail(_amazon(CANCEL_SUBJECT, _cancel_body(ITEM))).updates
    assert apply_update(parcels, u, NOW) is not None
    assert parcels[order].result.status is ParcelStatus.CANCELLED
    assert parcels[order].result.status_text == CANCELLED_TEXT


# ----- AliExpress in English (#76) -----

ALI_ORDER = "9999999999990901"
DHL = "00340999999999990902"
LINK = "https://www.aliexpress.com/p/tracking/index.html?_login=yes&tradeOrderId="


def _ali(subject: str, body: str, html: str | None = None) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"AliExpress <{ALIEXPRESS_SENDER}>"
    msg["Subject"] = subject
    msg["Date"] = "Thu, 05 Nov 2026 12:01:46 -0800"
    if html is None:
        msg.set_content(body)
    else:
        msg.set_content(html, subtype="html")
    return msg


COLLECTED_BODY = (
    "Track shipping status inside\nPackage in transit\nHi Max Mustermann,\n"
    f"Your package, containing order {ALI_ORDER}, has been collected by our shipping "
    "partner.\nTrack delivery\nPackage details\nBeispiel Zigbee Drehknopf Th...\n"
    "TP-1, Germany\nx1\n"
)


def test_an_order_collected_by_the_carrier_is_on_its_way():
    [u] = parse_mail(_ali(f"Order {ALI_ORDER}: collected by the carrier", COLLECTED_BODY)).updates
    assert (u.number, u.carrier) == (f"ALI{ALI_ORDER}", "aliexpress")
    assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, "Vom Kurier abgeholt")
    assert u.title == "Beispiel Zigbee Drehknopf Th…"


def test_a_package_out_for_delivery_is_in_delivery_for_its_order():
    html = f'<html><body><a href="{LINK}{ALI_ORDER}">Track delivery</a></body></html>'
    [u] = parse_mail(_ali(f"Package {DHL} is out for delivery", "", html=html)).updates
    assert (u.number, u.status) == (f"ALI{ALI_ORDER}", ParcelStatus.OUT_FOR_DELIVERY)
    assert (u.tracking_ref, u.tracking_carrier) == (DHL, "dhl")


def test_a_package_out_for_delivery_without_an_order_follows_the_carrier():
    [u] = parse_mail(_ali(f"Package {DHL} is out for delivery", "Hi Max Mustermann,")).updates
    assert (u.number, u.carrier, u.status) == (DHL, "dhl", ParcelStatus.OUT_FOR_DELIVERY)


@pytest.mark.parametrize(
    "subject",
    [f"Order {ALI_ORDER}: something new", f"Package {DHL} has news for you"],
)
def test_english_steps_nobody_knows_stay_unrecognised(subject):
    result = parse_mail(_ali(subject, "Hi Max Mustermann,"))
    assert result.updates == [] and not result.ignored


def test_waiting_for_your_return_is_still_ignored():
    result = parse_mail(_ali(f"Order {ALI_ORDER}: Waiting for your return", "Hi"))
    assert result.ignored and not result.updates

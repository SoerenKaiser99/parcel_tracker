"""Issue #36: the import duty (Zoll) named in a DHL mail of the day of delivery.

"Die Einfuhrabgaben i.H.v. 12,34€ (inkl. 7,50€ Auslagepauschale und darin enthaltener MWSt.)
sind bei Zustellung, möglichst passend, in bar zu bezahlen." The amount, its currency and the
cash request are kept on the parcel until it is delivered.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.shipping import parse_dhl_mail
from custom_components.parcel_tracker.models import Parcel, ParcelStatus

from .conftest import load_mail

FIXTURE = "178_dhl_zustellung_kommt_heute_einfuhrabgaben.eml"
NUMBER = "LE999999901BE"
NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
SENTENCE = (
    "Die Einfuhrabgaben i.H.v. {amount} (inkl. 7,50€ Auslagepauschale und darin enthaltener "
    "MWSt.) sind bei Zustellung, möglichst passend, in bar zu bezahlen."
)


def _msg(body: str, subject: str = "Ihre DHL Sendung kommt heute") -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "DHL Zustell-Update <zustellung@dhl.de>"
    msg["Subject"] = subject
    msg["Date"] = "Mon, 28 Sep 2026 07:23:12 +0200"
    msg.set_content(body)
    return msg


def _customs(update):
    return update.customs_amount, update.customs_currency, update.customs_cash


# ----- the parser -----


def test_the_mail_names_amount_currency_and_cash():
    [u] = parse_mail(load_mail(FIXTURE)).updates
    assert (u.number, u.carrier, u.status) == (NUMBER, "dhl", ParcelStatus.OUT_FOR_DELIVERY)
    assert _customs(u) == (12.34, "EUR", True)


@pytest.mark.parametrize(
    ("written", "amount"),
    [
        ("12,34€", 12.34),
        ("12,34 €", 12.34),
        ("12,34 EUR", 12.34),
        ("1.234,56€", 1234.56),
        ("5€", 5.0),
        ("7,5 €", 7.5),
        ("18,76€", 18.76),
    ],
)
def test_amounts_as_they_are_written(written, amount):
    body = f"Sendungsnummer {NUMBER}\n" + SENTENCE.format(amount=written)
    [u] = parse_dhl_mail(_msg(body))
    assert (u.customs_amount, u.customs_currency) == (amount, "EUR")


def test_the_first_amount_counts_not_the_fees_in_brackets():
    [u] = parse_dhl_mail(_msg(f"{NUMBER}\n" + SENTENCE.format(amount="12,34€")))
    assert u.customs_amount == 12.34  # not 7,50


@pytest.mark.parametrize(
    "body",
    [
        f"{NUMBER}\nIhre Sendung kommt heute.",  # no duty at all
        f"{NUMBER}\n" + SENTENCE.format(amount="0,00€"),  # nothing to pay
        f"{NUMBER}\nDie Einfuhrabgaben sind bei Zustellung zu bezahlen.",  # no amount
        f"{NUMBER}\nDie Einfuhrabgaben i.H.v. zwölf Euro sind zu bezahlen.",  # no number
        f"{NUMBER}\nDie Einfuhrabgaben i.H.v. 12,34 Dollar sind zu bezahlen.",  # no euro
    ],
)
def test_no_amount_no_duty(body):
    [u] = parse_dhl_mail(_msg(body))
    assert _customs(u) == (None, None, False)


def test_cash_only_when_the_mail_asks_for_it_right_behind_the_amount():
    card = f"{NUMBER}\nDie Einfuhrabgaben i.H.v. 12,34€ sind bei Zustellung per Karte zu zahlen."
    assert _customs(parse_dhl_mail(_msg(card))[0]) == (12.34, "EUR", False)
    far = f"{NUMBER}\nDie Einfuhrabgaben i.H.v. 12,34€ sind fällig. " + "x " * 200 + "in bar"
    assert _customs(parse_dhl_mail(_msg(far))[0]) == (12.34, "EUR", False)


def test_a_long_line_without_the_duty_is_read_quickly():
    body = f"{NUMBER}\n" + "Einfuhrabgaben i.H.v. " * 2000
    assert parse_dhl_mail(_msg(body))[0].customs_amount is None


def test_the_duty_is_read_from_the_html_part_when_the_text_part_has_nothing():
    msg = _msg("Ihre Sendung kommt heute.")
    msg.add_alternative(
        "<html><body><p>Ihre Sendung</p><p>" + NUMBER + "</p>"
        "<table><tr><td>" + SENTENCE.format(amount="12,34€") + "</td></tr></table>"
        "</body></html>",
        subtype="html",
    )
    [u] = parse_dhl_mail(msg)
    assert (u.number, _customs(u)) == (NUMBER, (12.34, "EUR", True))


def test_only_dhl_mails_name_a_duty():
    body = f"Sendungsnummer 00340999999999999917\n{SENTENCE.format(amount='12,34€')}"
    msg = _msg(body)
    del msg["From"]
    msg["From"] = "Shop <shop@example.org>"
    assert all(u.customs_amount is None for u in parse_mail(msg).updates)


# ----- the parcel -----


def _apply(parcels, update, now=NOW):
    return apply_update(parcels, update, now)


def test_the_parcel_keeps_the_duty_until_it_is_delivered():
    [first] = parse_mail(load_mail(FIXTURE)).updates
    parcels: dict[str, Parcel] = {}
    _apply(parcels, first)
    parcel = parcels[NUMBER]
    assert (parcel.customs_amount, parcel.customs_currency, parcel.customs_cash) == (
        12.34,
        "EUR",
        True,
    )
    assert parcel.customs_due == (12.34, "EUR", True)

    # a later mail that does not name the duty again leaves it as it is
    later = replace(
        first,
        sent_at=first.sent_at + timedelta(hours=1),
        customs_amount=None,
        customs_currency=None,
        customs_cash=False,
    )
    _apply(parcels, later, NOW + timedelta(hours=1))
    assert parcel.customs_due == (12.34, "EUR", True)

    # a corrected amount replaces it
    corrected = replace(first, sent_at=first.sent_at + timedelta(hours=2), customs_amount=15.0)
    _apply(parcels, corrected, NOW + timedelta(hours=2))
    assert parcel.customs_due == (15.0, "EUR", True)

    # the delivery ends it
    delivered = replace(
        first,
        status=ParcelStatus.DELIVERED,
        sent_at=first.sent_at + timedelta(hours=3),
        customs_amount=None,
        customs_currency=None,
        customs_cash=False,
    )
    _apply(parcels, delivered, NOW + timedelta(hours=3))
    assert parcel.status is ParcelStatus.DELIVERED
    assert (parcel.customs_amount, parcel.customs_currency, parcel.customs_cash) == (
        None,
        None,
        False,
    )
    assert parcel.customs_due is None


def test_a_delivery_the_carrier_tells_ends_it_too():
    [update] = parse_mail(load_mail(FIXTURE)).updates
    parcels: dict[str, Parcel] = {}
    _apply(parcels, update)
    parcel = parcels[NUMBER]
    assert parcel.customs_due is not None
    parcel.result = replace(parcel.result, status=ParcelStatus.DELIVERED)
    assert parcel.customs_due is None  # (the stored amount is not shown any more)


def test_the_duty_survives_a_restart():
    [update] = parse_mail(load_mail(FIXTURE)).updates
    parcels: dict[str, Parcel] = {}
    _apply(parcels, update)
    again = Parcel.from_dict(parcels[NUMBER].to_dict())
    assert again.customs_due == (12.34, "EUR", True)


@pytest.mark.parametrize("amount", ["12,34", True, -5, 0, None, [], {}])
def test_a_stored_amount_that_is_none_is_dropped(amount):
    [update] = parse_mail(load_mail(FIXTURE)).updates
    parcels: dict[str, Parcel] = {}
    _apply(parcels, update)
    data = parcels[NUMBER].to_dict() | {"customs_amount": amount}
    assert Parcel.from_dict(data).customs_due is None


def test_a_parcel_stored_by_an_older_version_has_no_duty():
    [update] = parse_mail(load_mail(FIXTURE)).updates
    parcels: dict[str, Parcel] = {}
    _apply(parcels, update)
    data = parcels[NUMBER].to_dict()
    for key in ("customs_amount", "customs_currency", "customs_cash"):
        del data[key]
    parcel = Parcel.from_dict(data)
    assert (parcel.customs_amount, parcel.customs_currency, parcel.customs_cash) == (
        None,
        None,
        False,
    )

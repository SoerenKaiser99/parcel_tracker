"""Mails of Österreichische Post (meinesendung@post.at).

The fixtures are built after real mails; numbers, names and places are invented.
"""

from dataclasses import replace
from datetime import UTC, date, datetime

from custom_components.parcel_tracker.mail import known_sender_domain, parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import sent_at
from custom_components.parcel_tracker.models import Parcel, ParcelStatus

from .conftest import load_mail

NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
AMAZON_POST = "1099999999999998212303"
PLAETTCHEN = "AMZ99991565342587125"


def _one(name: str, read_otp: bool = False):
    [update] = parse_mail(load_mail(name), read_otp).updates
    return update


def test_sender_is_known():
    assert known_sender_domain("meinesendung@post.at") == "post.at"


def test_amazon_in_distribution_names_amazon_and_the_day():
    u = _one("300_post_at_amazon_in_verteilung.eml")
    assert (u.number, u.carrier, u.status) == (AMAZON_POST, "post_at", ParcelStatus.IN_TRANSIT)
    assert u.shop == "amazon"
    assert u.eta_date == date(2026, 11, 14)


def test_amazon_in_delivery_is_today():
    msg = load_mail("301_post_at_amazon_in_zustellung.eml")
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.shop) == (AMAZON_POST, ParcelStatus.OUT_FOR_DELIVERY, "amazon")
    assert u.eta_date == sent_at(msg).date()


def test_plain_mails_name_no_shop():
    u = _one("302_post_at_sendung_in_verteilung.eml")
    assert (u.number, u.status, u.shop) == (
        "158999999999999999901230",
        ParcelStatus.IN_TRANSIT,
        None,
    )
    assert u.eta_date == date(2026, 9, 2)
    assert _one("303_post_at_sendung_in_zustellung.eml").status is ParcelStatus.OUT_FOR_DELIVERY


def test_pickup_with_place_deadline_and_code_only_when_asked():
    u = _one("304_post_at_paket_ist_da.eml")
    assert (u.number, u.status) == ("1099999999999997012309", ParcelStatus.AWAITING_PICKUP)
    assert u.pickup_point == "Abholstation 9999, Musterstraße 1"
    assert u.pickup_until == date(2026, 10, 20)
    assert u.delivery_code is None
    assert _one("304_post_at_paket_ist_da.eml", read_otp=True).delivery_code == "ABC123"
    # name, customer number and weight are never taken
    text = repr(u)
    assert "Mustermann" not in text and "999999" not in text.replace(u.number, "")


def test_redirect_only_names_the_parcel():
    u = _one("305_post_at_so_stellen_wir_zu.eml")
    assert (u.number, u.carrier, u.status) == ("1099999999999996012306", "post_at", None)


def test_other_post_mails_are_ignored():
    result = parse_mail(load_mail("306_post_at_kiosk_ebeleg.eml"))
    assert result.ignored and not result.updates


def test_post_mail_creates_a_pollable_post_parcel():
    parcels: dict[str, Parcel] = {}
    change = apply_update(parcels, _one("302_post_at_sendung_in_verteilung.eml"), NOW)
    assert change.created
    p = parcels["158999999999999999901230"]
    assert p.carrier == "post_at"
    assert p.poll_target == ("post_at", "158999999999999999901230")


def test_amazon_post_mail_joins_the_amazon_order():
    parcels: dict[str, Parcel] = {}
    for name in ("001_bestellbestaetigung_bestellt.eml", "074_versandbestaetigung_versendet.eml"):
        for u in parse_mail(load_mail(name)).updates:
            apply_update(parcels, u, NOW)
    order = parcels[PLAETTCHEN]
    post = replace(_one("300_post_at_amazon_in_verteilung.eml"), eta_date=order.result.eta_date)
    change = apply_update(parcels, post, NOW)
    assert change.parcel is order and not change.created
    assert (order.tracking_ref, order.tracking_carrier) == (AMAZON_POST, "post_at")
    assert order.poll_target == ("post_at", AMAZON_POST)
    assert AMAZON_POST not in parcels


def test_pickup_code_holds_until_the_last_day_to_pick_up_and_a_reminder_carries_it_on():
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    from custom_components.parcel_tracker.mail.apply import apply_update

    now = datetime(2026, 11, 14, 8, 0, tzinfo=UTC)
    update = _one("304_post_at_paket_ist_da.eml", read_otp=True)
    assert update.pickup_until is not None
    parcels: dict = {}
    apply_update(parcels, update, now)
    [parcel] = parcels.values()
    assert parcel.delivery_code == "ABC123"
    assert parcel.delivery_code_day == update.pickup_until  # not only the day of the mail
    # "Erinnerung: Ihr Paket ist da!" with the same code and a later last day
    later = replace(update, pickup_until=update.pickup_until + timedelta(days=2))
    apply_update(parcels, later, now + timedelta(days=3))
    assert parcel.delivery_code_day == later.pickup_until

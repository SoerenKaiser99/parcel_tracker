from dataclasses import replace
from datetime import UTC, date, datetime

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.models import Parcel, ParcelStatus

from .conftest import load_mail

NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
AIRPODS = "AMZ99905626221455530"
PLAETTCHEN = "AMZ99991565342587125"
JJD = "JJD000012978217606560"


def _updates(name: str, read_otp: bool = False):
    return parse_mail(load_mail(name), read_otp).updates


def _apply(parcels: dict, name: str, read_otp: bool = False):
    return [apply_update(parcels, u, NOW) for u in _updates(name, read_otp)]


def test_amazon_order_is_created_and_moves_forward():
    parcels: dict[str, Parcel] = {}
    [change] = _apply(parcels, "002_bestellbestaetigung_bestellt.eml")
    assert change.created and change.old_status is None
    p = parcels[AIRPODS]
    assert (p.carrier, p.carrier_mode, p.name) == ("amazon", "mail", "Apple AirPods Pro 3…")
    assert p.mail_title == "Apple AirPods Pro 3…"
    assert p.status is ParcelStatus.PRE_TRANSIT
    assert p.result.status_text == "Bestellt"
    assert p.result.eta_from == datetime(2026, 8, 20, 18, 0, tzinfo=BERLIN)

    [change] = _apply(parcels, "096_shipment_tracking_zustellung_heute_f_r_d.eml", read_otp=True)
    assert not change.created
    assert change.old_status is ParcelStatus.PRE_TRANSIT
    assert p.status is ParcelStatus.OUT_FOR_DELIVERY
    assert p.delivery_code == "123456"
    assert p.delivery_code_day == date(2026, 8, 20)
    assert p.last_change_at == NOW

    [change] = _apply(parcels, "023_order_update_geliefert.eml")
    assert p.status is ParcelStatus.DELIVERED
    assert p.result.delivered_at == datetime(2026, 8, 20, 21, 3, 46, tzinfo=BERLIN)
    assert p.result.eta_date == date(2026, 8, 20)
    assert p.delivery_code is None
    assert [e.text for e in p.result.events] == ["Zugestellt", "In Zustellung", "Bestellt"]
    assert len(parcels) == 1


def test_older_mail_does_not_move_status_back():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    assert _apply(parcels, "001_bestellbestaetigung_bestellt.eml") == [None]
    assert parcels[PLAETTCHEN].status is ParcelStatus.IN_TRANSIT
    _apply(parcels, "002_bestellbestaetigung_bestellt.eml")
    _apply(parcels, "023_order_update_geliefert.eml")
    assert _apply(parcels, "096_shipment_tracking_zustellung_heute_f_r_d.eml", True) == [None]
    assert parcels[AIRPODS].status is ParcelStatus.DELIVERED
    assert parcels[AIRPODS].delivery_code is None


def test_multi_order_mail_creates_one_parcel_per_order():
    parcels: dict[str, Parcel] = {}
    changes = _apply(parcels, "009_bestellbestaetigung_bestellt.eml")
    assert all(c.created for c in changes)
    assert set(parcels) == {
        "AMZ99923739412707206",
        "AMZ99959817950965324",
        "AMZ99993317899923321",
    }
    _apply(parcels, "097_shipment_tracking_zustellung_heute_f_r_d.eml")
    _apply(parcels, "093_order_update_zugestellt_4.eml")
    homematic = parcels["AMZ99923739412707206"]
    assert homematic.status is ParcelStatus.DELIVERED
    assert homematic.name == "Homematic IP Fenster- und Türkontakt – verdeckter Einbau"
    assert len(parcels) == 3


def test_further_shipment_of_same_order_gets_suffix():
    parcels: dict[str, Parcel] = {}
    [first] = _updates("074_versandbestaetigung_versendet.eml")
    apply_update(parcels, first, NOW)
    second = replace(first, title="Magnethalter…")
    change = apply_update(parcels, second, NOW)
    assert change.created
    assert change.parcel.number == f"{PLAETTCHEN}P2"
    assert change.parcel.name == "Magnethalter… (2)"
    out = replace(first, title="Magnethalter…", status=ParcelStatus.OUT_FOR_DELIVERY)
    assert apply_update(parcels, out, NOW).parcel.number == f"{PLAETTCHEN}P2"
    assert parcels[PLAETTCHEN].status is ParcelStatus.IN_TRANSIT
    assert len(parcels) == 2


def test_first_shipping_mail_with_other_title_joins_the_ordered_parcel():
    parcels: dict[str, Parcel] = {}
    [ordered] = _updates("001_bestellbestaetigung_bestellt.eml")
    apply_update(parcels, replace(ordered, title="Ganz anderer Titel"), NOW)
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    assert list(parcels) == [PLAETTCHEN]
    assert parcels[PLAETTCHEN].status is ParcelStatus.IN_TRANSIT


def test_dhl_amazon_mail_merges_when_unambiguous():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "001_bestellbestaetigung_bestellt.eml")
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    [change] = _apply(parcels, "045_noreply_ihre_amazon_sendung_ist_unterweg.eml")
    p = parcels[PLAETTCHEN]
    assert change.parcel is p and not change.created
    assert (p.tracking_ref, p.tracking_carrier) == (JJD, "dhl")
    assert p.poll_target == ("dhl", JJD)
    assert p.next_poll_at is None
    assert JJD not in parcels

    [change] = _apply(parcels, "049_noreply_ihre_amazon_sendung_kommt_heute_.eml")
    assert change.parcel is p
    assert p.status is ParcelStatus.OUT_FOR_DELIVERY
    assert p.result.eta_from == datetime(2026, 7, 31, 13, 10, tzinfo=BERLIN)
    assert len(parcels) == 1


def test_dhl_amazon_mail_is_separate_when_ambiguous():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "074_versandbestaetigung_versendet.eml")  # ETA 31.07.
    _apply(parcels, "073_versandbestaetigung_versandt.eml")  # ETA 31.07. as well
    [change] = _apply(parcels, "045_noreply_ihre_amazon_sendung_ist_unterweg.eml")
    assert change.created
    dhl = parcels[JJD]
    assert (dhl.carrier, dhl.name, dhl.carrier_mode) == ("dhl", "Amazon-Sendung (DHL)", "mail")
    assert dhl.status is ParcelStatus.IN_TRANSIT
    assert dhl.poll_target == ("dhl", JJD)
    assert all(p.tracking_ref is None for p in parcels.values())


def test_dhl_amazon_mail_without_day_needs_exactly_one_in_transit():
    [dhl] = _updates("045_noreply_ihre_amazon_sendung_ist_unterweg.eml")
    no_day = replace(dhl, eta_date=None)
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "017_bestellbestaetigung_bestellt.eml")  # ordered only, not in transit
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    assert apply_update(parcels, no_day, NOW).parcel.number == PLAETTCHEN

    parcels = {}
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    _apply(parcels, "075_versandbestaetigung_versendet.eml")
    assert apply_update(parcels, no_day, NOW).created


def test_ups_announcement_then_delivery():
    parcels: dict[str, Parcel] = {}
    [change] = _apply(parcels, "070_pkginfo_ups_versandbenachrichtigung_kont.eml")
    ups = parcels["1Z999AA11026832876"]
    assert change.created
    assert (ups.carrier, ups.name) == ("ups", "Beispiel Versand GmbH")
    assert ups.poll_target is None
    assert ups.result.status_text == "Angekündigt"
    _apply(parcels, "071_pkginfo_ups_zustellbenachrichtigung_kont.eml")
    assert ups.status is ParcelStatus.DELIVERED
    assert ups.result.delivered_at == datetime(2019, 3, 5, 13, 43, tzinfo=BERLIN)
    assert ups.result.eta_date == date(2019, 3, 6)


def test_generic_number_creates_pollable_parcel_without_result():
    parcels: dict[str, Parcel] = {}
    [dhl] = _updates("045_noreply_ihre_amazon_sendung_ist_unterweg.eml")
    generic = replace(dhl, status=None, title="Shop", amazon_shipment=False, eta_date=None)
    change = apply_update(parcels, generic, NOW)
    assert change.created
    p = parcels[JJD]
    assert (p.carrier, p.name, p.result, p.next_poll_at) == ("dhl", "Shop", None, None)
    assert p.poll_target == ("dhl", JJD)


def test_mail_for_known_pollable_parcel_asks_carrier_again():
    parcels = {JJD: Parcel(JJD, "dhl", "auto", "Oma", NOW, NOW, next_poll_at=NOW)}
    _apply(parcels, "045_noreply_ihre_amazon_sendung_ist_unterweg.eml")
    assert len(parcels) == 1
    assert parcels[JJD].next_poll_at is None
    assert parcels[JJD].name == "Oma"


def test_eta_range_is_carried_and_cleared():
    parcels: dict[str, Parcel] = {}
    [change] = _apply(parcels, "098_bestellbestaetigung_bestellt_zeitraum.eml")
    p = change.parcel
    assert (p.result.eta_date, p.result.eta_latest) == (date(2026, 10, 2), date(2026, 10, 5))

    # a mail without any ETA keeps the window
    update = replace(_updates("098_bestellbestaetigung_bestellt_zeitraum.eml")[0],
                     status=ParcelStatus.IN_TRANSIT, eta_date=None, eta_latest=None)
    apply_update(parcels, update, NOW)
    assert (p.result.eta_date, p.result.eta_latest) == (date(2026, 10, 2), date(2026, 10, 5))

    # a later single date clears it
    update = replace(update, eta_date=date(2026, 10, 3))
    apply_update(parcels, update, NOW)
    assert (p.result.eta_date, p.result.eta_latest) == (date(2026, 10, 3), None)

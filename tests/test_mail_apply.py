from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.carriers.track17 import standalone
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate, sent_at
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)

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
    assert ups.poll_target == ("ups", "1Z999AA11026832876")  # only polled with UPS API
    assert ups.result.status_text == "Angekündigt"
    _apply(parcels, "071_pkginfo_ups_zustellbenachrichtigung_kont.eml")
    assert ups.status is ParcelStatus.DELIVERED
    assert ups.result.delivered_at == datetime(2019, 3, 5, 13, 43, tzinfo=BERLIN)
    assert ups.result.eta_date == date(2019, 3, 6)


def test_generic_number_creates_pollable_parcel_without_result():
    parcels: dict[str, Parcel] = {}
    [dhl] = _updates("045_noreply_ihre_amazon_sendung_ist_unterweg.eml")
    generic = replace(dhl, status=None, title="Shop", shop=None, eta_date=None)
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


EBAY_SHIPPED = "104_ebay_ihre_sendung_ist_jetzt_beim_versand.eml"
EBAY_ORDER = "EBAY992179315376"
HERMES_ON_THE_WAY = "103_noreply_ihre_hermes_sendung_ist_auf_dem_.eml"
HERMES_ANNOUNCED = "105_noreply_information_zur_zustellung_an_de.eml"
HERMES_DELIVERED = "099_noreply_dein_hermes_paket_von_amazon_eu_.eml"
HERMES_2023 = "H9999767129584220767"


def test_ebay_order_is_created_with_hint_and_moves_forward():
    parcels: dict[str, Parcel] = {}
    [change] = _apply(parcels, EBAY_SHIPPED)
    p = parcels[EBAY_ORDER]
    assert change.created
    assert (p.carrier, p.carrier_mode, p.shipping_carrier_hint) == ("ebay", "mail", "hermes")
    assert p.name == "Bambu Lab PLA Basic Filament Blue Bl… und 1 weiterer Artikel"
    assert (p.status, p.result.status_text) == (ParcelStatus.IN_TRANSIT, "Versendet")
    assert (p.result.eta_date, p.result.eta_latest) == (date(2026, 1, 28), date(2026, 1, 29))
    assert p.poll_target is None
    [update] = _updates(EBAY_SHIPPED)
    apply_update(parcels, replace(update, status=ParcelStatus.DELIVERED, title=None), NOW)
    assert (p.status, p.result.status_text) == (ParcelStatus.DELIVERED, "Zugestellt")


def test_hermes_mail_merges_into_ebay_order_by_hint_within_window():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, EBAY_SHIPPED)
    [hermes] = _updates(HERMES_ON_THE_WAY)
    in_window = replace(hermes, eta_date=date(2026, 1, 29), eta_from=None, eta_to=None)
    change = apply_update(parcels, in_window, NOW)
    p = parcels[EBAY_ORDER]
    assert change.parcel is p and not change.created
    assert (p.tracking_ref, p.tracking_carrier) == ("H9999978276078000836", "hermes")
    assert p.poll_target == ("hermes", "H9999978276078000836")
    assert p.result.eta_date == date(2026, 1, 29)
    assert len(parcels) == 1


def test_hermes_mail_outside_the_window_stays_separate():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, EBAY_SHIPPED)
    [hermes] = _updates(HERMES_ON_THE_WAY)  # ETA 2020-04-02
    change = apply_update(parcels, hermes, NOW)
    assert change.created and change.parcel.carrier == "hermes"
    assert parcels[EBAY_ORDER].tracking_ref is None


def test_legacy_amazon_hermes_number_catches_the_hermes_mail():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "102_versandbestaetigung_ihre_amazon_de_beste.eml")
    p = parcels["AMZ99900779704106459"]
    assert (p.tracking_ref, p.tracking_carrier) == ("H9999978276078000836", "hermes")
    assert p.next_poll_at is None
    [change] = _apply(parcels, HERMES_ON_THE_WAY)
    assert change.parcel is p
    assert p.result.eta_from == datetime(2020, 4, 2, 14, 0, tzinfo=BERLIN)
    assert len(parcels) == 1


def test_amazon_order_takes_the_hermes_number_and_delivery():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    [change] = _apply(parcels, HERMES_ANNOUNCED)  # shop Amazon, no day
    p = parcels[PLAETTCHEN]
    assert change.parcel is p
    assert (p.tracking_ref, p.tracking_carrier) == (HERMES_2023, "hermes")
    assert p.status is ParcelStatus.IN_TRANSIT  # an announcement never moves it back
    _apply(parcels, HERMES_DELIVERED)
    assert p.status is ParcelStatus.DELIVERED
    assert p.name == "4 Ersatz Metallplättchen…"
    assert len(parcels) == 1


def test_hermes_mail_is_separate_when_two_amazon_orders_are_open():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    _apply(parcels, "075_versandbestaetigung_versendet.eml")
    [change] = _apply(parcels, HERMES_ANNOUNCED)
    assert change.created
    hermes = parcels[HERMES_2023]
    assert (hermes.carrier, hermes.name, hermes.status) == (
        "hermes",
        "Amazon EU SARL",
        ParcelStatus.PRE_TRANSIT,
    )
    assert hermes.result.status_text == "Angekündigt"


def test_carrier_mail_names_an_unnamed_parcel_once():
    parcels = {HERMES_2023: Parcel(HERMES_2023, "hermes", "auto", None, NOW, NOW)}
    _apply(parcels, HERMES_DELIVERED)
    assert parcels[HERMES_2023].name == "Amazon EU SARL"
    parcels[HERMES_2023].name = "Oma"
    _apply(parcels, HERMES_ANNOUNCED)
    assert parcels[HERMES_2023].name == "Oma"


def test_dhl_mail_without_shop_does_not_merge_into_amazon():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    [dhl] = _updates("045_noreply_ihre_amazon_sendung_ist_unterweg.eml")
    change = apply_update(parcels, replace(dhl, shop=None, title=None), NOW)
    assert change.created
    assert parcels[PLAETTCHEN].tracking_ref is None


def test_ups_mail_does_not_trigger_an_extra_ups_call():
    ups = "1Z999AA11026832876"
    parcels = {ups: Parcel(ups, "ups", "auto", "Schuhe", NOW, NOW, next_poll_at=NOW)}
    _apply(parcels, "070_pkginfo_ups_versandbenachrichtigung_kont.eml")
    assert parcels[ups].next_poll_at == NOW


def test_mail_takes_over_from_a_17track_only_result_but_never_moves_it_back():
    number = "1Z999AA19999999901"
    seen = TrackingResult(
        ParcelStatus.OUT_FOR_DELIVERY, "Fahrzeug beladen", date(2026, 9, 30), None, None,
        "Köln", None, None, None, [TrackingEvent(NOW, "Fahrzeug beladen", "Köln")],
    )
    parcel = Parcel(
        number, "ups", "manual", None, NOW, NOW,
        result=standalone(seen), track17=True, track17_result=seen,
    )
    parcels = {number: parcel}
    late = MailUpdate(number, "ups", ParcelStatus.IN_TRANSIT, NOW)
    assert apply_update(parcels, late, NOW) is None
    assert parcel.result == standalone(seen)

    newer = MailUpdate(number, "ups", ParcelStatus.DELIVERED, NOW)
    assert apply_update(parcels, newer, NOW) is not None
    r = parcel.result
    assert (r.status, r.status_text, r.delivered_at) == (ParcelStatus.DELIVERED, "Zugestellt", NOW)
    assert [e.text for e in r.events] == ["Zugestellt"]  # the mail's own history
    assert (r.location, r.enriched) == ("Köln", ("location",))  # 17track fills the gap only
    assert r.eta_date is None


GLS_TODAY = "108_no_reply_dein_gls_paket_kommt_heute.eml"
GLS_TODAY_SECOND = "109_no_reply_dein_gls_paket_kommt_heute.eml"
GLS_DROP_OFF = "110_no_reply_dein_paket_wird_an_dem_gew_nsch.eml"
GLS_SOON = "111_no_reply_dein_paket_wird_in_wenigen_tage.eml"
GLS_DELIVERED = "112_no_reply_dein_paket_wurde_an_deinem_wuns.eml"
GLS_FIRST, GLS_SECOND = "99999999901", "99999999902"


def test_gls_mails_create_and_advance_their_own_parcels():
    parcels: dict[str, Parcel] = {}
    [change] = _apply(parcels, GLS_DROP_OFF)
    first = parcels[GLS_FIRST]
    assert change.created
    assert (first.carrier, first.carrier_mode, first.name) == ("gls", "mail", "Beispiel GmbH")
    assert (first.status, first.result.status_text) == (ParcelStatus.PRE_TRANSIT, "Angekündigt")
    assert first.poll_target == ("gls", GLS_FIRST)
    _apply(parcels, GLS_TODAY)
    assert first.status is ParcelStatus.OUT_FOR_DELIVERY
    assert first.result.eta_date == sent_at(load_mail(GLS_TODAY)).date()
    _apply(parcels, GLS_DELIVERED)
    assert (first.status, first.result.status_text) == (ParcelStatus.DELIVERED, "Zugestellt")
    assert first.result.delivered_at == sent_at(load_mail(GLS_DELIVERED))

    _apply(parcels, GLS_SOON)
    second = parcels[GLS_SECOND]
    assert (second.status, second.result.status_text) == (ParcelStatus.IN_TRANSIT, "Unterwegs")
    assert second.result.eta_from.date() == second.result.eta_date
    _apply(parcels, GLS_TODAY_SECOND)
    assert second.status is ParcelStatus.OUT_FOR_DELIVERY
    assert len(parcels) == 2


def test_gls_drop_off_notice_never_moves_a_parcel_back():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, GLS_TODAY)
    [change] = _apply(parcels, GLS_DROP_OFF)
    assert change is None
    assert parcels[GLS_FIRST].status is ParcelStatus.OUT_FOR_DELIVERY


def test_gls_mail_merges_into_the_ebay_order_that_named_gls():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, EBAY_SHIPPED)  # window 28.–29.01.2026
    order = parcels[EBAY_ORDER]
    order.shipping_carrier_hint = "gls"
    [gls] = _updates(GLS_SOON)
    in_window = replace(gls, eta_date=date(2026, 1, 28), eta_from=None, eta_to=None)
    change = apply_update(parcels, in_window, NOW)
    assert change.parcel is order and not change.created
    assert (order.tracking_ref, order.tracking_carrier) == (GLS_SECOND, "gls")
    assert order.poll_target == ("gls", GLS_SECOND)
    assert order.name.startswith("Bambu Lab")  # the shop parcel keeps its item title
    assert len(parcels) == 1


def test_gls_mail_outside_the_window_or_without_hint_stays_separate():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, EBAY_SHIPPED)  # hint "hermes"
    [gls] = _updates(GLS_SOON)  # its own day lies outside the order's window
    in_window = replace(gls, eta_date=date(2026, 1, 28))
    assert apply_update(parcels, in_window, NOW).created  # the order named another carrier
    del parcels[GLS_SECOND]
    parcels[EBAY_ORDER].shipping_carrier_hint = "gls"
    assert apply_update(parcels, gls, NOW).created  # day outside the order's window
    assert parcels[EBAY_ORDER].tracking_ref is None


def test_gls_mail_naming_amazon_merges_into_the_one_open_amazon_order():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    [gls] = _updates(GLS_DROP_OFF)  # no day: exactly one order in transit qualifies
    change = apply_update(parcels, replace(gls, shop="amazon"), NOW)
    order = parcels[PLAETTCHEN]
    assert change.parcel is order
    assert (order.tracking_ref, order.tracking_carrier) == (GLS_FIRST, "gls")
    assert order.status is ParcelStatus.IN_TRANSIT  # the notice never moves it back
    assert len(parcels) == 1


def test_gls_mail_is_separate_when_two_amazon_orders_are_open():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    _apply(parcels, "075_versandbestaetigung_versendet.eml")
    [gls] = _updates(GLS_DROP_OFF)
    change = apply_update(parcels, replace(gls, shop="amazon"), NOW)
    assert change.created and change.parcel.carrier == "gls"
    assert parcels[PLAETTCHEN].tracking_ref is None


def test_pickup_from_a_mail_reads_abholbereit():
    parcels: dict[str, Parcel] = {}
    [gls] = _updates(GLS_DELIVERED)
    apply_update(parcels, replace(gls, status=ParcelStatus.AWAITING_PICKUP), NOW)
    result = parcels[GLS_FIRST].result
    assert (result.status, result.status_text) == (ParcelStatus.AWAITING_PICKUP, "Abholbereit")
    assert result.delivered_at is None


def test_pickup_mail_does_not_keep_the_old_eta():
    parcels: dict[str, Parcel] = {}
    [gls] = _updates(GLS_DELIVERED)
    eta = date(2026, 10, 2)
    transit = replace(gls, status=ParcelStatus.IN_TRANSIT, eta_date=eta, eta_latest=None)
    apply_update(parcels, transit, NOW)
    result = parcels[GLS_FIRST].result
    assert result.eta_date == eta
    pickup = replace(gls, status=ParcelStatus.AWAITING_PICKUP, eta_date=None, eta_latest=None)
    apply_update(parcels, pickup, NOW)
    result = parcels[GLS_FIRST].result
    assert result.status is ParcelStatus.AWAITING_PICKUP
    assert (result.eta_date, result.eta_from, result.eta_to, result.eta_latest) == (None,) * 4


def test_pickup_mail_merged_into_a_shop_order_reads_abholbereit():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, "074_versandbestaetigung_versendet.eml")
    [gls] = _updates(GLS_DROP_OFF)
    pickup = replace(gls, shop="amazon", status=ParcelStatus.AWAITING_PICKUP)
    change = apply_update(parcels, pickup, NOW)
    order = parcels[PLAETTCHEN]
    assert change.parcel is order and order.tracking_ref == GLS_FIRST
    result = order.result
    assert (result.status, result.status_text) == (ParcelStatus.AWAITING_PICKUP, "Abholbereit")
    assert result.events[0].text == "Abholbereit"


def test_gls_mail_merges_into_an_order_with_a_raw_hint_from_before_the_upgrade():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, EBAY_SHIPPED)  # window 28.–29.01.2026
    order = parcels[EBAY_ORDER]
    order.shipping_carrier_hint = "GLS Paket"  # stored before carrier_key() knew GLS
    [gls] = _updates(GLS_SOON)
    in_window = replace(gls, eta_date=date(2026, 1, 28), eta_from=None, eta_to=None)
    change = apply_update(parcels, in_window, NOW)
    assert change.parcel is order and not change.created
    assert order.poll_target == ("gls", GLS_SECOND)
    assert len(parcels) == 1


def test_raw_hint_of_another_carrier_or_no_hint_does_not_merge():
    for hint in ("Hermes Germany", "Spedition Beispiel", None):
        parcels: dict[str, Parcel] = {}
        _apply(parcels, EBAY_SHIPPED)
        parcels[EBAY_ORDER].shipping_carrier_hint = hint
        [gls] = _updates(GLS_SOON)
        in_window = replace(gls, eta_date=date(2026, 1, 28), eta_from=None, eta_to=None)
        assert apply_update(parcels, in_window, NOW).created, hint


# ----- v0.3.15 review: a carrier's display name stored as the name counts as "no name" -----
def _named(name: str | None, carrier: str = "dhl") -> dict[str, Parcel]:
    number = "00340999999999999917" if carrier == "dhl" else "AMZ99999999999999901"
    return {number: Parcel(number, carrier, "mail", name, NOW, NOW)}


def _dhl_update(title: str | None, status=ParcelStatus.IN_TRANSIT) -> MailUpdate:
    return MailUpdate("00340999999999999917", "dhl", status, NOW.astimezone(BERLIN), title=title)


def test_a_stored_carrier_display_name_is_replaced_by_a_proper_name():
    for legacy in ("📦 DHL Paketankündigung", "DHL Zustell-Update", "DHL Paket",
                   "DPD Versandinfo", "GLS Real Time Tracking", "Hermes Sendungsinfo"):
        parcels = _named(legacy)
        change = apply_update(parcels, _dhl_update("Beispiel GmbH"), NOW)
        assert change is not None and not change.created
        [parcel] = parcels.values()
        assert parcel.name == "Beispiel GmbH", legacy


def test_a_stored_carrier_display_name_is_replaced_even_without_a_status():
    parcels = _named("DHL Zustell-Update")
    change = apply_update(parcels, _dhl_update("Beispiel GmbH", status=None), NOW)
    assert change is not None
    assert next(iter(parcels.values())).name == "Beispiel GmbH"


def test_a_stored_carrier_display_name_stays_until_a_mail_brings_a_name():
    parcels = _named("DHL Zustell-Update")
    apply_update(parcels, _dhl_update(None), NOW)
    assert next(iter(parcels.values())).name == "DHL Zustell-Update"


def test_any_other_stored_name_is_never_replaced():
    for name in ("Schuhe", "DHL Schuhe für Erika", "Back-UPS 700", "Amazon-Sendung (DHL)",
                 "Beispiel GmbH", "Österreich", "Paket", "Express", "Info", "Hermes", "DPD",
                 "DHL Express", "DHL Geschenk", "Zustell-Update", "Deutschland Service"):
        parcels = _named(name)
        apply_update(parcels, _dhl_update("Andere Beispiel AG"), NOW)
        assert next(iter(parcels.values())).name == name


def test_a_mail_never_names_a_parcel_after_a_carrier():
    """Defence in depth: whatever a parser hands over, a carrier's display name is no name."""
    parcels: dict[str, Parcel] = {}
    change = apply_update(parcels, _dhl_update("DHL Paketankündigung"), NOW)
    assert change.created and next(iter(parcels.values())).name is None
    apply_update(parcels, _dhl_update("📦 DHL Zustell-Update", ParcelStatus.DELIVERED), NOW)
    assert next(iter(parcels.values())).name is None


# ----- v0.3.15: a carrier mail naming the brand joins the one open shop order -----
TODAY = NOW.astimezone(BERLIN).date()
ORDER = "AMZ99999999999999901"
OTHER_ORDER = "AMZ99999999999999902"
SHORT_DHL = "999999999901"


def _order(number: str, title: str, first=None, last=None, carrier: str = "amazon",
           status=ParcelStatus.IN_TRANSIT) -> Parcel:
    result = TrackingResult(status, "Versendet", first, None, None, None, None, None, None, [],
                            eta_latest=last)
    return Parcel(number, carrier, "mail", title, NOW, NOW, result=result, mail_title=title)


def _brand_mail(title: str | None = "Beispielmarke GmbH", day=TODAY, carrier: str = "dhl",
                status=ParcelStatus.OUT_FOR_DELIVERY) -> MailUpdate:
    return MailUpdate(SHORT_DHL, carrier, status, NOW.astimezone(BERLIN), title=title,
                      eta_date=day)


def _range():
    from datetime import timedelta

    return TODAY - timedelta(days=1), TODAY + timedelta(days=2)


def test_carrier_mail_naming_the_brand_joins_the_one_order_whose_title_starts_with_it():
    first, last = _range()
    parcels = {
        ORDER: _order(ORDER, "Beispielmarke Trinkflasche 600 ml Edelstahl…", first, last),
        OTHER_ORDER: _order(OTHER_ORDER, "Musterfirma Kabel 2 m", first, last),
    }
    change = apply_update(parcels, _brand_mail(), NOW)
    assert not change.created and change.parcel is parcels[ORDER]
    assert set(parcels) == {ORDER, OTHER_ORDER}  # no parcel of its own
    order = parcels[ORDER]
    assert (order.tracking_ref, order.tracking_carrier) == (SHORT_DHL, "dhl")
    assert order.name == "Beispielmarke Trinkflasche 600 ml Edelstahl…"
    assert order.status is ParcelStatus.OUT_FOR_DELIVERY
    assert order.poll_target == ("dhl", SHORT_DHL)
    assert parcels[OTHER_ORDER].tracking_ref is None
    # the next mail about the number finds the order again
    again = apply_update(parcels, _brand_mail(status=ParcelStatus.DELIVERED), NOW)
    assert again.parcel is order and len(parcels) == 2


@pytest.mark.parametrize("carrier", ["dhl", "hermes", "gls", "ups"])
def test_brand_merge_for_every_carrier(carrier):
    parcels = {ORDER: _order(ORDER, "BEISPIELMARKE Trinkflasche", *_range())}
    change = apply_update(parcels, _brand_mail(carrier=carrier), NOW)
    assert not change.created and parcels[ORDER].tracking_carrier == carrier


@pytest.mark.parametrize("carrier", ["dhl", "hermes", "gls", "ups"])
def test_brand_merge_never_takes_an_ebay_order(carrier):
    number = "EBAY999999999901"
    parcels = {number: _order(number, "Beispielmarke Trinkflasche", *_range(), carrier="ebay")}
    change = apply_update(parcels, _brand_mail(carrier=carrier), NOW)
    assert change.created and parcels[number].tracking_ref is None
    assert parcels[SHORT_DHL].name == "Beispielmarke GmbH"


@pytest.mark.parametrize(
    ("order_day", "mail_day", "merged"),
    [
        ("range", "today", True),
        ("today", "today", True),
        (None, "today", True),  # the order names no day, but it is shipped
        ("range", None, True),  # the mail names no day, but the order is shipped
        ("later", "today", False),  # the day is outside of the order's range
        ("earlier", "today", False),
    ],
)
def test_brand_merge_needs_a_day_that_fits(order_day, mail_day, merged):
    from datetime import timedelta

    days = {
        "range": _range(),
        "today": (TODAY, None),
        None: (None, None),
        "later": (TODAY + timedelta(days=2), TODAY + timedelta(days=4)),
        "earlier": (TODAY - timedelta(days=5), TODAY - timedelta(days=1)),
    }[order_day]
    parcels = {ORDER: _order(ORDER, "Beispielmarke Trinkflasche", *days)}
    status = ParcelStatus.OUT_FOR_DELIVERY if mail_day else ParcelStatus.IN_TRANSIT
    change = apply_update(parcels, _brand_mail(day=TODAY if mail_day else None, status=status), NOW)
    assert change.created is not merged
    assert (parcels[ORDER].tracking_ref == SHORT_DHL) is merged
    assert (SHORT_DHL in parcels) is not merged


def test_two_orders_of_the_brand_are_never_merged():
    first, last = _range()
    parcels = {
        ORDER: _order(ORDER, "Beispielmarke Trinkflasche", first, last),
        # even if only one of them fits the day
        OTHER_ORDER: _order(OTHER_ORDER, "Beispielmarke Filter", None, None),
    }
    change = apply_update(parcels, _brand_mail(), NOW)
    assert change.created and SHORT_DHL in parcels
    assert parcels[SHORT_DHL].name == "Beispielmarke GmbH"
    assert all(parcels[n].tracking_ref is None for n in (ORDER, OTHER_ORDER))


@pytest.mark.parametrize(
    ("title", "order_title"),
    [
        ("AB GmbH", "AB Trinkflasche"),  # shorter than three characters
        ("Shop GmbH", "Shop Trinkflasche"),  # a word that says nothing
        ("Die Beste GmbH", "Die Trinkflasche"),  # only a part of the name fits
        ("Beispiel GmbH", "Beispielmarke Trinkflasche"),  # not at a word boundary
        ("Beispielmarke GmbH", "Trinkflasche von Beispielmarke"),  # not the beginning
        ("Beispielmarke GmbH", "Musterfirma Trinkflasche"),
        (None, "Beispielmarke Trinkflasche"),  # the mail names no company
        ("Erika Beispielmarke", "Erika Beispielmarke Trinkflasche"),  # a person, no company
        ("DHL Paket GmbH", "DHL Paket Karton"),  # a carrier is no brand
        # words that are the "brand" of too many companies
        ("Neu GmbH", "NEU Apple iPhone 99 Hülle"),
        ("Top Shop GmbH", "Top Shop Kabel 2 m"),
        ("Smart Home GmbH", "Smart Home Steckdose"),
        ("Premium Handel GmbH & Co. KG", "Premium Handel Kabel"),
        ("Abcd GmbH", "Abcd Trinkflasche"),  # one word of fewer than five letters
        # a shop we know is a shop, never the brand of an article
        ("IKEA", "IKEA Kallax Regal weiß"),
        ("IKEA Deutschland GmbH & Co. KG", "IKEA Deutschland Kallax Regal"),
        ("Otto GmbH & Co KG", "Otto Trinkflasche"),
        ("Conrad Electronic SE", "Conrad Electronic Kabel"),
        ("Tchibo GmbH", "Tchibo Kaffee"),
        ("Zalando SE", "Zalando Schuhe"),
        ("Amazon EU SARL", "Amazon EU Kabel"),
        # every word of the brand must begin the title, in order
        ("Kabelwerk Premium GmbH", "Kabelwerk Aderleitung 10 m"),
        ("Kabelwerk Premium GmbH", "Premium Kabelwerk Aderleitung 10 m"),
    ],
)
def test_short_ambiguous_or_missing_shop_names_are_never_merged(title, order_title):
    parcels = {ORDER: _order(ORDER, order_title, *_range())}
    change = apply_update(parcels, _brand_mail(title), NOW)
    assert change.created and parcels[ORDER].tracking_ref is None


def test_brand_merge_leaves_other_orders_alone():
    first, last = _range()
    done = _order(ORDER, "Beispielmarke Trinkflasche", first, last, status=ParcelStatus.DELIVERED)
    tracked = _order(OTHER_ORDER, "Beispielmarke Filter", first, last)
    tracked.tracking_ref, tracked.tracking_carrier = "00340999999999999917", "dhl"
    parcels = {ORDER: done, OTHER_ORDER: tracked}
    change = apply_update(parcels, _brand_mail(), NOW)
    # a delivered order and one that has its number are no candidates
    assert change.created and done.tracking_ref is None
    assert tracked.tracking_ref == "00340999999999999917"
    # and a mail without a status never merges
    parcels = {ORDER: _order(ORDER, "Beispielmarke Trinkflasche", first, last)}
    assert apply_update(parcels, _brand_mail(status=None, day=None), NOW).created


def test_an_existing_carrier_parcel_is_left_alone():
    """Folding a parcel that already exists into an order is not done: both stay."""
    first, last = _range()
    parcels = {
        ORDER: _order(ORDER, "Beispielmarke Trinkflasche", first, last),
        SHORT_DHL: Parcel(SHORT_DHL, "dhl", "mail", None, NOW, NOW),
    }
    change = apply_update(parcels, _brand_mail(), NOW)
    assert change.parcel is parcels[SHORT_DHL] and parcels[ORDER].tracking_ref is None


# ----- v0.3.15 second review: the brand rule is for Amazon orders and needs more proof -----
def test_two_word_brand_with_a_common_second_word_still_merges():
    """The production case: "<Marke> Premium GmbH" and the title "<Marke> Premium …"."""
    parcels = {ORDER: _order(ORDER, "Kabelwerk Premium Aderleitung H07V-K 10 m", *_range())}
    change = apply_update(parcels, _brand_mail("Kabelwerk Premium GmbH"), NOW)
    assert not change.created and parcels[ORDER].tracking_ref == SHORT_DHL


def test_brand_merge_skips_an_order_that_names_another_carrier():
    parcels = {ORDER: _order(ORDER, "Beispielmarke Trinkflasche", *_range())}
    parcels[ORDER].shipping_carrier_hint = "Hermes"
    change = apply_update(parcels, _brand_mail(carrier="dhl"), NOW)
    assert change.created and parcels[ORDER].tracking_ref is None
    # an order that names this carrier or none is still taken, also next to the other one
    parcels = {
        ORDER: _order(ORDER, "Beispielmarke Trinkflasche", *_range()),
        OTHER_ORDER: _order(OTHER_ORDER, "Beispielmarke Filter", *_range()),
    }
    parcels[ORDER].shipping_carrier_hint = "hermes"
    parcels[OTHER_ORDER].shipping_carrier_hint = "DHL Paket"
    change = apply_update(parcels, _brand_mail(carrier="dhl"), NOW)
    assert not change.created and change.parcel is parcels[OTHER_ORDER]


def _ordered(first=None, last=None) -> dict[str, Parcel]:
    order = _order(ORDER, "Beispielmarke Trinkflasche", first, last,
                   status=ParcelStatus.PRE_TRANSIT)
    return {ORDER: order}


def test_delivered_mail_never_turns_an_ordered_parcel_into_delivered():
    for days in ((None, None), (TODAY, None), _range()):
        parcels = _ordered(*days)
        mail = _brand_mail(day=None, status=ParcelStatus.DELIVERED)
        change = apply_update(parcels, mail, NOW)
        assert change.created and parcels[ORDER].status is ParcelStatus.PRE_TRANSIT, days
        assert parcels[ORDER].tracking_ref is None


@pytest.mark.parametrize(
    ("status", "mail_day", "order_days", "order_status", "merged"),
    [
        # an order that is only "Bestellt" needs a matching day
        (ParcelStatus.IN_TRANSIT, "today", "range", ParcelStatus.PRE_TRANSIT, True),
        (ParcelStatus.OUT_FOR_DELIVERY, None, "range", ParcelStatus.PRE_TRANSIT, True),
        (ParcelStatus.IN_TRANSIT, None, "range", ParcelStatus.PRE_TRANSIT, False),
        (ParcelStatus.IN_TRANSIT, "today", None, ParcelStatus.PRE_TRANSIT, False),
        (ParcelStatus.OUT_FOR_DELIVERY, None, None, ParcelStatus.PRE_TRANSIT, False),
        (ParcelStatus.PRE_TRANSIT, None, None, ParcelStatus.PRE_TRANSIT, False),
        # without a day on one side the order must be shipped
        (ParcelStatus.IN_TRANSIT, None, "range", ParcelStatus.IN_TRANSIT, True),
        (ParcelStatus.OUT_FOR_DELIVERY, None, None, ParcelStatus.IN_TRANSIT, True),
        (ParcelStatus.DELIVERED, None, None, ParcelStatus.IN_TRANSIT, True),
        # the day a mail was sent counts for "in Zustellung" and "zugestellt"
        (ParcelStatus.DELIVERED, None, "range", ParcelStatus.IN_TRANSIT, True),
        (ParcelStatus.OUT_FOR_DELIVERY, None, "later", ParcelStatus.IN_TRANSIT, False),
        (ParcelStatus.DELIVERED, None, "later", ParcelStatus.IN_TRANSIT, False),
        (ParcelStatus.DELIVERED, None, "earlier", ParcelStatus.IN_TRANSIT, False),
        # ... not for "unterwegs": that mail names no day
        (ParcelStatus.IN_TRANSIT, None, "later", ParcelStatus.IN_TRANSIT, True),
    ],
)
def test_brand_merge_day_and_shipping_rules(status, mail_day, order_days, order_status, merged):
    from datetime import timedelta

    days = {
        "range": _range(),
        None: (None, None),
        "later": (TODAY + timedelta(days=2), TODAY + timedelta(days=4)),
        "earlier": (TODAY - timedelta(days=5), TODAY - timedelta(days=1)),
    }[order_days]
    parcels = {ORDER: _order(ORDER, "Beispielmarke Trinkflasche", *days, status=order_status)}
    mail = _brand_mail(day=TODAY if mail_day else None, status=status)
    change = apply_update(parcels, mail, NOW)
    assert change.created is not merged
    assert (parcels[ORDER].tracking_ref == SHORT_DHL) is merged


# ----- v0.3.23 (issue 11): a postponed delivery may move a parcel back -----
_DHL = "999999999912"


def _dhl(status, sent, **more):
    return MailUpdate(number=_DHL, carrier="dhl", status=status, sent_at=sent, **more)


def test_a_postponed_delivery_takes_the_parcel_back_with_its_new_day():
    parcels: dict[str, Parcel] = {}
    morning = datetime(2026, 10, 7, 8, 0, tzinfo=BERLIN)
    today = _dhl(ParcelStatus.OUT_FOR_DELIVERY, morning, eta_date=date(2026, 10, 7))
    apply_update(parcels, today, NOW)
    late = datetime(2026, 10, 7, 17, 0, tzinfo=BERLIN)
    change = apply_update(
        parcels,
        _dhl(ParcelStatus.IN_TRANSIT, late, eta_date=date(2026, 10, 8), postponed=True),
        NOW,
    )
    assert change is not None and change.old_status is ParcelStatus.OUT_FOR_DELIVERY
    p = parcels[_DHL]
    assert p.status is ParcelStatus.IN_TRANSIT
    assert p.result.eta_date == date(2026, 10, 8)
    assert p.result.eta_from is None and p.result.eta_to is None


def test_the_same_mail_without_the_mark_does_not_move_the_parcel_back():
    parcels: dict[str, Parcel] = {}
    morning = datetime(2026, 10, 7, 8, 0, tzinfo=BERLIN)
    today = _dhl(ParcelStatus.OUT_FOR_DELIVERY, morning, eta_date=date(2026, 10, 7))
    apply_update(parcels, today, NOW)
    late = datetime(2026, 10, 7, 17, 0, tzinfo=BERLIN)
    update = _dhl(ParcelStatus.IN_TRANSIT, late, eta_date=date(2026, 10, 8))
    assert apply_update(parcels, update, NOW) is None
    assert parcels[_DHL].status is ParcelStatus.OUT_FOR_DELIVERY


@pytest.mark.parametrize("final", [ParcelStatus.DELIVERED, ParcelStatus.AWAITING_PICKUP])
def test_a_postponed_delivery_never_reopens_a_parcel_that_arrived(final):
    parcels: dict[str, Parcel] = {}
    done = datetime(2026, 10, 7, 12, 0, tzinfo=BERLIN)
    apply_update(parcels, _dhl(final, done), NOW)
    late = datetime(2026, 10, 7, 17, 0, tzinfo=BERLIN)
    update = _dhl(ParcelStatus.IN_TRANSIT, late, eta_date=date(2026, 10, 8), postponed=True)
    assert apply_update(parcels, update, NOW) is None
    assert parcels[_DHL].status is final


# ----- Amazon "Versuchte Zustellung": the order is taken back and has no day -----
def _attempt(title: str = "Beispielmarke Trinkflasche") -> MailUpdate:
    return MailUpdate(ORDER, "amazon", ParcelStatus.IN_TRANSIT, NOW.astimezone(BERLIN),
                      title=title, postponed=True, status_text="Zustellung versucht")


def test_an_attempted_delivery_takes_the_order_back_and_drops_its_day():
    out = ParcelStatus.OUT_FOR_DELIVERY
    parcels = {ORDER: _order(ORDER, "Beispielmarke Trinkflasche", TODAY, status=out)}
    change = apply_update(parcels, _attempt(), NOW)
    assert change is not None and change.old_status is out
    result = parcels[ORDER].result
    assert (result.status, result.status_text) == (ParcelStatus.IN_TRANSIT, "Zustellung versucht")
    assert result.eta_date is None
    assert [e.text for e in result.events] == ["Zustellung versucht"]


def test_an_attempted_delivery_is_never_a_further_shipment():
    # (an order that is "Versendet" already: the same status, yet the history tells it)
    parcels = {ORDER: _order(ORDER, "Beispielmarke Trinkflasche", TODAY)}
    change = apply_update(parcels, _attempt(title="Ein ganz anderer Artikel"), NOW)
    assert list(parcels) == [ORDER] and change.created is False
    result = parcels[ORDER].result
    assert result.status_text == "Zustellung versucht" and result.eta_date is None
    assert [e.text for e in result.events] == ["Zustellung versucht"]


@pytest.mark.parametrize("final", [ParcelStatus.DELIVERED, ParcelStatus.AWAITING_PICKUP])
def test_an_attempted_delivery_never_reopens_an_order_that_arrived(final):
    parcels = {ORDER: _order(ORDER, "Beispielmarke Trinkflasche", TODAY, status=final)}
    assert apply_update(parcels, _attempt(), NOW) is None
    assert parcels[ORDER].status is final

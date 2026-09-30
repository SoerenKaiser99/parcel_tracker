from datetime import date, datetime

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail.amazon import (
    order_number,
    parse_amazon,
    parse_amazon_legacy,
    stage_status,
    subject_status,
    subject_title,
)
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail


def _one(name: str, read_otp: bool = False):
    updates = parse_amazon(load_mail(name), read_otp)
    assert len(updates) == 1
    return updates[0]


def test_order_number():
    assert order_number("999-9156534-2587125") == "AMZ99991565342587125"


@pytest.mark.parametrize(
    ("subj", "expected"),
    [
        ("Bestellt: „4 Ersatz Metallplättchen...“", "4 Ersatz Metallplättchen…"),
        ('Geliefert: "Apple AirPods Pro 3...“', "Apple AirPods Pro 3…"),
        ("Zugestellt: 4 „Homematic IP Fenster- und...“", "Homematic IP Fenster- und…"),
        (
            "Bestellt: „DEMO Quantum - USV für...“ und 5 weitere Artikel",
            "DEMO Quantum - USV für… und 5 weitere Artikel",
        ),
        (
            "Versandt: „greate 16A CEE Adapter mit...“ und 1 weiterer Artikel",
            "greate 16A CEE Adapter mit… und 1 weiterer Artikel",
        ),
        ("Zustellung heute: Für deine Amazon-Lieferung ist ein Einmalpasswort erforderlich", None),
        ('Versendet: „Samsung 27" Monitor mit...“', 'Samsung 27" Monitor mit…'),
        ('Geliefert: "Samsung 27" Monitor...“', 'Samsung 27" Monitor…'),
        ('Bestellt: „Samsung 27" Monitor...“ und 2 weitere Artikel',
         'Samsung 27" Monitor… und 2 weitere Artikel'),
    ],
)
def test_subject_title(subj, expected):
    assert subject_title(subj) == expected


@pytest.mark.parametrize(
    ("subj", "expected"),
    [
        ("Bestellt: „x“", ParcelStatus.PRE_TRANSIT),
        ("Versendet: „x“", ParcelStatus.IN_TRANSIT),
        ("Versandt: „x“", ParcelStatus.IN_TRANSIT),
        ("In Zustellung: „x“", ParcelStatus.OUT_FOR_DELIVERY),
        ("Zustellung heute: Für deine Amazon-Lieferung …", ParcelStatus.OUT_FOR_DELIVERY),
        ('Geliefert: "x“', ParcelStatus.DELIVERED),
        ("Zugestellt: 4 „x“", ParcelStatus.DELIVERED),
        ("Deine Rücksendung", None),
    ],
)
def test_subject_status(subj, expected):
    assert subject_status(subj) is expected


def test_stage_status_counts_completed_stages():
    text = "[Abgeschlossen]\nBestellt\n[Abgeschlossen]\nVersendet\n[Ausstehend]\nIn Zustellung"
    assert stage_status(text) is ParcelStatus.IN_TRANSIT
    assert stage_status("Dein Paket wurde zugestellt!") is ParcelStatus.DELIVERED
    assert stage_status("nichts") is None


def test_ordered_arrives_tomorrow():
    u = _one("001_bestellbestaetigung_bestellt.eml")
    assert u.number == "AMZ99991565342587125"
    assert u.carrier == "amazon"
    assert u.status is ParcelStatus.PRE_TRANSIT
    assert u.title == "4 Ersatz Metallplättchen…"
    assert u.sent_at == datetime(2026, 7, 30, 18, 57, 10, tzinfo=BERLIN)
    assert u.eta_date == date(2026, 7, 31)
    assert u.eta_from is None and u.eta_to is None


def test_ordered_with_window_today_and_tomorrow():
    u = _one("002_bestellbestaetigung_bestellt.eml")
    assert u.eta_date == date(2026, 8, 20)
    assert u.eta_from == datetime(2026, 8, 20, 18, 0, tzinfo=BERLIN)
    assert u.eta_to == datetime(2026, 8, 20, 22, 0, tzinfo=BERLIN)
    u = _one("017_bestellbestaetigung_bestellt.eml")
    assert u.eta_date == date(2026, 9, 17)
    assert u.eta_from == datetime(2026, 9, 17, 7, 0, tzinfo=BERLIN)
    assert u.eta_to == datetime(2026, 9, 17, 11, 0, tzinfo=BERLIN)


def test_one_mail_with_three_orders_gives_three_updates():
    updates = parse_amazon(load_mail("009_bestellbestaetigung_bestellt.eml"), False)
    assert [u.number for u in updates] == [
        "AMZ99923739412707206",
        "AMZ99959817950965324",
        "AMZ99993317899923321",
    ]
    assert [u.title for u in updates] == [
        "Homematic IP Fenster- und Türkontakt – verdeckter Einbau",
        "2 Jahre Garantieverlängerung für ein Heimmedienprodukt von…",
        "DEMO Quantum - USV für Computer, 2200 VA / 1320 Watt, 230v",
    ]
    assert all(u.status is ParcelStatus.PRE_TRANSIT and u.eta_date is None for u in updates)


def test_shipped_versendet_and_versandt():
    u = _one("074_versandbestaetigung_versendet.eml")
    assert (u.number, u.status, u.eta_date) == (
        "AMZ99991565342587125",
        ParcelStatus.IN_TRANSIT,
        date(2026, 7, 31),
    )
    u = _one("073_versandbestaetigung_versandt.eml")
    assert u.number == "AMZ99976861735742021"
    assert u.title == "greate 16A CEE Adapter mit… und 1 weiterer Artikel"
    assert u.eta_date == date(2026, 7, 31)  # sent 03:28 Berlin on 31.07., "Ankunft heute"


def test_out_for_delivery_with_hyphen_window():
    u = _one("051_shipment_tracking_in_zustellung.eml")
    assert u.status is ParcelStatus.OUT_FOR_DELIVERY
    assert u.eta_from == datetime(2026, 9, 7, 14, 0, tzinfo=BERLIN)
    assert u.eta_to == datetime(2026, 9, 7, 16, 0, tzinfo=BERLIN)


def test_otp_only_when_enabled():
    assert _one("096_shipment_tracking_zustellung_heute_f_r_d.eml").delivery_code is None
    u = _one("096_shipment_tracking_zustellung_heute_f_r_d.eml", read_otp=True)
    assert u.delivery_code == "123456"
    assert u.number == "AMZ99905626221455530"
    assert u.status is ParcelStatus.OUT_FOR_DELIVERY
    assert u.title == "Apple AirPods Pro 3 Kabellose In‑Ear Kopfhörer, Aktive Gerä…"
    assert u.eta_date == date(2026, 8, 20)


def test_delivered_uses_mail_time():
    u = _one("023_order_update_geliefert.eml")
    assert u.status is ParcelStatus.DELIVERED
    assert u.number == "AMZ99905626221455530"
    assert u.delivered_at == datetime(2026, 8, 20, 21, 3, 46, tzinfo=BERLIN)
    u = _one("094_order_update_zugestellt.eml")
    assert u.title == "Würth 2K Cuttermesser 18mm… und 2 weitere Artikel"


def test_legacy_format_yields_ups_number():
    updates = parse_amazon_legacy(load_mail("046_versandbestaetigung_ihre_amazon_de_beste.eml"))
    assert len(updates) == 1
    u = updates[0]
    assert (u.number, u.carrier, u.status) == (
        "1Z999AA11048020581",
        "ups",
        ParcelStatus.IN_TRANSIT,
    )
    assert u.title == "LED-Leuchtstoffröhre G13 T8…"
    assert u.eta_date == date(2016, 12, 14)
    other = parse_amazon_legacy(load_mail("047_versandbestaetigung_ihre_amazon_de_beste.eml"))
    assert other[0].number == "1Z999AA11128489401"


def test_mail_without_order_number_gives_nothing():
    msg = load_mail("001_bestellbestaetigung_bestellt.eml")
    msg.set_content("Bestellt: kein Bestellnummer-Block")
    assert parse_amazon(msg, False) == []


def test_legacy_title_keeps_inch_mark():
    msg = load_mail("046_versandbestaetigung_ihre_amazon_de_beste.eml")
    msg.replace_header(
        "Subject", 'Ihre Amazon.de Bestellung von "Samsung 27" Monitor..." wurde versandt!'
    )
    [u] = parse_amazon_legacy(msg)
    assert u.title == 'Samsung 27" Monitor…'

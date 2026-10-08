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
        (
            "Bestellt: „DEMO Quantum - USV für...“ und 1 mehr Artikel",
            "DEMO Quantum - USV für… und 1 weiterer Artikel",
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


def test_orders_in_amazons_own_text_part_are_named_after_their_first_item():
    # "* title" lines instead of "[title]<link>"; the subject names only the first order.
    updates = parse_amazon(load_mail("124_bestellbestaetigung_bestellt.eml"), False)
    assert [u.number for u in updates] == ["AMZ99927581034893895", "AMZ99900481738659171"]
    assert [u.title for u in updates] == [
        "Bosch Professional 1x Expert ‘Hollow Brick’ S 1543 HM Säbel…",
        "Bosch PRO 18V System Akku Säbelsäge GSA 18V-24 (inkl. S922E…",
    ]
    assert all(u.status is ParcelStatus.PRE_TRANSIT for u in updates)


def test_each_order_of_one_mail_has_its_own_delivery_day():
    # "Zustellung: 13. Oktober" above the first order number, "… 15. Oktober" above the second.
    updates = parse_amazon(load_mail("124_bestellbestaetigung_bestellt.eml"), False)
    assert [u.eta_date for u in updates] == [date(2026, 10, 13), date(2026, 10, 15)]
    assert all(u.eta_latest is None and u.eta_from is None and u.eta_to is None for u in updates)


def test_an_order_without_a_day_keeps_the_day_of_the_order_before_it():
    msg = load_mail("124_bestellbestaetigung_bestellt.eml")
    msg.set_content(msg.get_content().replace("Zustellung: 15. Oktober", ""))
    updates = parse_amazon(msg, False)
    assert [u.eta_date for u in updates] == [date(2026, 10, 13), date(2026, 10, 13)]


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


def _eta(line: str, mail_date: str = "Tue, 30 Sep 2026 19:49:54 +0000"):
    msg = load_mail("098_bestellbestaetigung_bestellt_zeitraum.eml")
    text = msg.get_body(preferencelist=("plain",)).get_content()
    msg.set_content(text.replace("Zustellung: 2. Oktober - 5. Oktober", line))
    msg.replace_header("Date", mail_date)
    [u] = parse_amazon(msg, False)
    return u.eta_date, u.eta_latest


def test_range_fixture():
    u = _one("098_bestellbestaetigung_bestellt_zeitraum.eml")
    assert u.number == "AMZ99960312290000000"
    assert u.status is ParcelStatus.PRE_TRANSIT
    assert u.title == "MAS Premium Aderleitung H07…"
    assert (u.eta_date, u.eta_latest) == (date(2026, 10, 2), date(2026, 10, 5))
    assert u.eta_from is None and u.eta_to is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Zustellung: 2. Oktober - 5. Oktober", (date(2026, 10, 2), date(2026, 10, 5))),
        ("Zustellung: 2. Oktober – 5. Oktober", (date(2026, 10, 2), date(2026, 10, 5))),
        ("Zustellung: Freitag, 3. Oktober", (date(2026, 10, 3), None)),
        ("Ankunft 3. Oktober", (date(2026, 10, 3), None)),
        ("Ankunft Freitag, 3. Oktober", (date(2026, 10, 3), None)),
        ("Zustellung: Do., 2. Okt. – Mo., 6. Okt.", (date(2026, 10, 2), date(2026, 10, 6))),
        ("Zustellung: 30. Sep. – 2. Okt.", (date(2026, 9, 30), date(2026, 10, 2))),
        ("Zustellung: 30. September - 2. Oktober", (date(2026, 9, 30), date(2026, 10, 2))),
        ("Ankunft 12. Mär.", (date(2027, 3, 12), None)),
        ("Ankunft Freitag", (date(2026, 10, 2), None)),  # mail is a Wednesday
        ("Ankunft Mittwoch", (date(2026, 10, 7), None)),  # same weekday: a week later
        ("Zustellung: Montag - Mittwoch", (date(2026, 10, 5), date(2026, 10, 7))),
        ("Zustellung: 31. Februar", (None, None)),
        ("Zustellung: bald", (None, None)),
    ],
)
def test_date_forms(line, expected):
    assert _eta(line) == expected


def test_range_rolls_into_next_year():
    mail = "Sun, 28 Dec 2026 10:00:00 +0000"
    assert _eta("Zustellung: 2. Januar - 5. Januar", mail) == (date(2027, 1, 2), date(2027, 1, 5))
    assert _eta("Zustellung: 30. Dezember - 2. Januar", mail) == (
        date(2026, 12, 30),
        date(2027, 1, 2),
    )


def test_recent_past_date_keeps_mail_year():
    mail = "Sun, 28 Dec 2026 10:00:00 +0000"
    assert _eta("Ankunft 20. Dezember", mail) == (date(2026, 12, 20), None)


def test_today_tomorrow_and_windows_unchanged():
    u = _one("002_bestellbestaetigung_bestellt.eml")
    assert u.eta_date == date(2026, 8, 20) and u.eta_latest is None
    assert u.eta_from == datetime(2026, 8, 20, 18, 0, tzinfo=BERLIN)
    assert _eta("Ankunft morgen") == (date(2026, 10, 1), None)


@pytest.mark.parametrize(
    ("name", "number", "ref", "eta", "title"),
    [
        (
            "100_versandbestaetigung_ihre_amazon_de_beste.eml",
            "AMZ99942584722619639",
            "99992958672143",
            date(2017, 7, 6),
            "Logitech Slim Folio…",
        ),
        (
            "101_versandbestaetigung_ihre_amazon_de_beste.eml",
            "AMZ99942535315689263",
            "99995859260802",
            date(2018, 1, 20),
            "Raspberry Pi 3 Model B…",
        ),
        (
            "102_versandbestaetigung_ihre_amazon_de_beste.eml",
            "AMZ99900779704106459",
            "H9999978276078000836",
            date(2020, 4, 2),
            "Profi Cook SV-1112… und 1 weiterer Artikel",
        ),
    ],
)
def test_legacy_hermes_keeps_the_order_and_refers_to_hermes(name, number, ref, eta, title):
    [u] = parse_amazon_legacy(load_mail(name))
    assert (u.number, u.carrier, u.status) == (number, "amazon", ParcelStatus.IN_TRANSIT)
    assert (u.tracking_ref, u.tracking_carrier) == (ref, "hermes")
    assert (u.eta_date, u.title) == (eta, title)


def test_legacy_14_digits_without_hermes_stay_an_order():
    msg = load_mail("100_versandbestaetigung_ihre_amazon_de_beste.eml")
    text = msg.get_body(preferencelist=("plain",)).get_content()
    msg.set_content(text.replace("mit Hermes versandt", "versandt"))
    [u] = parse_amazon_legacy(msg)
    assert (u.number, u.tracking_ref, u.tracking_carrier) == (
        "AMZ99942584722619639",
        None,
        None,
    )


def test_legacy_ups_numbers_keep_their_own_parcel():
    [u] = parse_amazon_legacy(load_mail("046_versandbestaetigung_ihre_amazon_de_beste.eml"))
    assert (u.carrier, u.tracking_ref) == ("ups", None)

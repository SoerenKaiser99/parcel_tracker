from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.base import sent_at
from custom_components.parcel_tracker.mail.shipping import (
    AMAZON_DHL_NAME,
    parse_dhl_mail,
    parse_generic,
    parse_ups_mail,
)
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail


def _msg(subject: str, body: str, from_: str) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = from_
    msg["Subject"] = subject
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content(body)
    return msg


def test_dhl_amazon_shipment_with_day_and_month():
    [u] = parse_dhl_mail(load_mail("045_noreply_ihre_amazon_sendung_ist_unterweg.eml"))
    assert (u.number, u.carrier) == ("JJD000012978217606560", "dhl")
    assert u.status is ParcelStatus.IN_TRANSIT
    assert u.shop == "amazon"
    assert u.title == AMAZON_DHL_NAME == "Amazon-Sendung (DHL)"
    assert u.eta_date == date(2026, 7, 31)
    assert u.eta_from is None


def test_dhl_today_window():
    [u] = parse_dhl_mail(load_mail("049_noreply_ihre_amazon_sendung_kommt_heute_.eml"))
    assert u.status is ParcelStatus.OUT_FOR_DELIVERY
    assert u.shop == "amazon"
    assert u.eta_date == date(2026, 7, 31)
    assert u.eta_from == datetime(2026, 7, 31, 13, 10, tzinfo=BERLIN)
    assert u.eta_to == datetime(2026, 7, 31, 14, 40, tzinfo=BERLIN)


def test_dhl_day_without_month_and_not_amazon():
    msg = _msg(
        "Ihre Sendung ist unterwegs",
        "Ihre Sendung wird Ihnen voraussichtlich\nam Freitag, den 2.\nzugestellt.\n"
        "00340999999999999917",
        "DHL Paket <noreply@dhl.de>",
    )
    [u] = parse_dhl_mail(msg)
    assert u.number == "00340999999999999917"
    assert u.shop is None
    assert u.title is None
    assert u.eta_date == date(2026, 10, 2)


def test_dhl_without_number_gives_nothing():
    assert parse_dhl_mail(_msg("Hallo", "kein Paket", "DHL Paket <noreply@dhl.de>")) == []


def test_ups_announcement():
    [u] = parse_ups_mail(load_mail("070_pkginfo_ups_versandbenachrichtigung_kont.eml"))
    assert (u.number, u.carrier) == ("1Z999AA11026832876", "ups")
    assert u.status is ParcelStatus.PRE_TRANSIT
    assert u.eta_date == date(2019, 3, 6)
    assert u.title == "Beispiel Versand GmbH"


def test_ups_delivered_with_time():
    [u] = parse_ups_mail(load_mail("071_pkginfo_ups_zustellbenachrichtigung_kont.eml"))
    assert u.status is ParcelStatus.DELIVERED
    assert u.delivered_at == datetime(2019, 3, 5, 13, 43, tzinfo=BERLIN)
    assert u.title is None


def test_generic_takes_only_safe_numbers_and_no_unknown_sender_name():
    msg = _msg(
        "Deine Bestellung ist unterwegs",
        "Sendungsnummer 00340999999999999917, Kundennummer 09999999999901",
        "Kaffeerösterei Beispiel <shop@example.org>",
    )
    updates = parse_generic(msg)
    assert [(u.carrier, u.number, u.title, u.status) for u in updates] == [
        ("dhl", "00340999999999999917", None, None)
    ]


def test_generic_dpd_needs_dpd_in_text_and_a_label():
    msg = _msg("Versand mit DPD", "Paketnummer 09999999999901", "Shop <shop@example.org>")
    assert [(u.carrier, u.number) for u in parse_generic(msg)] == [("dpd", "09999999999901")]
    msg = _msg("Versand", "Paketnummer 09999999999901", "Shop <shop@example.org>")
    assert parse_generic(msg) == []


def test_generic_dpd_probe_yields_exactly_one_number():
    body = (
        "Vielen Dank für deine Bestellung.\n"
        "Bestellnummer 10105012345678\n"
        "Dein Paket ist mit DPD unterwegs.\n"
        "Paketnummer: 09999999999901\n"
        "Fragen? Hotline 08001234567890\n"
    )
    msg = _msg("Deine Bestellung ist unterwegs", body, "Shop <shop@example.org>")
    assert [(u.carrier, u.number) for u in parse_generic(msg)] == [("dpd", "09999999999901")]


def test_generic_mail_from_dpd_takes_unlabelled_numbers():
    msg = _msg(
        "Ihr Paket kommt heute",
        "Ihr Paket 09999999999901 kommt heute.",
        "DPD <noreply@service.dpd.de>",
    )
    # the carrier's display name is no parcel name
    assert [(u.carrier, u.number, u.title) for u in parse_generic(msg)] == [
        ("dpd", "09999999999901", None)
    ]


def test_forwarded_mail_never_takes_the_sender_name():
    msg = _msg(
        "WG: Ihr Paket kommt heute",
        "Ihr Paket 09999999999901 kommt heute.\nDHL: 00340999999999999917",
        "Max Mustermann <noreply@service.dpd.de>",
    )
    updates = parse_generic(msg)
    assert {u.number for u in updates} == {"09999999999901", "00340999999999999917"}
    assert all(u.title is None for u in updates)


def test_forwarded_shop_mail_has_no_name():
    msg = _msg(
        "Fwd: Versandbestätigung",
        "---------- Forwarded message ---------\nVon: Shop <shop@example.org>\n"
        "Ihre DHL-Sendungsnummer: JJD000012978217606560",
        "Max Mustermann <max@example.org>",
    )
    assert [(u.carrier, u.number, u.title) for u in parse_generic(msg)] == [
        ("dhl", "JJD000012978217606560", None)
    ]


def test_ups_shipper_names_the_shop():
    msg = load_mail("070_pkginfo_ups_versandbenachrichtigung_kont.eml")
    [u] = parse_ups_mail(msg)
    assert u.shop is None
    text = msg.get_body(preferencelist=("plain",)).get_content()
    msg.set_content(text.replace("Beispiel Versand GmbH", "Amazon EU S.a.r.L."))
    [u] = parse_ups_mail(msg)
    assert (u.shop, u.title) == ("amazon", "Amazon EU S.a.r.L.")


@pytest.mark.parametrize(
    ("shipper", "title"),
    [
        ("Erika Musterfrau", None),  # a person is never stored
        ("Musterfrau Erika c/o Max Mustermann", None),
        ("Beispiel Versand GmbH Erika Musterfrau", "Beispiel Versand GmbH"),
        ("Erika Musterfrau, Beispiel Versand GmbH", "Beispiel Versand GmbH"),
        ("Zalando", "Zalando"),
        ("UPS Customer Service", None),
    ],
)
@pytest.mark.parametrize("name", [
    "070_pkginfo_ups_versandbenachrichtigung_kont.eml",
])
def test_ups_shipper_goes_through_the_naming_gate(shipper, title, name):
    from dataclasses import asdict

    msg = load_mail(name)
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Beispiel Versand GmbH" in text
    msg.set_content(text.replace("Beispiel Versand GmbH", shipper))
    [u] = parse_ups_mail(msg)
    assert u.title == title
    if title is None:
        assert "Musterfrau" not in repr(asdict(u)) and "Mustermann" not in repr(asdict(u))


# ----- v0.3.15: every dhl.de sender, the shop in the subject, international numbers -----
NEW_LAYOUT = "113_dhl_paketankuendigung_amazon_unterwegs.eml"
INTERNATIONAL = "118_dhl_international_unterwegs.eml"
S10 = "CQ999999901DE"


def test_dhl_second_sender_is_routed_to_the_dhl_parser():
    """paketankuendigung@dhl.de; its text part carries HTML table markup."""
    msg = load_mail(NEW_LAYOUT)
    assert "paketankuendigung@dhl.de" in str(msg["From"])
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (
        "00340999999999999901", "dhl", ParcelStatus.IN_TRANSIT,
    )
    assert (u.shop, u.title) == ("amazon", AMAZON_DHL_NAME)
    # "am Montag, den …" is the day the mail itself was sent.
    assert u.eta_date == sent_at(msg).date()
    assert (u.eta_from, u.eta_to, u.delivered_at) == (None, None, None)


def test_dhl_international_mail_names_the_shop_and_invents_no_day():
    msg = load_mail(INTERNATIONAL)
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (S10, "dhl", ParcelStatus.IN_TRANSIT)
    assert (u.title, u.shop) == ("Beispiel GmbH", None)
    assert (u.eta_date, u.eta_latest, u.eta_from, u.eta_to, u.delivered_at) == (None,) * 5


@pytest.mark.parametrize(
    "address", ["noreply@dhl.de", "paketankuendigung@dhl.de", "service@dhl.de", "x@mail.dhl.de"]
)
def test_every_dhl_sender_reads_status_and_s10_number(address):
    body = "Ihre Sendung wird Ihnen voraussichtlich\nam Freitag, den 2.\nzugestellt.\n" + S10
    [u] = parse_mail(_msg("Ihre Sendung ist unterwegs", body, f"DHL <{address}>")).updates
    assert (u.number, u.carrier, u.status) == (S10, "dhl", ParcelStatus.IN_TRANSIT)
    assert u.eta_date == date(2026, 10, 2)


def test_s10_number_counts_only_in_mails_from_dhl():
    body = f"Ihre Sendung {S10} ist unterwegs."
    assert parse_mail(_msg("Versand", body, "Shop <shop@example.org>")).updates == []
    assert parse_mail(_msg("Versand", body, "DHL <noreply@notdhl.de>")).updates == []
    # a national number wins over an international one named in the same mail
    both = f"{S10}\n00340999999999999917"
    [u] = parse_dhl_mail(_msg("Ihre Sendung ist unterwegs", both, "DHL <noreply@dhl.de>"))
    assert u.number == "00340999999999999917"


@pytest.mark.parametrize(
    ("subject", "title", "shop", "status"),
    [
        ("Ihre Beispiel GmbH Sendung ist unterwegs", "Beispiel GmbH", None,
         ParcelStatus.IN_TRANSIT),
        ("Ihre Zalando Sendung kommt heute", "Zalando", None, ParcelStatus.OUT_FOR_DELIVERY),
        ("Ihre eBay Sendung ist unterwegs", "eBay", "ebay", ParcelStatus.IN_TRANSIT),
        ("Ihre Amazon Sendung kommt heute", AMAZON_DHL_NAME, "amazon",
         ParcelStatus.OUT_FOR_DELIVERY),
        ("Ihre Beispiel GmbH Sendung kommt morgen", "Beispiel GmbH", None,
         ParcelStatus.IN_TRANSIT),
        ("Ihre Beispiel GmbH Sendung wird heute zugestellt", "Beispiel GmbH", None,
         ParcelStatus.OUT_FOR_DELIVERY),
        ("Ihre Beispiel GmbH Sendung liegt zur Abholung bereit", "Beispiel GmbH", None,
         ParcelStatus.AWAITING_PICKUP),
        ("Ihre Erika Beispiel Sendung liegt zur Abholung bereit", None, None,
         ParcelStatus.AWAITING_PICKUP),
        # a person, a word that is no shop, no shop at all: no name
        ("Ihre Erika Beispiel Sendung ist unterwegs", None, None, ParcelStatus.IN_TRANSIT),
        ("Ihre DHL Sendung ist unterwegs", None, None, ParcelStatus.IN_TRANSIT),
        ("Ihre Sendung ist unterwegs", None, None, ParcelStatus.IN_TRANSIT),
        # nothing behind the legal form is taken
        ("Ihre Beispiel Handels OHG (AT-B2C) Erika Musterfrau Sendung ist unterwegs",
         "Beispiel Handels OHG", None, ParcelStatus.IN_TRANSIT),
        ("Ihre Beispiel GmbH Max Mustermann Sendung kommt heute", "Beispiel GmbH", None,
         ParcelStatus.OUT_FOR_DELIVERY),
    ],
)
def test_dhl_subject_names_the_shop_only_through_the_naming_gate(subject, title, shop, status):
    [u] = parse_dhl_mail(_msg(subject, "00340999999999999917", "DHL <noreply@dhl.de>"))
    assert (u.title, u.shop, u.status) == (title, shop, status)


def test_dhl_shop_name_is_cut_and_never_taken_from_a_forwarded_mail():
    long_name = "Beispiel Versandhandel für Haus und Garten und Werkstatt und Hobby GmbH"
    [u] = parse_dhl_mail(
        _msg(f"Ihre {long_name} Sendung ist unterwegs", S10, "DHL <noreply@dhl.de>")
    )
    assert len(u.title) == 60 and u.title.endswith("…") and long_name.startswith(u.title[:-1])
    [u] = parse_dhl_mail(
        _msg("WG: Ihre Beispiel GmbH Sendung ist unterwegs", S10, "Max Mustermann <noreply@dhl.de>")
    )
    assert u.title is None


# ----- v0.3.15 review: the subject decides the status of a DHL mail -----
DHL_NUMBER = "00340999999999999917"
WINDOW_BODY = f"Ihre Sendung kommt heute zwischen 13:10 - 14:40 Uhr.\n{DHL_NUMBER}\n"
DAY_BODY = (
    f"Ihre Sendung wird Ihnen voraussichtlich\nam Freitag, den 2.\nzugestellt.\n{DHL_NUMBER}\n"
)


@pytest.mark.parametrize(
    ("subject", "status"),
    [
        ("Ihre Sendung ist unterwegs", ParcelStatus.IN_TRANSIT),
        ("Ihre Beispiel GmbH Sendung ist unterwegs", ParcelStatus.IN_TRANSIT),
        ("Ihre Sendung kommt heute", ParcelStatus.OUT_FOR_DELIVERY),
        ("Ihre Sendung kommt heute zwischen 13:10 - 14:40 Uhr", ParcelStatus.OUT_FOR_DELIVERY),
        ("Ihre Sendung wurde zugestellt", ParcelStatus.DELIVERED),
        ("Ihre Beispiel GmbH Sendung wurde erfolgreich zugestellt", ParcelStatus.DELIVERED),
        # no delivery
        ("Ihre Sendung wurde an den gewünschten Ablageort zugestellt", ParcelStatus.DELIVERED),
        ("Ihre Beispiel GmbH Sendung wurde heute an einen Nachbarn im Haus zugestellt",
         ParcelStatus.DELIVERED),
        # waits for the recipient
        ("Ihre Sendung wurde an Packstation 123 zugestellt", ParcelStatus.AWAITING_PICKUP),
        ("Ihre Sendung wurde in die Filiale Beispielweg 1 zugestellt",
         ParcelStatus.AWAITING_PICKUP),
        ("Ihre Sendung liegt in der Packstation 123 zur Abholung bereit",
         ParcelStatus.AWAITING_PICKUP),
        ("Ihre Sendung liegt zur Abholung bereit", ParcelStatus.AWAITING_PICKUP),
        ("Ihre Sendung wird heute zugestellt", ParcelStatus.OUT_FOR_DELIVERY),
        ("Ihre Beispiel GmbH Sendung wird heute zwischen 13:10 - 14:40 Uhr zugestellt",
         ParcelStatus.OUT_FOR_DELIVERY),
        ("Ihre Sendung kommt morgen", ParcelStatus.IN_TRANSIT),
        ("Ihre Sendung wird morgen zugestellt", ParcelStatus.IN_TRANSIT),
        # no delivery, but a mail about a parcel: it is on its way (as before v0.3.15)
        ("Ihre Sendung wurde nicht zugestellt", ParcelStatus.IN_TRANSIT),
        ("Ihre Sendung konnte nicht zugestellt werden", ParcelStatus.IN_TRANSIT),
        ("Ihre Sendung wurde leider noch nicht zugestellt", ParcelStatus.IN_TRANSIT),
        ("Ihre Sendung liegt nicht zur Abholung bereit", ParcelStatus.IN_TRANSIT),
        ("Das Zustellfoto zu Ihrer Sendung", ParcelStatus.IN_TRANSIT),
        ("Neuigkeiten zu Ihrer Sendung", ParcelStatus.IN_TRANSIT),
        ("Ihre Sendung wurde mit sehr vielen weiteren Wörtern dazwischen irgendwann zugestellt",
         ParcelStatus.IN_TRANSIT),
        # a question (survey) and a subject that names no "Sendung" tell no status
        ("Wurde Ihre Sendung zugestellt? Ihre Meinung zählt", None),
        ("Wie zufrieden waren Sie mit der Zustellung Ihrer Sendung?", None),
        ("Ihr Abholcode für die Packstation", None),
        ("Ihr Paket wartet", None),
    ],
)
@pytest.mark.parametrize("body", [WINDOW_BODY, DAY_BODY])
def test_dhl_status_comes_only_from_the_subject(subject, status, body):
    msg = _msg(subject, body, "DHL Paket <noreply@dhl.de>")
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (DHL_NUMBER, "dhl", status)
    if status is ParcelStatus.DELIVERED:
        assert u.delivered_at == sent_at(msg)
        assert (u.eta_date, u.eta_from, u.eta_to) == (None, None, None)
    else:
        assert u.delivered_at is None
    lower = subject.lower()
    if status is ParcelStatus.OUT_FOR_DELIVERY:
        assert u.eta_date == sent_at(msg).date()
        assert (u.eta_from is not None) is (body is WINDOW_BODY)
    elif "morgen" in lower:
        assert u.eta_date == sent_at(msg).date() + timedelta(days=1)
        assert (u.eta_from, u.eta_to) == (None, None)
    elif "ist unterwegs" in lower:
        assert u.eta_date == (date(2026, 10, 2) if body is DAY_BODY else None)
    else:
        # only "ist unterwegs" reads the day the body names
        assert (u.eta_date, u.eta_from, u.eta_to) == (None, None, None)


@pytest.mark.parametrize(
    "subject",
    [
        "Ihre Sendung liegt in der Packstation 123 zur Abholung bereit",
        "Ihr Abholcode für die Packstation",
    ],
)
def test_dhl_packstation_mail_creates_the_parcel_and_never_reads_the_code(subject):
    from dataclasses import asdict

    from custom_components.parcel_tracker.mail.apply import apply_update

    body = (
        f"Ihre Sendung {DHL_NUMBER} liegt in der Packstation 123 bereit.\n"
        "Abholcode: 4711\nmTAN 9182\nPostNummer 99999901\n"
    )
    msg = _msg(subject, body, "DHL Paket <noreply@dhl.de>")
    status = ParcelStatus.AWAITING_PICKUP if "bereit" in subject else None
    for read_otp in (False, True):
        [u] = parse_mail(msg, read_otp).updates
        assert (u.number, u.status, u.delivery_code, u.title) == (DHL_NUMBER, status, None, None)
        for secret in ("4711", "9182", "99999901", "Packstation"):
            assert secret not in repr(asdict(u)), secret
    parcels: dict = {}
    change = apply_update(parcels, u, sent_at(msg))
    assert change.created
    parcel = parcels[DHL_NUMBER]
    assert (parcel.status, parcel.delivery_code, parcel.name) == (status, None, None)
    assert "4711" not in repr(parcel.to_dict()) and "Packstation" not in repr(parcel.to_dict())


def test_dhl_status_less_mail_never_moves_a_parcel():
    from custom_components.parcel_tracker.mail.apply import apply_update

    parcels: dict = {}
    first = _msg("Ihre Sendung kommt heute", WINDOW_BODY, "DHL Paket <noreply@dhl.de>")
    [u] = parse_mail(first).updates
    apply_update(parcels, u, sent_at(first))
    survey = _msg(
        "Wie zufrieden waren Sie mit der Zustellung Ihrer Sendung?", DAY_BODY,
        "DHL Paket <noreply@dhl.de>",
    )
    [u] = parse_mail(survey).updates
    assert apply_update(parcels, u, sent_at(survey)) is None
    assert parcels[DHL_NUMBER].status is ParcelStatus.OUT_FOR_DELIVERY


# ----- v0.3.15 review: a carrier's display name never names a parcel -----
@pytest.mark.parametrize(
    ("from_", "title"),
    [
        ("📦 DHL Paketankündigung <paketankuendigung@dhl.de>", None),
        ("DHL Zustell-Update <noreply@dhl.de>", None),
        ("DHL Paket <noreply@dhl.de>", None),
        ("UPS Quantum View <pkginfo@ups.com>", None),
        ("DPD <noreply@service.dpd.de>", None),
        ("Paketankündigung <info@amazon.de>", None),
        ("Amazon Logistics <versand@amazon.de>", None),
        ("Erika Musterfrau <erika@amazon.de>", None),
        ("Amazon.de <versandbestaetigung@amazon.de>", "Amazon"),
    ],
)
def test_generic_never_takes_a_carrier_display_name(from_, title):
    body = "Sendungsnummer 00340999999999999917, 1Z999AA11026832876, Paket 09999999999901"
    updates = parse_generic(_msg("Neuigkeiten zu Ihrer Sendung", body, from_))
    assert updates and all(u.title == title for u in updates)


@pytest.mark.parametrize(
    "from_",
    ["📦 DHL Paketankündigung <paketankuendigung@dhl.de>", "DHL Zustell-Update <noreply@dhl.de>"],
)
def test_dhl_mail_without_a_status_is_not_named_after_its_sender(from_):
    for subject, status in (
        ("Ihr Abholcode für die Packstation", None),
        ("Neuigkeiten zu Ihrer Sendung", ParcelStatus.IN_TRANSIT),
    ):
        [u] = parse_mail(_msg(subject, DAY_BODY, from_)).updates
        assert (u.number, u.status, u.title, u.eta_date) == (DHL_NUMBER, status, None, None)


# ----- v0.3.15: zustellung@dhl.de, 12-digit numbers behind their label -----
DELIVERY_UPDATE = "120_dhl_zustellung_kommt_heute.eml"
FORWARDED = "121_dhl_weitergeleitet_kommt_heute.eml"
SHORT = "999999999901"


def test_delivery_update_mail_with_a_12_digit_number_in_table_markup():
    """zustellung@dhl.de: label and number in separate cells of a text part with markup."""
    msg = load_mail(DELIVERY_UPDATE)
    assert "zustellung@dhl.de" in str(msg["From"])
    assert "<td" in msg.get_body(("plain",)).get_content()
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (SHORT, "dhl", ParcelStatus.OUT_FOR_DELIVERY)
    assert u.eta_date == sent_at(msg).date()
    assert (u.eta_from, u.eta_to, u.delivered_at) == (None, None, None)
    # the subject names a carrier's subsidiary, a warehouse and a shop: no name
    assert (u.title, u.shop) == (None, None)


def test_forwarded_dhl_mail_only_names_the_parcel():
    """Forwarded from a private address: the generic path, no status, never a name."""
    msg = load_mail(FORWARDED)
    assert str(msg["Subject"]).startswith("Fw: ") and "dhl.de" not in str(msg["From"])
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status, u.title) == (
        "00340999999999999902", "dhl", None, None,
    )
    assert u.sent_at == sent_at(msg) and u.sent_at.date() == sent_at(msg).date()
    assert (u.eta_date, u.eta_from, u.delivered_at) == (None, None, None)


@pytest.mark.parametrize(
    "body",
    [
        f"Ihre Sendungsnummer\n{SHORT}\n",
        f"Ihre Sendungsnummer: {SHORT}\n",
        f"Sendungsnummer {SHORT}.\n",
        f"Ihre Sendungsnummer\n\n   {SHORT}   \n",
        f"<table><tr><td style='x'>\n Ihre Sendungsnummer\n</td></tr>\n<tr><td>\n {SHORT}\n</td>"
        "</tr></table>",
        f"<p><b>Sendungsnummer</b>:&nbsp;<span>{SHORT}</span></p>",
    ],
)
def test_12_digit_dhl_number_is_read_behind_its_label(body):
    msg = _msg("Ihre Sendung kommt heute", body, "DHL Zustell-Update <zustellung@dhl.de>")
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == (SHORT, "dhl", ParcelStatus.OUT_FOR_DELIVERY)
    assert u.eta_date == sent_at(msg).date()


@pytest.mark.parametrize(
    "body",
    [
        f"Ihre Sendung {SHORT} kommt heute.",  # no label
        f"Artikelnummer {SHORT}",
        f"Bestellnummer: {SHORT}\nIhre Sendungsnummer finden Sie in der App.",
        f"Ihre Sendungsnummer\nfinden Sie hier.\n{SHORT}",  # not directly behind the label
        f"Sendungsnummer {SHORT}9",  # 13 digits
        f"Sendungsnummer 9{SHORT}99",  # 15 digits
        f"Kundennummer\n{SHORT}",
    ],
)
def test_12_digits_without_the_label_are_no_dhl_number(body):
    msg = _msg("Ihre Sendung kommt heute", body, "DHL Zustell-Update <zustellung@dhl.de>")
    assert parse_mail(msg).updates == []


def test_12_digit_number_counts_only_in_mails_from_dhl():
    body = f"DHL bringt Ihr Paket.\nIhre Sendungsnummer\n{SHORT}\n"
    for from_ in ("Shop <shop@example.org>", "DHL <noreply@notdhl.de>", "eBay <ebay@ebay.com>"):
        assert parse_mail(_msg("Ihre Sendung kommt heute", body, from_)).updates == []
    # the long national number wins over a 12-digit one in the same mail
    both = f"Ihre Sendungsnummer\n{SHORT}\n{DHL_NUMBER}\n"
    [u] = parse_mail(_msg("Ihre Sendung kommt heute", both, "DHL <zustellung@dhl.de>")).updates
    assert u.number == DHL_NUMBER


def test_12_digit_dhl_parcel_is_polled_at_dhl_and_can_be_added_by_hand():
    from custom_components.parcel_tracker.carriers.base import Match
    from custom_components.parcel_tracker.carriers.dhl import DhlCarrier
    from custom_components.parcel_tracker.carriers.dpd import DpdCarrier
    from custom_components.parcel_tracker.carriers.gls import GlsCarrier
    from custom_components.parcel_tracker.carriers.hermes import HermesCarrier
    from custom_components.parcel_tracker.carriers.ups import UpsCarrier
    from custom_components.parcel_tracker.detect import candidates
    from custom_components.parcel_tracker.mail.apply import apply_update

    msg = load_mail(DELIVERY_UPDATE)
    parcels: dict = {}
    [u] = parse_mail(msg).updates
    apply_update(parcels, u, sent_at(msg))
    parcel = parcels[SHORT]
    assert parcel.poll_target == ("dhl", SHORT) and parcel.name is None
    real = {"dhl": DhlCarrier, "dpd": DpdCarrier, "gls": GlsCarrier, "hermes": HermesCarrier,
            "ups": UpsCarrier}
    assert DhlCarrier.matches(SHORT) is Match.POSSIBLE
    assert candidates(SHORT, real) == ["dhl"]  # "Automatisch" and the choice "DHL"


@pytest.mark.parametrize(
    ("subject", "title"),
    [
        # a carrier's subsidiary in front of the warehouse and the shop: no name at all
        ("Ihre GLS Logistik (Austria) GmbH c/o Musterlager Beispielquell Sendung kommt heute",
         None),
        ("Ihre DHL Paket (Austria) GmbH c/o Beispiellager Musterquell Sendung kommt heute",
         None),
        ("Ihre Hermes Fulfilment GmbH Sendung kommt heute", None),
        ("Ihre Deutsche Post AG Sendung kommt heute", None),
        # the carrier only behind the company: the company is the name
        ("Ihre Beispielmarke GmbH c/o DHL Lager Musterstadt Sendung kommt heute",
         "Beispielmarke GmbH"),
    ],
)
def test_a_subject_naming_a_carrier_company_gives_no_name(subject, title):
    msg = _msg(subject, f"Ihre Sendungsnummer\n{SHORT}\n", "DHL <zustellung@dhl.de>")
    [u] = parse_mail(msg).updates
    assert (u.title, u.status, u.eta_date) == (
        title, ParcelStatus.OUT_FOR_DELIVERY, sent_at(msg).date(),
    )

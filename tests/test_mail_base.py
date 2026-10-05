from datetime import date, datetime
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail.base import (
    at,
    body_text,
    brand_of,
    carrier_for,
    carrier_key,
    clean,
    company_name,
    find_numbers,
    html_text,
    is_carrier_display,
    is_carrier_title,
    known_shop,
    names_carrier,
    relative_day,
    sender,
    sent_at,
    shop_of,
    shorten,
    subject,
    title_key,
    upcoming_date,
)

from .conftest import load_mail


def _msg(subject_: str, body: str, from_: str = "Shop <shop@example.org>") -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = from_
    msg["Subject"] = subject_
    msg["Date"] = "Thu, 30 Jul 2026 16:57:10 +0000"
    msg.set_content(body)
    return msg


def test_clean_drops_direction_marks_and_filler():
    assert clean("Bestellnr. ‫999-9156534-2587125") == "Bestellnr. 999-9156534-2587125"
    assert clean("a͏ ‌   ­b") == "a b"
    assert clean("  Ankunft heute 18h – 22h  \nx") == "Ankunft heute 18h – 22h\nx"


def test_fixture_helpers():
    msg = load_mail("001_bestellbestaetigung_bestellt.eml")
    assert sender(msg) == ("bestellbestaetigung@amazon.de", "Amazon.de")
    assert subject(msg) == "Bestellt: „4 Ersatz Metallplättchen...“"
    assert sent_at(msg) == datetime(2026, 7, 30, 18, 57, 10, tzinfo=BERLIN)
    assert "Bestellnr. 999-9156534-2587125" in body_text(msg).splitlines()


def test_subject_folds_spaces_and_strips_forward_prefix():
    msg = load_mail("073_versandbestaetigung_versandt.eml")
    assert subject(msg) == "Versandt: „greate 16A CEE Adapter mit...“ und 1 weiterer Artikel"
    assert subject(_msg("WG: Fwd: Versendet: „X“", "b")) == "Versendet: „X“"


def test_sent_at_requires_date():
    msg = EmailMessage(policy=policy.default)
    msg["Subject"] = "x"
    with pytest.raises(ValueError):
        sent_at(msg)


def test_relative_day_and_at():
    ref = datetime(2026, 7, 30, 22, 12, tzinfo=BERLIN)
    assert relative_day("heute", ref) == date(2026, 7, 30)
    assert relative_day("morgen", ref) == date(2026, 7, 31)
    assert at(date(2026, 7, 31), 13, 10) == datetime(2026, 7, 31, 13, 10, tzinfo=BERLIN)


@pytest.mark.parametrize(
    ("day", "month", "ref", "expected"),
    [
        (31, 7, date(2026, 7, 31), date(2026, 7, 31)),
        (31, None, date(2026, 7, 31), date(2026, 7, 31)),
        (2, None, date(2026, 7, 31), date(2026, 8, 2)),
        (14, 12, date(2016, 12, 13), date(2016, 12, 14)),
        (2, 1, date(2026, 12, 30), date(2027, 1, 2)),
        (31, 2, date(2026, 1, 10), None),
    ],
)
def test_upcoming_date(day, month, ref, expected):
    assert upcoming_date(day, month, ref) == expected


def test_shorten_and_title_key():
    assert shorten("x" * 60) == "x" * 60
    assert shorten("x" * 70) == "x" * 59 + "…"
    assert title_key("Apple AirPods Pro 3…") == "apple airpods p"
    assert title_key("Apple AirPods Pro 3 Kabellose In‑Ear Kopfhörer…") == "apple airpods p"
    assert title_key("greate 16A CEE Adapter mit… und 1 weiterer Artikel") == "greate 16a cee "


def test_find_numbers_and_carrier_for():
    text = "JJD000012978217606560 and 1Z999AA11026832876, 00340999999999999917 or 09999999999901"
    assert find_numbers(text) == [
        ("dhl", "JJD000012978217606560"),
        ("ups", "1Z999AA11026832876"),
        ("dhl", "00340999999999999917"),
    ]
    assert ("dpd", "09999999999901") in find_numbers(text, "any")
    assert ("dpd", "09999999999901") not in find_numbers(text, "labelled")
    assert find_numbers("1Z999AA11026832876 1Z999AA11026832876") == [
        ("ups", "1Z999AA11026832876")
    ]
    assert carrier_for("1Z999AA11048020581") == "ups"
    assert carrier_for("JJD000012978217606560") == "dhl"
    assert carrier_for("09999999999901") is None


@pytest.mark.parametrize(
    "label",
    ["Paketnummer", "Sendungsnummer:", "Paket-Nr.", "Paket-Nr", "Paketscheinnummer :",
     "Sendungs-Nr.", "sendungsnummer"],
)
def test_labelled_dpd_number(label):
    assert find_numbers(f"DPD {label} 09999999999901 x", "labelled") == [
        ("dpd", "09999999999901")
    ]


def test_dpd_probe_with_order_and_hotline_numbers():
    text = (
        "Bestellnummer 10105012345678\nVersand mit DPD\n"
        "Paketnummer: 09999999999901\nHotline 08001234567890"
    )
    assert find_numbers(text, "labelled") == [("dpd", "09999999999901")]


def test_html_text_keeps_blocks_as_lines_and_drops_styles():
    markup = (
        "<html><head><style>p {color: red}</style><title>t</title></head><body>"
        "<table><tr><td>Lieferung ca.:</td></tr><tr><td>Mi, 28. Jan&nbsp;- Do, 29. Jan</td></tr>"
        "</table><p>A<br>B</p><div>  C  &amp; D </div><script>x()</script></body></html>"
    )
    assert html_text(markup) == "Lieferung ca.:\nMi, 28. Jan - Do, 29. Jan\nA\nB\nC & D"


def test_body_text_falls_back_to_html():
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "eBay <ebay@ebay.com>"
    msg.set_content("<p>Bestellnummer:</p><p>\u200c99-00000-00001</p>", subtype="html")
    assert body_text(msg) == "Bestellnummer:\n99-00000-00001"
    both = _msg("x", "nur Text")
    both.add_alternative("<p>HTML</p>", subtype="html")
    assert body_text(both) == "nur Text"


def test_body_text_of_html_fixture():
    text = body_text(load_mail("104_ebay_ihre_sendung_ist_jetzt_beim_versand.eml"))
    assert "Lieferung ca.:\nMi, 28. Jan - Do, 29. Jan" in text
    assert "<p>" not in text


def test_hermes_numbers_are_safe_on_their_own():
    assert carrier_for("H9999999999999999901") == "hermes"
    assert carrier_for("H999999999999999999") is None
    assert find_numbers("Sendungsnummer H9999767129584220767.") == [
        ("hermes", "H9999767129584220767")
    ]
    # 14 digits stay ambiguous: never Hermes without context
    assert find_numbers("Nummer 99992958672143") == []


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("Hermes Germany", "hermes"),
        ("DHL Paket", "dhl"),
        ("Deutsche Post", "dhl"),
        ("DPD Deutschland", "dpd"),
        ("UPS Standard", "ups"),
        ("GLS Paket", "gls"),
        ("Eagles Versand", None),
        ("FedEx", None),
        ("", None),
    ],
)
def test_carrier_key(text, key):
    assert carrier_key(text) == key


@pytest.mark.parametrize(
    ("text", "shop"),
    [("Amazon EU SARL", "amazon"), ("eBay-Verkäufer", "ebay"), ("Beispiel Versand GmbH", None)],
)
def test_shop_of(text, shop):
    assert shop_of(text) == shop


@pytest.mark.parametrize(
    ("text", "known"),
    [
        ("Amazon EU SARL", True),
        ("eBay-Händler", True),
        ("Otto", True),
        ("otto.de", True),
        ("Zalando SE", True),
        ("MediaMarkt Online", True),
        ("Otto Beispiel", False),
        ("Erika Musterfrau", False),
        ("Beispiel Versand GmbH", False),
    ],
)
def test_known_shop(text, known):
    assert known_shop(text) is known


# ----- v0.3.15: one helper cuts every company name, carriers never name a parcel -----
@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Beispiel GmbH", "Beispiel GmbH"),
        # nothing behind the legal form is taken: no branch code, no contact person
        ("Beispiel Handels OHG (AT-B2C) Erika Musterfrau Max Mustermann", "Beispiel Handels OHG"),
        ("Beispiel Handels OHG (AT-B2C)", "Beispiel Handels OHG"),
        ("Beispiel GmbH Erika Musterfrau", "Beispiel GmbH"),
        ("Beispiel GmbH, z. Hd. Erika Musterfrau", "Beispiel GmbH"),
        ("OTTO GmbH & Co KG Erika Musterfrau", "OTTO GmbH & Co KG"),
        ("Beispiel GmbH & Co. KG Max Mustermann", "Beispiel GmbH & Co. KG"),
        ("Hofladen Muster e.K. Max Mustermann", "Hofladen Muster e.K."),
        ("Exemple S.à r.l. Erika Musterfrau", "Exemple S.à r.l."),
        ("Amazon EU SARL Erika Musterfrau", "Amazon EU SARL"),
        ("Amazon EU S.a.r.l.", "Amazon EU S.a.r.l."),
        # a shop we know without a legal form: only the shop
        ("Zalando", "Zalando"),
        ("MediaMarkt Online", "MediaMarkt Online"),
        ("Zalando Versand Erika Musterfrau", "Zalando Versand"),
        ("Amazon Erika Musterfrau", "Amazon"),
        ("Erika Musterfrau über eBay", "eBay"),
        # a token with "ebay"/"amazon" is the shop, never a seller's handle
        ("eBay-Händler", "eBay"),
        ("ebay_haendler99", "eBay"),
        ("Verkäufer haendler99-ebay", "eBay"),
        ("Amazon.de", "Amazon"),
        ("amazon-marketplace-haendler99", "Amazon"),
        # a person in front of the company is cut at the comma
        ("Erika Musterfrau, Beispiel GmbH", "Beispiel GmbH"),
        ("Erika Musterfrau; Beispiel Handels OHG (AT-B2C)", "Beispiel Handels OHG"),
        ("Musterfrau, Erika, Beispiel GmbH & Co. KG Max", "Beispiel GmbH & Co. KG"),
        ("Erika Musterfrau, GmbH", None),
        # a person, a legal form without a name in front of it, nothing
        ("Erika Musterfrau", None),
        ("Otto Beispiel", None),
        ("GmbH Erika Musterfrau", None),
        ("", None),
        # a carrier is no shop
        ("DHL Paket GmbH", None),
        ("DPD Deutschland GmbH", None),
        ("📦 DHL Paketankündigung", None),
        ("X" * 70 + " GmbH Erika Musterfrau", "X" * 59 + "…"),
    ],
)
def test_company_name_ends_at_the_legal_form(text, name):
    assert company_name(text) == name


@pytest.mark.parametrize(
    ("text", "broad", "title", "legacy"),
    [
        ("📦 DHL Paketankündigung", True, True, True),
        ("DHL Zustell-Update", True, True, True),
        ("DHL Paket", True, True, True),
        ("DPD Versandinfo", True, True, True),
        ("myDPD Paketinfo", True, True, True),
        ("GLS Real Time Tracking", True, True, True),
        ("Hermes Paketankündigung", True, True, True),
        ("Hermes Sendungsinfo", True, True, True),
        ("DHL Zustellung", True, True, True),
        ("Deutsche Post Sendungsverfolgung", True, True, True),
        ("UPS Quantum View", True, True, True),
        # no name a mail may give, but as a stored name it may be somebody's own
        ("DPD", True, True, False),
        ("myDPD", True, True, False),
        ("Hermes", True, True, False),
        ("Deutsche Post", True, True, False),
        ("Amazon Logistics", True, True, False),
        ("Paketankündigung", True, True, False),
        ("Zustell-Update", True, True, False),
        ("Paket", True, True, False),
        ("Express", True, True, False),
        ("Info", True, True, False),
        ("Österreich", True, True, False),
        ("DHL Express", True, True, False),
        ("DHL Österreich", True, True, False),
        # names a carrier, but is more than a carrier's display name
        ("DHL Geschenk", True, False, False),
        ("DHL Schuhe für Erika", True, False, False),
        ("Back-UPS 700", True, False, False),
        ("Amazon-Sendung (DHL)", True, False, False),
        ("Beispiel GmbH", False, False, False),
        ("Amazon.de", False, False, False),
        ("Gruppenspiel", False, False, False),  # "ups"/"gls" inside a word is no carrier
        ("", False, False, False),
    ],
)
def test_carrier_display_names(text, broad, title, legacy):
    assert names_carrier(text) is broad
    assert is_carrier_title(text) is title
    assert is_carrier_display(text) is legacy


@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Beispielmarke GmbH", "Beispielmarke"),
        ("Abcde GmbH", "Abcde"),
        ("Kabelwerk Premium GmbH", "Kabelwerk Premium"),
        ("Premium  Kabelwerk GmbH & Co. KG", "Premium Kabelwerk"),
        ("AB Technik GmbH", "AB Technik"),
        # one short word, or nothing but words every other company carries
        ("Abcd GmbH", None),
        ("AB GmbH", None),
        ("AB CD GmbH", None),
        ("Neu GmbH", None),
        ("Premium GmbH", None),
        ("Express Logistik GmbH", None),
        ("Smart Home GmbH", None),
        ("Top Shop Online GmbH", None),
        ("Mein Paket Service Deutschland GmbH", None),
        ("Bio Baby Sport AG", None),
        # a shop we know is a shop, not the brand of an article
        ("IKEA", None),
        ("IKEA Deutschland GmbH & Co. KG", None),
        ("Otto GmbH & Co KG", None),
        ("Conrad Electronic SE", None),
        ("Tchibo GmbH", None),
        ("Zalando SE", None),
        ("Amazon EU SARL", None),
        ("eBay GmbH", None),
        # no company
        ("Erika Musterfrau", None),
        ("DHL Paket GmbH", None),
        (None, None),
        ("", None),
    ],
)
def test_brand_of(title, brand):
    assert brand_of(title) == brand

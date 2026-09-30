"""The local anonymiser scrubs Hermes and eBay mails (synthetic personal data only)."""

import email
import subprocess
import sys
from email import policy
from email.message import EmailMessage
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "anonymize_mail.py"
ARGS = ["54321", "Beispielhausen", "Jörg", "Probst", "privatpost"]


def _mail(sender: str, subject: str, text: str, html: bool = False) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "joerg.probst@privatpost.de"
    msg["Subject"] = subject
    msg["Date"] = "Tue, 18 Jul 2023 08:02:46 +0000"
    msg["Message-ID"] = f"<{abs(hash(subject))}@example.com>"
    if html:
        msg.set_content(
            "<html><head><style>p{}</style></head><body><table>"
            + "".join(f"<tr><td>{line}</td></tr>" for line in text.splitlines())
            + "</table></body></html>",
            subtype="html",
        )
    else:
        msg.set_content(text)
    return bytes(msg)


HERMES = _mail(
    "Hermes Zustellbenachrichtigung <noreply@paketankuendigung.myhermes.de>",
    "Dein Hermes Paket von Amazon EU SARL wurde an deinen WunschAblageort zugestellt.",
    "Hallo,\n\ndeine Sendung von Amazon EU SARL wurde an deinem WunschAblageort zugestellt.\n\n"
    "Gewählter WunschAblageort:\nUnter der Treppe links neben der Tonne\n\n"
    "Wir haben deinen dauerhaften Ablageort Unter der Treppe links neben der Tonne erkannt.\n"
    "Sendungsnummer H9999999999999999902\n",
)
EBAY = _mail(
    "eBay <ebay@ebay.com>",
    "BESTELLUNG ZUGESTELLT: Filament Blau Probst-Edition",
    "Hallo joergp, jetzt können Sie Ihre Sendung verfolgen!\n"
    "Filament Blau 1Kg\nArtikelnr.:\n999999999901\n999999999901\n"
    "Bestellnummer:\n99-00000-00001\n99-00000-00001\n"
    "Verkäufer:\nhaendler-meier\nhaendler-meier\n"
    "Geliefert an:\nJörg Probst\nLindenweg 7\n54321 Beispielhausen\nDeutschland\n"
    "Lieferung ca.:\nMi, 28. Jan - Do, 29. Jan\n"
    "E-Mail-Referenznr.: [#0123456789abcdef0123456789abcdef]\n",
    html=True,
)
AMAZON = _mail(
    '"Amazon.de" <versandbestaetigung@amazon.de>',
    'Ihre Amazon.de Bestellung von "Tastatur..." wurde versandt!',
    "Bestellnummer: #999-0000000-0000001\nDie Sendung geht an:\n   Jörg Probst\n"
    "   Lindenweg 7\n   Beispielhausen,\n   NRW\n   54321\n   Deutschland\n"
    "Die Sendung wurde mit Hermes versandt. Paketverfolgungsnummer: 99999999999901.\n",
)
IGNORED = _mail('"rueckgabe@amazon.de" <rueckgabe@amazon.de>', "Rücksendung", "Jörg Probst")


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> dict[str, EmailMessage]:
    tmp_path = tmp_path_factory.mktemp("anon")
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (dst / "007_existing.eml").write_bytes(_mail("x <x@example.org>", "alt", "alt"))
    for name, raw in (("h.eml", HERMES), ("h2.eml", HERMES), ("e.eml", EBAY),
                      ("a.eml", AMAZON), ("r.eml", IGNORED)):
        (src / name).write_bytes(raw)
    subprocess.run([sys.executable, str(SCRIPT), str(src), str(dst), *ARGS], check=True,
                   capture_output=True)
    return {
        p.name: email.message_from_bytes(p.read_bytes(), policy=policy.default)
        for p in sorted(dst.glob("0*.eml"))
        if p.name != "007_existing.eml"
    }


def test_numbering_continues_and_duplicates_are_skipped(out):
    assert [name[:4] for name in out] == ["008_", "009_", "010_"]


def test_no_personal_value_survives(out):
    for msg in out.values():
        dump = msg.as_string() + msg.get_body(("plain", "html")).get_content()
        for value in ("54321", "Beispielhausen", "Jörg", "Joerg", "joerg", "Probst",
                      "privatpost", "Lindenweg", "Treppe", "haendler-meier",
                      "999-0000000-0000001", "99999999999901", "H9999999999999999902",
                      "999999999901", "99-00000-00001", "0123456789ab"):
            assert value not in dump, value


def test_hermes_drop_off_becomes_garage(out):
    [hermes] = [m for m in out.values() if "myhermes" in str(m["From"])]
    text = hermes.get_body(("plain",)).get_content()
    assert "Gewählter WunschAblageort:\nGarage" in text
    assert "dauerhaften Ablageort Garage erkannt" in text
    assert "Sendungsnummer H9999" in text


def test_ebay_html_only_stays_html_with_fake_numbers(out):
    [ebay] = [m for m in out.values() if "ebay" in str(m["From"])]
    assert ebay.get_body(("plain",)) is None
    markup = ebay.get_body(("html",)).get_content()
    assert "<style>" not in markup
    assert "<p>Hallo Max, jetzt können Sie Ihre Sendung verfolgen!</p>" in markup
    assert "<p>Lieferung ca.:</p>\n<p>Mi, 28. Jan - Do, 29. Jan</p>" in markup
    assert "<p>Verkäufer:</p>\n<p>beispielshop</p>" in markup
    assert "<p>Max Mustermann</p>\n<p>Musterstraße 1</p>\n<p>12345 Musterstadt</p>" in markup
    assert "<p>99-" in markup and "<p>9999" in markup


def test_file_names_come_from_the_scrubbed_subject_without_titles(out):
    names = [name[4:] for name in out]
    assert "ebay_bestellung_zugestellt.eml" in names
    assert "versandbestaetigung_ihre_amazon_de_beste.eml" in names
    assert not any("filament" in n or "probst" in n or "tastatur" in n for n in names)


def test_region_line_is_dropped(out):
    [amazon] = [m for m in out.values() if "amazon" in str(m["From"])]
    assert "NRW" not in amazon.get_body(("plain",)).get_content()


def test_amazon_hermes_number_is_replaced(out):
    [amazon] = [m for m in out.values() if "amazon" in str(m["From"])]
    text = amazon.get_body(("plain",)).get_content()
    assert "Paketverfolgungsnummer: 9999" in text
    assert "Bestellnummer: #999-" in text

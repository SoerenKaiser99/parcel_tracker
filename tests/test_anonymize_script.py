"""The local anonymiser scrubs Hermes, eBay and GLS mails (synthetic personal data only)."""

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


# ----- GLS mails (v0.3.2) -----
GLS_FROM = "GLS Paket <no-reply@gls-pakete.de>"
GLS_LINK = "( https://url0000.gls-pakete.de/ls/click?upn=u001.abcDEF123 )"
GLS_FOOTER = (
    "General Logistics Systems Germany GmbH & Co. OHG\n"
    "Sitz: Neuenstein Geschäftsführer: Vera Vorstand\n"
)
GLS_TODAY = _mail(
    GLS_FROM,
    "📦 Dein GLS Paket kommt heute!",
    f"*Hallo Jörg Probst,*\n\nSendungsverfolgung {GLS_LINK}\n\n"
    "*Zustelladresse*\nJörg Probst\nLindenweg 7 ,\n54321 Beispielhausen\n\n"
    "** *Versender*\nHolzwurm Möbel GmbH\nSägeweg 3 ,\n98765 Spanstadt\n\n"
    f"*Paketnummer*\n12345678901 {GLS_LINK}  (Referenz: AB2508-XY99) {GLS_LINK} \n\n"
    + GLS_FOOTER,
)
GLS_PLACE = _mail(
    GLS_FROM,
    "📦 Dein Paket wird an dem gewünschten Ort abgestellt",
    "* *Hallo Jörg Probst +4915112345678,* *\n\ndein Paket von dem Absender\n\n"
    "** *Holzwurm Möbel GmbH * **\n\nwird an dem von dir gewünschten Abstellort abgelegt.\n\n"
    "------------------------\n*Gewünschter Abstellort*\n\n------------------------\n\n"
    "---------------\nHinter der Regentonne am Schuppen\n---------------\n\n"
    f"*Sendungsnummer*\n12345678901 {GLS_LINK}\n\n"
    "*Versender*\nHolzwurm Möbel GmbH \nSägeweg 3 , 98765 Spanstadt\n\n"
    "*Empfänger*\nJörg Probst +4915112345678\nLindenweg 7 ,\n54321 Beispielhausen\n\n"
    + GLS_FOOTER,
)
GLS_SOON = _mail(
    GLS_FROM,
    "📦 Dein Paket wird in wenigen Tagen zugestellt",
    "*Hallo Jörg Probst,*\n\ndein Paket von\n\n*Holzwurm Möbel GmbH*\n\n"
    "wurde GLS übergeben und wird innerhalb von 1 bis 3 Werktagen zugestellt.\n\n"
    "*Voraussichtliche Lieferung*\n\n----------\nFreitag, 2. Oktober\n"
    "zwischen 10:15 und 11:45 Uhr\n----------\n\n"
    f"*Sendungsnummer*\n 12345678902 {GLS_LINK}\n\n"
    "*Versender*\nHolzwurm Möbel GmbH\nSägeweg 3\n98765 Spanstadt\n\n"
    "*Empfänger*\nJörg Probst\nLindenweg 7 7 \n54321 Beispielhausen\n\n" + GLS_FOOTER,
)
UNKNOWN = _mail(
    "Holzwurm <noreply@holzwurm.example>",
    "Versand Ihrer Bestellung // Holzwurm Möbel GmbH",
    "Hallo Jörg Probst,\n\nIhre Bestellung wird an GLS übergeben.\n",
)
# Another recipient than the one on the command line, a street without a house number.
GLS_OTHER = _mail(
    GLS_FROM,
    "📦 Dein Paket wurde zugestellt",
    f"*Hallo Erika Sonnenschein,*\n\nSendungsverfolgung {GLS_LINK}\n\n"
    "*Zustelladresse*\nErika Sonnenschein\nAm Alten Hafen ,\n67890 Anderswo\n\n"
    "*Versender*\nHolzwurm Möbel GmbH\nSägeweg 3 ,\n98765 Spanstadt\n\n"
    "*Empfänger*\nErika Sonnenschein 0151 12345678\nAm Alten Hafen\n67890 Anderswo\n\n"
    "----------\n*an Erika Sonnenschein*\nAm Alten Hafen\n67890 Anderswo\n----------\n\n"
    f"*Sendungsnummer*\n12345678901 {GLS_LINK}\n\n" + GLS_FOOTER,
)
GLS_PHONES = _mail(
    GLS_FROM,
    "📦 Dein Paket wird in wenigen Tagen zugestellt",
    "*Hallo Jörg Probst 0151 12345678,*\n\n"
    "Rückruf: 02151/123456-7 oder 0151-1234-5678 oder 015112345678 oder +49 151 1234 5678\n\n"
    "Freitag, 02.10.2026\nzwischen 08:15 und 09:45 Uhr\n\n"
    f"*Sendungsnummer*\n01234567890 {GLS_LINK}\n\n"
    "*Versender*\nHolzwurm Möbel GmbH\nSägeweg 3 ,\n01067 Spanstadt\n\n" + GLS_FOOTER,
)
GLS_SUBJECT = _mail(
    GLS_FROM,
    "📦 Dein GLS Paket 12345678903 (Referenz: AB2508-XY99) von Holzwurm Möbel GmbH kommt heute!",
    f"*Hallo Jörg Probst,*\n\n*Paketnummer*\n12345678903 {GLS_LINK}\n\n"
    "*Versender*\nHolzwurm Möbel GmbH\n\n" + GLS_FOOTER,
)


def _run(tmp_path, mails, *extra):
    """Run the script on ``mails``: (finished process, {file name: written mail})."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    for i, raw in enumerate(mails):
        (src / f"{i}.eml").write_bytes(raw)
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(src), str(dst), *ARGS, *extra],
        capture_output=True, text=True,
    )
    return done, {
        p.name: email.message_from_bytes(p.read_bytes(), policy=policy.default)
        for p in sorted(dst.glob("*.eml"))
    }


@pytest.fixture(scope="module")
def gls(tmp_path_factory) -> dict[str, EmailMessage]:
    done, written = _run(
        tmp_path_factory.mktemp("anon_gls"), [GLS_TODAY, GLS_PLACE, GLS_SOON, UNKNOWN]
    )
    assert done.returncode == 0, done.stderr
    return written


def _text(msg: EmailMessage) -> str:
    return msg.get_body(("plain",)).get_content()


def test_gls_file_names_are_neutral_and_unknown_senders_are_skipped(gls):
    assert list(gls) == [
        "001_no_reply_dein_gls_paket_kommt_heute.eml",
        "002_no_reply_dein_paket_wird_an_dem_gew_nsch.eml",
        "003_no_reply_dein_paket_wird_in_wenigen_tage.eml",
    ]


def test_gls_no_personal_value_survives(gls):
    for msg in gls.values():
        dump = msg.as_string() + _text(msg) + str(msg["Subject"])
        for value in ("54321", "Beispielhausen", "Jörg", "Joerg", "Probst", "privatpost",
                      "Lindenweg", "Holzwurm", "holzwurm", "Sägeweg", "98765", "Spanstadt",
                      "Regentonne", "Schuppen", "12345678901", "12345678902", "4915112345678",
                      "AB2508", "abcDEF123", "Vera Vorstand", "General Logistics"):
            assert value not in dump, value


def test_gls_blocks_get_placeholders(gls):
    today, place, soon = gls.values()
    assert str(today["From"]) == GLS_FROM
    assert "Dein GLS Paket kommt heute!" in str(today["Subject"])
    text = _text(today)
    assert "*Zustelladresse*\nMax Mustermann\nMusterstraße 1 ,\n12345 Musterstadt\n" in text
    assert "*Versender*\nBeispiel GmbH\nBeispielweg 2 ,\n00000 Beispielstadt\n" in text
    assert (
        "*Paketnummer*\n99999999901 ( https://url0000.gls-pakete.de/… )  (Referenz: REF-0001)"
        in text
    )
    text = _text(place)
    assert "Hallo Max Mustermann +49 000 0000000," in text
    assert "dein Paket von dem Absender\n\n** *Beispiel GmbH * **" in text
    assert "---------------\nAblageort: Garage\n---------------" in text
    assert "*Sendungsnummer*\n99999999901 (" in text  # same parcel, same number
    assert "*Empfänger*\nMax Mustermann +49 000 0000000\nMusterstraße 1 ,\n" in text
    text = _text(soon)
    assert "dein Paket von\n\n*Beispiel GmbH*" in text
    assert "Freitag, 2. Oktober\nzwischen 10:15 und 11:45 Uhr" in text
    assert "*Sendungsnummer*\n 99999999902 (" in text  # second parcel, next number
    assert "*Empfänger*\nMax Mustermann\nMusterstraße 1 ,\n12345 Musterstadt" in text


def test_gls_recipient_block_is_replaced_by_its_structure(tmp_path):
    done, written = _run(tmp_path, [GLS_OTHER])
    assert done.returncode == 0, done.stderr
    [msg] = written.values()
    text = _text(msg)
    assert "*Hallo Max Mustermann,*" in text
    assert "*Zustelladresse*\nMax Mustermann\nMusterstraße 1 ,\n12345 Musterstadt\n\n" in text
    assert (
        "*Empfänger*\nMax Mustermann +49 000 0000000\nMusterstraße 1 ,\n12345 Musterstadt\n\n"
        in text
    )
    # the "delivered to" block of the delivery mail
    assert "-\n*an Max Mustermann*\nMusterstraße 1 ,\n12345 Musterstadt\n-" in text
    assert "*Sendungsnummer*\n99999999901 (" in text
    for value in ("Erika", "Sonnenschein", "Alten", "Hafen", "67890", "Anderswo", "12345678"):
        assert value not in text, value


def test_gls_national_phone_numbers_are_replaced(tmp_path):
    done, written = _run(tmp_path, [GLS_PHONES])
    assert done.returncode == 0, done.stderr
    [msg] = written.values()
    text = _text(msg)
    assert "*Hallo Max Mustermann +49 000 0000000,*" in text
    assert "Rückruf: " + " oder ".join(["+49 000 0000000"] * 4) + "\n" in text
    # Dates, times and postcodes are no phone numbers; 11 bare digits are a parcel number.
    assert "Freitag, 02.10.2026\nzwischen 08:15 und 09:45 Uhr\n" in text
    assert "*Sendungsnummer*\n99999999901 (" in text
    for value in ("0151", "02151", "123456", "1234", "5678", "01234567890"):
        assert value not in text, value


def test_gls_subject_and_file_name_are_scrubbed(tmp_path):
    done, written = _run(tmp_path, [GLS_SUBJECT])
    assert done.returncode == 0, done.stderr
    [(name, msg)] = written.items()
    assert str(msg["Subject"]) == (
        "📦 Dein GLS Paket 99999999901 (Referenz: REF-0001) von Beispiel GmbH kommt heute!"
    )
    assert name == "001_no_reply_dein_gls_paket_99999999901_refe.eml"
    assert "*Paketnummer*\n99999999901 (" in _text(msg)  # the same number as in the subject


@pytest.mark.parametrize("option", ["--shop-sender=noreply@holzwurm.example", "--dry-run", "-x"])
def test_unknown_option_is_an_error(tmp_path, option):
    done, written = _run(tmp_path, [GLS_TODAY], option)
    assert done.returncode == 2
    assert f"unknown option {option.split('=')[0]}" in done.stderr
    assert "holzwurm" not in done.stderr  # an option's value may be private
    assert written == {}


def test_missing_arguments_are_an_error(tmp_path):
    done = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), str(tmp_path / "dst")],
                          capture_output=True, text=True)
    assert done.returncode == 2 and done.stderr.startswith("usage: anonymize_mail.py")

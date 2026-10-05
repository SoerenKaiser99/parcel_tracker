"""Tester mode of the anonymiser: every sender, given values, generic scrubbing (invented mails)."""

import email
import html
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import zipfile
from email import policy
from email.message import EmailMessage
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "anonymize_mail.py"
VALUES = [
    "--name", "Jörg Probst", "--street", "Lindenweg 7", "--postcode", "54321",
    "--city", "Beispielhausen", "--phone", "0151 12345678",
    "--email", "joerg.probst@privatpost.example",
]
JJD = "JJD000390007812345678"
UPS = "1Z999AA10123456784"
HERMES = "H1234567890123456789"
ORDER = "HW-2025-004711"
# Nothing of this may be left in any written byte (compared in lower case).
SECRETS = [
    "jörg", "joerg", "j&ouml;rg", "probst", "lindenweg", "54321", "beispielhausen",
    "12345678", "privatpost", JJD.lower(), UPS.lower(), HERMES.lower(), ORDER.lower(),
    "blauen tonne", "regentonne", "secret-host", "mx.gateway", "geheimer-mailer", "piececode",
    "kundin-4711", "beleg", "erika", "sonnenschein", "zweitadresse", "selector1",
]
ALLOWED_HEADERS = {
    "from", "to", "subject", "date", "message-id", "mime-version", "content-type",
    "content-transfer-encoding",
}


def _headers(msg: EmailMessage, sender: str, subject: str, number: int) -> None:
    msg["Received"] = "from mx.gateway.example (secret-host [203.0.113.7]) by mx.privatpost.example"
    msg["Return-Path"] = "<bounce-kundin-4711@bounces.example>"
    msg["From"] = sender
    msg["To"] = "Jörg Probst <joerg.probst@privatpost.example>"
    msg["Cc"] = "Erika Sonnenschein <erika@zweitadresse.example>"
    msg["Delivered-To"] = "joerg.probst@privatpost.example"
    msg["Subject"] = subject
    msg["Date"] = "Tue, 18 Jul 2023 08:02:46 +0000"
    msg["Message-ID"] = f"<{number}.kundin-4711@secret-host.example>"
    msg["X-Mailer"] = "geheimer-mailer 1.0"
    msg["X-Customer"] = "Probst, Joerg"
    msg["DKIM-Signature"] = "v=1; a=rsa-sha256; d=dhl.de; s=selector1; b=abc"
    msg["ARC-Seal"] = "i=1; a=rsa-sha256; d=privatpost.example; s=selector1"
    msg["Authentication-Results"] = "mx.privatpost.example; spf=pass"
    msg["List-Unsubscribe"] = "<https://news.example/u?kundin-4711>"


def _known() -> bytes:
    msg = EmailMessage()
    _headers(msg, "DHL Paket <noreply@dhl.de>", f"Jörg, Ihr DHL Paket {JJD} kommt morgen", 1)
    msg.set_content(
        "Hallo Jörg Probst,\n\n"
        f"Ihre Sendung ist unterwegs. Sendungsnummer: {JJD}\n\n"
        "Lieferadresse:\nJörg Probst\nLindenweg 7\n54321 Beispielhausen\n\n"
        "Ablageort: Hinter der blauen Tonne\n\n"
        "Rückfragen an 0151 12345678 oder +49 151 12345678.\n"
        "Benachrichtigt wurde joerg.probst@privatpost.example, Fragen an service@dhl.de, "
        "Absender dieser Mail ist noreply@dhl.de.\n"
        f"Verfolgen: https://www.dhl.de/de/verfolgen.html?piececode={JJD}&zip=54321\n"
        "Zustellung: Mittwoch, 19.07.2023 zwischen 10:15 und 11:45 Uhr\n"
    )
    return bytes(msg)


def _unknown() -> bytes:
    msg = EmailMessage()
    _headers(
        msg, "Holzwurm Shop <versand@holzwurm-shop.example>", "Deine Bestellung ist unterwegs", 2
    )
    msg.set_content(
        "Guten Tag Herr Probst,\n\n"
        f"Bestellnummer: {ORDER}\nKundennummer: 48213\n"
        f"Wir haben dein Paket an DHL übergeben: {JJD}\n"
        f"Zweites Paket mit UPS: {UPS}, drittes mit Hermes: {HERMES}\n\n"
        "Versandadresse: JOERG PROBST, Lindenweg 7, 54321 Beispielhausen\n"
        "Der Lindenweg ist gesperrt, wir liefern trotzdem nach Beispielhausen.\n"
        "*Gewünschter Abstellort*\n\n-----\nHinter der Regentonne\n-----\n"
        "Rechnung an probst.joerg@privatpost.example\n",
        cte="quoted-printable",
    )
    msg.add_alternative(
        "<html><head><title>Bestellung Probst</title><style>p{color:red}</style></head><body>"
        "<p>Guten Tag Herr Probst,</p>"
        f"<p>Bestellnummer: <b>{ORDER}</b></p>"
        f'<p>Sendung <a href="https://dhl.example/t?piececode={JJD}">{JJD}</a></p>'
        "</body></html>",
        subtype="html",
        cte="base64",
    )
    return bytes(msg)


def _html_only() -> bytes:
    msg = EmailMessage()
    _headers(
        msg,
        "Paketflitzer <tracking@paketflitzer.example>",
        "Paket für Jörg Probst in 54321 Beispielhausen",
        3,
    )
    msg.set_content(
        "<html><body><table>"
        "<tr><td>Hallo J&ouml;rg,</td></tr>"
        '<tr><td><a href="https://paketflitzer.example/t?name=Probst&amp;plz=54321" '
        'title="Paket für Jörg Probst">Sendung verfolgen</a></td></tr>'
        '<tr><td><img alt="Jörg Probst, Lindenweg 7" '
        'src="https://img.paketflitzer.example/p.gif?u=joerg.probst%40privatpost.example"></td></tr>'
        f"<tr><td>Paketnummer</td></tr><tr><td>{HERMES}</td></tr>"
        '<tr><td data-kunde="kundin-4711">Zustellung an Lindenweg 7a in Beispielhausen</td></tr>'
        "<tr><td>Wir haben deinen Wunschort Hinter der Regentonne gespeichert.</td></tr>"
        "<!-- Kunde: Probst --></table></body></html>",
        subtype="html",
        cte="base64",
    )
    msg.add_attachment(
        "Beleg für Jörg Probst".encode(),
        maintype="application",
        subtype="pdf",
        filename="Beleg_Probst.pdf",
    )
    return bytes(msg)


def _write(folder: Path, mails) -> Path:
    folder.mkdir()
    for i, raw in enumerate(mails):
        (folder / f"mail{i}.eml").write_bytes(raw)
    (folder / "notizen.txt").write_text("Jörg Probst", encoding="utf-8")
    return folder


def _call(*args, script: Path = SCRIPT, **kwargs):
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"}, **kwargs,
    )


def _dump(raw: bytes) -> str:
    """Everything a reader could get out of a written mail, decoded in every way, lower case."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    chunks = [raw.decode("utf-8", "replace"), raw.decode("latin-1")]
    chunks += [f"{key}: {value}" for key, value in msg.items()]
    for part in msg.walk():
        if part.is_multipart():
            continue
        payload = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        chunks += [payload, html.unescape(payload), str(part.get_filename() or "")]
    text = "\n".join(chunks)
    return (text + urllib.parse.unquote(text)).lower()


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    src = _write(tmp_path_factory.mktemp("tester") / "mails", [_known(), _unknown(), _html_only()])
    done = _call(src, "--zip", *VALUES)
    assert done.returncode == 0, done.stderr
    out = src / "anonymisiert"
    return done, out, {p.name: p.read_bytes() for p in sorted(out.glob("*.eml"))}


def _msg(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=policy.default)


def _plain(raw: bytes) -> str:
    return _msg(raw).get_body(("plain",)).get_content()


def test_every_sender_is_taken_and_file_names_are_neutral(run):
    _, out, files = run
    assert list(files) == [
        "001_dhl.de.eml", "002_holzwurm-shop.example.eml", "003_paketflitzer.example.eml",
    ]
    assert sorted(p.name for p in out.iterdir()) == [*files, "paket-tracker-beispiele.zip"]


def test_no_input_value_is_left_in_any_output_byte(run):
    _, _, files = run
    for name, raw in files.items():
        dump = _dump(raw)
        for secret in SECRETS:
            assert secret not in dump, (name, secret)


def test_zip_holds_exactly_the_written_files(run):
    _, out, files = run
    with zipfile.ZipFile(out / "paket-tracker-beispiele.zip") as archive:
        assert archive.namelist() == list(files)
        for name, raw in files.items():
            assert archive.read(name) == raw
    packed = (out / "paket-tracker-beispiele.zip").read_bytes().decode("latin-1").lower()
    assert "probst" not in packed and "mail0" not in packed


def test_technical_headers_are_removed_or_replaced(run):
    _, _, files = run
    for number, (name, raw) in enumerate(files.items(), start=1):
        msg = _msg(raw)
        for part in msg.walk():
            assert {key.lower() for key in part.keys()} <= ALLOWED_HEADERS, name
        assert str(msg["To"]) == "max@example.org"
        assert str(msg["Message-ID"]) == f"<beispiel-{number:03d}@example.org>"
        assert str(msg["Date"]) == "Tue, 18 Jul 2023 08:02:46 +0000"
    known, unknown, flitzer = (_msg(raw) for raw in files.values())
    assert str(known["From"]) == "DHL Paket <noreply@dhl.de>"
    assert str(unknown["From"]) == "Holzwurm Shop <versand@holzwurm-shop.example>"
    assert str(flitzer["From"]) == "Paketflitzer <tracking@paketflitzer.example>"
    assert str(flitzer["Subject"]) == "Paket für Max Mustermann in 12345 Musterstadt"
    assert re.fullmatch(r"Max, Ihr DHL Paket JJD\d{18} kommt morgen", str(known["Subject"]))


def test_given_values_become_placeholders(run):
    _, _, files = run
    known, unknown = (_plain(raw) for raw in list(files.values())[:2])
    assert "Hallo Max Mustermann," in known
    assert "Lieferadresse:\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\n" in known
    assert "Rückfragen an +49 000 0000000 oder +49 000 0000000." in known
    assert "Guten Tag Herr Max Mustermann," in unknown
    assert "Versandadresse: Max Mustermann, Musterstraße 1, 12345 Musterstadt\n" in unknown
    assert "Der Musterstraße ist gesperrt, wir liefern trotzdem nach Musterstadt." in unknown


def test_mail_addresses_urls_and_drop_off_places(run):
    _, _, files = run
    known, unknown = (_plain(raw) for raw in list(files.values())[:2])
    assert (
        "Benachrichtigt wurde max@example.org, Fragen an max@example.org, "
        "Absender dieser Mail ist noreply@dhl.de." in known
    )
    assert "Verfolgen: https://www.dhl.de/…\n" in known
    assert "Ablageort: Garage\n" in known
    assert "Zustellung: Mittwoch, 19.07.2023 zwischen 10:15 und 11:45 Uhr" in known
    assert "*Gewünschter Abstellort*\n\n-----\nAblageort: Garage\n-----\n" in unknown
    assert "Rechnung an max@example.org" in unknown


def test_numbers_keep_their_format_and_map_identically_in_every_mail(run):
    _, _, files = run
    known, unknown = (_plain(raw) for raw in list(files.values())[:2])
    flitzer = _msg(files["003_paketflitzer.example.eml"]).get_body(("html",)).get_content()
    [jjd] = set(re.findall(r"JJD\d{18}\b", known))
    assert jjd != JJD
    assert set(re.findall(r"JJD\d+", unknown)) == {jjd}
    assert jjd in str(_msg(files["001_dhl.de.eml"])["Subject"])
    [ups] = re.findall(r"\b1Z[0-9A-Z]{16}\b", unknown)
    [hermes] = re.findall(r"\bH\d{19}\b", unknown)
    assert ups != UPS and hermes != HERMES
    assert f"<p>{hermes}</p>" in flitzer  # the same parcel in another mail
    [order] = set(re.findall(r"Bestellnummer: (HW-\d{4}-\d{6})\n", unknown))
    assert order != ORDER
    [customer] = re.findall(r"Kundennummer: (\d{5})\n", unknown)
    assert customer != "48213"
    html_part = _msg(files["002_holzwurm-shop.example.eml"]).get_body(("html",)).get_content()
    assert f"<p>Bestellnummer: {order}</p>" in html_part and f"<p>Sendung {jjd}</p>" in html_part


def test_html_only_mail_stays_html_without_attributes_and_attachments(run):
    _, _, files = run
    msg = _msg(files["003_paketflitzer.example.eml"])
    assert [part.get_content_type() for part in msg.walk()] == ["text/html"]
    markup = msg.get_content()
    assert "<p>Hallo Max Mustermann,</p>" in markup
    assert "<p>Sendung verfolgen</p>" in markup
    assert "<p>Zustellung an Musterstraße 1 in Musterstadt</p>" in markup
    assert "<p>Wir haben deinen Wunschort Garage gespeichert.</p>" in markup
    assert "href" not in markup and "<img" not in markup and "<!--" not in markup
    both = _msg(files["002_holzwurm-shop.example.eml"])
    assert [part.get_content_type() for part in both.walk()] == [
        "multipart/alternative", "text/plain", "text/html",
    ]


def test_bodies_are_readable_in_a_text_editor(run):
    _, _, files = run
    assert "Rückfragen an".encode() in files["001_dhl.de.eml"]
    assert "<p>Zustellung an Musterstraße 1".encode() in files["003_paketflitzer.example.eml"]


def test_final_message_lists_the_files_and_never_echoes_a_value(run):
    done, out, files = run
    for name in [*files, "paket-tracker-beispiele.zip"]:
        assert name in done.stdout
    assert "Jede Datei vor dem Hochladen selbst öffnen und durchlesen" in done.stdout
    assert "nie die Original-Mails" in done.stdout
    said = (done.stdout + done.stderr).lower()
    for secret in SECRETS:
        assert secret not in said, secret
    assert "bitte" not in said and "erfolgreich" not in said


def test_single_file_and_out_option(tmp_path):
    src = _write(tmp_path / "mails", [_known()])
    done = _call(src / "mail0.eml", *VALUES)
    assert done.returncode == 0, done.stderr
    assert [p.name for p in (src / "anonymisiert").iterdir()] == ["001_dhl.de.eml"]
    done = _call(src, "--out", tmp_path / "ziel", "--zip", "--name=Jörg Probst")
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in (tmp_path / "ziel").iterdir()) == [
        "001_dhl.de.eml", "paket-tracker-beispiele.zip",
    ]


def test_without_values_only_generic_scrubbing(tmp_path):
    src = _write(tmp_path / "mails", [_known()])
    done = _call(src, "--ohne-angaben")
    assert done.returncode == 0, done.stderr
    assert "Ohne eigene Angaben" in done.stdout
    assert "nur allgemein bereinigt" in done.stdout
    raw = (src / "anonymisiert" / "001_dhl.de.eml").read_bytes()
    dump = _dump(raw)
    for secret in ("privatpost", "12345678", JJD.lower(), "blauen tonne", "secret-host",
                   "lindenweg", "piececode"):
        assert secret not in dump, secret
    text = _plain(raw)
    assert "Hallo Max Mustermann," in text
    assert "Lieferadresse:\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\n" in text


@pytest.mark.skipif(sys.platform == "win32", reason="needs a pseudo terminal")
def test_missing_values_are_asked_in_german_on_a_terminal(tmp_path):
    import pty

    src = _write(tmp_path / "mails", [_known()])
    master, slave = pty.openpty()
    try:
        os.write(master, "Jörg Probst\n54321\nBeispielhausen\n\n\n".encode())
        done = subprocess.run(
            [sys.executable, str(SCRIPT), str(src), "--street", "Lindenweg 7"],
            stdin=slave, capture_output=True, text=True, encoding="utf-8", timeout=60,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    finally:
        os.close(slave)
        os.close(master)
    assert done.returncode == 0, done.stderr
    for prompt in ("Vor- und Nachname", "Postleitzahl", "Ort", "Telefonnummer", "Mail-Adresse"):
        assert prompt in done.stdout, prompt
    assert "Straße und Hausnummer" not in done.stdout  # given as an option
    assert "leer lassen" in done.stdout.lower()
    assert "Ohne eigene Angaben" not in done.stdout
    dump = _dump((src / "anonymisiert" / "001_dhl.de.eml").read_bytes())
    for secret in ("jörg", "probst", "54321", "beispielhausen", "lindenweg"):
        assert secret not in dump, secret
        assert secret not in done.stdout.lower(), secret


def test_private_sender_of_a_forwarded_mail_is_replaced(tmp_path):
    msg = EmailMessage()
    msg["From"] = "Jörg Probst <jp1987@gmx.de>"
    msg["To"] = "pakete@postfach.example"
    msg["Subject"] = "WG: Ihr Paket kommt"
    msg["Date"] = "Tue, 18 Jul 2023 08:02:46 +0000"
    msg.set_content("Von: noreply@dhl.de\nIhr Paket kommt. Antwort an jp1987@gmx.de\n")
    src = _write(tmp_path / "mails", [bytes(msg)])
    done = _call(src, "--ohne-angaben")
    assert done.returncode == 0, done.stderr
    [written] = (src / "anonymisiert").iterdir()
    assert written.name == "001_privat.eml"
    assert "jp1987" not in _dump(written.read_bytes())
    assert str(_msg(written.read_bytes())["Subject"]) == "WG: Ihr Paket kommt"
    assert "privaten Adresse" in done.stdout


def test_private_senders_and_sellers_are_replaced_companies_stay(tmp_path):
    hermes = "Hermes <noreply@paketankuendigung.myhermes.de>"
    private = EmailMessage()
    private["From"] = hermes
    private["Subject"] = "Dein Hermes Paket von Erika Sonnenschein wurde zugestellt."
    private.set_content(
        "Hallo,\n\ndeine Sendung von Erika Sonnenschein wurde zugestellt.\n\n"
        "*Versender*\nErika Sonnenschein\nAm Alten Hafen 3\n67890 Anderswo\n\n"
        "----------\n*an Jörg Probst*\nLindenweg 7\n54321 Beispielhausen\n----------\n\n"
        "Verkäufer: haendler-meier\nNoch ein Gruß von haendler-meier.\n"
        "Referenz [#0123456789abcdef0123456789abcdef]\n"
        "Ihr Einmalpasswort lautet 4821.\n"
        "Geplantes Zustelldatum: 02/10/2026, Rückruf 0049 (0) 151 1234 5678\n"
        "DHL: 00340434123456780001, Rückruf 0151 12345678 99887766554\n"
    )
    company = EmailMessage()
    company["From"] = hermes
    company["Subject"] = "Dein Hermes Paket von Holzwurm Möbel GmbH wurde zugestellt."
    company.set_content(
        "deine Sendung von Holzwurm Möbel GmbH wurde zugestellt.\n\n"
        "*Versender*\nHolzwurm Möbel GmbH\nSägeweg 3 ,\n98765 Spanstadt\n\n"
        "Danke, Erika Sonnenschein\n"
        "Dein Paket von GLS wird heute zugestellt.\nAblageort: Carport\nDer Carport ist frei.\n"
    )
    src = _write(tmp_path / "mails", [bytes(private), bytes(company)])
    done = _call(src, "--ohne-angaben")
    assert done.returncode == 0, done.stderr
    first, second = sorted((src / "anonymisiert").iterdir())
    for path in (first, second):
        dump = _dump(path.read_bytes())
        for secret in ("erika", "sonnenschein", "alten hafen", "anderswo", "jörg", "probst",
                       "lindenweg", "haendler", "0123456789", "abcdef", "1234 5678", "sägeweg",
                       "spanstadt"):
            assert secret not in dump, (path.name, secret)
        # whole numbers only: invented digits may contain a short number by chance
        assert not re.search(r"(?<!\d)(?:67890|54321|98765|4821)(?!\d)", dump), path.name
    text = _plain(first.read_bytes())
    assert str(_msg(first.read_bytes())["Subject"]) == (
        "Dein Hermes Paket von Beispielversender wurde zugestellt."
    )
    assert "deine Sendung von Beispielversender wurde zugestellt." in text
    assert "*Versender*\nBeispielversender\nBeispielweg 2\n00000 Beispielstadt\n" in text
    assert "*an Max Mustermann*\nMusterstraße 1\n12345 Musterstadt\n----------" in text
    assert "Verkäufer: beispielshop\nNoch ein Gruß von beispielshop.\n" in text
    assert re.search(r"Referenz \[#[0-9a-f]{32}\]\n", text)
    assert re.search(r"Ihr Einmalpasswort lautet \d{4}\.\n", text)
    assert "Geplantes Zustelldatum: 02/10/2026, Rückruf +49 000 0000000\n" in text
    assert re.search(r"DHL: 00340\d{15}, Rückruf \+49 000 0000000 \d{11}\n", text)
    assert "00340434123456780001" not in text and "99887766554" not in text
    text = _plain(second.read_bytes())
    assert str(_msg(second.read_bytes())["Subject"]) == (
        "Dein Hermes Paket von Holzwurm Möbel GmbH wurde zugestellt."
    )
    assert "*Versender*\nHolzwurm Möbel GmbH\nBeispielweg 2\n00000 Beispielstadt\n" in text
    assert "Danke, Beispielversender\n" in text
    # a single common word is replaced at its place only, a carrier is no private sender
    assert (
        "Dein Paket von GLS wird heute zugestellt.\nAblageort: Garage\nDer Carport ist frei.\n"
        in text
    )


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((), "usage: anonymize_mail.py"),
        (("--zip",), "Datei oder Ordner fehlt"),
        (("fehlt.eml",), "nicht gefunden"),
        (("leer",), "Keine .eml-Dateien gefunden"),
        (("leer", "--geheim=Probst"), "Unbekannte Option --geheim"),
        (("leer", "--name"), "Option --name braucht einen Wert"),
    ],
)
def test_usage_errors_exit_with_2(tmp_path, args, message):
    (tmp_path / "leer").mkdir()
    done = _call(*args, cwd=tmp_path)
    assert done.returncode == 2
    assert done.stderr.startswith("usage: anonymize_mail.py") and message in done.stderr
    assert "Probst" not in done.stderr and done.stdout == ""
    assert not (tmp_path / "leer" / "anonymisiert").exists()


def test_help_is_german_and_exits_with_0():
    done = _call("--help")
    assert done.returncode == 0
    for text in ("--zip", "--out", "--name", "--street", "--postcode", "--city", "--phone",
                 "--email", "--ohne-angaben", "anonymisiert", "paket-tracker-beispiele.zip"):
        assert text in done.stdout, text


def test_script_runs_as_a_single_copied_file(tmp_path):
    copy = Path(shutil.copy(SCRIPT, tmp_path / "anonymize_mail.py"))
    src = _write(tmp_path / "mails", [_unknown()])
    done = _call(src, *VALUES, script=copy, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert [p.name for p in (src / "anonymisiert").iterdir()] == ["001_holzwurm-shop.example.eml"]


def test_script_uses_only_the_standard_library_and_no_network():
    source = SCRIPT.read_text(encoding="utf-8")
    modules = set(re.findall(r"(?m)^(?:import|from) (\w+)", source))
    assert modules <= {
        "email", "glob", "hashlib", "html", "os", "re", "secrets", "sys", "unicodedata", "zipfile",
    }
    assert not modules & {"socket", "urllib", "http", "ssl", "subprocess"}


# ----- v0.3.15 second review: a forwarded mail may still carry the forwarder's signature -----
def _forward_case(subject: str, body: str, sender: str = "Jörg Probst <jp1987@gmx.de>") -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "pakete@postfach.example"
    msg["Subject"] = subject
    msg["Date"] = "Tue, 18 Jul 2023 08:02:46 +0000"
    msg.set_content(body)
    return bytes(msg)


QUOTED = (
    "Viele Grüße\n\n-------- Weitergeleitete Nachricht --------\n"
    "Von: DHL <noreply@dhl.de>\nGesendet: Dienstag, 18. Juli 2023 08:00\n"
    "Betreff: Ihr Paket kommt\n\nIhr Paket kommt.\n"
)


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("WG: Ihr Paket kommt", "Ihr Paket kommt.\n"),
        ("Fwd: Ihr Paket kommt", "Ihr Paket kommt.\n"),
        ("Fw: Ihr Paket kommt", "Ihr Paket kommt.\n"),
        ("FW: WG: Ihr Paket kommt", "Ihr Paket kommt.\n"),
        ("Ihr Paket kommt", QUOTED),
    ],
)
def test_a_mail_that_looks_forwarded_gets_a_warning_line(tmp_path, subject, body):
    src = _write(tmp_path / "mails", [_known(), _forward_case(subject, body)])
    done = _call(src, "--name", "Jörg Probst")
    assert done.returncode == 0, done.stderr
    [line] = [text for text in done.stdout.splitlines() if "weitergeleitet aus" in text]
    assert line.startswith("ACHTUNG:")
    names = sorted(path.name for path in (src / "anonymisiert").glob("*.eml"))
    assert names[1] in line and names[0] not in line
    assert "Signatur" in done.stdout and "Original" in done.stdout
    for secret in ("jörg", "probst", "jp1987"):
        assert secret not in done.stdout.lower(), secret


def test_original_mails_get_no_forward_warning(tmp_path):
    src = _write(tmp_path / "mails", [_known(), _unknown()])
    done = _call(src, "--name", "Jörg Probst")
    assert done.returncode == 0, done.stderr
    assert "weitergeleitet aus" not in done.stdout

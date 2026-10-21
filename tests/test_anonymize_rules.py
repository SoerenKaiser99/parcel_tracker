"""Tester mode of the anonymiser: rules of the v0.3.3 final review (invented mails only)."""

import email
import html
import os
import re
import subprocess
import sys
import urllib.parse
from email import policy
from email.message import EmailMessage
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "anonymize_mail.py"
DATE = "Tue, 18 Jul 2023 08:02:46 +0000"
SHOP = "Paketflitzer <tracking@paketflitzer.example>"
HERMES = "Hermes <noreply@paketankuendigung.myhermes.de>"


def _mail(sender: str, subject: str, text: str, to: str = "pakete@postfach.example") -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = DATE
    msg.set_content(text)
    return bytes(msg)


def _call(*args, **kwargs):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"}, **kwargs,
    )


def _run(tmp_path: Path, mails, *args):
    """Anonymise ``mails`` without personal values: (process, [(file name, message)])."""
    src = tmp_path / "mails"
    src.mkdir()
    for i, raw in enumerate(mails):
        (src / f"mail{i}.eml").write_bytes(raw)
    done = _call(src, *(args or ("--ohne-angaben",)))
    assert done.returncode == 0, done.stderr
    written = sorted((src / "anonymisiert").glob("*.eml"))
    return done, [
        (p.name, email.message_from_bytes(p.read_bytes(), policy=policy.default)) for p in written
    ]


def _text(msg: EmailMessage) -> str:
    return msg.get_body(("plain",)).get_content()


def _dump(msg: EmailMessage) -> str:
    """Everything readable in a written mail, lower case."""
    raw = bytes(msg)
    chunks = [raw.decode("utf-8", "replace"), *(f"{key}: {value}" for key, value in msg.items())]
    for part in msg.walk():
        if not part.is_multipart():
            payload = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
            chunks += [payload, html.unescape(payload)]
    text = "\n".join(chunks)
    return (text + urllib.parse.unquote(text)).lower()


def _absent(msg: EmailMessage, *secrets: str) -> None:
    dump = _dump(msg)
    for secret in secrets:
        assert secret not in dump, secret


# ----- 1: address blocks -----

def test_address_blocks_with_other_labels_and_postcode_layouts(tmp_path):
    raw = _mail(
        SHOP,
        "Ihr Paket ist unterwegs",
        "Ihr Paket ist unterwegs.\n\n"
        "Ship To: \n\nErika Sonnenschein\nAm Alten Hafen 3\nANDERSWO NW 67890\nDE\n\n"
        "Lieferanschrift\nErika Sonnenschein\nAm Alten Hafen 3\nAnderswo, 67890\n\n"
        "Deliver to:\nErika Sonnenschein\nAm Alten Hafen 3\n67890\nAnderswo\n"
        "Sendungsnummer: JJD000390007812345678\n\n"
        "Delivery\nErika Sonnenschein\nAm Alten Hafen 3\n67890 Anderswo\nEnde\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    block = "Max Mustermann\nMusterstraße 1\n12345 Musterstadt\n"
    assert "Ship To: \n" + block + "DE\n" in text
    assert "Lieferanschrift\n" + block + "\nDeliver to:\n" in text
    # the city on its own line below the postcode goes too, the next label stays
    assert "Deliver to:\n" + block + "Sendungsnummer: JJD" in text
    assert "Delivery\n" + block + "Ende\n" in text
    _absent(msg, "erika", "sonnenschein", "alten hafen", "anderswo", "67890")


# ----- eBay: purchase confirmations and messages, each mail on its own -----

EBAY = "eBay <ebay@ebay.com>"
TILDA = ("tilda", "sonnberg", "ahornallee", "80000", "anderswo", "kugelfisch77")


@pytest.mark.parametrize(
    "block",
    [
        # the current layout: the country above the name, a phone number above the postcode
        "Ihre Bestellung wird verschickt an:\nDeutschland\nTilda Sonnberg\nAhornallee 5\n"
        "0151 2345678\n80000 Anderswo\n",
        "Ihre Bestellung wird verschickt nach:\nTilda Sonnberg\nAhornallee 5, 0151 2345678\n"
        "Anderswo 80000\n",
        "Versandziel:\nTilda Sonnberg\nAhornallee 5\n80000 Anderswo\n",
    ],
)
def test_ebay_purchase_confirmation_keeps_no_name_address_or_user_name(tmp_path, block):
    raw = _mail(
        EBAY, "kugelfisch77, Ihre Bestellung wurde bestätigt.",
        "Willkommen zurück, kugelfisch77! Danke, dass Sie wieder bei uns gekauft haben.\n"
        f"{block}\nDiese Nachricht wurde von eBay an Tilda Sonnberg (kugelfisch77) gesendet.\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    _absent(msg, *TILDA)
    assert msg["Subject"] == "beispielnutzer, Ihre Bestellung wurde bestätigt."
    assert "Willkommen zurück, beispielnutzer! Danke" in text
    assert "Max Mustermann\nMusterstraße 1\n12345 Musterstadt" in text
    assert "von eBay an Max Mustermann (beispielnutzer) gesendet." in text


def test_ebay_message_keeps_no_name_or_user_name_of_the_buyer(tmp_path):
    raw = _mail(
        "eBay - kugelfisch77 <member@ebay.com>",
        "kugelfisch77 hat eine Nachricht gesendet zu Akku-Laubbläser #123456789012",
        "Hallo, ich bräuchte noch eine Rechnung.\nVG T. Sonnberg\n- kugelfisch77\n\n"
        "Diese Nachricht wurde von eBay gesendet an Tilda Sonnberg (kugelfisch77). Mehr.\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    _absent(msg, *TILDA)
    assert "\n- beispielnutzer\n" in text
    assert msg["Subject"].startswith("beispielnutzer hat eine Nachricht gesendet zu")


# ----- 2: private senders -----

def test_private_sender_names_in_sentences_and_label_lines(tmp_path):
    raw = _mail(
        HERMES,
        "Deine Sendung ist unterwegs",
        "Dein Paket von Erika Sonnenschein mit der Sendungsnummer H1234567890123456789 kommt.\n"
        "Ihre Sendung von Bodo Ballermann, die Sie erwarten, ist unterwegs.\n"
        "Wir haben ein Paket von Clara Kirschbaum.\n"
        "Absender: Dieter Donnerwetter\n"
        "Versender: Holzwurm Möbel GmbH\n"
        "Dein Paket von Zalando.\n"
        "Die Sendung von Montag, dem 3. Juli, kommt morgen.\n"
        "Noch ein Gruß an Bodo Ballermann.\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    assert re.search(r"Dein Paket von Beispielversender mit der Sendungsnummer H\d{19} kommt", text)
    assert "Ihre Sendung von Beispielversender, die Sie erwarten, ist unterwegs.\n" in text
    assert "Wir haben ein Paket von Beispielversender.\n" in text
    assert "Absender: Beispielversender\n" in text
    assert "Versender: Holzwurm Möbel GmbH\n" in text
    assert "Dein Paket von Zalando.\n" in text
    assert "Die Sendung von Montag, dem 3. Juli, kommt morgen.\n" in text
    assert "Noch ein Gruß an Beispielversender.\n" in text  # learnt: replaced everywhere
    _absent(msg, "sonnenschein", "ballermann", "kirschbaum", "donnerwetter")


def test_private_name_in_from_display_and_subject_is_replaced_and_learnt(tmp_path):
    private = _mail(
        "Gundula Gartenzwerg <versand@kleinerladen.example>",
        "Fritz Feuerstein hat dir ein Paket geschickt",
        "Dein Paket ist unterwegs.\n\nViele Grüße\nGundula Gartenzwerg\n"
        "Danke an Fritz Feuerstein.\n",
    )
    subject = _mail(
        SHOP, "Paket für Wilma Wolkenbruch ist unterwegs", "Bald da, Wilma Wolkenbruch.\n"
    )
    shop = _mail("Holzwurm Shop <versand@holzwurm-shop.example>", "Deine Bestellung", "Danke.\n")
    carrier = _mail("DHL Paket <noreply@dhl.de>", "Ihr DHL Paket kommt", "Bald.\n")
    _, [(name, first), (_, second), (_, third), (_, fourth)] = _run(
        tmp_path, [private, subject, shop, carrier]
    )
    assert name == "001_kleinerladen.example.eml"
    assert str(first["From"]) == "Beispielversender <versand@kleinerladen.example>"
    assert str(first["Subject"]) == "Beispielversender hat dir ein Paket geschickt"
    assert "Viele Grüße\nBeispielversender\nDanke an Beispielversender.\n" in _text(first)
    assert str(second["Subject"]) == "Paket für Max Mustermann ist unterwegs"
    assert "Bald da, Max Mustermann.\n" in _text(second)
    assert str(third["From"]) == "Holzwurm Shop <versand@holzwurm-shop.example>"
    assert str(fourth["From"]) == "DHL Paket <noreply@dhl.de>"
    assert str(fourth["Subject"]) == "Ihr DHL Paket kommt"
    for msg in (first, second):
        _absent(msg, "gundula", "gartenzwerg", "feuerstein", "wilma", "wolkenbruch")


# ----- 3: neighbours and recipients -----

def test_neighbour_and_recipient_names(tmp_path):
    raw = _mail(
        "DHL Paket <noreply@dhl.de>",
        "Ihr Paket wurde zugestellt",
        "Zugestellt an Nachbar: Bodo Ballermann\n"
        "Ihr Paket wurde beim Nachbarn Herrn Kirschbaum abgegeben.\n"
        "Empfangen von: D. DONNERWETTER\n"
        "Unterschrift: Feuerstein\n"
        "Das Paket wurde entgegengenommen von Gundula Gartenzwerg.\n"
        "Die Sendung wurde übergeben an Erika Sonnenschein\n"
        "Das Paket wurde abgegeben bei Wilma Wolkenbruch\n"
        "Die Sendung wurde übergeben an DHL.\n"
        "Eine Unterschrift ist erforderlich.\n"
        "Das Paket wurde an den Nachbarn abgegeben.\n"
        "Übergeben an Empfänger\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    for line in (
        "Zugestellt an Nachbar: Beispielnachbar\n",
        "Ihr Paket wurde beim Nachbarn Herrn Beispielnachbar abgegeben.\n",
        "Empfangen von: Max Mustermann\n",
        "Unterschrift: Max Mustermann\n",
        "Das Paket wurde entgegengenommen von Max Mustermann.\n",
        "Die Sendung wurde übergeben an Max Mustermann\n",
        "Das Paket wurde abgegeben bei Beispielnachbar\n",
        "Die Sendung wurde übergeben an DHL.\n",
        "Eine Unterschrift ist erforderlich.\n",
        "Das Paket wurde an den Nachbarn abgegeben.\n",
        "Übergeben an Empfänger\n",
    ):
        assert line in text, line
    _absent(msg, "ballermann", "kirschbaum", "donnerwetter", "feuerstein", "gartenzwerg",
            "sonnenschein", "wolkenbruch")


# ----- 4: generic mode -----

def test_amazon_name_and_place_line_above_the_order_number(tmp_path):
    raw = _mail(
        '"Amazon.de" <shipment-tracking@amazon.de>',
        "In Zustellung: „Tastatur...“",
        "Paket befindet sich in Zustellung!\n\nAnkunft heute 18h – 22h\n"
        "Jörg – Beispielhausen\nBestellnr. ‫302-1234567-7654321\n\n"
        "Lieferung nach Beispielhausen für Jörg.\nHeute – morgen\nLieferung verfolgen\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    assert re.search(
        r"Ankunft heute 18h – 22h\nMax – Musterstadt\nBestellnr\. \d{3}-\d{7}-\d{7}\n", text
    )
    assert "Lieferung nach Musterstadt für Max.\n" in text
    assert "Heute – morgen\nLieferung verfolgen\n" in text  # no order number below: stays
    _absent(msg, "jörg", "beispielhausen", "302-1234567")


def test_salutation_without_punctuation_and_names_learnt_from_it(tmp_path):
    raw = _mail(
        SHOP,
        "Ihre Bestellung",
        "Guten Tag Jörg Probst\n\nIhre Bestellung ist unterwegs.\n"
        "Danke, Herr Probst, für den Einkauf. Jörgs Paket kommt.\n\nHallo zusammen,\nbis bald.\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    assert "Guten Tag Max Mustermann\n\nIhre Bestellung ist unterwegs.\n" in text
    assert "Danke, Herr Mustermann, für den Einkauf. Max Paket kommt.\n" in text
    assert "bis bald.\n" in text
    _absent(msg, "jörg", "probst")


def test_name_of_the_to_header_is_learnt(tmp_path):
    raw = _mail(
        SHOP, "Ihre Bestellung", "Vielen Dank, Jörg!\nProbst steht auf dem Paket.\n",
        to="Jörg Probst <jp@privatpost.example>",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    assert "Vielen Dank, Max!\nMustermann steht auf dem Paket.\n" in _text(msg)
    _absent(msg, "jörg", "probst")


def test_postcode_and_city_lines_without_a_label(tmp_path):
    raw = _mail(
        SHOP,
        "Ihre Bestellung",
        "Wir liefern an:\nErika Sonnenschein\nAm Alten Hafen 3\n67890 Anderswo\n\n"
        "Abholung: Paketshop Kiosk, Sägeweg 3, 98765 Spanstadt\n"
        "Der Laden im Sägeweg hat bis 18 Uhr auf, Am Alten Hafen ist gesperrt.\n"
        "Erika Sonnenschein in 67890 Anderswo hat 20000 Punkte gesammelt.\n\n"
        "Holzwurm Möbel GmbH\nSpanplatz 12\n98765 Spanstadt\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    assert "Wir liefern an:\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\n" in text
    assert "Abholung: Paketshop Kiosk, Musterstraße 1, 12345 Musterstadt\n" in text
    assert "Der Laden im Sägeweg hat bis 18 Uhr auf, Musterstraße ist gesperrt.\n" in text
    assert "Max Mustermann in 12345 Musterstadt hat 20000 Punkte gesammelt.\n" in text
    assert "Holzwurm Möbel GmbH\nMusterstraße 1\n12345 Musterstadt\n" in text
    _absent(msg, "erika", "sonnenschein", "alten hafen", "anderswo", "67890", "spanstadt",
            "98765", "spanplatz")


def test_without_values_the_flag_is_required(tmp_path):
    src = tmp_path / "mails"
    src.mkdir()
    (src / "mail0.eml").write_bytes(_mail(SHOP, "Ihre Bestellung", "Hallo Jörg,\ndanke.\n"))
    done = _call(src)
    assert done.returncode == 2
    assert done.stdout == ""
    assert "--ohne-angaben" in done.stderr and "--name" in done.stderr
    assert "Ohne eigene Angaben" in done.stderr
    assert not (src / "anonymisiert").exists()
    done = _call(src, "--ohne-angaben")
    assert done.returncode == 0, done.stderr
    assert "ACHTUNG" in done.stdout
    assert "Namen und Orte können stehen bleiben" in done.stdout
    assert (src / "anonymisiert" / "001_paketflitzer.example.eml").is_file()
    # a value makes the flag unnecessary, and the warning goes
    done = _call(src, "--name", "Jörg Probst")
    assert done.returncode == 0, done.stderr
    assert "ACHTUNG" not in done.stdout


def test_without_a_stdin_nothing_is_asked(tmp_path):
    """Started without a console (pythonw, a service), a script has no stdin: it is None."""
    src = tmp_path / "mails"
    src.mkdir()
    (src / "mail0.eml").write_bytes(_mail(SHOP, "Ihre Bestellung", "Hallo Jörg,\ndanke.\n"))
    code = (
        "import runpy, sys\n"
        "sys.stdin, sys.argv = None, sys.argv[1:]\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code, str(SCRIPT), str(src)],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert done.returncode == 2
    assert done.stdout == ""
    assert "Ohne eigene Angaben" in done.stderr
    assert not (src / "anonymisiert").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="needs a pseudo terminal")
def test_terminal_with_only_empty_answers_needs_the_flag_too(tmp_path):
    import pty

    src = tmp_path / "mails"
    src.mkdir()
    (src / "mail0.eml").write_bytes(_mail(SHOP, "Ihre Bestellung", "Hallo Jörg,\ndanke.\n"))
    master, slave = pty.openpty()
    try:
        os.write(master, b"\n\n\n\n\n\n")
        done = subprocess.run(
            [sys.executable, str(SCRIPT), str(src)],
            stdin=slave, capture_output=True, text=True, encoding="utf-8", timeout=60,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    finally:
        os.close(slave)
        os.close(master)
    assert done.returncode == 2
    assert "Vor- und Nachname" in done.stdout  # the questions were asked
    assert "--ohne-angaben" in done.stderr
    assert not (src / "anonymisiert").exists()


# ----- more layouts of addresses, forms and recipients -----

def test_name_behind_recipient_without_an_address(tmp_path):
    raw = _mail(
        "DPD <noreply@service.dpd.de>", "Ihr Paket kommt heute",
        "Empfänger:\nTilda Sonnberg\nPaket live verfolgen\n"
        "[01234567890123](https://my.dpd.de/x)Empfänger:Tilda Sonnberg   [Paket live verfolgen]\n"
        "Empfänger: DPD Deutschland GmbH\nEmpfänger:\nDeutsche Post\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    _absent(msg, "tilda", "sonnberg")
    assert "Empfänger:\nMax Mustermann\nPaket live verfolgen\n" in text
    assert "Empfänger: DPD Deutschland GmbH\nEmpfänger:\nDeutsche Post\n" in text


def test_fields_of_a_form(tmp_path):
    raw = _mail(
        SHOP, "Auftragsbestätigung",
        "Name / Unternehmen: Tilda Sonnberg\nStraßenname: Ahornallee 5\nPLZ & Ort: 80000 Anderswo\n"
        "Land: Deutschland\n\nVorname:\nTilda\nNachname:\nSonnberg\n\n"
        "Straßenname:\nPostfach\nKundenname: Paketflitzer Service\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    _absent(msg, "tilda", "sonnberg", "ahornallee", "80000", "anderswo")
    assert (
        "Name / Unternehmen: Max Mustermann\nStraßenname: Musterstraße 1\n"
        "PLZ & Ort: 12345 Musterstadt\nLand: Deutschland\n\nVorname:\nMax\nNachname:\nMustermann\n"
    ) in text
    assert "Straßenname:\nPostfach\nKundenname: Paketflitzer Service\n" in text


def test_postcode_behind_a_pickup_place_in_bold(tmp_path):
    raw = _mail(
        "DHL <noreply@dhl.de>", "Ihr Paket liegt bereit",
        "Abgabestelle\n**Packstation 123, ****80000 Anderswo**\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    _absent(msg, "80000", "anderswo")
    assert ", ****12345 Musterstadt**\n" in _text(msg)


def test_first_name_and_place_below_amazons_old_ship_to(tmp_path):
    raw = _mail(
        "Amazon.de <versandbestaetigung@amazon.de>", "Ihre Amazon.de-Bestellung wurde versandt",
        "Die Sendung geht an:\n    Tilda\n    Anderswo\nGesamtbetrag der Bestellung: EUR 18,99\n"
        "Hallo Tilda, Anderswo freut sich.\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    _absent(msg, "tilda", "anderswo")
    assert "Die Sendung geht an:\n    Max\n    Musterstadt\nGesamtbetrag der Bestellung:" in text


@pytest.mark.parametrize(
    "block",
    [
        "an folgende Adresse zu:\nTilda Sonnberg\nTilda Sonnberg\nAhornallee 5\n"
        "DE-80000 Anderswo\n",
        "Ich habe Ihr Paket erfolgreich zugestellt:\nTilda Sonnberg\nAhornallee 5\n"
        "DE-80000 Anderswo\n",
        "Das Paket wurde an folgender Adresse zugestellt (bei einer Wunschzustellung ggf. "
        "abweichend):\n  Tilda Sonnberg, 0151 2345678\nAhornallee 5\n80000 Anderswo\n",
        "Ship to\nAhornallee, 5\nAnderswo, Bayern\nTilda Sonnberg (+49)1512345678\n",
        "Ship to\nAhornallee, 5, Anderswo, Bayern\nPayment method\n",
        "Lieferanschrift\nAnderswo, Bavaria, Ahornallee 5\nDE\n",
    ],
)
def test_more_address_blocks(tmp_path, block):
    raw = _mail(SHOP, "Ihre Sendung", f"Ihr Paket kommt.\n{block}Viel Freude damit.\n")
    _, [(_, msg)] = _run(tmp_path, [raw])
    _absent(msg, "tilda", "sonnberg", "ahornallee", "80000", "anderswo")
    assert "Viel Freude damit.\n" in _text(msg)


@pytest.mark.parametrize(
    "place",
    [
        "Adresse\nPackstation 123\nLindenstr. 9, Supermarkt\n80000Anderswo\n",
        "Pickup Paketshop:\nKiosk Beispiel\nBirkenweg 3\nDE-80000 Anderswo\n",
    ],
)
def test_street_of_a_pickup_place_with_more_layouts(tmp_path, place):
    raw = _mail("DHL <noreply@dhl.de>", "Ihr Paket liegt bereit", f"Abholen bei:\n{place}")
    _, [(_, msg)] = _run(tmp_path, [raw])
    _absent(msg, "lindenstr", "birkenweg", "80000", "anderswo")


def test_more_fields_of_a_form(tmp_path):
    raw = _mail(
        SHOP, "Auftragsbestätigung",
        "Straße | Nr.: Ahornallee 5\nPlz: 80000\nOrt: Anderswo\nPLZ, Ort: 80000 Anderswo\n"
        "Ort: 80000 Anderswo\nOrt: Haustür ist zu\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    _absent(msg, "ahornallee", "80000", "anderswo")
    assert (
        "Straße | Nr.: Musterstraße 1\nPlz: 12345\nOrt: Musterstadt\nPLZ, Ort: 12345 Musterstadt\n"
        "Ort: 12345 Musterstadt\nOrt: Haustür ist zu\n"
    ) in text


# ----- 5: forwarded and private mails -----

def test_forwarded_mail_of_a_private_sender_with_an_own_domain(tmp_path):
    by_subject = _mail(
        "Erika Sonnenschein <erika@kleinefirma.example>",
        "Fwd: Ihre Bestellung ist unterwegs",
        "Schau mal.\n\nIhre Bestellung ist unterwegs.\n",
    )
    by_block = _mail(
        "Erika Sonnenschein <erika@kleinefirma.example>",
        "Paketinfo",
        "-------- Weitergeleitete Nachricht --------\n"
        "Von: Holzwurm Shop <versand@holzwurm-shop.example>\n"
        "Gesendet: Dienstag, 18. Juli 2023 10:02\n"
        "An: erika@kleinefirma.example\nBetreff: Ihre Bestellung\n\n"
        "Ihre Bestellung ist unterwegs.\n",
    )
    # "Von:" as a field of the mail itself (UPS) is no quoted header block
    plain = _mail(
        "UPS Quantum View <pkginfo@ups.com>",
        "UPS Versandbenachrichtigung",
        "Sendungsdetails\n\nVon: Holzwurm Möbel GmbH\n\nKontrollnummer: 1Z999AA10123456784\n",
    )
    done, [(one, first), (two, second), (three, third)] = _run(
        tmp_path, [by_subject, by_block, plain]
    )
    assert (one, two, three) == ("001_privat.eml", "002_privat.eml", "003_ups.com.eml")
    for msg in (first, second):
        assert str(msg["From"]) == "Max Mustermann <max@example.org>"
        _absent(msg, "erika", "sonnenschein", "kleinefirma")
    assert str(first["Subject"]) == "Fwd: Ihre Bestellung ist unterwegs"
    assert str(third["From"]) == "UPS Quantum View <pkginfo@ups.com>"
    assert "2 Mail(s) kommen von einer privaten Adresse" in done.stdout


@pytest.mark.parametrize("prefix", ["WG:", "Fwd:", "Fw:", "FW:", "AW:", "Re:"])
def test_every_forward_and_reply_prefix_marks_the_sender_as_private(tmp_path, prefix):
    raw = _mail("Erika Sonnenschein <erika@kleinefirma.example>", f"{prefix} Ihr Paket", "Text\n")
    _, [(name, msg)] = _run(tmp_path, [raw])
    assert name == "001_privat.eml"
    assert str(msg["From"]) == "Max Mustermann <max@example.org>"


# ----- 7 to 9: phone numbers, drop-off permissions, encoded sender addresses -----

def test_phone_number_with_three_separators(tmp_path):
    raw = _mail(SHOP, "Rückruf", "Rückruf unter 0211 / 123 45 67 oder (0211) 123-45-67.\n")
    _, [(_, msg)] = _run(tmp_path, [raw])
    assert "Rückruf unter +49 000 0000000 oder +49 000 0000000.\n" in _text(msg)
    _absent(msg, "0211", "123 45", "123-45")


def test_drop_off_permission_lines(tmp_path):
    raw = _mail(
        "DHL Paket <noreply@dhl.de>",
        "Ihr Paket kommt",
        "Abstellgenehmigung: Hinter dem Gartenhaus rechts\n"
        "Abstell-Okay: Carport am Seiteneingang\n"
        "Abstellerlaubnis\nUnter dem Vordach\n\nBis bald.\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    assert text.count("Ablageort: Garage\n") == 3
    assert "Bis bald.\n" in text
    _absent(msg, "gartenhaus", "seiteneingang", "vordach")


def test_sender_address_that_carries_the_recipient_is_replaced_as_a_whole(tmp_path):
    raw = _mail(
        "Holzwurm Shop <bounce+joerg.probst=gmx.de@holzwurm-shop.example>",
        "Deine Bestellung",
        "Antwort an bounce+joerg.probst=gmx.de@holzwurm-shop.example\n",
    )
    _, [(name, msg)] = _run(tmp_path, [raw])
    assert name == "001_holzwurm-shop.example.eml"
    assert str(msg["From"]) == "Holzwurm Shop <absender@holzwurm-shop.example>"
    assert "Antwort an max@example.org\n" in _text(msg)
    _absent(msg, "gmx", "bounce", "probst", "joerg")


# ----- 10: stale results -----

def test_stale_results_are_cleared_before_writing(tmp_path):
    src = tmp_path / "mails"
    src.mkdir()
    for i in range(3):
        (src / f"mail{i}.eml").write_bytes(_mail(SHOP, f"Paket {i}", "Unterwegs.\n"))
    done = _call(src, "--ohne-angaben", "--zip")
    assert done.returncode == 0, done.stderr
    out = src / "anonymisiert"
    assert len(list(out.glob("*.eml"))) == 3 and (out / "paket-tracker-beispiele.zip").is_file()
    (out / "notiz.txt").write_text("bleibt", encoding="utf-8")
    foreign = _mail(SHOP, "Fremde Mail", "Nicht vom Skript geschrieben.\n")
    (out / "009_fremd.eml").write_bytes(foreign)
    (src / "mail1.eml").unlink()
    (src / "mail2.eml").unlink()
    done = _call(src, "--ohne-angaben")
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in out.iterdir()) == [
        "001_paketflitzer.example.eml", "009_fremd.eml", "notiz.txt",
    ]
    assert (out / "009_fremd.eml").read_bytes() == foreign


# ----- found in the real-world check: layouts of HTML mails, senders named in sentences -----

def test_sender_block_with_the_city_on_its_own_line(tmp_path):
    raw = _mail(
        "GLS Paket <no-reply@gls-pakete.de>",
        "Dein GLS Paket kommt heute!",
        "Versender\nHolzwurm Möbel GmbH\nSägeweg 3\n,\n98765\nSpanstadt\n"
        "Paketnummer\n12345678901\n"
        "Empfänger\nErika Sonnenschein\nAm Alten Hafen\n3,\n67890\nAnderswo\nZustellung\n"
        "Am Alten Hafen ist gesperrt.\n",
    )
    _, [(_, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    assert (
        "Versender\nHolzwurm Möbel GmbH\nBeispielweg 2\n00000 Beispielstadt\nPaketnummer\n" in text
    )
    assert "Empfänger\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\nZustellung\n" in text
    assert "Musterstraße ist gesperrt.\n" in text  # the street stands above its house number
    _absent(msg, "spanstadt", "98765", "sägeweg", "anderswo", "67890", "alten hafen")


def test_sender_named_in_a_carrier_sentence(tmp_path):
    raw = _mail(
        "UPS Quantum View <pkginfo@ups.com>",
        "UPS Versandbenachrichtigung",
        "Diese Nachricht kommt auf Antrag von Kirschbaum , um Sie zu informieren.\n"
        "Im Auftrag von Ballermann möchten wir Sie mit dieser Benachrichtigung informieren.\n"
        "This message was sent to you at the request of Donnerwetter to notify you.\n"
        "Auf Antrag von Holzwurm Möbel GmbH , um Sie zu informieren.\n"
        "Von: Kirschbaum\n\nKontrollnummer: 1Z999AA10123456784\n"
        "Der Zustellversuch für deine Sendungvon Haselnuss findet am Donnerstag statt.\n",
    )
    _, [(name, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    assert name == "001_ups.com.eml"
    assert "auf Antrag von Beispielversender , um Sie zu informieren.\n" in text
    assert "Im Auftrag von Beispielversender möchten wir Sie" in text
    assert "at the request of Beispielversender to notify you.\n" in text
    assert "Auf Antrag von Holzwurm Möbel GmbH , um Sie zu informieren.\n" in text
    assert "Von: Beispielversender\n" in text
    assert "deine Sendungvon Beispielversender findet am Donnerstag statt.\n" in text
    _absent(msg, "kirschbaum", "ballermann", "donnerwetter", "haselnuss")


# ----- --salt: each mail gives the same file in every run, alone or with others -----

SALT = "3f" * 32  # the form the script writes: 64 hex digits


def _salted(tmp_path: Path, mails: dict, *args, salt: str = SALT):
    """Anonymise ``mails`` ({file name: bytes}) with a salt: (process, {name: bytes})."""
    src = tmp_path / "mails"
    src.mkdir(parents=True, exist_ok=True)
    for name, raw in mails.items():
        (src / name).write_bytes(raw)
    (tmp_path / "salt.txt").write_text(f"{salt}\n", encoding="utf-8")
    done = _call(src, "--salt", tmp_path / "salt.txt", *(args or ("--ohne-angaben",)))
    assert done.returncode == 0, done.stderr
    out = src / "anonymisiert"
    return done, {p.name: p.read_bytes() for p in out.iterdir()}


def _two_parts(number: str, message_id: str) -> bytes:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Date"] = SHOP, "jp@postfach.example", "Paket", DATE
    msg["Message-ID"] = message_id
    msg.set_content(f"Ihre Sendungsnummer {number} ist unterwegs.\n")
    msg.add_alternative(f"<p>Ihre Sendungsnummer {number} ist unterwegs.</p>", subtype="html")
    return bytes(msg)


def test_salt_gives_the_same_file_for_a_mail_alone_and_among_others(tmp_path):
    mails = {
        f"mail{i}.eml": _two_parts(f"0034043416109401234{i}", f"<{i}@paketflitzer.example>")
        for i in range(5)
    }
    _, alone = _salted(tmp_path / "a", {"mail3.eml": mails["mail3.eml"]})
    _, together = _salted(tmp_path / "b", mails)
    [(name, data)] = alone.items()
    assert together[name] == data
    assert re.fullmatch(r"2023-07-18_paketflitzer\.example_[0-9a-f]{12}\.eml", name)
    tag = name[-16:-4]
    assert data.count(f"--===============beispiel-{tag}==".encode()) == 3
    assert f"Message-ID: <beispiel-{tag}@example.org>".encode() in data
    assert b"00340434161094012343" not in data and b"3@paketflitzer" not in data
    # another salt: other numbers, another name
    _, other = _salted(tmp_path / "c", {"mail3.eml": mails["mail3.eml"]}, salt="a1" * 32)
    [(other_name, other_data)] = other.items()
    assert other_name != name
    assert re.findall(rb"00340\d{15}", other_data) != re.findall(rb"00340\d{15}", data)


def test_without_salt_every_run_has_its_own_secret(tmp_path):
    src = tmp_path / "mails"
    src.mkdir()
    (src / "a.eml").write_bytes(_two_parts("00340434161094012345", "<a@paketflitzer.example>"))
    numbers = []
    for _ in range(2):
        assert _call(src, "--ohne-angaben").returncode == 0
        [written] = (src / "anonymisiert").glob("*.eml")
        assert written.name == "001_paketflitzer.example.eml"
        numbers.append(re.findall(rb"00340\d{15}", written.read_bytes()))
    assert len(set(numbers[0])) == 1 and numbers[0] != numbers[1]


def test_salt_clears_a_run_without_salt_and_names_older_results_with_salt(tmp_path):
    """Nothing of an earlier run goes up by mistake: the ZIP and the NNN_*.eml of a run
    without a salt are removed, a result with a salt that this run did not write is named."""
    raw = _two_parts("00340434161094012345", "<a@paketflitzer.example>")
    _, first = _salted(tmp_path, {"a.eml": raw, "b.eml": _two_parts("1", "<b@x.example>")})
    (tmp_path / "mails" / "b.eml").unlink()
    out = tmp_path / "mails" / "anonymisiert"
    for name in first:
        (out / name).write_bytes(b"alt\nMessage-ID: <beispiel-alt@example.org>\n")
    (out / "001_paketflitzer.example.eml").write_bytes(b"\nMessage-ID: <beispiel-001@x.example>\n")
    (out / "paket-tracker-beispiele.zip").write_bytes(b"alt")
    done, second = _salted(tmp_path, {"a.eml": raw})
    [stale] = (name for name in first if second[name].startswith(b"alt"))
    assert sorted(second) == sorted(first)  # the result of a.eml written over, no ZIP, no 001
    assert f"früheren Lauf, nicht aus\ndiesem. Nicht mit hochladen: {stale}\n" in done.stdout
    assert "Hochgeladen werden nur die Dateien dieses Laufs (oben aufgelistet)" in done.stdout


def test_salt_learns_from_every_mail_of_the_run(tmp_path):
    """A neighbour named in one mail is looked for in the others, as without a salt."""
    mails = {
        "a.eml": _mail(SHOP, "Zugestellt", "Ihr Paket liegt bei Ihrem Nachbarn Lena Holzer.\n"),
        "b.eml": _mail(SHOP, "Danke", "Lena Holzer hat für Sie unterschrieben.\n"),
    }
    _, salted = _salted(tmp_path, mails)
    texts = [email.message_from_bytes(data, policy=policy.default) for data in salted.values()]
    assert len(texts) == 2 and all("Holzer" not in _text(msg) for msg in texts)


def test_a_missing_salt_file_is_written_by_the_script(tmp_path):
    src = tmp_path / "mails"
    src.mkdir()
    (src / "a.eml").write_bytes(_mail(SHOP, "Paket", "Unterwegs.\n"))
    salt = tmp_path / "salt.txt"
    first = _call(src, "--ohne-angaben", "--salt", salt)
    assert first.returncode == 0, first.stderr
    assert re.fullmatch(r"[0-9a-f]{64}\n", salt.read_text(encoding="utf-8"))
    assert f"Neuer Salt in {salt}" in first.stdout
    second = _call(src, "--ohne-angaben", "--salt", salt)
    assert second.returncode == 0 and "Neuer Salt" not in second.stdout


@pytest.mark.parametrize(
    ("place", "content", "message"),
    [
        # one of the tester's own could be found from a number whose original is public
        ("salt.txt", "sommerurlaub2026\n", "stammt nicht von diesem Skript"),
        ("salt.txt", "3F" * 32, "stammt nicht von diesem Skript"),
        ("mails/anonymisiert/salt.txt", "3f" * 32, "darf nicht im Zielordner liegen"),
    ],
)
def test_salt_file_of_ones_own_or_in_the_out_folder_is_refused(tmp_path, place, content, message):
    src = tmp_path / "mails"
    src.mkdir()
    (src / "a.eml").write_bytes(_mail(SHOP, "Paket", "Unterwegs.\n"))
    (tmp_path / place).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / place).write_text(content, encoding="utf-8")
    done = _call(src, "--ohne-angaben", "--salt", tmp_path / place)
    assert done.returncode == 2 and message in done.stderr, done.stderr
    assert done.stdout == ""
    assert sorted(p.name for p in (src / "anonymisiert").glob("*")) == (
        ["salt.txt"] if "anonymisiert" in place else []
    )


# ----- words glued together -----

def _html_mail(sender: str, subject: str, markup: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "pakete@postfach.example"
    msg["Subject"] = subject
    msg["Date"] = DATE
    msg.set_content(f"<html><body>{markup}</body></html>", subtype="html")
    return bytes(msg)


GIVEN = ("--name", "Jonas Meier", "--street", "Lindenweg 3", "--postcode", "80331",
         "--city", "München")


def test_given_name_and_street_glued_to_the_next_word_are_replaced(tmp_path):
    """Some senders write their text part without the line breaks of the HTML part, or put
    inline elements next to each other without a space."""
    glued = _html_mail(
        SHOP,
        "Ihre Bestellung",
        "<div>Herr <b>Meier</b><span>Ihre Bestellung wurde verschickt.</span></div>"
        "<div>Lieferadresse:<b>Jonas Meier</b><span>Lindenweg 3</span><span>80331 München</span>"
        "</div><div>Zustellung in <b>München</b><span>Deutschland</span></div>",
    )
    plain = _mail(
        SHOP,
        "Ihre Bestellung",
        "FrauMeierIhr Paket kommt in den LindenwegHeute.\n"
        "HERRMeier, JONAS MEIERLindenweg 3 in MÜNCHENDeutschland.\n",
    )
    done, [(_, first), (_, second)] = _run(tmp_path, [glued, plain], *GIVEN)
    markup = first.get_body(("html",)).get_content()
    assert "<p>Herr MustermannIhre Bestellung wurde verschickt.</p>" in markup
    # (house number and postcode are one run of digits there: invented as a whole)
    assert re.search(r"<p>Lieferadresse:Max MustermannMusterstraße \d{6} Musterstadt</p>", markup)
    assert "<p>Zustellung in MusterstadtDeutschland</p>" in markup
    assert "FrauMustermannIhr Paket kommt in den MusterstraßeHeute.\n" in _text(second)
    # in capitals: the last capital of a run starts the next word
    assert "HERRMustermann, Max MustermannMusterstraße 1 in MusterstadtDeutschland.\n" in (
        _text(second)
    )
    for msg in (first, second):
        _absent(msg, "jonas", "meier", "lindenweg", "80331", "münchen")
    assert "steht noch eine der eigenen Angaben" not in done.stdout


def test_learnt_name_glued_to_the_next_word_is_replaced(tmp_path):
    known = _mail(SHOP, "Ihre Bestellung", "Hallo Jonas Meier,\n\ndanke.\n")
    glued = _mail(SHOP, "Ihr Paket", "Herr MeierIhre Bestellung ist da.\n")
    _, [(_, first), (_, second)] = _run(tmp_path, [known, glued])
    assert "Herr MustermannIhre Bestellung ist da.\n" in _text(second)
    for msg in (first, second):
        _absent(msg, "jonas", "meier")


def test_a_short_name_is_still_no_part_of_an_ordinary_word(tmp_path):
    line = (
        "Das Paket steht daneben, die angegebene Adresse stimmt, ANGEGEBENE AUCH, "
        "angegebeneAdresse, Benedikt, Waldweg und der Buchenwald bleiben."
    )
    raw = _mail(SHOP, "Ihre Bestellung", f"Hallo Bene Wald,\n{line}\nBeneIhr Paket, HerrWald.\n")
    _, [(_, msg)] = _run(tmp_path, [raw], "--name", "Bene Wald")
    text = _text(msg)
    assert line + "\n" in text
    assert "MaxIhr Paket, HerrMustermann.\n" in text

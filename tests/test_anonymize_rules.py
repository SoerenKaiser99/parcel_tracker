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
        "Von: Kirschbaum\n\nKontrollnummer: 1Z999AA10123456784\n",
    )
    _, [(name, msg)] = _run(tmp_path, [raw])
    text = _text(msg)
    assert name == "001_ups.com.eml"
    assert "auf Antrag von Beispielversender , um Sie zu informieren.\n" in text
    assert "Im Auftrag von Beispielversender möchten wir Sie" in text
    assert "at the request of Beispielversender to notify you.\n" in text
    assert "Auf Antrag von Holzwurm Möbel GmbH , um Sie zu informieren.\n" in text
    assert "Von: Beispielversender\n" in text
    _absent(msg, "kirschbaum", "ballermann", "donnerwetter")

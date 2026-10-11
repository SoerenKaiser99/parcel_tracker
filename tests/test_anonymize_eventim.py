"""The anonymiser and Eventim mails (invented mails): nothing of the buyer, the purchase or
the event stays, and the parser still reads what is written."""

import email
import subprocess
import sys
from datetime import date
from email import policy
from email.message import EmailMessage
from pathlib import Path

import pytest

from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.models import ParcelStatus

SCRIPT = Path(__file__).parent.parent / "scripts" / "anonymize_mail.py"
ARGS = ["54321", "Beispielhausen", "Jörg", "Probst", "privatpost"]
ORDER_SENDER = "EVENTIM <bestellstatus@eventim.de>"
ORDER_A, ORDER_B = "781234567", "7812345678"
IMPRINT = (
    "HINWEISE\nDu hast Fragen zu deiner Bestellung?\nPREISBESTANDTEILE\n"
    "------------------------------------------\nCTS EVENTIM AG & Co. KGaA\n"
    "Vorstand: Ferdinand Vorsitz (Vorsitzender),\nAlma Zweitname, Dr. Egon Drittname\n"
    "Sitz: München | AG München, HRB 990001\n"
)
# Nothing of this may be left in a written mail (compared in lower case).
SECRETS = [
    "jörg", "joerg", "probst", "lindenweg", "beispielhausen", "54321", "privatpost",
    ORDER_A, ORDER_B, "funkelstern", "glitzerhalle", "sternstraße", "konzertbüro wunderlich",
    "nordkurve", "reihe 7", "platz 12", "89,50", "184,90", "5,90", "paypal", "14.03.2026",
    "21.11.2026", "17. august", "vip-upgrade", "rollstuhl", "sv glitzerhausen",
    "glitzerhausen", "vorsitz", "zweitname", "drittname", "990001", "nicht verpassen",
    "sat, 14 mar", "08:02:46", "ganz neuer absatz", "k7m2x9q4pz", "4f8e1a7c",
]


def _mail(sender: str, subject: str, text: str, number: int) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "Jörg Probst <joerg.probst@privatpost.de>"
    msg["Subject"] = subject
    msg["Date"] = "Sat, 14 Mar 2026 08:02:46 +0000"
    msg["Message-ID"] = f"<{number}@eventim.de>"
    msg.set_content(text)
    msg.add_alternative(f"<html><body><p>{text}</p></body></html>", subtype="html")
    return bytes(msg)


def _event(name: str, venue: str) -> str:
    return (
        f"{name}\nDatum: Sa., 21.11.2026, 20:00\nOrt: {venue}, Sternstraße 5, 54321 "
        "Beispielhausen\nVeranstalter: Konzertbüro Wunderlich GmbH, Sternstraße 9, 54321 "
        "Beispielhausen, Deutschland\n\nSitzplatz, Normalpreis: 2 x € 89,50 = € 179,00\n"
        "Block Nordkurve, Reihe 7, Platz 12\nBlock Nordkurve, Reihe 7, Platz 13\n"
        "------------------------------------------\nHinweisVIP-Upgrade inklusive, "
        "Rollstuhlplatz auf Anfrage.\n------------------------------------------\n"
        "Zwischensumme: € 179,00\n==========================================\n"
    )


ORDER = _mail(
    ORDER_SENDER,
    f"Deine EVENTIM-Bestellung: Funkelstern - Die Tour 2026 - Bestellnummer {ORDER_A}",
    "\nBESTELLBESTÄTIGUNG\n\nVielen Dank für deine Bestellung.\n\nHallo Jörg,\n"
    f"vielen Dank für deinen Einkauf vom 14.03.2026 bei EVENTIM. Deine Bestellung mit der "
    f"Ordernummer {ORDER_A} haben wir erhalten.\n"
    "Klicke auf einen der folgenden Punkte, wenn du hierzu Informationen oder Hilfe benötigst:\n"
    "Lieferadresse: https://www.eventim.de/faq/de_de/lieferadresse-aendern/?kunde=4711secret\n"
    "Lieferzeiten: https://www.eventim.de/faq/de_de/lieferzeit/\n\nDEINE BESTELLUNG\n\n"
    f"Bestellnummer: {ORDER_A}\nBestelldatum: 14.03.2026\nGesamtwert: € 184,90\n"
    "Rechnung als PDF herunterladen: https://www.eventim.de/imageservlet?fun=invoice&t=SeCrEt\n"
    "Rechnungsadresse:\nJörg Probst\nLindenweg 7\n54321 Beispielhausen\nDeutschland\n"
    "Die Lieferanschrift für diese Bestellung entspricht deiner angegebenen "
    "Rechnungsanschrift.\n\nLiefermethode: Standardversand (Deutschland)\n\n"
    "Die Zustellung erfolgt spätestens innerhalb von 2 bis 4 Werktagen (Montag bis Samstag, "
    "Feiertage ausgenommen) nach Vertragsabschluss.\n\nZahlungsart: PayPal\n\n"
    "Ein ganz neuer Absatz, den noch niemand kennt.\n\n"
    "EINZELHEITEN DEINER BESTELLUNG\n\n" + _event("Funkelstern - Die Tour 2026", "Glitzerhalle")
    + "\nGESAMT\n\nVersandkosten: € 5,90\n------------------------------------------\n"
    "Gesamtsumme inkl. MwSt.: € 184,90\n==========================================\n\n"
    "IM KALENDER SPEICHERN\n\nFunkelstern - Die Tour 2026 Glitzerhalle, Sa., 21.11.2026\n"
    + IMPRINT,
    1,
)
# An older layout: label and value on two lines; tickets for two events, sent later.
ORDER_OLD = _mail(
    ORDER_SENDER,
    f"Deine EVENTIM-Bestellung: Funkelstern - Die Tour 2026 und 1 mehr - Bestellnummer {ORDER_B}",
    "Vielen Dank für deine Bestellung.\n\nHallo Jörg,\n\nBestellnummer:\n"
    f"{ORDER_B}\n\nBestelldatum:\n14.03.2026\n\nGesamtwert:\n€ 184,90\n\nRechnungsadresse:\n"
    "Dr. Jörg Probst\nLindenweg 7\n54321 Beispielhausen\nDeutschland\n\n"
    "Die Lieferanschrift für diese Bestellung entspricht deiner angegebenen "
    "Rechnungsanschrift.\n\nLiefermethode:\nStandardversand (Deutschland)\n"
    "Der Versand der Tickets erfolgt zwischen dem 17. August und 21. August 2026. Die "
    "Lieferzeit beträgt 2 - 8 Werktage.\n\nZahlungsart:\nPayPal\n\n"
    "EINZELHEITEN DEINER BESTELLUNG\n\n" + _event("Sternenzelt Festival", "Glitzerhalle")
    + _event("Funkelstern - Die Tour 2026", "Glitzerhalle") + IMPRINT,
    2,
)
SHIPPED = _mail(
    ORDER_SENDER,
    f"eventim.de - Versandbenachrichtigung - Deine Bestellung Nr. {ORDER_A}",
    f"\nVERSANDBENACHRICHTIGUNG\n\nHallo Jörg,\nwir haben heute deine Bestellung Nr. {ORDER_A} "
    "versandt.\nVielen Dank für deinen Einkauf bei EVENTIM!\nDein EVENTIM-Kundenservice\n"
    "Lieferadresse:\nJörg Probst\nLindenweg 7\n54321 Beispielhausen\nDeutschland\n\n"
    "Liefermethode: Standardversand (Deutschland)\nVoraussichtliche Ankunft: Die Zustellung "
    "der Tickets erfolgt innerhalb von 2 bis 4 Werktagen. In Ausnahmefällen kann es zu "
    "Verzögerungen kommen.\n\nEINZELHEITEN DEINER BESTELLUNG\n\nFunkelstern - Die Tour 2026\n"
    "Datum: Sa., 21.11.2026, 20:00\nOrt: Glitzerhalle, Sternstraße 5, 54321 Beispielhausen\n"
    "Veranstalter: Konzertbüro Wunderlich GmbH, Sternstraße 9, 54321 Beispielhausen\n\n"
    + IMPRINT,
    3,
)
UNKNOWN = _mail(
    ORDER_SENDER, f"Funkelstern: Deine Bestellung {ORDER_A} wurde storniert",
    "Hallo Jörg,\nFunkelstern in der Glitzerhalle fällt aus.\n", 4,
)
ALARM = _mail(
    "EVENTIM Ticketalarm <ticketalarm@service.eventim.de>",
    "🔔 Funkelstern - Tickets jetzt bei EVENTIM!",
    "Hallo Jörg,\nnicht verpassen: Funkelstern in der Glitzerhalle.\n", 5,
)
CLUB = _mail(
    "SV Glitzerhausen <kundenservice-glitzerhausen@eventim.de>",
    "Deine Buchung 781234567812 vom 14.03.2026 im Online-Ticketshop des SV Glitzerhausen",
    "Hallo Jörg Probst,\nBlock Nordkurve, Reihe 7, Platz 12\n", 6,
)
PRESENTS = _mail(
    "Funkelstern Festival <info@eventimpresents.com>", "Funkelstern: nicht verpassen!",
    "Lindenweg\n", 7,
)
RELAYED = _mail(
    "bestellstatus_at_eventim_de_k7m2x9q4pz_4f8e1a7c@privaterelay.appleid.com",
    f"eventim.de - Versandbenachrichtigung - Deine Bestellung Nr. {ORDER_B}",
    f"Hallo Jörg,\nwir haben heute deine Bestellung Nr. {ORDER_B} versandt.\n"
    "Liefermethode: Standardversand (Deutschland)\n", 8,
)
OTHER = _mail("Holzwurm <info@holzwurm.example>", "Deine Tickets", "Hallo Jörg Probst\n", 9)
MAILS = (ORDER, ORDER_OLD, SHIPPED, UNKNOWN, ALARM, CLUB, PRESENTS, RELAYED, OTHER)


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> dict[str, EmailMessage]:
    tmp_path = tmp_path_factory.mktemp("anon_evt")
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    for index, raw in enumerate(MAILS, 1):
        (src / f"{index}.eml").write_bytes(raw)
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--fixtures", str(src), str(dst), *ARGS],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    return {
        p.name: email.message_from_bytes(p.read_bytes(), policy=policy.default)
        for p in sorted(dst.glob("*.eml"))
    }


def _text(msg: EmailMessage) -> str:
    return msg.get_body(("plain",)).get_content()


def test_eventim_mails_are_taken_and_named_by_their_kind(out):
    assert list(out) == [
        "001_eventim_deine_bestellung.eml",
        "002_eventim_deine_bestellung.eml",
        "003_eventim_versandbenachrichtigung_deine_be.eml",
        "004_eventim_neuigkeiten_von.eml",
        "005_eventim_ticketalarm.eml",
        "006_eventim_kundenservice_musterverein.eml",
        "007_eventim_info.eml",
        "008_eventim_versandbenachrichtigung_deine_be.eml",
    ]  # (the shop that is not Eventim is never taken)


def test_no_personal_value_survives(out):
    for name, msg in out.items():
        dump = (name + msg.as_string() + _text(msg) + str(msg["Subject"])).lower()
        for secret in SECRETS:
            assert secret.lower() not in dump, (name, secret)
        assert msg.get_content_type() == "text/plain"  # the HTML part is not written


def test_only_sender_subject_and_an_invented_day_stay_of_the_headers(out):
    days = []
    for msg in out.values():
        assert sorted(msg.keys()) == sorted(
            ["From", "To", "Subject", "Date", "Message-ID", "Content-Type",
             "Content-Transfer-Encoding", "MIME-Version"]
        )
        assert str(msg["To"]) == "max@example.org"
        assert str(msg["Message-ID"]).endswith("@example.org>")
        days.append(msg["Date"].datetime)
    # One invented day after the other from Monday, 5 January 2026, always at ten.
    assert [(d.date(), d.hour, d.utcoffset().total_seconds()) for d in days] == [
        (date(2026, 1, 5 + n), 10, 3600) for n in range(8)
    ]


def test_order_numbers_are_counted_and_the_same_in_every_mail(out):
    order, old, shipped, *_rest, relayed = out.values()
    assert str(order["Subject"]) == (
        "Deine EVENTIM-Bestellung: Beispielband – Tour 2026 - Bestellnummer 999999901"
    )
    assert str(old["Subject"]) == (
        "Deine EVENTIM-Bestellung: Beispielband – Tour 2026 und 1 mehr - Bestellnummer 9999999902"
    )
    assert str(shipped["Subject"]) == (
        "eventim.de - Versandbenachrichtigung - Deine Bestellung Nr. 999999901"
    )
    assert str(relayed["Subject"]).endswith("Deine Bestellung Nr. 9999999902")
    assert "Bestellnummer: 999999901\n" in _text(order)
    assert "Ordernummer 999999901 haben wir erhalten." in _text(order)
    assert "Bestellnummer:\n9999999902\n" in _text(old)
    assert "deine Bestellung Nr. 999999901 versandt." in _text(shipped)


def test_buyer_address_dates_payment_and_prices_are_invented(out):
    order, old, shipped = list(out.values())[:3]
    text = _text(order)
    assert "Hallo Max,\n" in text
    assert (
        "Rechnungsadresse:\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\nDeutschland\n"
        "Die Lieferanschrift für diese Bestellung"
    ) in text
    assert "Einkauf vom 05.01.2026 bei EVENTIM" in text and "Bestelldatum: 05.01.2026\n" in text
    assert "Gesamtwert: € 1,99\n" in text and "Versandkosten: € 1,99\n" in text
    assert "Gesamtsumme inkl. MwSt.: € 1,99\n" in text and "Zahlungsart: Rechnung\n" in text
    # Links are cut to the host.
    assert "Lieferadresse: https://www.eventim.de/…\n" in text
    assert "Rechnung als PDF herunterladen: https://www.eventim.de/…\n" in text
    assert "secret" not in text.lower()
    # The older layout: values on their own lines, a title in front of the name.
    assert "Rechnungsadresse:\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\n" in _text(old)
    assert "Bestelldatum:\n05.01.2026\n" in _text(old) and "Zahlungsart:\nRechnung\n" in _text(old)
    assert "zwischen dem 1. Juni und 5. Juni 2026. Die Lieferzeit beträgt 2 - 8" in _text(old)
    assert "Lieferadresse:\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\nDeutschland\n" in (
        _text(shipped)
    )


def test_event_venue_organiser_and_tickets_are_invented(out):
    order, old, shipped = list(out.values())[:3]
    block = (
        "Beispielband – Tour 2026\nDatum: Sa., 05.12.2026, 20:00\n"
        "Ort: Musterhalle, Musterstraße 1, 12345 Musterstadt\n"
        "Veranstalter: Beispiel Konzert GmbH, Musterstraße 2, 12345 Musterstadt, Deutschland\n"
    )
    assert "EINZELHEITEN DEINER BESTELLUNG\n" + block + "Stehplatz, Normalpreis: € 1,99\n" in (
        _text(order)
    )
    assert "EINZELHEITEN DEINER BESTELLUNG\n" + block + "HINWEISE\n" in _text(shipped)
    # The same event gets the same invented name, another event another one.
    assert "Musterfestival 2026 – Wochenendticket\nDatum: Sa., 05.12.2026, 20:00\n" in _text(old)
    assert _text(old).count("Beispielband – Tour 2026\nDatum:") == 1
    for msg in (order, old, shipped):
        assert "Platz" not in _text(msg).replace("Stehplatz", "") and "Hinweis" not in _text(msg)


def test_text_ends_with_the_heading_of_the_hints_and_unknown_lines_are_dropped(out):
    for msg in list(out.values())[:3]:
        text = _text(msg)
        assert text.endswith("HINWEISE\n")
        assert "Du hast Fragen" not in text and "Vorstand" not in text and "KGaA" not in text
        assert "KALENDER" not in text
    assert "Absatz" not in _text(next(iter(out.values())))


def test_of_every_other_mail_only_the_sender_stays(out):
    unknown, alarm, club, presents = list(out.values())[3:7]
    for msg in (unknown, alarm, club, presents):
        assert str(msg["Subject"]) == "Neuigkeiten von EVENTIM"
    for msg in (alarm, club, presents):
        assert _text(msg) == "[Inhalt entfernt: keine Bestellung mit Postversand]\n"
    assert str(unknown["From"]) == "EVENTIM <bestellstatus@eventim.de>"
    assert _text(unknown) == "Hallo Max,\n"  # no line of it is one the script knows
    assert str(alarm["From"]) == "EVENTIM <ticketalarm@service.eventim.de>"
    assert str(club["From"]) == "EVENTIM <kundenservice-musterverein@eventim.de>"
    assert str(presents["From"]) == "EVENTIM <info@eventimpresents.com>"


def test_relay_address_keeps_its_shape_with_invented_ids(out):
    relayed = list(out.values())[-1]
    assert str(relayed["From"]) == (
        "EVENTIM <bestellstatus_at_eventim_de_0a1b2c3d4e_0a1b2c3d@privaterelay.appleid.com>"
    )
    assert "Liefermethode: Standardversand (Deutschland)\n" in _text(relayed)


def test_the_parser_reads_the_written_mails(out):
    order, old, shipped, unknown, alarm, club, presents, relayed = out.values()
    (update,) = parse_mail(order).updates
    assert (update.number, update.carrier, update.status, update.title, update.eta_date) == (
        "EVT999999901", "eventim", ParcelStatus.PRE_TRANSIT, "Beispielband – Tour 2026", None,
    )
    (update,) = parse_mail(old).updates
    assert (update.number, update.title) == (
        "EVT9999999902", "Beispielband – Tour 2026 und 1 mehr",
    )
    (update,) = parse_mail(shipped).updates
    assert (update.number, update.status, update.title) == (
        "EVT999999901", ParcelStatus.IN_TRANSIT, "Beispielband – Tour 2026",
    )
    # Sent on the invented Wednesday, 7 January 2026: Friday to Monday.
    assert (update.eta_date, update.eta_latest) == (date(2026, 1, 9), date(2026, 1, 12))
    assert parse_mail(unknown).updates == [] and not parse_mail(unknown).ignored
    for msg in (alarm, club, presents):
        assert parse_mail(msg).ignored
    (update,) = parse_mail(relayed).updates
    assert (update.number, update.status) == ("EVT9999999902", ParcelStatus.IN_TRANSIT)


def test_the_fixtures_of_the_repository_are_written_this_way():
    """The six Eventim fixtures came out of this mode: invented days in a row, counted
    numbers, the invented event and nothing below the heading of the hints."""
    folder = Path(__file__).parent / "fixtures" / "mail"
    mails = [
        email.message_from_bytes(path.read_bytes(), policy=policy.default)
        for path in sorted(folder.glob("*_eventim_*.eml"))
    ]
    assert [m["Date"].datetime.date() for m in mails] == [date(2026, 1, 5 + n) for n in range(6)]
    for msg in mails:
        assert str(msg["To"]) == "max@example.org"
        text = _text(msg)
        assert text.endswith("HINWEISE\n") or text.startswith("[Inhalt entfernt")
        assert "Max" in text or text.startswith("[Inhalt entfernt")


def test_tester_mode_replaces_buyer_and_address(tmp_path):
    (tmp_path / "1.eml").write_bytes(ORDER)
    (tmp_path / "2.eml").write_bytes(SHIPPED)
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "--name", "Jörg Probst",
         "--street", "Lindenweg 7", "--postcode", "54321", "--city", "Beispielhausen",
         "--email", "joerg.probst@privatpost.de"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    assert done.returncode == 0, done.stderr
    order, shipped = (
        email.message_from_bytes(path.read_bytes(), policy=policy.default)
        for path in sorted((tmp_path / "anonymisiert").glob("*.eml"))
    )
    for msg in (order, shipped):
        dump = (msg.as_string() + msg.get_body(("plain", "html")).get_content()).lower()
        for secret in ("probst", "jörg", "joerg", "lindenweg", "privatpost", ORDER_A,
                       "secret", "4711"):
            assert secret not in dump, secret
    # Still Eventim's two mails for the parser, with the delivery method and the estimate.
    (update,) = parse_mail(order).updates
    assert (update.carrier, update.status) == ("eventim", ParcelStatus.PRE_TRANSIT)
    (update,) = parse_mail(shipped).updates
    assert (update.carrier, update.status) == ("eventim", ParcelStatus.IN_TRANSIT)
    assert update.eta_date is not None and update.eta_latest is not None

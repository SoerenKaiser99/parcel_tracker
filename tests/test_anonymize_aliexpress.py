"""The anonymiser and AliExpress mails, also behind Apple's mail relay (invented mails)."""

import email
import html
import subprocess
import sys
from email import policy
from email.message import EmailMessage
from pathlib import Path

import pytest

from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.models import ParcelStatus

SCRIPT = Path(__file__).parent.parent / "scripts" / "anonymize_mail.py"
ARGS = ["54321", "Beispielhausen", "Jörg", "Probst", "privatpost"]
DIRECT = "AliExpress <transaction@notice.aliexpress.com>"
RELAY = "transaction_at_notice_aliexpress_com_k7m2x9q4pz_4f8e1a7c@privaterelay.appleid.com"
OFFERS = "ae-angebote_at_deals_aliexpress_com_k7m2x9q4pz_4f8e1a7c@privaterelay.appleid.com"
ORDER_A, ORDER_B, ORDER_C = "3051234567891234", "3051234567895678", "8201234567894321"
DHL = "00340434161094012345"
FOOTER = (
    "Das könnte Ihnen auch gefallen\n12,34€\n56,78€\nWeitere Artikel anzeigen\n"
    "Diese E-Mail wurde gesendet an joerg.probst@privatpost.de\nAliExpress Servicecenter\n"
)
# Nothing of this may be left in a written mail (compared in lower case).
SECRETS = [
    "jörg", "joerg", "probst", "ae4711234", "lindenweg", "beispielhausen", "hinterhof",
    "beispielland", "0151", "12345678", "privatpost", "k7m2x9q4pz", "4f8e1a7c", ORDER_A,
    ORDER_B, ORDER_C, DHL, DHL[5:], "funkelstern", "zahnbürste", "nachtlicht", "türkis",
    "paypal", "7,49", "12,34", "56,78", "mär 14", "trk-secret",
]


def _mail(sender: str, subject: str, text: str, plain: bool = False, links: str = "") -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "Jörg Probst <joerg.probst@privatpost.de>"
    msg["Subject"] = subject
    msg["Date"] = "Sat, 14 Mar 2026 08:02:46 +0000"
    msg["Message-ID"] = f"<{abs(hash(subject))}@notice.aliexpress.com>"
    if plain:
        msg.set_content(text)
    else:
        rows = "".join(f"<tr><td>{html.escape(line)}</td></tr>" for line in text.splitlines())
        msg.set_content(
            f"<html><head><style>p{{}}</style></head><body><table>{rows}</table>{links}"
            "</body></html>",
            subtype="html",
        )
    return bytes(msg)


SHIPPED = _mail(
    f"AliExpress <{RELAY}>",
    f"Bestellung {ORDER_A}: Bestellung versandt",
    "Verfolgen Sie Ihre Bestellung\nHallo ae4711234 Probst,\n"
    f"Ihre Bestellung {ORDER_A} wurde versandt.\nBestelldetails\n"
    "Aufgegeben am Mär 14,2026, 07:55\nFunkelstern Official Store\n"
    "Elektrische Zahnbürste mi...\nTürkis, 2 Stk\n€ 7,49x2\n"
    f"Bestell-Nr.\n{ORDER_A}\nBestellsumme\n14,98€\nBestellung prüfen\n"
    "Versand nach\nLindenweg, 7, Beispielhausen, Other\nZahlungsmethode\nWALLET_PAYPAL\n"
    + FOOTER,
)
PARCEL = _mail(
    DIRECT,
    f"Packstück {DHL} hat die Abflugregion verlassen",
    "Infos zu Ihrem Paket in der Nachricht\nHallo Jörg Probst,\n"
    f"Ihr Packstück {DHL} hat den Abflugort verlassen.\nLieferung verfolgen\nPaketinfos\n"
    "Elektrische Zahnbürste mit Reiseetui...\nTürkis, 2 Stk\nx2\n"
    "Nachtlicht mit Bewegungsmelder für d...\nx1\n"
    "Versand nach\nBeispielhausen, Lindenweg, 7\nHinterhof, Beispielland\n"
    "Jörg Probst (+49) 015112345678\n"
    "Die pünktliche Ankunft Ihres Pakets hat für uns höchste Priorität.\n" + FOOTER,
    links=(
        '<a href="https://www.aliexpress.com/p/tracking/index.html?_login=yes&amp;tradeOrderId='
        f'{ORDER_A}&amp;trk=trk-secret">Lieferung verfolgen</a>'
        f'<a href="https://www.aliexpress.com/ssr/1?o_ids={ORDER_C}&amp;x=1">Artikel</a>'
    ),
)
ORDERS = _mail(
    DIRECT,
    f"2 Bestellungen wurden bestätigt: {ORDER_A} & weitere",
    "Wir bereiten alles für Sie vor\nHallo Jörg Peter Probst,\n"
    f"Insgesamt 2 Bestellungen wurden bestätigt （No. {ORDER_A}\nund weitere）.\n"
    "Bestelldetails anzeigen <https://click.aliexpress.com/e/trk-secret>\n"
    f"Bestellung 1{ORDER_A}\nElektrische Zahnbürste mit Re...\nTürkis, 2 S...\nx2\n"
    f"Gesamtbetrag 14,98€\nBestellung 2{ORDER_B}\nNachtlicht mit Bewegungsmelde...\nx1\n"
    "Gesamtbetrag 7,49€\nAlle anzeigen\n"
    "Die in dieser E-Mail angezeigten Preise können sich jederzeit ändern.\n" + FOOTER,
    plain=True,
)
MARKETING = _mail(
    f"AliExpress <{OFFERS}>",
    "Ihre Bestellung hat einen lokalen Boost erhalten!",
    "ae4711234.Probst, Sonderangebot im Inneren\n-51%\n12,34€\nAngebote shoppen\n"
    "Beliebte Kategorien\nElektronik\n" + FOOTER,
)
OTHER = _mail("Holzwurm <info@holzwurm.example>", "Ihre Bestellung", "Hallo Jörg Probst\n")


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> dict[str, EmailMessage]:
    tmp_path = tmp_path_factory.mktemp("anon_ali")
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    for name, raw in (("1.eml", ORDERS), ("2.eml", SHIPPED), ("3.eml", PARCEL),
                      ("4.eml", MARKETING), ("5.eml", OTHER)):
        (src / name).write_bytes(raw)
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
    return msg.get_body(("plain", "html")).get_content()


def test_aliexpress_mails_are_taken_also_through_the_relay_and_named_by_their_step(out):
    assert list(out) == [
        "001_aliexpress_2_bestellungen_wurden_best_ti.eml",
        "002_aliexpress_bestellung_bestellung_versand.eml",
        "003_aliexpress_packst_ck_hat_die_abflugregio.eml",
        "004_aliexpress_ihre_bestellung_hat_einen_lok.eml",
    ]


def test_no_personal_value_survives(out):
    for name, msg in out.items():
        dump = (name + msg.as_string() + html.unescape(_text(msg))).lower()
        for secret in SECRETS:
            assert secret.lower() not in dump, (name, secret)


def test_relay_address_keeps_its_shape_with_invented_ids(out):
    senders = [str(msg["From"]) for msg in out.values()]
    assert senders[0] == senders[2] == DIRECT
    assert senders[1] == (
        "AliExpress <transaction_at_notice_aliexpress_com_0a1b2c3d4e_0a1b2c3d"
        "@privaterelay.appleid.com>"
    )
    assert senders[3] == (
        "AliExpress <ae-angebote_at_deals_aliexpress_com_0a1b2c3d4e_0a1b2c3d"
        "@privaterelay.appleid.com>"
    )
    assert {str(msg["To"]) for msg in out.values()} == {"max@example.org"}


def test_numbers_are_counted_and_the_same_in_every_mail(out):
    orders, shipped, parcel, _ = out.values()
    assert str(orders["Subject"]) == "2 Bestellungen wurden bestätigt: 9999999999990001 & weitere"
    text = _text(orders)
    # (the running number in front of the order number stays)
    assert "Bestellung 19999999999990001\n" in text and "Bestellung 29999999999990002\n" in text
    assert str(shipped["Subject"]) == "Bestellung 9999999999990001: Bestellung versandt"
    assert "<p>9999999999990001</p>" in _text(shipped)
    # DHL's prefix stays, so the carrier is still told.
    assert str(parcel["Subject"]) == "Packstück 00340999999999990003 hat die Abflugregion verlassen"
    assert "Ihr Packstück 00340999999999990003 hat" in _text(parcel)


def test_text_ends_before_offers_and_footer_and_the_buyer_is_replaced(out):
    orders, shipped, parcel, marketing = out.values()
    for msg in out.values():
        text = _text(msg)
        assert "könnte Ihnen auch gefallen" not in text and "gesendet an" not in text
        assert "Zahlungsmethode" not in text and "http://" not in text
    assert "Hallo Max Mustermann," in _text(orders)
    assert "<p>Hallo Max Mustermann,</p>" in _text(shipped)
    assert "<p>Versand nach</p>\n<p>Musterstraße 1, Musterstadt</p>\n</body>" in _text(shipped)
    assert (
        "<p>Versand nach</p>\n<p>Musterstraße 1, Musterstadt</p>\n"
        "<p>Max Mustermann (+49) 0000000000</p>\n<p>Die pünktliche Ankunft"
    ) in _text(parcel)
    assert _text(marketing).startswith(
        "<html><body>\n<p>Max Mustermann, Sonderangebot im Inneren</p>\n<p>-51%</p>\n<p>1,99€</p>"
    )


def test_shop_items_variants_and_prices_are_invented(out):
    orders, shipped, parcel, _ = out.values()
    assert (
        "<p>Aufgegeben am Jan 01,2026, 12:00</p>\n<p>Beispiel Store</p>\n"
        "<p>Beispiel-Kabel USB-C auf...</p>\n<p>Variante A</p>\n<p>€ 1,99x1</p>\n"
        "<p>Bestell-Nr.</p>"
    ) in _text(shipped)
    assert "<p>Bestellsumme</p>\n<p>1,99€</p>" in _text(shipped)
    # The same item gets the same invented name, cut where the real one was cut; an item
    # without a variant keeps its shape.
    assert (
        "Bestellung 19999999999990001\nBeispiel-Kabel USB-C auf USB-...\nVariante A\nx1\n"
        "Gesamtbetrag 1,99€\nBestellung 29999999999990002\nBeispiel-Sensor für Temperatu...\n"
        "x1\nGesamtbetrag 1,99€\n"
    ) in _text(orders)
    assert (
        "<p>Paketinfos</p>\n<p>Beispiel-Kabel USB-C auf USB-A geflo...</p>\n<p>Variante A</p>\n"
        "<p>x1</p>\n<p>Beispiel-Sensor für Temperatur und L...</p>\n<p>x1</p>\n"
    ) in _text(parcel)


def test_parcel_mail_keeps_one_invented_link_per_order(out):
    text = _text(list(out.values())[2])
    link = "https://www.aliexpress.com/p/tracking/index.html?tradeOrderId="
    assert text.count("<a href=") == 2
    assert f'<p><a href="{link}9999999999990001">Lieferung verfolgen</a></p>' in text
    assert f'<p><a href="{link}9999999999990004">Lieferung verfolgen</a></p>' in text


def test_the_parser_reads_the_written_mails(out):
    orders, shipped, parcel, marketing = (parse_mail(msg) for msg in out.values())
    assert [(u.number, u.title) for u in orders.updates] == [
        ("ALI9999999999990001", "Beispiel-Kabel USB-C auf USB-…"),
        ("ALI9999999999990002", "Beispiel-Sensor für Temperatu…"),
    ]
    [u] = shipped.updates
    assert (u.number, u.status, u.title) == (
        "ALI9999999999990001",
        ParcelStatus.IN_TRANSIT,
        "Beispiel-Kabel USB-C auf…",
    )
    assert [(u.number, u.tracking_ref, u.tracking_carrier) for u in parcel.updates] == [
        ("ALI9999999999990001", "00340999999999990003", "dhl"),
        ("ALI9999999999990004", "00340999999999990003", "dhl"),
    ]
    assert marketing.ignored


def test_tester_mode_invents_the_relay_ids_and_replaces_the_address_block(tmp_path):
    (tmp_path / "1.eml").write_bytes(PARCEL)
    (tmp_path / "2.eml").write_bytes(SHIPPED)
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "--name", "Jörg Probst",
         "--email", "joerg.probst@privatpost.de"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    assert done.returncode == 0, done.stderr
    parcel, shipped = (
        email.message_from_bytes(path.read_bytes(), policy=policy.default)
        for path in sorted((tmp_path / "anonymisiert").glob("*.eml"))
    )
    assert str(shipped["From"]) == (
        "AliExpress <transaction_at_notice_aliexpress_com_0a1b2c3d4e_0a1b2c3d"
        "@privaterelay.appleid.com>"
    )
    for msg in (parcel, shipped):
        dump = (msg.as_string() + html.unescape(_text(msg))).lower()
        for secret in ("probst", "jörg", "lindenweg", "beispielhausen", "hinterhof", "0151",
                       "k7m2x9q4pz", "4f8e1a7c", "privatpost", ORDER_A, DHL):
            assert secret not in dump, secret
    assert "Versand nach</p>\n<p>Musterstraße 1, Musterstadt</p>\n<p>Max Mustermann +49" in _text(
        parcel
    )
    assert "Versand nach</p>\n<p>Musterstraße 1, Musterstadt</p>" in _text(shipped)
    # The relayed mail is still one of AliExpress for the parser.
    [u] = parse_mail(shipped).updates
    assert (u.carrier, u.status) == ("aliexpress", ParcelStatus.IN_TRANSIT)

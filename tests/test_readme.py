import re
import struct
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
DEMO = ROOT / "docs" / "demo"
IMAGES = ("karte-hell.png", "karte-dunkel.png", "karte-detail.png")
RAW = "https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main"

SENDERS = [
    "bestellbestaetigung@amazon.de",
    "versandbestaetigung@amazon.de",
    "shipment-tracking@amazon.de",
    "order-update@amazon.de",
    "noreply@dhl.de",
    "noreply@service.dpd.de",
    "pkginfo@ups.com",
    "noreply@paketankuendigung.myhermes.de",
    "ebay@ebay.com",
    "no-reply@gls-pakete.de",
]


def test_readme_documents_mail_import():
    assert "## E-Mail-Import" in README
    assert "Nur ein eigenes Paket-Postfach eintragen, nie das Hauptpostfach" in README
    assert "### Von Hand weiterleiten" in README
    assert 'redirect :copy "pakete@example.org";' in README
    for address in SENDERS:
        assert f"`{address}`" in README
    assert "Paket-Tracker-Verarbeitet" in README
    assert "Paket-Tracker-Nicht-erkannt" in README


def test_readme_says_delivery_code_is_readable_via_attributes():
    assert "Verdeckt ist er nur auf der Karte" in README
    assert "im Klartext lesen" in README


def test_readme_explains_the_ups_api_and_its_budget():
    assert "## UPS-Live-Status (optional)" in README
    for text in ("developer.ups.com", "**Tracking**", "Track Alert", "Pending",
                 "Monatsbudget", "Standard 100", "alle 4 Stunden"):
        assert text in README, text
    assert '"noreply@paketankuendigung.myhermes.de", "ebay@ebay.com"' in README


def test_readme_roadmap_and_status():
    assert "## Roadmap & Status" in README
    for line in (
        "UPS Live-Status (offizielle API): umgesetzt, noch nicht mit echten Zugangsdaten "
        "getestet (UPS-Freischaltung ausstehend)",
        "Hermes Live-Abfrage: umgesetzt; mit einer aktuellen Sendung noch nicht live getestet",
        "eBay-Mails: umgesetzt",
        "17track: Anmeldung live getestet, Anreicherung noch ohne Live-Fall",
        "GLS-Live-Abfrage: umgesetzt, Live-Test ausstehend",
        "GLS-Mails: umgesetzt",
        "Amazon per Konto-Anmeldung: verworfen zugunsten des Mail-Imports",
    ):
        assert line in README, line
    assert "Roadmap & Status" in README.split("## English summary")[1]


def test_readme_explains_17track():
    assert "## 17track (optional)" in README
    for text in (
        "api.17track.net",
        "200 Nummern",
        "Details über 17track holen",
        "Andere (über 17track)",
        "parcel_tracker.track_17track",
        "sensor.paket_tracker_17track_kontingent",
        "alle 6 Stunden",
        "Ort via 17track",
        "location_source",
        "höchstens 40 Nummern",
    ):
        assert text in README, text
    assert "17track registration has been tested live" in README


def test_readme_explains_gls():
    assert "\n## GLS\n" in README and "### GLS-Pakete" in README
    for text in (
        "gls-group.com",
        "11 Ziffern",
        "eBay-Artikelnummern",
        "Carrier-Wahl „GLS“",
        "bis zu 20 Ereignisse",
        "höchstens alle 30 Minuten",
        "Kein offizieller Zugang",
        "GLS-Mails, und „Details über 17track holen“",
        "Dein GLS Paket kommt heute!",
        "Rechtsform",
        "Abstellort, Zustelladresse, Empfängername, Telefonnummer und Referenzen",
        "GLS als blauer Punkt mit „G“",
    ):
        assert text in README, text
    assert '"no-reply@gls-pakete.de"\n] {' in README
    assert "the GLS live lookup is implemented (live test pending)" in README


def test_readme_privacy_names_dhl_and_gls_for_the_postcode():
    assert "Die PLZ geht nur an DHL und GLS" in README
    assert "Die PLZ geht ausschließlich an DHL" not in README
    assert "the postcode is sent only to DHL and GLS" in README
    assert "(DHL, DPD, GLS, Hermes bzw." in README


def test_readme_says_it_is_built_for_germany():
    intro = README.split("## Installation")[0]
    assert "für Deutschland gebaut" in intro
    for text in (
        "DHL (offizielle API, weltweit)",
        "UPS (offizielle API)",
        "jeder Carrier über 17track",
        "nur deutsche Mails",
        "amazon.de",
    ):
        assert text in intro, text
    assert "built for Germany" in README


def test_readme_roadmap_lists_international():
    roadmap = README.split("## Roadmap & Status")[1].split("## English summary")[0]
    for text in (
        "**International**",
        "Karte auch auf Englisch",
        "weitere Amazon-Länder im Mail-Import",
        "Royal Mail, PostNL, USPS",
        "anonymisierten Beispielmails von Testern",
    ):
        assert text in roadmap, text
    assert "International roadmap item" in README


def _section(title: str) -> str:
    return README.split(f"\n## {title}\n")[1].split("\n## ")[0]


def test_readme_explains_how_to_report_a_bug():
    section = _section("Fehler melden")
    for text in (
        "**Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen**",
        "issues/new?template=fehler.yml",
        "**Die Diagnose enthält:**",
        "**Die Diagnose enthält nie:**",
        "API-Keys, Passwörter, das UPS-Secret, den 17track-Key, den IMAP-Benutzer",
        "die PLZ",
        "Zustell-Codes",
        "Mail-Inhalte",
        "Ziffern werden zu `9`, Buchstaben zu `A`",
        "`JJD999999999999999999`",
        "Absender-Domain",
        # what Home Assistant adds by itself, and the host of an own mail server
        "Home Assistant ergänzt die Datei selbst um Systeminformationen",
        "Liste der installierten benutzerdefinierten Integrationen",
        "steht nur als `custom` drin",
    ):
        assert text in section, text


def test_readme_explains_how_to_send_sample_mails():
    section = _section("Beispielmails einreichen")
    for text in (
        "**Nie rohe Mails hochladen.**",
        "**Nie Mails privat an den Autor schicken.**",
        "als `.eml` speichern",
        "nicht weiterleiten",
        "https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/scripts/"
        "anonymize_mail.py",
        "python3 anonymize_mail.py <Ordner> --zip",
        "leer lassen",
        "Das Skript fragt nach Name, Straße und Hausnummer, Postleitzahl, Ort",
        "`--ohne-angaben`",
        "Namen und Orte können dann stehen bleiben",
        "Frühere Ergebnisse",
        "ohne Netzwerkzugriff",
        "`anonymisiert/`",
        "Jede Datei",
        "`paket-tracker-beispiele.zip`",
        "issues/new?template=mail-nicht-erkannt.yml",
        "„Mail wird nicht erkannt“",
    ):
        assert text in section, text
    steps = [line for line in section.splitlines() if line[:2] in ("1.", "2.", "3.", "4.", "5.")]
    assert len(steps) == 5
    assert section.index(".eml") < section.index("raw.githubusercontent") < section.index(
        "anonymisiert/"
    ) < section.index("issues/new")


def test_readme_report_sections_come_right_before_the_roadmap():
    titles = [line[3:] for line in README.splitlines() if line.startswith("## ")]
    at = titles.index("Roadmap & Status")
    assert titles[at - 2:at] == ["Fehler melden", "Beispielmails einreichen"]
    assert "[Beispielmails einreichen](#beispielmails-einreichen)" in _section("Fehler melden")


def test_readme_german_texts_avoid_banned_words():
    german = README.split("## English summary")[0].lower()
    assert "bitte" not in german and "erfolgreich" not in german


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", data[16:24])


def test_readme_shows_the_card_screenshots_at_the_top():
    intro = README.split("## Was es kann")[0]
    for name in IMAGES:
        path = ROOT / "docs" / "images" / name
        assert path.is_file(), name
        assert path.stat().st_size < 400_000, name
        width, height = _png_size(path)
        assert width >= 900 and height > width, name
        # absolute: HACS shows the README without the repository around it
        assert f'src="{RAW}/docs/images/{name}"' in intro, name
    assert 'src="docs/' not in README
    alts = re.findall(r'<img [^>]*alt="([^"]+)"', intro)
    assert len(alts) == len(IMAGES)
    assert all("Karte" in alt for alt in alts)
    assert "hellen Design" in intro and "dunklen Design" in intro and "aufgeklappten" in intro
    assert "Die Bilder zeigen erfundene Pakete" in intro
    assert "docs/demo/index.html" in intro


def test_demo_page_loads_the_real_card():
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    card = "../../custom_components/parcel_tracker/frontend/parcel-tracker-card.js"
    assert f'<script src="{card}"></script>' in html
    assert (DEMO / card).resolve().is_file()
    assert '<script src="demo.js"></script>' in html
    assert "erfunden" in html
    assert not re.search(r"https?://", html), "the demo page loads nothing from the network"


def test_demo_page_shows_one_parcel_per_carrier_and_the_fixed_sensors():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    for carrier in ("dhl", "dpd", "gls", "hermes", "ups", "amazon", "ebay", "other"):
        assert re.search(rf'parcel\("[a-z_]+", "{carrier}", ', js), carrier
    for text in (
        '"sensor.pakete_heute"',
        '"sensor.paket_tracker_17track_kontingent", "187"',
        'location_source: "17track"',
        'shipping_carrier_hint: "hermes"',
        "delivery_code:",
        "delivered_at:",
        'last_error: "unavailable"',
        "nicht ausgeführt",
    ):
        assert text in js, text
    assert not re.search(r"https?://", js)
    # Dates are computed from today: no fixed calendar date in the file.
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", js)


def test_demo_page_contains_only_synthetic_numbers():
    """Every long digit run is a 9-style placeholder (e.g. 00340999999999999901)."""
    files = sorted(p for p in DEMO.rglob("*") if p.is_file())
    assert {p.name for p in files} >= {"index.html", "demo.js"}
    runs = []
    for path in files:
        runs += re.findall(r"\d{8,}", path.read_text(encoding="utf-8"))
    assert len(runs) >= 10
    for run in runs:
        assert "9999999" in run and set(run[:-2]) <= set("0349"), run


def test_brand_icons_are_shipped_where_home_assistant_looks_for_them():
    """HA 2026.3+ serves custom_components/<domain>/brand/icon.png and icon@2x.png."""
    brand = ROOT / "custom_components" / "parcel_tracker" / "brand"
    assert _png_size(brand / "icon.png") == (256, 256)
    assert _png_size(brand / "icon@2x.png") == (512, 512)


def test_readme_says_why_right_after_intro_and_screenshots():
    titles = [line[3:] for line in README.splitlines() if line.startswith("## ")]
    assert titles[:2] == ["Warum?", "Was es kann"]
    assert README.index("karte-dunkel.png") < README.index("\n## Warum?\n")
    section = _section("Warum?")
    lines = [line for line in section.splitlines() if line.strip()]
    assert 5 <= len(lines) <= 8
    for text in (
        "„Kommt heute ein Paket, und wann?“",
        "an einer Stelle",
        "statt in fünf Apps",
        "Versandmails",
        "Amazons eigene Lieferungen",
        "keine öffentliche Sendungsverfolgung",
        "Automationen",
        "Kalender",
        "„Pakete heute“",
        "kein Cloud-Konto",
        "kein fremder Tracking-Dienst",
        "Zugangsdaten bleiben in Home Assistant",
        "nur ein eigenes Paket-Postfach",
        "Open Source",
        "deutsche Carrier",
    ):
        assert text in section, text
    assert "Ich " in section  # the owner's own words
    english = README.split("## English summary")[1]
    assert "Why:" in english and "no cloud account" in english
    assert "third-party tracking service" in english


def test_readme_brand_note_names_the_dhl_badge():
    section = _section("Markenhinweis")
    assert "DHL als gelbes Schild mit rotem Schriftzug" in section

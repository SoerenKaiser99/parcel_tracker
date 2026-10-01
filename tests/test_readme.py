from pathlib import Path

README = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")

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


def test_readme_german_texts_avoid_banned_words():
    german = README.split("## English summary")[0].lower()
    assert "bitte" not in german and "erfolgreich" not in german

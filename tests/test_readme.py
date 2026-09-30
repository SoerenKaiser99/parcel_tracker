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
        "17track für DPD-Orte: geplant",
        "Amazon per Konto-Anmeldung: verworfen zugunsten des Mail-Imports",
    ):
        assert line in README, line
    assert "Roadmap & Status" in README.split("## English summary")[1]

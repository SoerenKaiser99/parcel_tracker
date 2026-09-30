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

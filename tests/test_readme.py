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
    "paketankuendigung@dhl.de",
    "zustellung@dhl.de",
    "noreply@service.dpd.de",
    "no_reply@dpd.at",
    "noreply@gls-group.eu",
    "noreply@gls-rtt.com",
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
        'last_error: "missing_key"',
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


BLUEPRINT_RAW = RAW + "/blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml"


def test_readme_explains_notifications():
    section = _section("Benachrichtigungen")
    for text in (
        "Paket Tracker → Konfigurieren**",
        "„Benachrichtigungen“",
        "`notify.",
        "in Zustellung",
        "zugestellt",
        "abholbereit",
        "Problem",
        # the example texts
        "📦 Kopfhörer (DHL) ist in Zustellung – heute 14:00–16:00 Uhr",
        "✅ Kopfhörer (DHL) wurde zugestellt",
        "📍 Kopfhörer (DHL) liegt zur Abholung bereit – Bonn bis 06.10.",
        "⚠️ Kopfhörer (DHL): Problem bei der Zustellung",
        "Paket …2557",
        # what is never part of it
        "Zustell-Code",
        "vollständige Sendungsnummer",
        "Adresse",
        "Ablageort",
        "Ereignistexte",
        # when
        "sobald Home Assistant fertig gestartet ist",
        "`parcel_tracker_status_changed`",
        # limits of notify.send_message and the blueprint
        "`notify.send_message`",
        "### Blueprint",
        "`data.url`",
        "`data.clickAction`",
        "`data.tag`",
        "blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml",
    ):
        assert text in section, text
    assert "notify_url" not in README


def test_readme_explains_both_kinds_of_targets():
    """Notify entities and classic services (Pushover has only the latter)."""
    section = _section("Benachrichtigungen")
    for text in (
        "Benachrichtigungs-Entitäten",
        "Klassische Dienste",
        "„Dienst notify.pushover“",
        # Pushover has to exist in Home Assistant first
        "Pushover zuerst in Home Assistant als Integration einrichten",
        # a target that is gone
        "„nicht mehr vorhanden“",
        # the classic service of the app replaces the earlier notification
        "„Dienst notify.mobile_app_<gerät>“",
        "ersetzt eine neue Meldung die frühere zum selben Paket",
        "nur eines von beiden",
    ):
        assert text in section, text
    english = README.split("## English summary")[1]
    assert "classic notify services such as Pushover" in english
    assert "getrennt nach Entitäten und klassischen Diensten" in _section("Datenschutz")


def test_readme_no_longer_says_nothing_happens_at_startup():
    assert "nicht beim Start" not in README


def test_readme_event_section_lists_the_carrier_name():
    section = _section("Beispiel-Automation")
    for field in ("number", "name", "carrier", "carrier_name", "old_status", "new_status",
                  "eta_date", "eta_from", "eta_to", "location"):
        assert f"`{field}`" in section, field
    assert "trigger.event.data.carrier_name" in section


def test_readme_blueprint_import_link():
    from urllib.parse import quote

    link = (
        "https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url="
        + quote(BLUEPRINT_RAW, safe="")
    )
    assert link in _section("Benachrichtigungen")
    assert "%3A%2F%2Fraw.githubusercontent.com%2FSoerenKaiser99%2Fparcel_tracker%2Fmain%2F" in link
    assert (ROOT / "blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml").is_file()


def test_readme_lists_notifications_as_done():
    assert "- **Benachrichtigungen**" in _section("Was es kann")
    assert "[Benachrichtigungen](#benachrichtigungen)" in _section("Was es kann")
    why = _section("Warum?")
    assert "Benachrichtigung" in why and "ohne eigene Automation" in why
    roadmap = _section("Roadmap & Status")
    assert "Benachrichtigungen (Optionen und Blueprint): umgesetzt" in roadmap
    english = README.split("## English summary")[1]
    assert "push notifications" in english and "blueprint" in english


def test_no_planning_docs_in_the_repo():
    assert not (ROOT / "docs" / "superpowers").exists()


def test_hacs_is_not_told_about_the_blueprints_folder():
    """HACS installs custom_components/parcel_tracker only; the blueprint is imported
    through its link, so hacs.json stays as it is."""
    import json

    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert set(hacs) == {"name", "homeassistant", "render_readme", "zip_release", "filename"}


def test_hacs_installs_from_the_release_zip():
    """zip_release makes HACS fetch the release asset, which GitHub counts as a
    download. Every release from v0.3.6 on needs parcel_tracker.zip attached
    (scripts/build_release_zip.sh)."""
    import json

    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "parcel_tracker.zip"
    assert hacs["name"] == "Paket Tracker"
    assert hacs["homeassistant"] == "2025.10.0"
    assert hacs["render_readme"] is True


def test_readme_card_not_found_section():
    section = README.split("\n### Karte wird nicht gefunden?\n")[1].split("\n## ")[0]
    for text in (
        "Custom element doesn't exist: parcel-tracker-card",
        "Behoben in v0.3.6",
        "nur noch als Dashboard-Ressource",
        "Integration auf v0.3.6 oder neuer aktualisieren, Home Assistant neu starten",
        "Bis v0.3.5: normal neu laden (F5",
        "Kein hartes Neuladen",
        "Einstellungen → Dashboards → ⋮ → Ressourcen",
        "`resource_mode: yaml`",
        "**Einstellungen → Reparaturen**",
        "`type: module`",
    ):
        assert text in section, text
    steps = [line for line in section.splitlines() if line[:2] in ("1.", "2.", "3.", "4.")]
    assert len(steps) == 4
    # ≤ v0.3.5 a hard reload triggers the bug, so it is never the advice
    assert "Seite neu laden (am Rechner Strg+F5" not in README
    assert "Frontend-Cache leeren" not in README


def test_readme_says_when_local_is_used():
    section = _section("Karte hinzufügen")
    assert "wenn der Ordner `www` beim Start schon existierte" in section
    assert "`/parcel_tracker/parcel-tracker-card.js`" in section
    assert "Seite einmal neu laden" in section


def test_readme_explains_sure_and_possible_parcels_of_today():
    """v0.3.7: "Pakete heute" counts only sure parcels, ranges are "möglich"."""
    what = _section("Was es kann")
    sensors = next(line for line in what.splitlines() if line.startswith("- **Sensoren**"))
    for text in (
        "`sensor.pakete_heute` zählt die Pakete, die heute sicher kommen",
        "„In Zustellung“",
        "fester Liefertag heute",
        "„2.–5. Okt.“",
        "`possible`",
        "`possible_count`",
        "`parcels`",
        "Automationen",
        "wechselt es von selbst",
    ):
        assert text in sensors, text
    card = _section("Karte hinzufügen")
    for text in ("„1 möglich“", "„Bis 5. Okt.“", "Lieferspanne"):
        assert text in card, text
    assert "bitte" not in (sensors + card).lower()


def test_readme_explains_the_three_badges_and_delivered_today():
    """v0.3.10: three badges in the card's head; the sensor lists what was delivered today."""
    card = _section("Karte hinzufügen")
    for text in (
        "bis zu drei Schilder",
        "„1 heute“",
        "„1 möglich“",
        "„1 zugestellt“",
        "steht immer da",
        "nur, wenn",
        "„0 heute“",
        "`sensor.pakete_heute`",
    ):
        assert text in card, text
    assert card.index("„1 heute“") < card.index("„1 möglich“") < card.index("„1 zugestellt“")
    assert "„1 heute · 1 möglich“" not in README  # the combined text is gone
    what = _section("Was es kann")
    sensors = next(line for line in what.splitlines() if line.startswith("- **Sensoren**"))
    for text in (
        "`delivered_today`",
        "`delivered_today_count`",
        "`delivered_at`",
        "Zeitzone von Home Assistant",
        "Tag des Statuswechsels",
        "{{ state_attr('sensor.pakete_heute', 'delivered_today_count') }}",
    ):
        assert text in sensors, text
    assert "bitte" not in (sensors + card).lower()
    english = _section("English summary")
    assert "`delivered_today`" in english and "`delivered_today_count`" in english


def test_readme_says_the_card_is_german_in_any_home_assistant_language():
    card = _section("Karte hinzufügen")
    assert "Die Karte ist deutsch" in card
    assert "unabhängig von der Sprache" in card


def test_readme_screenshots_show_all_three_badges_worth_of_parcels():
    intro = README.split("## Was es kann")[0]
    assert "zwölf Pakete" in intro and "elf Pakete" not in intro
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    assert len(re.findall(r'^    parcel\("', js, re.M)) == 12
    assert "delivered_today:" in js and "delivered_today_count:" in js


def test_readme_explains_the_plus_button_the_add_form_option_and_the_reload_hint():
    """v0.3.9: the add form sits behind a plus button; `add_form` picks the look."""
    card = _section("Karte hinzufügen")
    for text in (
        "Plus-Knopf",
        "„Sendung hinzufügen“",
        "klappt die Eingabe wieder zu",
        "add_form: button",
        "`button`",
        "`always`",
        "`never`",
        "(Standard)",
        "„Neue Version installiert – Seite neu laden, um die Karte zu aktualisieren.“",
        "„Neu laden“",
        "`integration_version`",
    ):
        assert text in card, text
    assert "type: custom:parcel-tracker-card\nadd_form: button" in card
    assert "bitte" not in card.lower()
    intro = README.split("## Was es kann")[0]
    assert "`?add=open`" in intro and "`?add=always`" in intro
    assert "geöffneter Eingabe" in intro  # the detail screenshot shows the open form
    what = _section("Was es kann")
    assert "`integration_version`" in what


def test_demo_page_knows_the_add_form_views():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    for text in ("?add=open", "?add=always", "?add=never", "?hint=1", "integration_version:"):
        assert text in js, text
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    assert 'href="?add=open"' in html and 'href="?add=always"' in html


def test_readme_status_changes_during_start_and_reload():
    """v0.3.8: announced once Home Assistant has started, at the latest two minutes
    after the integration loaded; a pending announcement survives a reload."""
    section = _section("Benachrichtigungen")
    for text in (
        "geht nichts verloren",
        "sobald Home Assistant fertig gestartet ist",
        "spätestens zwei Minuten nachdem die Integration geladen wurde",
        "übersteht auch ein erneutes Neuladen",
        "nach einem Neuladen im laufenden Betrieb sofort",
    ):
        assert text in section, text


def test_readme_explains_the_three_summary_sensors_and_the_show_option():
    """v0.3.11: sensors for "on the way", "possible", "delivered today"; card option `show`."""
    what = _section("Was es kann")
    sensors = next(line for line in what.splitlines() if line.startswith("- **Sensoren**"))
    for text in (
        "`sensor.pakete_unterwegs`",
        "`sensor.pakete_moeglich`",
        "`sensor.pakete_zugestellt_heute`",
        "noch nicht zugestellt",
    ):
        assert text in sensors, text
    card = _section("Karte hinzufügen")
    for text in (
        "`show`",
        "`always` (Standard)",
        "`active`",
        "`today`",
        "`today_possible`",
        "show: active",
        "„Ausgeblendet, solange nichts ansteht (show: …)“",
        "Bearbeitungsmodus",
        "visibility:",
        "condition: numeric_state",
        "entity: sensor.pakete_unterwegs",
        "above: 0",
    ):
        assert text in card, text
    assert "bitte" not in (sensors + card).lower()
    english = _section("English summary")
    assert "`sensor.pakete_unterwegs`" in english and "`show`" in english


def test_demo_page_knows_the_show_option():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    for text in (
        "?show=active", "?show=today", "?show=today_possible", "?empty=1", "?edit=1",
        '"sensor.pakete_unterwegs"', '"sensor.pakete_moeglich"',
        '"sensor.pakete_zugestellt_heute"',
    ):
        assert text in js, text
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    assert 'href="?show=active&amp;empty=1"' in html


def test_readme_explains_the_update_order_and_since_when_the_reload_hint_exists():
    """v0.3.12: testers on an older card waited for a hint that card cannot show."""
    card = _section("Karte hinzufügen")
    assert "Den Hinweis gibt es ab v0.3.9" in card
    assert "Eine ältere Karte kennt ihn nicht" in card
    steps = [
        "1. Das Update in HACS installieren.",
        "2. Home Assistant neu starten.",
        "3. Die Seite im Browser neu laden oder die Home-Assistant-App schließen"
        " und wieder öffnen.",
    ]
    assert "\n".join(steps) in card
    assert "Die Integration zu entfernen und neu hinzuzufügen ist dafür nie nötig" in card


def test_readme_explains_expanding_a_parcel_and_the_missing_dhl_key():
    """v0.3.12: rows show a chevron; without a key a DHL parcel reads "Kein Live-Status"."""
    card = _section("Karte hinzufügen")
    for text in (
        "Ein Tipp auf ein Paket klappt es auf",
        "Verlauf der Sendung",
        "„Umbenennen“",
        "„Löschen“",
        "„Wirklich löschen?“",
        "„Noch kein Termin“",
        "„Kein Live-Status“",
    ):
        assert text in card, text
    dhl = _section("DHL-API-Key anlegen")
    assert "„Kein Live-Status“" in dhl
    assert "„Kein Live-Status: DHL-API-Key fehlt (unter „Konfigurieren“ eintragen).“" in dhl
    assert "vertippt" in dhl
    assert "„Kein Live-Status“" in _section("Was es kann")
    assert '"DHL-API-Key fehlt"' not in README


def test_demo_page_has_a_dhl_parcel_without_key_and_without_result():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    block = re.search(r'parcel\("unknown", "dhl", [^)]*\{([^}]*)\}\)', js)
    assert block and 'last_error: "missing_key"' in block.group(1)
    assert "events" not in block.group(1) and "eta_days" not in block.group(1)


def test_readme_lists_the_country_among_the_setup_fields():
    """v0.3.13: country DE/AT/CH, the postcode length follows it."""
    fields = README.split("### Einrichtungsfelder")[1].split("\n## ")[0]
    assert "- **Land** (Deutschland, Österreich oder Schweiz" in fields
    assert fields.index("**Land**") < fields.index("**PLZ**")
    for text in (
        "Deutschland 5 Ziffern",
        "Österreich und Schweiz 4 Ziffern",
        "Alle vier Felder",
        "Bestehende Einrichtungen bleiben ohne Zutun auf Deutschland",
    ):
        assert text in fields, text


def test_readme_says_honestly_what_works_in_austria_and_switzerland():
    section = README.split("### Österreich und Schweiz")[1].split("\n## ")[0]
    for text in (
        "PLZ mit 4 Ziffern",
        "DHL mit API-Key über die offizielle API",
        "UPS über die offizielle API",
        "jeder Carrier über 17track",
        "GLS",
        "mit echten Paketen noch nicht getestet",
        "Für die Schweiz bleibt die GLS-Abfrage auf der deutschen Variante",
        "Noch nicht",
        "DPD-Live-Abfrage für Österreich",
        "DPD Schweiz",
        "Österreichische Post",
        "Schweizerische Post",
        "erkennt andere ausländische Nummernformate nicht automatisch",
        "anonymisierte Beispielmails",
        "Diagnose-Datei",
        "(#beispielmails-einreichen)",
        "(#fehler-melden)",
    ):
        assert text in section, text


def test_readme_roadmap_names_the_austrian_post():
    roadmap = README.split("## Roadmap & Status")[1].split("## English summary")[0]
    international = next(line for line in roadmap.splitlines() if "**International**" in line)
    assert "Österreichische Post" in international
    assert "- Land (Deutschland, Österreich, Schweiz)" in roadmap


def test_readme_english_summary_names_the_country_setting():
    english = README.split("## English summary")[1]
    assert english.count("country setting") == 1
    assert "Austria" in english and "Switzerland" in english


def test_readme_diagnostics_name_the_country():
    section = README.split("\n## Fehler melden\n")[1].split("\n## ")[0]
    assert "das eingestellte Land" in section


def test_readme_table_says_what_each_service_needs():
    """v0.3.14: new users add a DHL number without a key and think the integration is broken."""
    assert README.index("\n## Installation\n") < README.index(
        "\n## Was brauche ich für welchen Dienst?\n"
    ) < README.index("\n## DHL-API-Key anlegen\n")
    section = _section("Was brauche ich für welchen Dienst?")
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|")
    ]
    assert rows[0] == ["Dienst", "Live-Status direkt", "aus Mails (Mail-Import)", "Voraussetzung"]
    table = {row[0]: row[1:] for row in rows[2:]}
    assert list(table) == ["DHL", "DPD", "GLS", "Hermes", "UPS", "Amazon", "eBay", "andere Carrier"]
    assert all(len(cells) == 3 for cells in table.values())
    expected = {
        "DHL": ("nur mit DHL-API-Key", "DHL-Mails", "kostenloser [DHL-API-Key]"),
        "DPD": ("ohne Key (nur Status, kein Ort)", "optional", "keine"),
        "GLS": ("ohne Key (offene Abfrage, mit PLZ auch der Verlauf)", "GLS-Mails", "keine"),
        "Hermes": ("ja, ohne Key", "Hermes-Mails", "keine"),
        "UPS": ("nur mit eigenem UPS-Entwicklerzugang", "UPS-Mails", "Client-ID und Secret"),
        "Amazon": ("nein", "nur aus Mails", "E-Mail-Import"),
        "eBay": ("nein", "nur aus Mails", "E-Mail-Import"),
        "andere Carrier": ("17track", "nein", "200 Nummern einmalig"),
    }
    for service, texts in expected.items():
        for cell, text in zip(table[service], texts, strict=True):
            assert text in cell, (service, text)
    assert "„Kein Live-Status“" in section and "beim Hinzufügen" in section
    assert "bitte" not in section.lower()


def test_readme_table_matches_what_the_integration_does():
    """The table's statements, checked against the code they describe."""
    from custom_components.parcel_tracker import const
    from custom_components.parcel_tracker.mail.base import DPD_DOMAINS

    assert const.OPTIONAL_API_CARRIERS == frozenset({"ups"})  # UPS: live only with credentials
    assert set(const.MAIL_CARRIERS) == {"amazon", "ebay"}  # shops: mails only
    assert "service.dpd.de" in DPD_DOMAINS  # DPD mails are read (for the number)
    assert "200 Nummern" in _section("17track (optional)")


def test_readme_explains_the_note_after_adding_a_parcel_without_key():
    card = _section("Karte hinzufügen")
    source = (
        ROOT / "custom_components" / "parcel_tracker" / "frontend" / "parcel-tracker-card.js"
    ).read_text(encoding="utf-8")
    for text in (
        "Hinzugefügt. Ohne DHL-API-Key gibt es dafür keinen Live-Status: Key unter"
        " „Konfigurieren“ eintragen – oder der Status kommt aus den DHL-Mails über den"
        " Mail-Import.",
        "Hinzugefügt. Ohne UPS-Zugangsdaten gibt es dafür keinen Live-Status: Zugangsdaten"
        " unter „Konfigurieren“ eintragen – oder der Status kommt aus den UPS-Mails über den"
        " Mail-Import.",
    ):
        assert text in card and text in source, text
    for text in ("**Hinweis nach dem Hinzufügen:**", "das ×", "`add_form: always`", "aus Mails"):
        assert text in card, text
    ups = _section("UPS-Live-Status (optional)")
    assert "„Kein Live-Status: UPS-Zugangsdaten fehlen (unter „Konfigurieren“ eintragen).“" in ups


def test_demo_page_can_show_the_note_after_adding():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    for text in ("?added=missing_key", "?added=ups", 'last_error: "missing_key"'):
        assert text in js, text
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    assert 'href="?added=missing_key"' in html


def test_readme_sieve_example_names_every_listed_sender():
    """v0.3.15: three more senders (GLS and DPD Austria)."""
    sieve = README.split("```sieve")[1].split("```")[0]
    for address in SENDERS:
        assert f'"{address}"' in sieve, address


def test_readme_says_what_v0_3_15_reads_from_austria():
    section = README.split("### Österreich und Schweiz")[1].split("\n## ")[0]
    for text in (
        "`noreply@gls-group.eu`",
        "`noreply@gls-rtt.com`",
        "mehrere Pakete in einer Mail",
        "`no_reply@dpd.at`",
        "„Ein DPD Paket für dich“",
        "„Neuigkeiten zu deinem Paket“",
        "derzeit nur aus diesen Mails",
        "mydpd.at",
        "anderen Format",
        "ungültigen Nummer",
        "`CQ…DE`",
        "ohne Liefertag",
    ):
        assert text in section, text
    assert "versteht weiter nur deutsche Mails" not in README


def test_readme_says_dhl_mails_name_the_shop():
    section = README.split("### Kein Key? Dann die DHL-Mails")[1].split("\n## ")[0]
    assert "„Ihre Beispiel GmbH Sendung ist unterwegs“" in section
    assert "Rechtsform" in section and "nie der Name einer Privatperson" in section


def test_readme_matches_the_senders_the_parsers_know():
    from custom_components.parcel_tracker.mail.dpd import DPD_AT_SENDER
    from custom_components.parcel_tracker.mail.gls import GLS_GROUP_SENDER, GLS_RTT_SENDER

    for address in (DPD_AT_SENDER, GLS_GROUP_SENDER, GLS_RTT_SENDER):
        assert address in SENDERS


# ----- v0.3.15 review -----
def test_readme_says_where_a_company_name_ends_and_that_carriers_never_name_a_parcel():
    dhl = README.split("### Kein Key? Dann die DHL-Mails")[1].split("\n## ")[0]
    gls = README.split("### GLS-Pakete")[1].split("\n### ")[0]
    for section in (dhl, gls):
        assert "endet an der Rechtsform" in section
    assert "Anzeigename eines Carriers" in dhl and "„DHL Paketankündigung“" in dhl
    privacy = README.split("## Datenschutz")[1].split("\n## ")[0]
    assert "den Namen eines Shops oder einer Firma (nur bis zur Rechtsform" in privacy
    assert "nie den Anzeigenamen eines Carriers" in privacy


def test_readme_says_which_dhl_subjects_set_a_status():
    section = README.split("### Kein Key? Dann die DHL-Mails")[1].split("\n## ")[0]
    for text in (
        "nur aus dem Betreff",
        "„ist unterwegs“",
        "„kommt heute“",
        "„wurde zugestellt“",
        "Zustellfoto",
        "Packstation",
        "Abholcodes liest der Import nie",
    ):
        assert text in section, text


def test_readme_says_what_a_dpd_austria_mail_means():
    section = README.split("### Österreich und Schweiz")[1].split("\n## ")[0]
    for text in (
        "„zugestellt“, „abgestellt“",
        "am gewünschten Abstellort bzw. Wunschort „hinterlegt“",
        "Pickup Paketshop",
        "„Abholbereit“",
        "an DPD übergeben",
        "im Depot",
        "setzt keinen Status",
    ):
        assert text in section, text


def test_readme_says_one_gls_mail_may_create_several_parcels():
    section = README.split("### Österreich und Schweiz")[1].split("\n## ")[0]
    assert "für jede Nummer ein eigenes Paket" in section


def test_readme_says_which_grouped_numbers_the_anonymiser_replaces():
    section = README.split("## Beispielmails einreichen")[1].split("\n## ")[0]
    assert (
        "Nummern ab 10 Ziffern, die in Gruppen geschrieben sind (getrennt durch Leerzeichen,"
        " Tabulator, Punkt oder Bindestrich), und internationale Nummern in Gruppen"
        " („CQ 123 456 785 DE“) behalten ihre Gruppen und bekommen erfundene Ziffern"
    ) in section
    assert "in Gruppen geschriebene Nummern behalten ihre Gruppen." not in section


def test_readme_lists_the_three_dhl_senders_and_the_domain_rule():
    senders = README.split("### Welche Absender")[1].split("\n### ")[0]
    for address in ("noreply@dhl.de", "paketankuendigung@dhl.de", "zustellung@dhl.de"):
        assert f"`{address}`" in senders
        assert f'"{address}"' in senders  # the Sieve example
    assert "Regel auf die ganze Domain `dhl.de`" in senders
    no_key = README.split("### Kein Key? Dann die DHL-Mails")[1].split("\n## ")[0]
    assert "`noreply@dhl.de`, `paketankuendigung@dhl.de` und `zustellung@dhl.de`" in no_key
    assert "12 Ziffern" in no_key and "„Ihre Sendungsnummer“" in no_key


def test_readme_gives_the_tip_for_the_dhl_key_application():
    section = README.split("## DHL-API-Key anlegen")[1].split("### Kein Key?")[0]
    assert "eigene Sendungen verfolgen" in section
    assert "dafür ist die Tracking-API gedacht" in section


def test_readme_says_when_a_carrier_mail_joins_a_shop_order():
    section = README.split("### Zusammenführen")[1].split("\n### ")[0]
    for text in (
        "Nennt die Carrier-Mail statt des Shops die Marke",
        "genau eines offenen",
        "beginnt",
        "Besteht das Carrier-Paket schon",
        # second review: Amazon only, and under which conditions
        "nur zu einem offenen **Amazon-Paket**",
        "nie zu einem eBay-Paket",
        "keinen anderen Versanddienstleister nennt",
        "muss das Paket schon „Versendet“ sein",
        "ein Wort ab 5 Buchstaben oder mehrere Wörter",
        "bekannte Shops (IKEA",
        "aus einem nur bestellten Paket nie ein zugestelltes",
    ):
        assert text in section, text
    assert "Amazon- oder eBay-Paket ohne Sendungsnummer nur dann" not in section


def test_readme_says_which_stored_carrier_names_are_replaced():
    section = README.split("### Kein Key? Dann die DHL-Mails")[1].split("\n## ")[0]
    for text in (
        "Wörtern einer Benachrichtigung",
        "„DPD Versandinfo“",
        "auch „Hermes“, „DHL Express“ oder „Paket“",
    ):
        assert text in section, text


def test_readme_names_the_further_dhl_subjects():
    section = README.split("### Kein Key? Dann die DHL-Mails")[1].split("\n## ")[0]
    for text in (
        "„kommt morgen“",
        "„wird heute zugestellt“",
        "„wurde an den gewünschten Ablageort zugestellt“",
        "„Abholbereit“",
        "Fragezeichen",
        "nie einen Status zurück",
    ):
        assert text in section, text


def test_readme_says_what_a_forwarded_sample_mail_means():
    section = _section("Beispielmails einreichen")
    for text in (
        "Weitergeleitete Mails helfen deutlich weniger als Originale",
        "besonders genau gelesen",
        "Signatur",
        "„ACHTUNG“-Zeile",
        "„2026-09-28 11:51“",
    ):
        assert text in section, text


def test_readme_privacy_covers_the_ups_shipper_and_seller_names():
    privacy = README.split("## Datenschutz")[1].split("\n## ")[0]
    assert "Absenderzeile „Von:“ einer UPS-Mail" in privacy
    assert "nur „Amazon“ bzw. „eBay“" in privacy
    dpd = README.split("### Österreich und Schweiz")[1].split("\n## ")[0]
    assert "„beim Nachbarn abgegeben“" in dpd and "„umgeleitet“ reicht nicht" in dpd

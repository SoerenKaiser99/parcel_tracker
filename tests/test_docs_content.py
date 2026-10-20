"""What the documentation site says, page by page.

These facts were pinned in the README until it became a landing page; the details
live in docs/*.md now, and each test reads the page (and section) that carries them.
"""

import json
import re
import textwrap
from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
TEXTS = {page.name: page.read_text(encoding="utf-8") for page in sorted(DOCS.glob("*.md"))}
RAW = "https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main"
BLUEPRINT_RAW = RAW + "/blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml"

SENDERS = [
    "bestellbestaetigung@amazon.de",
    "versandbestaetigung@amazon.de",
    "shipment-tracking@amazon.de",
    "order-update@amazon.de",
    "pickup-point@amazon.de",
    "noreply@dhl.de",
    "paketankuendigung@dhl.de",
    "zustellung@dhl.de",
    "sendungsupdate@dhl.de",
    "abholung@dhl.de",
    "noreply.odd@dhl.com",
    "noreply@service.dpd.de",
    "no_reply@dpd.at",
    "noreply@gls-group.eu",
    "noreply@gls-rtt.com",
    "pkginfo@ups.com",
    "noreply@paketankuendigung.myhermes.de",
    "ebay@ebay.com",
    "no-reply@gls-pakete.de",
    "transaction@notice.aliexpress.com",
    "bestellstatus@eventim.de",
]


def _section(page: str, title: str) -> str:
    """The text below a heading, up to the next heading of the same or a higher level."""
    text = TEXTS[page]
    found = re.search(rf"^(#+) {re.escape(title)}\n", text, re.M)
    assert found, (page, title)
    rest = text[found.end():]
    end = re.search(rf"^#{{1,{len(found.group(1))}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def _tab(page: str, name: str) -> str:
    """One content tab (=== "name"), up to the next tab or heading."""
    text = TEXTS[page]
    rest = text[text.index(f'\n=== "{name}"\n') + 1:]
    end = re.search(r'^(=== "|#+ )', rest[4:], re.M)
    return rest[: end.start() + 4] if end else rest


def _all_have(section: str, texts) -> None:
    for text in texts:
        assert text in section, text


MAIL = "mail-import.md"
SERVICES = "dienste.md"
CARD = "karte.md"
NOTIFY = "benachrichtigungen.md"
AUTOMATIONS = "automationen.md"
SENSORS = "sensoren.md"
PRIVACY = "datenschutz.md"
HELP = "hilfe.md"
STATUS = "stand.md"
INSTALL = "installation.md"

AUSTRIA = "Österreich und Schweiz"
NO_KEY = "Kein Key? Dann die DHL-Mails"
MERGE = "Zusammenführen: Carrier-Mail und Bestellung"
TODAY = "`sensor.pakete_heute`"


# ----- E-Mail-Import -----
def test_mail_import_page_documents_the_import():
    page = TEXTS[MAIL]
    assert page.startswith("# E-Mail-Import\n")
    assert "Nur ein eigenes Paket-Postfach eintragen, nie das Hauptpostfach" in page
    assert "\n## Von Hand weiterleiten\n" in page
    assert 'redirect :copy "pakete@example.org";' in page
    senders = _section(MAIL, "Filterregel anlegen")
    for address in SENDERS:
        assert f"`{address}`" in senders
    assert "Paket-Tracker-Verarbeitet" in page
    assert "Paket-Tracker-Nicht-erkannt" in page


def test_docs_explain_cancelled_orders():
    amazon = _tab(MAIL, "Amazon")
    _all_have(amazon, ("„Ihre Bestellung wurde storniert.“", "„Artikel … storniert: …“",
                       "„… Stornierung von Artikeln …“", "„Storniert“", "`cancelled`",
                       "ohne Benachrichtigung", "genau aus diesem Artikel",
                       "Storniert wird nur, was noch nicht versendet ist",
                       "nach Liefertagen getrennt"))
    aliexpress = _tab(MAIL, "AliExpress")
    assert "„Stornierte Bestellung wegen überfälligem Versand“" in aliexpress
    assert "„Your order … is closed“ (die Mail sagt nicht" in aliexpress  # only read
    _all_have(_tab(MAIL, "eBay"), ("„Kauf … wurde abgebrochen“",
                                   "„OK - Sie möchten den Kauf abbrechen“ wird nur als gelesen"))
    assert "| `cancelled` |" in TEXTS[SENSORS] and "| `cancelled` |" in TEXTS[AUTOMATIONS]
    assert "`cancelled`" in _section(NOTIFY, "Wann wird gesendet?")
    assert "| „Storniert“ |" in TEXTS[CARD]
    assert "einer stornierten Bestellung fehlt der Knopf" in TEXTS[CARD]


def test_docs_explain_the_ebay_purchase_confirmation():
    ebay = _tab(MAIL, "eBay")
    _all_have(ebay, ("„Bestellung bestätigt: …“", "„Ihre Bestellung wurde bestätigt“",
                     "als „Bestellt“", "„Ihre Bestellung ist eingegangen!“",
                     "„Kauf bestätigt: …“", "nur aus dem Betreff"))
    assert "ab der Kaufbestätigung als „Bestellt“" in TEXTS[SERVICES]


def test_docs_say_the_delivery_code_is_readable_via_attributes():
    section = _section(PRIVACY, "Zustell-Codes")
    assert "Verdeckt ist er nur auf der Karte" in section
    assert "im Klartext lesen" in section
    assert "Verdeckt ist der Code nur auf der Karte" in _section(SENSORS, "Attribute")


def test_docs_explain_the_ups_api_and_its_budget():
    section = _section(SERVICES, "UPS")
    _all_have(section, ("developer.ups.com", "**Tracking**", "Track Alert", "Pending",
                        "Monatsbudget", "Standard 100", "alle 4 Stunden"))
    assert '"noreply@paketankuendigung.myhermes.de", "ebay@ebay.com"' in TEXTS[MAIL]


def test_status_page_lists_what_is_done_confirmed_and_dropped():
    page = TEXTS[STATUS]
    assert page.startswith("# Roadmap & Status\n")
    _all_have(page, (
        "| UPS Live-Status (offizielle API) | noch nicht mit echten Zugangsdaten "
        "getestet (UPS-Freischaltung ausstehend) |",
        "| Hermes Live-Abfrage | umgesetzt; von einem Tester mit einer aktuellen Sendung"
        " bestätigt |",
        "| eBay-Mails | umgesetzt |",
        "| 17track | umgesetzt; Abfrage von einem Tester bestätigt (das Kontingent wird einmal "
        "belastet, die Karte füllt sich) |",
        "| Von Hand weitergeleitete Mails | umgesetzt; von einem Tester bestätigt |",
        "| GLS-Live-Abfrage | umgesetzt; von einem Tester mit einem echten Paket bestätigt |",
        "| GLS-Mails | umgesetzt |",
        "| Amazon per Konto-Anmeldung | verworfen zugunsten des Mail-Imports |",
    ))
    assert "Live-Test ausstehend" not in page


def test_docs_explain_17track():
    section = _section(SERVICES, "17track (optional)")
    _all_have(section, (
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
    ))


def test_docs_explain_gls():
    section = _section(SERVICES, "GLS")
    _all_have(section, (
        "gls-group.com",
        "11 Ziffern",
        "eBay-Artikelnummern",
        "Carrier-Wahl „GLS“",
        "bis zu 20 Ereignisse",
        "höchstens alle 30 Minuten",
        "Kein offizieller Zugang",
        "GLS-Mails, und „Details über 17track holen“",
    ))
    mails = _tab(MAIL, "GLS")
    _all_have(mails, (
        "Dein GLS Paket kommt heute!",
        "Rechtsform",
        "Abstellort, Zustelladresse, Empfängername, Telefonnummer und Referenzen",
    ))
    assert "GLS als blauer Punkt mit „G“" in _section(PRIVACY, "Markenhinweis")
    assert '"no-reply@gls-pakete.de"\n] {' in TEXTS[MAIL]
    assert "Live-Test ausstehend" not in "".join(TEXTS.values())


def test_privacy_page_names_dhl_and_gls_for_the_postcode():
    section = _section(PRIVACY, "Was geht wohin?")
    assert "| PLZ | nur DHL und GLS |" in section
    assert "ohne hinterlegte PLZ geht an GLS nur die Paketnummer" in section
    assert "Die PLZ geht ausschließlich an DHL" not in TEXTS[PRIVACY]
    assert "(DHL, DPD, GLS, Hermes, mit eigenen Zugangsdaten UPS)" in section


def test_status_page_lists_international():
    section = _section(STATUS, "Offen")
    row = next(line for line in section.splitlines() if "**International**" in line)
    _all_have(row, (
        "Karte auch auf Englisch",
        "weitere Amazon-Länder im Mail-Import",
        "Österreichische Post",
        "Royal Mail, PostNL, USPS",
        "anonymisierten Beispielmails von Testern",
    ))
    assert "| Land (Deutschland, Österreich, Schweiz) |" in TEXTS[STATUS]


# ----- Hilfe: Fehler melden, Beispielmails -----
def test_docs_explain_how_to_report_a_bug():
    section = _section(HELP, "Fehler melden")
    _all_have(section, (
        "**Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen**",
        "issues/new?template=fehler.yml",
        "Ziffern werden zu `9`, Buchstaben zu `A`",
        "[Diagnose](sensoren.md#diagnose)",
        "[Beispielmails einreichen](#beispielmails-einreichen)",
    ))
    diagnostics = _section(SENSORS, "Diagnose")
    _all_have(diagnostics, (
        "**Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen**",
        "**Die Diagnose enthält:**",
        "**Die Diagnose enthält nie:**",
        "API-Keys, Passwörter, das UPS-Secret, den 17track-Key, den IMAP-Benutzer",
        "die PLZ",
        "Zustell-Codes",
        "Mail-Inhalte",
        "Ziffern werden zu `9`, Buchstaben zu `A`",
        "`JJD999999999999999999`",
        "Absender-Domain",
        "bei einer Weiterleitung die Domain des ursprünglichen Absenders",
        # what Home Assistant adds by itself, and the host of an own mail server
        "Home Assistant ergänzt die Datei selbst um Systeminformationen",
        "Liste der installierten benutzerdefinierten Integrationen",
        "steht nur als `custom` drin",
        "das eingestellte Land",
        "ob „Namen ausblenden“ eingeschaltet ist",
        "getrennt nach Entitäten und klassischen Diensten",
    ))


def test_docs_explain_how_to_send_sample_mails():
    section = _section(HELP, "Beispielmails einreichen")
    _all_have(section, (
        "Nie rohe Mails hochladen. Nie Mails privat an den Autor schicken.",
        "Die Mail als `.eml` speichern",
        "leite sie nicht weiter",
        "https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/scripts/"
        "anonymize_mail.py",
        "python3 anonymize_mail.py <Ordner> --zip",
        "Leer lassen",
        "Das Skript fragt nach Name, Straße und Hausnummer, Postleitzahl, Ort",
        "`--ohne-angaben`",
        "Namen und Orte können dann stehen bleiben",
        "Frühere Ergebnisse",
        "ohne Netzwerkzugriff",
        "`anonymisiert/`",
        "jede Datei",
        "`paket-tracker-beispiele.zip`",
        "issues/new?template=mail-nicht-erkannt.yml",
        "„Mail wird nicht erkannt“",
    ))
    steps = re.findall(r"^### Schritt (\d): ", section, re.M)
    assert steps == ["1", "2", "3", "4", "5"]
    assert section.index(".eml") < section.index("raw.githubusercontent") < section.index(
        "<Ordner>/anonymisiert/"
    ) < section.index("issues/new")


def test_help_page_has_both_report_sections_at_the_end():
    titles = [line[3:] for line in TEXTS[HELP].splitlines() if line.startswith("## ")]
    assert titles[-2:] == ["Fehler melden", "Beispielmails einreichen"]


def test_docs_say_which_grouped_numbers_the_anonymiser_replaces():
    section = _section(HELP, "Beispielmails einreichen")
    assert (
        "Nummern ab 10 Ziffern, die in Gruppen geschrieben sind (getrennt durch Leerzeichen,"
        " Tabulator, Punkt oder Bindestrich), und internationale Nummern in Gruppen"
        " („CQ 123 456 785 DE“) behalten ihre Gruppen und bekommen erfundene Ziffern"
    ) in section
    assert "in Gruppen geschriebene Nummern behalten ihre Gruppen." not in section
    assert "„[Nummer nur im Link oder Bildtext: …]“" in section


def test_docs_say_what_a_forwarded_sample_mail_means():
    section = _section(HELP, "Beispielmails einreichen")
    _all_have(section, (
        "Weitergeleitete Mails helfen deutlich weniger als Originale",
        "besonders genau gelesen",
        "Signatur",
        "„ACHTUNG“-Zeile",
        "„2026-09-28 11:51“",
    ))


def test_docs_say_what_the_script_does_with_a_forwarded_sample_mail():
    section = _section(HELP, "Beispielmails einreichen")
    _all_have(section, (
        "übernimmt das Skript nur diesen Block und die Mail darunter",
        "Alles darüber (eigene Zeilen, die eigene Signatur) lässt es weg",
        "den ursprünglichen Absender im Block lässt es stehen",
        "die Empfänger ersetzt es",
        "leite sie nicht weiter",
    ))


def test_docs_card_not_found_section():
    section = _section(HELP, "Karte wird nicht gefunden?")
    _all_have(section, (
        "Custom element doesn't exist: parcel-tracker-card",
        "Behoben in v0.3.6",
        "nur noch als Dashboard-Ressource",
        "Integration auf v0.3.6 oder neuer aktualisieren, Home Assistant neu starten",
        "Bis v0.3.5 gilt: normal neu laden (F5",
        "Kein hartes Neuladen",
        "Einstellungen → Dashboards → ⋮ → Ressourcen",
        "`resource_mode: yaml`",
        "**Einstellungen → Reparaturen**",
        "type: module",
    ))
    steps = [line for line in section.splitlines() if line[:2] in ("1.", "2.", "3.")]
    assert len(steps) == 3
    # ≤ v0.3.5 a hard reload triggers the bug, so it is never the advice
    everything = "".join(TEXTS.values())
    assert "Seite neu laden (am Rechner Strg+F5" not in everything
    assert "Frontend-Cache leeren" not in everything


# ----- Benachrichtigungen -----
def test_docs_explain_notifications():
    page = TEXTS[NOTIFY]
    _all_have(page, (
        "Paket Tracker → Konfigurieren**",
        "„Benachrichtigungen“",
        "`notify.",
        "In Zustellung",
        "Zugestellt",
        "Abholbereit",
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
        "\n## Blueprint\n",
        "`data.url`",
        "`data.clickAction`",
        "`data.tag`",
        "blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml",
    ))
    assert "notify_url" not in "".join(TEXTS.values())


def test_docs_explain_both_kinds_of_targets():
    """Notify entities and classic services (Pushover has only the latter)."""
    section = _section(NOTIFY, "Ziele")
    _all_have(section, (
        "Benachrichtigungs-Entitäten",
        "Klassische Dienste",
        "„Dienst notify.pushover“",
        # Pushover has to exist in Home Assistant first
        "Richte Pushover zuerst in Home Assistant als Integration ein",
        # a target that is gone
        "„nicht mehr vorhanden“",
        # the classic service of the app replaces the earlier notification
        "„Dienst notify.mobile_app_&lt;gerät&gt;“",
        "ersetzt eine neue Meldung die frühere zum selben Paket",
        "nur eines von beiden",
    ))


def test_docs_no_longer_say_nothing_happens_at_startup():
    assert "nicht beim Start" not in "".join(TEXTS.values())


def test_docs_status_changes_during_start_and_reload():
    """v0.3.8: announced once Home Assistant has started, at the latest two minutes
    after the integration loaded; a pending announcement survives a reload."""
    section = _section(NOTIFY, "Wann wird gesendet?")
    _all_have(section, (
        "geht nichts verloren",
        "sobald Home Assistant fertig gestartet ist",
        "spätestens zwei Minuten nachdem die Integration geladen wurde",
        "übersteht auch ein erneutes Neuladen",
        "Nach einem Neuladen im laufenden Betrieb sofort",
    ))


def test_docs_blueprint_import_link():
    link = (
        "https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url="
        + quote(BLUEPRINT_RAW, safe="")
    )
    assert link in _section(NOTIFY, "Blueprint")
    assert "%3A%2F%2Fraw.githubusercontent.com%2FSoerenKaiser99%2Fparcel_tracker%2Fmain%2F" in link
    assert (ROOT / "blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml").is_file()


def test_status_page_lists_notifications_as_done():
    assert "| Benachrichtigungen (Optionen und Blueprint) | umgesetzt" in TEXTS[STATUS]


# ----- Automationen -----
def test_docs_event_section_lists_the_carrier_name():
    section = _section(AUTOMATIONS, "Felder des Events")
    for field in ("number", "name", "carrier", "carrier_name", "old_status", "new_status",
                  "eta_date", "eta_from", "eta_to", "location"):
        assert f"| `{field}` |" in section, field
    assert "trigger.event.data.carrier_name" in TEXTS[AUTOMATIONS]


def test_docs_document_the_assumed_field_of_the_event():
    assert "| `assumed` |" in _section(AUTOMATIONS, "Felder des Events")
    notify = _section(NOTIFY, "Wann wird gesendet?")
    assert "`assumed`" in notify
    assert "Abgeschlossen ohne Zustellbestätigung" in notify


def test_docs_explain_automations_without_yaml():
    titles = [line[3:] for line in TEXTS[AUTOMATIONS].splitlines() if line.startswith("## ")]
    at = titles.index("Auslöser ohne YAML")
    event_title = "Das Event `parcel_tracker_status_changed`"
    assert titles[at : at + 2] == ["Auslöser ohne YAML", event_title]
    section = _section(AUTOMATIONS, "Auslöser ohne YAML")
    _all_have(section, (
        "**Auslöser hinzufügen** → „Gerät“",
        "Als Gerät „Paket Tracker“ wählen",
        "**Paket ist in Zustellung**",
        "**Paket wurde zugestellt**",
        "**Paket liegt zur Abholung bereit**",
        "**Problem bei einem Paket**",
        "**Paketstatus hat sich geändert**",
        "{{ trigger.event.data.name }}",
        "**„Paket wurde zugestellt“ feuert dann nicht.**",
        "ihre Namen und Entitäts-IDs sind unverändert",
    ))
    # The event is still documented, with its new field.
    event = _section(AUTOMATIONS, event_title)
    assert "| `entry_id` |" in event
    assert "event_type: parcel_tracker_status_changed" in event


def test_docs_trigger_names_match_the_german_translation():
    de = json.loads(
        (ROOT / "custom_components/parcel_tracker/translations/de.json").read_text("utf-8")
    )
    section = _section(AUTOMATIONS, "Die fünf Auslöser")
    for name in de["device_automation"]["trigger_type"].values():
        assert f"**{name}**" in section, name


# ----- Karte -----
def test_docs_say_when_local_is_used():
    section = _section(INSTALL, "Karte hinzufügen")
    assert "wenn der Ordner `www` beim Start schon existierte" in section
    assert "`/parcel_tracker/parcel-tracker-card.js`" in section
    assert "Seite im Browser einmal neu laden" in section


def test_docs_explain_sure_and_possible_parcels_of_today():
    """v0.3.7: "Pakete heute" counts only sure parcels, ranges are "möglich"."""
    sensors = _section(SENSORS, TODAY)
    _all_have(sensors, (
        "Zählt die Pakete, die **heute sicher** kommen",
        "„In Zustellung“",
        "fester Liefertag heute",
        "„2.–5. Okt.“",
        "`possible`",
        "`possible_count`",
        "`parcels`",
        "In Templates",
        "{{ state_attr('sensor.pakete_heute', 'possible_count') }}",
        "wechselt es von selbst",
    ))
    _all_have(TEXTS[CARD], ("„1 möglich“", "„Bis 5. Okt.“", "Lieferspanne"))


def test_docs_explain_the_three_badges_and_delivered_today():
    """v0.3.10: three badges in the card's head; the sensor lists what was delivered today."""
    card = _section(CARD, "Die Schilder oben rechts")
    _all_have(card, (
        "bis zu drei Schilder",
        "„1 heute“",
        "„1 möglich“",
        "„1 zugestellt“",
        "immer, auch als „0 heute“",
        "nur, wenn",
        "`sensor.pakete_heute`",
    ))
    assert card.index("„1 heute“") < card.index("„1 möglich“") < card.index("„1 zugestellt“")
    assert "„1 heute · 1 möglich“" not in "".join(TEXTS.values())  # the combined text is gone
    sensors = _section(SENSORS, TODAY)
    _all_have(sensors, (
        "`delivered_today`",
        "`delivered_today_count`",
        "`delivered_at`",
        "Zeitzone von Home Assistant",
        "Tag des Statuswechsels",
        "{{ state_attr('sensor.pakete_heute', 'delivered_today_count') }}",
    ))


def test_docs_say_the_card_is_german_in_any_home_assistant_language():
    card = TEXTS[CARD].split("\n## ")[0]
    assert "Die Karte ist deutsch" in card
    assert "unabhängig von der Sprache" in card


def test_docs_explain_the_plus_button_the_add_form_option_and_the_reload_hint():
    """v0.3.9: the add form sits behind a plus button; `add_form` picks the look."""
    add = _section(CARD, "Paket hinzufügen")
    _all_have(add, ("Plus-Knopf", "„Sendung hinzufügen“", "klappt die Eingabe wieder zu"))
    option = _section(CARD, "`add_form` – die Eingabe")
    _all_have(option, (
        "`button` (Standard)",
        "`always`",
        "`never`",
        "(das Aussehen bis v0.3.8)",
        "type: custom:parcel-tracker-card\n    add_form: button",
    ))
    update = _section(CARD, "Nach einem Update: Seite neu laden")
    _all_have(update, (
        "„Neue Version installiert – Seite neu laden, um die Karte zu aktualisieren.“",
        "„Neu laden“",
        "`integration_version`",
    ))
    assert "| `integration_version` |" in _section(SENSORS, TODAY)


def test_docs_explain_the_demo_page_and_its_parameters():
    intro = TEXTS[CARD].split("\n## ")[0]
    _all_have(intro, (
        "(demo/index.html)",
        "`?theme=dark`",
        "`?open=1`",
        "`?add=open`",
        "`?add=always`",
        "`python3 -m http.server`",
        "`docs/demo/index.html`",
        "erfunden",
    ))
    js = (DOCS / "demo" / "demo.js").read_text(encoding="utf-8")
    for parameter in ("theme=dark", "open=1", "add=open", "add=always"):
        assert parameter.split("=")[0] in js, parameter
    assert "Die Bilder zeigen erfundene Pakete" in TEXTS["index.md"]


def test_docs_explain_the_summary_sensors_and_the_show_option():
    """v0.3.11: sensors for "on the way", "possible", "delivered today"; card option `show`."""
    sensors = _section(SENSORS, "Die vier Zählsensoren")
    _all_have(sensors, (
        "`sensor.pakete_unterwegs`",
        "`sensor.pakete_moeglich`",
        "`sensor.pakete_zugestellt_heute`",
        "noch nicht zugestellt",
    ))
    card = _section(CARD, "Optionen der Karte")
    _all_have(card, (
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
    ))


def test_docs_explain_the_update_order_and_since_when_the_reload_hint_exists():
    """v0.3.12: testers on an older card waited for a hint that card cannot show."""
    card = _section(CARD, "Nach einem Update: Seite neu laden")
    assert "Den Hinweis gibt es ab v0.3.9" in card
    assert "Eine ältere Karte kennt ihn nicht" in card
    steps = [
        "1. Das Update in HACS installieren.",
        "2. Home Assistant neu starten.",
        "3. Die Seite im Browser neu laden oder die Home-Assistant-App schließen"
        " und wieder öffnen.",
    ]
    update = _section(INSTALL, "Nach jedem Update")
    assert "\n".join(steps) in update
    assert "Die Integration zu entfernen und neu hinzuzufügen ist dafür nie nötig" in update


def test_docs_explain_expanding_a_parcel_and_the_missing_dhl_key():
    """v0.3.12: rows show a chevron; without a key a DHL parcel reads "Kein Live-Status"."""
    card = _section(CARD, "Paket aufklappen")
    _all_have(card, (
        "Ein Tipp auf ein Paket klappt es auf",
        "**Verlauf**",
        "Die Ereignisse der Sendung",
        "„Umbenennen“",
        "„Löschen“",
        "„Wirklich löschen?“",
    ))
    row = _section(CARD, "Was in einer Zeile steht")
    assert "| „Noch kein Termin“ |" in row and "| „Kein Live-Status“ |" in row
    dhl = _section(SERVICES, NO_KEY)
    assert "„Kein Live-Status“" in dhl
    assert "„Kein Live-Status: DHL-API-Key fehlt (unter „Konfigurieren“ eintragen).“" in dhl
    assert "vertippt" in dhl
    assert "„Noch keine Daten vom Carrier“" in dhl
    assert "„Kein Live-Status“" in TEXTS[SERVICES].split("\n## ")[0]
    assert '"DHL-API-Key fehlt"' not in "".join(TEXTS.values())


def test_docs_explain_the_note_after_adding_a_parcel_without_key():
    card = _section(CARD, "Paket hinzufügen")
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
    _all_have(card, ('"Hinweis nach dem Hinzufügen"', "das ×", "`add_form: always`", "aus Mails",
                     "schon in der Liste standen"))
    ups = _section(SERVICES, "UPS")
    assert "„Kein Live-Status: UPS-Zugangsdaten fehlen (unter „Konfigurieren“ eintragen).“" in ups


def test_docs_explain_the_tracking_link():
    card = _section(CARD, "Paket aufklappen")
    assert "**Sendung verfolgen**" in card
    assert "Öffnet die Sendungsverfolgung des Paketdienstes" in card
    assert "auch mit Land Österreich oder Schweiz" in card
    assert "`tracking_url`" in card
    assert "| `tracking_url` |" in _section(SENSORS, "Attribute")
    assert "`tracking_url`" in _section(PRIVACY, "Namen ausblenden")


# ----- Installation und Dienste -----
def test_docs_list_the_country_among_the_setup_fields():
    """v0.3.13: country DE/AT/CH, the postcode length follows it."""
    fields = _section(INSTALL, "Integration einrichten")
    assert "| **Land** | Deutschland, Österreich oder Schweiz." in fields
    assert fields.index("**Land**") < fields.index("**PLZ**")
    _all_have(fields, (
        "Deutschland 5 Ziffern",
        "Österreich und Schweiz 4 Ziffern",
        "Alle vier Felder",
        "Bestehende Einrichtungen bleiben ohne Zutun auf Deutschland",
        "den Schalter **Namen ausblenden** (siehe [Datenschutz](datenschutz.md#namen-ausblenden))",
    ))


def test_docs_say_honestly_what_works_in_austria_and_switzerland():
    section = _section(SERVICES, AUSTRIA)
    _all_have(section, (
        "PLZ mit 4 Ziffern",
        "DHL mit API-Key über die offizielle API",
        "UPS über die offizielle API",
        "jeder Paketdienst über 17track",
        "GLS",
        "Mit echten Paketen ist das noch nicht getestet",
        "Für die Schweiz bleibt die GLS-Abfrage auf der deutschen Variante",
        "Noch nicht",
        "DPD-Live-Abfrage für Österreich",
        "DPD Schweiz",
        "Österreichische Post",
        "Schweizerische Post",
        "erkennt andere ausländische Nummernformate nicht automatisch",
        "anonymisierte Beispielmails",
        "Diagnose-Datei",
        "(hilfe.md#beispielmails-einreichen)",
        "(hilfe.md#fehler-melden)",
    ))


def test_docs_table_says_what_each_service_needs():
    """v0.3.14: new users add a DHL number without a key and think the integration is broken."""
    nav = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))["nav"]
    setup = next(item["Einrichten"] for item in nav if "Einrichten" in item)
    assert [next(iter(item.values())) for item in setup][:2] == [INSTALL, SERVICES]
    page = TEXTS[SERVICES]
    assert page.startswith("# Was brauche ich für welchen Dienst?\n")
    assert page.index("| Dienst |") < page.index("\n### DHL-API-Key anlegen\n")
    section = page.split("\n## ")[0]
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|")
    ]
    assert rows[0] == ["Dienst", "Live-Status direkt", "Aus Mails (Mail-Import)", "Voraussetzung"]
    table = {row[0]: row[1:] for row in rows[2:]}
    assert list(table) == [
        "DHL", "DPD", "GLS", "Hermes", "UPS", "Amazon", "eBay", "AliExpress", "Eventim",
        "andere Paketdienste",
    ]
    assert all(len(cells) == 3 for cells in table.values())
    expected = {
        "DHL": ("nur mit DHL-API-Key", "DHL-Mails", "kostenloser [DHL-API-Key]"),
        "DPD": ("ohne Key (nur Status, kein Ort)", "optional", "keine"),
        "GLS": ("ohne Key (mit PLZ auch der Verlauf)", "GLS-Mails", "keine"),
        "Hermes": ("ja, ohne Key", "Hermes-Mails", "keine"),
        "UPS": ("nur mit eigenem UPS-Entwicklerzugang", "UPS-Mails", "Client-ID und Secret"),
        "Amazon": ("nein", "nur aus Mails", "E-Mail-Import"),
        "eBay": ("nein", "nur aus Mails", "E-Mail-Import"),
        "AliExpress": ("nein", "nur aus Mails", "E-Mail-Import"),
        "Eventim": ("nein", "nur Bestellungen mit Postversand", "E-Mail-Import"),
        "andere Paketdienste": ("17track", "nein", "200 Nummern einmalig"),
    }
    for service, texts in expected.items():
        for cell, text in zip(table[service], texts, strict=True):
            assert text in cell, (service, text)
    assert "„Kein Live-Status“" in section and "beim Hinzufügen" in section
    assert "offene Sendungsverfolgung von gls-group.com" in _section(SERVICES, "GLS")


def test_docs_table_matches_what_the_integration_does():
    """The table's statements, checked against the code they describe."""
    from custom_components.parcel_tracker import const
    from custom_components.parcel_tracker.mail.base import DPD_DOMAINS

    assert const.OPTIONAL_API_CARRIERS == frozenset({"ups"})  # UPS: live only with credentials
    # shops: mails only
    assert set(const.MAIL_CARRIERS) == {"amazon", "ebay", "aliexpress", "eventim"}
    assert "service.dpd.de" in DPD_DOMAINS  # DPD mails are read (for the number)
    assert "200 Nummern" in _section(SERVICES, "17track (optional)")


def test_docs_give_the_tip_for_the_dhl_key_application():
    section = _section(SERVICES, "DHL-API-Key anlegen")
    assert "eigenen Sendungen verfolgen" in section
    assert "Dafür ist die Tracking-API gedacht" in section


def test_docs_pass_on_which_mail_providers_dhl_accepts():
    section = _section(SERVICES, "Welche E-Mail-Adresse?")
    _all_have(section, (
        "von Hand geprüft",
        "Bots",
        "gmx.de und web.de",
        "Gmail",
        "hotmail.com und outlook.com",
        # two testers were refused with a gmx.de address: no promise for freemail
        "unter eigener Domain",
        "Eine Garantie gibt es bei Freemail-Adressen nicht",
    ))
    # The older, blanket warning named GMX and web.de among the refused ones.
    assert "Gmail, GMX, web.de" not in "".join(TEXTS.values())


def test_docs_say_when_dhl_shows_a_delivery_window():
    section = _section(SERVICES, "Zeitfenster")
    assert "wenn DHL eines nennt" in section
    assert "im Lauf des Tages erscheinen und wieder verschwinden" in section


def test_docs_say_automatic_asks_dhl_for_numbers_nobody_recognises():
    section = _section(PRIVACY, "Unbekannte Nummer mit DHL-Key")
    assert "„Automatisch“" in section
    assert "einmal bei DHL" in section


def test_docs_explain_the_twelve_digit_gls_number():
    gls = _section(SERVICES, "GLS")
    numbers = next(line for line in gls.splitlines() if line.startswith("- **12 Ziffern** "))
    _all_have(numbers, (
        "so steht die Nummer in den GLS-Mails und im Link zur Sendungsverfolgung",
        "Die letzte Ziffer ist eine Prüfziffer",
        "funktionieren mit der Carrier-Wahl „GLS“ und beim Import der GLS-Mails",
        "mit den ersten 11 Ziffern",
    ))
    assert "gelten nie automatisch als GLS" not in "".join(TEXTS.values())
    mails = _tab(MAIL, "GLS")
    assert "Prüfziffer als zwölfte Ziffer" in mails and "`gls-group.eu/track/…`" in mails


def test_docs_explain_the_one_time_gls_question_of_automatisch():
    gls = _section(SERVICES, "GLS")
    numbers = next(
        line for line in gls.splitlines() if line.startswith("- **12 Ziffern mit „Automatisch“:**")
    )
    _all_have(numbers, (
        "fragt die Nummer einmal mit allen 12 Ziffern bei GLS an",
        "nur mit der richtigen Prüfziffer",
        "Bei einem Treffer wird sie ein GLS-Paket",
        "Mit DHL-Key wird zuerst DHL gefragt",
        "GLS wird für dieses Paket nicht noch einmal gefragt",
        "höchstens drei Versuche",
        "eBay-Artikelnummern",
    ))
    # What v0.3.19 said no longer holds.
    everything = "".join(TEXTS.values())
    assert "erkennt eine 12-stellige Nummer nicht als GLS" not in everything
    assert "Trag die ersten 11 Ziffern ein oder wähle „GLS“" not in everything


def test_privacy_page_says_twelve_digits_may_go_to_gls_once():
    section = _section(PRIVACY, "Die eine Ausnahme: 12 Ziffern mit „Automatisch“")
    _all_have(section, (
        "Eine 12-stellige Nummer, die du mit „Automatisch“ einträgst",
        "Mit DHL-Key geht sie zuerst an DHL",
        "**einmal an GLS**",
        "alle 12 Ziffern, ohne PLZ",
        "Nummern aus Mails und Shop-Bestellungen gehen auf diesem Weg nie an GLS",
    ))


# ----- Österreich: was die Mails bedeuten -----
def test_docs_say_what_is_read_from_austria():
    section = _section(SERVICES, AUSTRIA)
    _all_have(section, (
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
    ))
    assert "versteht weiter nur deutsche Mails" not in "".join(TEXTS.values())


def test_docs_say_what_a_dpd_austria_mail_means():
    section = _section(SERVICES, AUSTRIA)
    _all_have(section, (
        "„zugestellt“, „abgestellt“",
        "am gewünschten Abstellort bzw. Wunschort „hinterlegt“",
        "Pickup Paketshop",
        "„Abholbereit“",
        "an DPD übergeben",
        "im Depot",
        "setzt keinen Status",
        "„beim Nachbarn abgegeben“",
        "„umgeleitet“ reicht nicht",
    ))


def test_docs_say_one_gls_mail_may_create_several_parcels():
    assert "für jede Nummer ein eigenes Paket" in _section(SERVICES, AUSTRIA)


# ----- DHL-Mails -----
def test_docs_say_dhl_mails_name_the_shop():
    section = _tab(MAIL, "DHL")
    assert "„Ihre Beispiel GmbH Sendung ist unterwegs“" in section
    assert "Rechtsform" in section and "nie der Name einer Privatperson" in section


def test_docs_say_where_a_company_name_ends_and_that_carriers_never_name_a_parcel():
    dhl = _tab(MAIL, "DHL")
    gls = _tab(MAIL, "GLS")
    for section in (dhl, gls):
        assert "endet an der Rechtsform" in section
    assert "Anzeigename eines Paketdienstes" in dhl and "„DHL Paketankündigung“" in dhl
    privacy = _section(PRIVACY, "Was aus Mails übernommen wird – und was nie")
    assert "der Name eines Shops oder einer Firma – nur bis zur Rechtsform" in privacy
    assert "nie der Anzeigename eines Paketdienstes" in privacy
    taken = _section(MAIL, "Was aus den Mails übernommen wird")
    assert "den Namen eines Shops oder einer Firma (nur bis zur Rechtsform" in taken
    assert "nie den Anzeigenamen eines Paketdienstes" in taken


def test_docs_say_which_dhl_subjects_set_a_status():
    section = _section(SERVICES, NO_KEY)
    _all_have(section, (
        "nur aus dem Betreff",
        "„ist unterwegs“",
        "„kommt heute“",
        "„wurde zugestellt“",
        "Zustellfoto",
        "Packstation",
        "Abholcodes liest der Import nie",
    ))


def test_docs_name_the_further_dhl_subjects():
    section = _section(SERVICES, NO_KEY)
    _all_have(section, (
        "„kommt morgen“",
        "„wird heute zugestellt“",
        "„wurde an den gewünschten Ablageort zugestellt“",
        "„Abholbereit“",
        "Fragezeichen",
        "nie einen Status zurück",
    ))


def test_docs_list_the_dhl_senders_and_the_domain_rule():
    senders = _section(MAIL, "Filterregel anlegen")
    for address in (
        "noreply@dhl.de",
        "paketankuendigung@dhl.de",
        "zustellung@dhl.de",
        "sendungsupdate@dhl.de",  # v0.3.22 (issue 11)
        "abholung@dhl.de",  # the pickup mail
    ):
        assert f"`{address}`" in senders
        assert f'"{address}"' in senders  # the Sieve example
    assert "Regel auf die ganze Domain `dhl.de`" in senders
    no_key = _section(SERVICES, NO_KEY)
    assert (
        "`noreply@dhl.de`, `paketankuendigung@dhl.de`, `zustellung@dhl.de`,"
        " `sendungsupdate@dhl.de` und `abholung@dhl.de`"
    ) in no_key
    mails = _tab(MAIL, "DHL")
    assert "12 Ziffern" in mails and "„Ihre Sendungsnummer“" in mails


def test_docs_say_which_stored_carrier_names_are_replaced():
    section = _tab(MAIL, "DHL")
    _all_have(section, (
        "Wörtern einer Benachrichtigung",
        "„DPD Versandinfo“",
        "auch „Hermes“, „DHL Express“ oder „Paket“",
    ))


def test_docs_sieve_example_names_every_listed_sender():
    """v0.3.15: three more senders (GLS and DPD Austria)."""
    sieve = TEXTS[MAIL].split("```sieve")[1].split("```")[0]
    for address in SENDERS:
        assert f'"{address}"' in sieve, address


def test_docs_match_the_senders_the_parsers_know():
    from custom_components.parcel_tracker.mail.dpd import DPD_AT_SENDER
    from custom_components.parcel_tracker.mail.gls import GLS_GROUP_SENDER, GLS_RTT_SENDER

    for address in (DPD_AT_SENDER, GLS_GROUP_SENDER, GLS_RTT_SENDER):
        assert address in SENDERS


def test_docs_explain_the_dpd_announcement():
    section = _tab(MAIL, "DPD")
    _all_have(section, (
        "„Bald ist Ihr DPD Paket da“",
        "`noreply@service.dpd.de`",
        "nie eine Privatperson",
        "„Ihre Sendung stellen wir in 1-2 Werktagen zu“",
        "Montag bis Samstag",
        "ab dem Tag der Mail",
    ))
    assert "den Versender und eine Lieferschätzung" in _section(SERVICES, "DPD")
    privacy = _section(PRIVACY, "Was aus Mails übernommen wird – und was nie")
    assert "Versender in der Ankündigung von DPD" in privacy


def test_privacy_page_covers_the_ups_shipper_and_seller_names():
    privacy = _section(PRIVACY, "Was aus Mails übernommen wird – und was nie")
    assert "Absenderzeile „Von:“ einer UPS-Mail" in privacy
    assert "nur „Amazon“ bzw. „eBay“" in privacy


# ----- Von Hand weiterleiten, HTTP -----
def test_docs_say_how_a_forward_by_hand_is_recognised():
    section = _section(MAIL, "Von Hand weiterleiten")
    _all_have(section, (
        "Der Import erkennt eine Weiterleitung wie die Original-Mail",
        "der ursprüngliche Absender",
        "„Von: … / Gesendet: … / An: … / Betreff: …“",
        "Alle gängigen Mailprogramme",
        "Outlook, Apple Mail, Gmail, Thunderbird",
        "„Als Anhang weiterleiten“ funktioniert",
        "ab dem Datum der Original-Mail",
        "zählt der Zeitpunkt der Weiterleitung",
        "liest er nie mit",
        "Am zuverlässigsten bleibt die automatische Filterregel",
        "Wenn der Block fehlt oder der Absender unbekannt ist",
    ))


def test_docs_explain_the_mail_endpoint():
    section = _section(MAIL, "Ohne Postfach: Mail per HTTP übergeben")
    _all_have(section, (
        "**langlebiges Zugriffstoken**",
        "`/api/parcel_tracker/import_mail`",
        'curl -H "Authorization: Bearer <Token>" --data-binary @mail.eml',
        "| `recognized` |",
        "| `unrecognized` |",
        "| `ignored` |",
        "| `stale` |",
        "| `duplicate` |",
        "| 401 |",
        "| 400 |",
        "| 415 |",
        "| 413 |",
        "| 503 |",
        "Warum gibt es dafür keinen Dienst?",
        "Recorder-Datenbank",
    ))


# ----- Bestellungen: Zusammenführen, Abschließen -----
def test_docs_say_when_a_carrier_mail_joins_a_shop_order():
    section = _section(MAIL, MERGE)
    _all_have(section, (
        "Nennt die Carrier-Mail statt des Shops die Marke",
        "genau eines offenen",
        "beginnt",
        "Das Carrier-Paket gibt es schon als eigenes Paket",
        # second review: Amazon only, and under which conditions
        "nur zu einem offenen **Amazon-Paket**",
        "nie zu einem eBay-Paket",
        "keinen anderen Versanddienstleister nennt",
        "muss das Paket schon „Versendet“ sein",
        "ein Wort ab 5 Buchstaben oder mehrere Wörter",
        "bekannte Shops (IKEA",
        "aus einem nur bestellten Paket nie ein zugestelltes",
    ))
    assert "Amazon- oder eBay-Paket ohne Sendungsnummer nur dann" not in section


def test_docs_explain_the_later_merge_of_a_delivered_carrier_parcel():
    merge = _section(MAIL, MERGE)
    assert "führt die Integration nicht nachträglich zusammen" not in merge
    assert "von Hand entfernen" not in merge
    _all_have(merge, (
        "Wird ein Carrier-Paket zugestellt",
        "nach denselben Regeln",
        "genau ein",
        "von Hand eingetragen",
        "nur einmal",
    ))


def test_docs_explain_orders_closed_without_a_delivery_mail():
    section = _section(MAIL, "Bestellungen ohne Zustellmail")
    _all_have(section, (
        "Abgeschlossen ohne Zustellbestätigung",
        "mehr als 3 volle Tage",
        "14 Tage",
        "`assumed_delivered`",
        "keine Benachrichtigung",
        "`sensor.pakete_zugestellt_heute`",
        "Sendungsnummer",
        "Das gilt für Amazon, eBay, AliExpress und Eventim",
    ))
    assert "| `assumed_delivered` |" in _section(SENSORS, "Attribute")
    assert "Abgeschlossen (ohne Zustellbestätigung)" in _section(CARD, "Die Schilder oben rechts")


def test_status_page_has_no_line_about_merging_existing_doubles():
    assert "Doppel" not in TEXTS[STATUS]
    assert "| Bestellungen ohne Zustellmail (Amazon, eBay, AliExpress, Eventim) |" in TEXTS[STATUS]


def test_docs_explain_aliexpress_and_apples_relay():
    section = _tab(MAIL, "AliExpress")
    _all_have(section, (
        "`ALI` + Bestellnummer",
        "Den Namen des Händlers übernimmt die Integration nie",
        "„Im Zielland angekommen“",
        "Es zählt deshalb nicht als heute",
        "„Voraussichtliche Zustellzeit“",
        "Ist es eine DHL- oder Hermes-Nummer, übernimmt die Bestellung sie",
        "Es entsteht kein zweites Paket",
        "(z. B. `AP…`) lässt sich bei keinem Paketdienst abfragen",
        "sie werden gelesen, nie aufgerufen",
        "„Lieferung bestätigt (laut AliExpress)“",
        "„Your order … is closed“",
        "3 Tage nach dem letzten Liefertag, ohne Liefertag nach 14 Tagen",
    ))
    relay = _section(MAIL, "Apple „E-Mail-Adresse verbergen“")
    assert "@privaterelay.appleid.com" in relay
    assert "`…@deals.aliexpress.com`" in _section(MAIL, "Was mit den Mails im Postfach passiert")
    unconfirmed = _section(STATUS, "Umgesetzt, aber noch nicht bestätigt")
    assert "| AliExpress-Mails (" in unconfirmed and "„E-Mail-Adresse verbergen“" in unconfirmed


def test_docs_match_the_aliexpress_code():
    from custom_components.parcel_tracker import const
    from custom_components.parcel_tracker.mail.aliexpress import (
        ALIEXPRESS_MARKETING_DOMAIN,
        ALIEXPRESS_SENDER,
        CONFIRMED_TEXT,
        PARCEL_NAME,
        order_number,
    )
    from custom_components.parcel_tracker.mail.base import RELAY_DOMAIN

    page = TEXTS[MAIL]
    assert ALIEXPRESS_SENDER in SENDERS
    assert f"…@{ALIEXPRESS_MARKETING_DOMAIN}" in page and f"@{RELAY_DOMAIN}" in page
    assert f"sensor.paket_{order_number('9999999999990000').lower()}" in page
    assert f"„{PARCEL_NAME}“" in page and f"„{CONFIRMED_TEXT}“" in page
    assert (const.ORDER_OVERDUE_DAYS, const.ORDER_NO_ETA_DAYS) == (3, 14)


# ----- Sensoren -----
def test_docs_explain_the_pickup_sensor_and_its_attributes():
    today = _section(SENSORS, TODAY)
    _all_have(today, (
        "`awaiting_pickup`",
        "`awaiting_pickup_count`",
        "Packstation, Filiale, PaketShop",
        "{{ state_attr('sensor.pakete_heute', 'awaiting_pickup_count') }}",
    ))
    counters = _section(SENSORS, "Die vier Zählsensoren")
    assert "`sensor.pakete_abholbereit`" in counters
    assert "Vier weitere Sensoren" in counters
    assert "Drei weitere Sensoren" not in "".join(TEXTS.values())


# ----- Namen ausblenden -----
def test_docs_explain_hide_names():
    section = _section(PRIVACY, "Namen ausblenden")
    _all_have(section, (
        "Schalter **Namen ausblenden** (Standard: aus)",
        "`DHL-Paket …2557`",
        "`Amazon-Bestellung …4321`",
        "`eBay-Bestellung …0001`",
        "`Paket …2557`",
        "| Karte |",
        "| Sensoren |",
        "`parcels`, `possible`, `delivered_today` und `awaiting_pickup`",
        "| Kalender |",
        "| Event | das Feld `name` von `parcel_tracker_status_changed`",
        "Blueprint",
        "| Benachrichtigungen | z. B. `✅ DHL-Paket …2557 wurde zugestellt` |",
        "### Selbst eingetippte Namen bleiben sichtbar",
        "`parcel_tracker.rename_parcel`",
        "vor v0.3.24 vergeben",
        "### Die gespeicherten Daten bleiben",
        "[Zusammenführen](mail-import.md#zusammenfuhren-carrier-mail-und-bestellung)",
        "sofort zurück",
        "Ein Neustart von Home Assistant ist nicht nötig",
        "Die Entitäts-IDs (`sensor.paket_<nummer>`) entstehen aus der Nummer",
        "Der Diagnose-Download enthielt noch nie Namen",
        "### Grenzen",
        "Der Verlauf von Home Assistant",
    ))


def test_docs_name_hide_names_where_notifications_are_explained():
    texts = _section(NOTIFY, "So sehen die Texte aus")
    assert "Mit [Namen ausblenden](datenschutz.md#namen-ausblenden) steht dort" in texts


# ----- v0.3.33: filing folders below INBOX, a community setup for an own mailbox -----
def test_docs_say_where_the_filing_folders_go_and_what_happens_when_it_fails():
    section = _section(MAIL, "Was mit den Mails im Postfach passiert")
    _all_have(section, [
        "`INBOX.Paket-Tracker-Verarbeitet`",
        "Seit v0.3.33 fragt der Import den Server",
        "Hast du die Ordner selbst im Mailprogramm angelegt",
        "je Ordner einmal eine Warnung im Protokoll",
        "im Abschnitt `filing`",
    ])
    assert "liegen immer auf der obersten Ebene" not in TEXTS[MAIL]
    _all_have(_section(SENSORS, "Diagnose"), ["`filing`", "MOVE und UIDPLUS", "NAMESPACE"])


def test_docs_carry_the_community_mailbox_setup_with_credit_and_our_notes():
    section = _section(MAIL, "Beispiel aus der Community: dovecot und imapfilter im Container")
    _all_have(section, [
        "Beitrag von Hanutawii ([Issue #26](https://github.com/SoerenKaiser99/parcel_tracker/issues/26))",
        "von uns getestet ist er nicht",
        "imapfilter (alle 5 Min)",
        "**Voraussetzungen:**",
        "**Einrichtung:**",
        "**Stolperfallen, auf die er gestoßen ist:**",
        "`options.starttls = false`",
        "Port 143",
        "`listen = *`",
        "Port 993 mit „Verschlüsselt, Zertifikat nicht prüfen“",
        "Modus 600",
        '??? example "paket-postfach-setup.sh"',
        "    #!/usr/bin/env bash",
        "    systemctl enable --now paket-mail.timer >/dev/null",
    ])
    assert len(re.findall(r"^\d\. ", section, re.M)) == 4


# ----- v0.3.34: number line on the card, DHL history without HTML, docs of the release ----
HELPING = "mithelfen.md"
RECIPES = "rezepte.md"


def test_docs_explain_the_number_line_of_the_card():
    section = _section(CARD, "Paket aufklappen")
    _all_have(section, [
        "**Sendungsnummer, Bestellnummer**",
        "„Sendungsnummer: …“",
        "„Bestellnummer: …“",
        "`999-9999999-9999999`",
        "markiert sie ganz",
        "[Namen ausblenden](datenschutz.md#namen-ausblenden)",
        "Die Option blendet nur Namen aus",
        "auch wenn der Paketdienst einen Link mitschickt (seit v0.3.34)",
    ])


def test_recipe_eleven_subtracts_the_parcels_waiting_for_pickup():
    section = _section(RECIPES, "11. Unterwegs ohne Abholbereite")
    _all_have(section, [
        '=== "Als Helfer (ohne YAML)"',
        '=== "In der configuration.yaml"',
        "{{ [states('sensor.pakete_unterwegs') | int(0) - states('sensor.pakete_abholbereit')"
        " | int(0), 0] | max }}",
        "{{ has_value('sensor.pakete_unterwegs') and has_value('sensor.pakete_abholbereit') }}",
        "**Maßeinheit**: `Pakete`, **Zustandsklasse**: „Messung“",
        "**Verfügbarkeitstemplate**",
        "Abholbereite zählen bei `sensor.pakete_unterwegs` und bei `sensor.pakete_abholbereit` mit",
        "`sensor.unterwegs_ohne_abholbereite`",
    ])
    yaml_block = section.split("```yaml\n", 1)[1].split("```", 1)[0]
    sensor = yaml.safe_load(textwrap.dedent(yaml_block))["template"][0]["sensor"][0]
    assert sensor["state_class"] == "measurement"
    assert sensor["unit_of_measurement"] == "Pakete"
    assert "has_value('sensor.pakete_unterwegs')" in sensor["availability"]
    assert "has_value('sensor.pakete_abholbereit')" in sensor["availability"]
    assert "| max" in sensor["state"]
    assert TEXTS[RECIPES].startswith("# Rezepte\n\nElf fertige Beispiele zum Kopieren.")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "**Rezepte**: elf Beispiele für Automationen und Karten" in readme
    assert "zehn Beispiele" not in readme and "Zehn fertige" not in TEXTS[RECIPES]


def test_community_setup_names_the_harmless_message_before_the_first_filed_mail():
    section = _section(MAIL, "Beispiel aus der Community: dovecot und imapfilter im Container")
    pitfalls = section.split("**Stolperfallen, auf die er gestoßen ist:**")[1].split(
        "Nützlich:")[0]
    _all_have(pitfalls, [
        "`NO [NONEXISTENT] Mailbox doesn't exist: Paket-Tracker-Verarbeitet`",
        "harmlos",
        "`doveadm mailbox create -u pakete Paket-Tracker-Verarbeitet`",
    ])
    # The script itself is unchanged: the folder is not created there.
    script = section.split('??? example "paket-postfach-setup.sh"')[1]
    assert "doveadm mailbox create" not in script


def test_helping_page_is_at_this_version():
    text = TEXTS[HELPING]
    assert "*Stand: 20. Oktober 2026, Version 0.3.40." in text
    _all_have(text, [
        # v0.3.38 (contributions by benep)
        "**DHL Express („DHL On Demand Delivery“)**",
        "**AliExpress: Mails der letzten Meile**",
        "**Amazon: „Sendung verfolgen“ führt zu Amazon**",
        "**Symbole hinter den Nummern**",
        "am Handy gut treffen",
        "**DHL mit API-Key: Verlauf ohne HTML**",
        "**DPD: die Mails nach der Ankündigung**",
        "**eBay: „Update zur Bestellung“ und „Zustellversuch“**",
        "**Hermes: „Deine Sendung kommt heute.“ und neuer Zustelltermin**",
        "**Nicht erkannte Mails erneut einlesen**",
        "**Sendungs- und Bestellnummer im aufgeklappten Paket**",
    ])
    # Sample mails PR #24 brought (fixtures 161-163, 167, 170, 173; 106 for eBay's
    # delivery) are no longer asked for; the rest of each row stays.
    missing = _section(HELPING, "2. Beispielmails: Diese fehlen uns")
    assert "**DPD Deutschland**" not in missing and "**eBay**" not in missing
    assert "Zustellversuch" not in missing and "Lieferung verspätet" not in missing
    _all_have(missing, [
        "| **Hermes** | im PaketShop abholbereit |",
        "| **Amazon** | Mails von Amazon in Österreich |",
        "**DPD Österreich**", "**DHL**", "**GLS**", "**UPS**", "**AliExpress**",
        "**Eventim**", "**Österreichische Post, Schweizer Post**", "**DHL Express**",
    ])
    # Confirmed by users: no longer asked for, listed as confirmed instead.
    assert "**Eigener Ordner im Postfach**" not in text
    assert "**Ablage-Ordner bei Postfächern mit INBOX-Präfix**" not in text
    confirmed = _section(STATUS, "Von Testern bestätigt")
    _all_have(confirmed, [
        "Eigener Ordner im Postfach", "Ablage-Ordner bei Postfächern mit INBOX-Präfix",
    ])


# ----- v0.3.35: eBay "PAKET ZUGESTELLT", DPD Austria's window, anonymiser address blocks ----
def test_helping_page_asks_to_confirm_the_v0335_mails():
    text = TEXTS[HELPING]
    _all_have(text, [
        "**eBay: „Paket zugestellt“**",
        "**DPD Österreich: „Ihr DPD Paket kommt zwischen … Uhr“**",
        "[Issue #31](https://github.com/SoerenKaiser99/parcel_tracker/issues/31)",
        "[Issue #32](https://github.com/SoerenKaiser99/parcel_tracker/issues/32)",
    ])
    missing = _section(HELPING, "2. Beispielmails: Diese fehlen uns")
    assert "Zustelltag oder Zeitfenster" not in missing
    assert (
        "| **DPD Österreich** | laufende Sendung mit Zustelltag, aber ohne Zeitfenster;" in missing
    )


def test_docs_explain_dpd_austrias_window_and_ebays_parcel_delivered():
    services = (ROOT / "docs" / "dienste.md").read_text(encoding="utf-8")
    mail = TEXTS[MAIL]
    assert "„Ihr DPD Paket kommt zwischen 13:00 und 14:00 Uhr“ setzt „In Zustellung“" in services
    assert "„Ihr DPD Paket kommt zwischen 13:00 und 14:00 Uhr“ setzt „In Zustellung“" in mail
    assert "„PAKET ZUGESTELLT“ (seit v0.3.35" in mail
    assert "den Verkäufer übernimmt der Import nie" in mail
    assert "Die Wörter zählen überall im Betreff" in mail and "„[EXTERN]“" in mail
    assert "in jeder Schreibweise) setzen" not in mail
    helping = (ROOT / "docs" / "hilfe.md").read_text(encoding="utf-8")
    assert "österreichischer oder Schweizer Postleitzahl (vier Ziffern)" in helping
    assert "„an folgende Adresse zugestellt:“ (seit v0.3.35)" in helping


# ----- v0.3.36: Amazon's pickup mail ("Paket zur Abholung bereit", issue #33) -----
def test_docs_explain_amazons_pickup_mail():
    amazon = _tab(MAIL, "Amazon")
    _all_have(amazon, [
        "„Paket zur Abholung bereit: …“ von `pickup-point@amazon.de` (seit v0.3.36)",
        "„Abholbereit“",
        "ohne die interne Nummer des Shops („HPS#…“), Postleitzahl und Ort",
        "`pickup_point`",
        "`pickup_until`",
        "nie nach dem Preis",
    ])
    senders = _section(MAIL, "Filterregel anlegen")
    assert "| `pickup-point@amazon.de` | Amazon (Paket liegt zur Abholung bereit" in senders
    privacy = _section(PRIVACY, "Was aus Mails übernommen wird – und was nie")
    assert "Name und Straße der Abholstelle (ohne Postleitzahl, Ort" in privacy


def test_helping_page_asks_to_confirm_amazons_pickup_mail():
    text = TEXTS[HELPING]
    _all_have(text, [
        "**Amazon: „Paket zur Abholung bereit“**",
        "[Issue #33](https://github.com/SoerenKaiser99/parcel_tracker/issues/33)",
    ])
    missing = _section(HELPING, "2. Beispielmails: Diese fehlen uns")
    assert "pickup-point@amazon.de" not in missing


def test_the_anonymiser_keeps_the_pickup_sender_in_fixture_mode():
    script = (ROOT / "scripts" / "anonymize_mail.py").read_text(encoding="utf-8")
    keep = script.split("KEEP = {")[1].split("}")[0]
    assert '"pickup-point@amazon.de"' in keep


def test_docs_say_the_notification_names_the_pickup_mails_place():
    notify = TEXTS[NOTIFY]
    assert "Ort der Filiale und letzter Abholtag stehen nur da, wenn der Paketdienst" not in notify
    assert "Abholort und letzter Abholtag stehen da, wenn der Paketdienst oder" in notify
    amazon = _tab(MAIL, "Amazon")
    assert "„… – Hermes PaketShop - Beispielkiosk Muster… bis 24.10.“" in amazon


def test_community_setup_says_its_sender_list_is_not_complete():
    section = _section(MAIL, "Beispiel aus der Community: dovecot und imapfilter im Container")
    notes = section.split("**Drei Hinweise von uns:**")[1]
    _all_have(notes, [
        "nicht jeden Absender, den Paket Tracker liest",
        "`pickup-point@amazon.de`",
        "`/etc/imapfilter/config.lua`",
        "[Filterregel anlegen](#filterregel-anlegen)",
    ])
    # The script itself is unchanged.
    script = section.split('??? example "paket-postfach-setup.sh"')[1]
    assert "pickup-point@amazon.de" not in script


# ----- v0.3.37: DHL mails with an S10 number of another country (issue #34) -----
def test_docs_say_dhl_mails_carry_numbers_of_other_countries():
    services = TEXTS[SERVICES]
    international = services.split("**DHL international:**")[1].split("\n\n")[0]
    _all_have(international, [
        "(seit v0.3.37)",
        "`LE…BE`",
        "`LW…NL`",
        "mit dem DHL-API-Key",
        "nicht als DHL",
    ])
    dhl = _tab(MAIL, "DHL")
    _all_have(dhl, [
        "Nummern aus anderen Ländern (z. B. `…BE`, `…NL`, seit v0.3.37)",
        "mit dem DHL-Key bei DHL ab",
    ])


def test_helping_page_asks_to_confirm_dhl_numbers_of_other_countries():
    text = TEXTS[HELPING]
    _all_have(text, [
        "**DHL: Sendungsnummern aus anderen Ländern**",
        "[Issue #34](https://github.com/SoerenKaiser99/parcel_tracker/issues/34)",
    ])


# ----- v0.3.40: Geschenkmodus, Storniert, mail interval up to 1440 -----
def test_docs_explain_the_gift_mode_and_its_limits():
    privacy = _section(PRIVACY, "Geschenkmodus")
    _all_have(privacy, [
        "Wähle zuerst, wer Geschenke sehen darf",
        "kann den Modus über die Oberfläche **niemand** mehr ausschalten",
        "nur eine Automation",
        "**eigenen Benutzer**",
        "`switch.paket_tracker_geschenkmodus`",
        "Konfigurations-Entität",
        "Assist, Alexa oder Google",
        "als Besitzer des Kontos",
        "Einmal Geschenk, immer Geschenk",
        "schon aufgezeichnet hat, bleibt dort",
        "Admins",
        "Wer das Paket-Postfach lesen kann, liest alles.",
    ])
    card = _section(CARD, "Geschenkmodus")
    _all_have(card, [
        "Auch die N offenen Pakete verbergen?",
        "weder zugestellt noch storniert",
        "eigenen Benutzer in Home Assistant",
        "Nicht mehr verbergen",
    ])


def test_docs_describe_the_gift_entities_and_the_automation():
    sensors = TEXTS[SENSORS]
    _all_have(sensors, [
        "| `gift` |",
        "## `switch.paket_tracker_geschenkmodus`",
        "weder zugestellt noch storniert",
    ])
    automations = _section(AUTOMATIONS, "Geschenkmodus per Automation schalten")
    _all_have(automations, [
        "switch.turn_on",
        "switch.turn_off",
        "15. November",
        "27. Dezember",
        "parcel_tracker.set_gift",
    ])
    # The date check sits inside the actions: "Aktionen ausführen" skips conditions.
    parsed = yaml.safe_load(automations.split("```yaml\n")[1].split("```")[0])["automation"]
    assert len(parsed) == 2
    for item in parsed:
        assert "conditions" not in item
        assert item["actions"][0]["condition"] == "template"
    _all_have(automations, ["Jeder Benutzer kann eine Automation starten", "automation.trigger"])
    privacy = _section(PRIVACY, "Geschenkmodus")
    _all_have(privacy, ["Anzeigename der Entität", "`calendar.pakete`", "bevor du bestellst"])
    assert "zeichnet der Recorder den Namen eines Pakets nicht mehr auf" not in privacy
    assert "auch bei einem Intervall von mehr als 60 Minuten" in TEXTS[MAIL]


def test_docs_say_the_mail_interval_reaches_1440_minutes():
    assert "1–1440 Minuten, Standard 5" in TEXTS[MAIL]
    assert "1–1440 (bis zu einmal am Tag), Standard: 5." in TEXTS[MAIL]
    assert "1–60" not in TEXTS[MAIL]


def test_roadmap_names_the_person_assignment_and_the_dhl_sender():
    status = TEXTS[STATUS]
    _all_have(status, [
        "**Personen zuordnen, Benachrichtigung nur an den Besteller**",
        "issues/39",
        "Geschenkmodus (v0.3.40)",
    ])
    open_items = _section(STATUS, "Offen")
    rows = [line for line in open_items.splitlines() if line.startswith("| ")]
    assert "Personen zuordnen" in rows[1]  # the first item, right below the header
    assert rows[-1].startswith("| **Absender aus der DHL-Abfrage**")


def test_helping_page_asks_to_confirm_the_v0340_changes():
    text = TEXTS[HELPING]
    _all_have(text, [
        "**Geschenkmodus: Karte**",
        "**Geschenkmodus: Schalter**",
        "**Geschenkmodus: wer darf ausschalten**",
        "**Geschenkmodus: Sprachassistent**",
        "**Storniert (Bestellung vom Shop abgebrochen)**",
        "[PR #23](https://github.com/SoerenKaiser99/parcel_tracker/pull/23)",
        "**Mail-Abfrage bis 1440 Minuten**",
    ])


# ----- CHANGELOG.md -----
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def _version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in tag.lstrip("v").split("."))


def test_changelog_starts_with_the_feature_section():
    assert CHANGELOG.startswith("# Änderungen am Paket Tracker\n")
    headings = re.findall(r"^## (.+)$", CHANGELOG, re.M)
    assert headings == ["Was die Integration kann", "Versionen"]
    features = CHANGELOG.split("## Was die Integration kann\n")[1].split("\n## ")[0]
    assert 20 <= len(re.findall(r"^- ", features, re.M)) <= 30
    _all_have(features, ["Geschenkmodus", "DHL", "Hermes", "GLS", "17track", "Eventim"])


def test_changelog_has_a_section_for_every_release_newest_first():
    import subprocess

    tags = subprocess.run(
        ["git", "tag", "--list", "v0.*"], cwd=ROOT, capture_output=True, encoding="utf-8",
        check=True,
    ).stdout.split()
    assert tags, "the repository has no release tags"
    versions = re.findall(r"^### (v\d+\.\d+\.\d+)(?: \(([^)]+)\))?$", CHANGELOG, re.M)
    listed = [version for version, _ in versions]
    assert "v0.3.40" in listed
    assert set(tags) <= set(listed)
    assert len(listed) == len(set(listed))
    assert listed == sorted(listed, key=_version_key, reverse=True)
    for version, date in versions:
        pattern = r"\d{2}\.\d{2}\.\d{4}" if version == "v0.3.40" else r"\d{4}-\d{2}-\d{2}"
        assert re.fullmatch(pattern, date), version


def test_readme_links_the_changelog():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "(https://github.com/SoerenKaiser99/parcel_tracker/blob/main/CHANGELOG.md)" in readme

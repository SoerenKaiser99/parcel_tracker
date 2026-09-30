# Paket Tracker

Home-Assistant-Integration, die Pakete von DHL und DPD verfolgt und Amazon- und UPS-Pakete aus E-Mails übernimmt: eigene Sensoren, ein Sammelsensor für "heute", ein Lieferkalender, ein Status-Event und eine eigene Dashboard-Karte.

## Was es kann

- **DHL**: Abfrage über die offizielle API "Shipment Tracking – Unified". Der API-Key ist optional; ohne Key zeigt ein DHL-Paket den Status "DHL-API-Key fehlt". Mit Key und hinterlegter PLZ liefert DHL zusätzliche Details (z. B. Standort).
- **DPD**: Abfrage über die öffentliche DPD-Sendungsverfolgung, nur mit der Sendungsnummer. DPD liefert Status und die fünf Meilenstein-Termine, aber keinen Standort und kein Zeitfenster. Die detailliertere DPD-Seite braucht eine Postleitzahl und ist durch ein Captcha geschützt, deshalb nutzt die Integration sie nicht.
- **E-Mail-Import** (optional): Liest ein eigenes Paket-Postfach per IMAP und legt Pakete aus Amazon-, DHL- und UPS-Mails automatisch an (siehe [E-Mail-Import](#e-mail-import)).
- **Karte**: `custom:parcel-tracker-card`, direkt von der Integration ausgeliefert, erscheint im Karten-Auswahldialog als "Paket Tracker". Pakete lassen sich dort hinzufügen, umbenennen und entfernen.
- **Sensoren**: `sensor.paket_<nummer>` pro Paket (Zustand = Status, mit Attributen wie Carrier, ETA, Standort, Abholpunkt, Zustellzeitpunkt `delivered_at`, Verlauf) sowie `sensor.pakete_heute` für die Anzahl der heute erwarteten Pakete.
- **Kalender**: `calendar.pakete` zeigt die erwarteten Zustelltermine.
- **Event**: `parcel_tracker_status_changed` feuert bei jedem Statuswechsel eines Pakets.
- **Dienste**: `parcel_tracker.add_parcel`, `remove_parcel`, `rename_parcel`, `refresh`.

Was (noch) nicht geht: Hermes und 17track (für genauere DPD-Daten) folgen in einer späteren Version. Amazon- und UPS-Pakete kennt die Integration nur aus Mails; eine Abfrage beim Carrier gibt es für sie nicht.

## Installation

1. HACS öffnen → Menü (⋮) → **Benutzerdefinierte Repositories**.
2. Repository `https://github.com/SoerenKaiser99/parcel_tracker` eintragen, Kategorie **Integration** wählen.
3. Paket Tracker installieren.
4. Home Assistant neu starten.
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → "Paket Tracker" suchen und einrichten.

### Einrichtungsfelder

- **DHL-API-Key** (optional): Wird beim Speichern geprüft. Leer lassen, wenn nur DPD genutzt wird oder der Key später ergänzt werden soll.
- **PLZ** (optional, z. B. 10115): Lässt DHL zusätzliche Details liefern.
- **Zugestellte Pakete ausblenden nach (Tagen)** (Standard: 3, Bereich 1–30): Nach dieser Zeit verschwindet ein zugestelltes Paket aus der Übersicht.

Alle drei Felder lassen sich später über **Konfigurieren** an der Integration ändern. Wird das Key-Feld beim Ändern leer gelassen, bleibt der vorhandene Key erhalten.

## DHL-API-Key anlegen

1. Auf [developer.dhl.com](https://developer.dhl.com) ein Konto anlegen oder anmelden.
2. Zu **Meine Apps** wechseln und eine neue App anlegen.
3. Als API **"Shipment Tracking – Unified"** auswählen (nicht "Parcel DE …").
4. Als Environment **"Production (Europe)"** wählen.
5. Nur der **API Key** wird gebraucht, das Secret nicht.
6. Die Freischaltung dauert bis zu 24 Stunden.

## E-Mail-Import

Amazon liefert viele Pakete selbst aus und bietet dafür keine öffentliche Sendungsverfolgung. Der E-Mail-Import liest deshalb die Versandmails: Bestellt, Versendet, In Zustellung, Zugestellt – samt Liefertag und Zeitfenster.

> **Wichtig: Nur ein eigenes Paket-Postfach eintragen, nie das Hauptpostfach.**
> Das IMAP-Passwort gibt Vollzugriff auf das Postfach. Leg bei deinem Mailanbieter ein zusätzliches Postfach an (z. B. `pakete@…`), das ausschließlich Paketmails bekommt, und trag nur dieses ein.

### Einrichten

1. Paket-Postfach anlegen (z. B. bei mailbox.org).
2. Im Hauptpostfach eine Filterregel anlegen, die Paketmails an das Paket-Postfach weiterleitet (siehe unten).
3. In Home Assistant: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → E-Mail-Import**:
   - **IMAP-Server** (Standard `imap.mailbox.org`, Port 993 mit SSL),
   - **Benutzername** und **Passwort** des Paket-Postfachs (Benutzername leer lassen schaltet den Import aus; ein leeres Passwortfeld behält das gespeicherte Passwort),
   - **Verarbeitete Mails in Ordner verschieben** (Standard: an),
   - **Zustell-Codes (Einmalpasswörter) mitlesen** (Standard: aus).
4. Speichern prüft die Anmeldung sofort.

Der Import schaut alle 5 Minuten nach ungelesenen Mails im Posteingang. Ist das Postfach nicht erreichbar, wartet er länger (5 → 10 → 20 → 40 → 60 Minuten). Lehnt der Server die Anmeldung ab, erscheint unter **Einstellungen → Reparaturen** ein Hinweis.

### Welche Absender

Diese Absender in die Filterregel aufnehmen:

- `bestellbestaetigung@amazon.de`
- `versandbestaetigung@amazon.de`
- `shipment-tracking@amazon.de`
- `order-update@amazon.de`
- `noreply@dhl.de`
- `noreply@service.dpd.de`
- `pkginfo@ups.com`

Beispiel als Sieve-Regel (z. B. mailbox.org → Einstellungen → Filter → Sieve), die eine Kopie ins Paket-Postfach schickt:

```sieve
require ["copy"];
if address :is "from" [
  "bestellbestaetigung@amazon.de", "versandbestaetigung@amazon.de",
  "shipment-tracking@amazon.de", "order-update@amazon.de",
  "noreply@dhl.de", "noreply@service.dpd.de", "pkginfo@ups.com"
] {
  redirect :copy "pakete@example.org";
}
```

In Gmail, Outlook & Co. heißt das „Filter" bzw. „Regel": Bedingung „Absender ist …", Aktion „Weiterleiten an pakete@…".

### Von Hand weiterleiten

Statt einer Filterregel lassen sich einzelne Mails auch von Hand an das Paket-Postfach weiterleiten. Amazon-Mails erkennt der Import auch weitergeleitet (Betreff mit „WG:" oder „Fwd:"). „Heute" und „morgen" rechnet er dann ab dem Zeitpunkt der Weiterleitung – leite also am selben Tag weiter. Aus allen anderen Mails übernimmt er nur eindeutige Sendungsnummern (DHL `00340…` und `JJD…`, UPS `1Z…`; DPD-Nummern nur, wenn „DPD" in der Mail steht und die Nummer direkt nach „Paketnummer", „Sendungsnummer" o. Ä. folgt, oder die Mail direkt von DPD kommt). Solche Pakete tragen keinen Namen aus dem Absender, sondern heißen „<Carrier> <Nummer>" – umbenennen geht auf der Karte. Mails, die älter als 14 Tage sind, markiert der Import nur als gelesen.

### Was mit den Mails passiert

- Erkannte Mails landen im Ordner `Paket-Tracker-Verarbeitet`, nicht erkannte im Ordner `Paket-Tracker-Nicht-erkannt`. Beide Ordner legt der Import bei Bedarf an. Mit ausgeschalteter Option bleiben die Mails im Posteingang und werden nur als gelesen markiert.
- Werbung und Konto-Mails von Amazon (`promotion…@amazon.de`, `no-reply@amazon.de`, `account-update@amazon.de`, `rueckgabe@amazon.de`, `no-reply@primevideo.com`) markiert der Import nur als gelesen.
- Jede Mail zählt nur einmal (erkannt an ihrer Message-ID).
- Erkennt der Import fünf Amazon-Mails in Folge nicht, erscheint ein Reparatur-Hinweis – meist hat Amazon dann das Mail-Format geändert.

### Amazon-Pakete

- Pro Bestellung entsteht ein Paket mit der Nummer `AMZ` + Bestellnummer (z. B. `sensor.paket_amz99991565342587125`), benannt nach dem Artikel. Kommt eine Bestellung in mehreren Sendungen, heißt das nächste Paket „… (2)".
- Der Status geht nur vorwärts: Eine ältere Mail setzt ein Paket nie zurück.
- Kündigt DHL eine „Amazon Sendung" an und passt genau ein offenes Amazon-Paket dazu (gleicher Liefertag), übernimmt das Amazon-Paket die DHL-Nummer und fragt ab dann DHL ab. Ist die Zuordnung nicht eindeutig, entsteht ein eigenes Paket „Amazon-Sendung (DHL)".

### Zustell-Code (Einmalpasswort)

Manche Amazon-Lieferungen gibt der Fahrer nur gegen einen Code heraus. Mit eingeschalteter Option liest der Import den Code aus der Mail. Die Karte zeigt ihn verdeckt: erst „Code anzeigen", dann die Rückfrage „Zustell-Code anzeigen?". Beim Zuklappen verschwindet er wieder. Der Code steht im Attribut `delivery_code`, wird nie gespeichert, landet nie im Verlauf (Recorder) und verfällt nach dem Liefertag. Verdeckt ist er nur auf der Karte: Wer Zugriff auf die Entitäts-Attribute oder die API von Home Assistant hat (Entwicklerwerkzeuge, Automationen, andere Dashboards, Apps), kann ihn im Klartext lesen.

## Karte hinzufügen

Dashboard bearbeiten → Karte hinzufügen → "Paket Tracker" auswählen. Alternativ per YAML:

```yaml
type: custom:parcel-tracker-card
```

Die Integration kopiert die Karte beim Start nach `www/parcel_tracker/` und trägt sie automatisch als Dashboard-Ressource ein (`/local/parcel_tracker/parcel-tracker-card.js`). Falls der Ordner `www` vorher nicht existierte, wird die Karte zunächst direkt von der Integration ausgeliefert; ein weiterer Neustart von Home Assistant aktiviert dann den `/local`-Pfad.

## Beispiel-Automation

Benachrichtigung, sobald ein Paket in Zustellung geht:

```yaml
triggers:
  - trigger: event
    event_type: parcel_tracker_status_changed
    event_data:
      new_status: out_for_delivery
actions:
  - action: notify.notify
    data:
      title: "Paket kommt heute"
      message: "{{ trigger.event.data.name or trigger.event.data.number }} ({{ trigger.event.data.carrier | upper }}) ist in Zustellung."
```

## Datenschutz

Sendungsnummern gehen nur an den jeweiligen Carrier (DHL bzw. DPD). Die PLZ geht ausschließlich an DHL.

Aus Mails übernimmt der Import nur Bestellnummer, einen auf 60 Zeichen gekürzten Artikeltitel, Status, Liefertag und Zeitfenster sowie – nur mit eingeschalteter Option und nur im Arbeitsspeicher – den Zustell-Code. Adresse, Name, Preise und Mail-Inhalte landen weder in Attributen noch im Log. Das IMAP-Passwort liegt wie der DHL-Key in der Konfiguration von Home Assistant.

## Markenhinweis

DHL, DPD, UPS und Amazon sind Marken ihrer Inhaber. Die Logos (Simple Icons, CC0) dienen nur zur Kennzeichnung des Carriers. Dieses Projekt ist nicht mit den Unternehmen verbunden.

---

## English summary

Paket Tracker is a Home Assistant custom integration that tracks parcels from DHL and DPD. DHL uses the official "Shipment Tracking – Unified" API (an API key is optional; without one, DHL parcels show a "key missing" status), while DPD uses DPD's public tracking page with only the tracking number, which yields status and the five milestone dates but no location or delivery window. The integration creates one sensor per parcel (`sensor.paket_<number>`), a summary sensor for today's expected parcels, a delivery calendar, and fires a `parcel_tracker_status_changed` event on every status change. It ships its own Lovelace card (`custom:parcel-tracker-card`, listed as "Paket Tracker" in the card picker) for adding, renaming, and removing parcels. Install it through HACS as a custom repository, then set up an optional DHL API key, a postcode, and how long delivered parcels stay visible. An optional mail import reads a dedicated parcel mailbox via IMAP (never enter your main mailbox: the IMAP password grants full access) and creates parcels from Amazon, DHL and UPS mails, including Amazon's own deliveries; a DHL "Amazon Sendung" mail is merged into the matching Amazon order when unambiguous. Delivery one-time codes are read only when enabled, shown on the card after a tap and a confirmation (hidden only on the card: anyone with access to the entity attributes or the Home Assistant API can read it), never stored and never recorded. Support for Hermes and 17track is planned for later versions. Tracking numbers are sent only to the matching carrier, and the postcode is sent only to DHL.

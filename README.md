# Paket Tracker

Home-Assistant-Integration, die Pakete von DHL und DPD verfolgt: eigene Sensoren, ein Sammelsensor für "heute", ein Lieferkalender, ein Status-Event und eine eigene Dashboard-Karte.

## Was es kann

- **DHL**: Abfrage über die offizielle API "Shipment Tracking – Unified". Der API-Key ist optional; ohne Key zeigt ein DHL-Paket den Status "DHL-API-Key fehlt". Mit Key und hinterlegter PLZ liefert DHL zusätzliche Details (z. B. Standort).
- **DPD**: Abfrage über die öffentliche DPD-Sendungsverfolgung, nur mit der Sendungsnummer. DPD liefert Status und die fünf Meilenstein-Termine, aber keinen Standort und kein Zeitfenster. Die detailliertere DPD-Seite braucht eine Postleitzahl und ist durch ein Captcha geschützt, deshalb nutzt die Integration sie nicht.
- **Karte**: `custom:parcel-tracker-card`, direkt von der Integration ausgeliefert, erscheint im Karten-Auswahldialog als "Paket Tracker". Pakete lassen sich dort hinzufügen, umbenennen und entfernen.
- **Sensoren**: `sensor.paket_<nummer>` pro Paket (Zustand = Status, mit Attributen wie Carrier, ETA, Standort, Abholpunkt, Zustellzeitpunkt `delivered_at`, Verlauf) sowie `sensor.pakete_heute` für die Anzahl der heute erwarteten Pakete.
- **Kalender**: `calendar.pakete` zeigt die erwarteten Zustelltermine.
- **Event**: `parcel_tracker_status_changed` feuert bei jedem Statuswechsel eines Pakets.
- **Dienste**: `parcel_tracker.add_parcel`, `remove_parcel`, `rename_parcel`, `refresh`.

Was (noch) nicht geht: Hermes und 17track (für genauere DPD-Daten) folgen in einer späteren Version, Amazon später über Konto-Login.

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

## Markenhinweis

DHL und DPD sind Marken ihrer Inhaber. Die Logos (Simple Icons, CC0) dienen nur zur Kennzeichnung des Carriers. Dieses Projekt ist nicht mit den Unternehmen verbunden.

---

## English summary

Paket Tracker is a Home Assistant custom integration that tracks parcels from DHL and DPD. DHL uses the official "Shipment Tracking – Unified" API (an API key is optional; without one, DHL parcels show a "key missing" status), while DPD uses DPD's public tracking page with only the tracking number, which yields status and the five milestone dates but no location or delivery window. The integration creates one sensor per parcel (`sensor.paket_<number>`), a summary sensor for today's expected parcels, a delivery calendar, and fires a `parcel_tracker_status_changed` event on every status change. It ships its own Lovelace card (`custom:parcel-tracker-card`, listed as "Paket Tracker" in the card picker) for adding, renaming, and removing parcels. Install it through HACS as a custom repository, then set up an optional DHL API key, a postcode, and how long delivered parcels stay visible. Support for Hermes, 17track, and Amazon is planned for later versions. Tracking numbers are sent only to the matching carrier, and the postcode is sent only to DHL.

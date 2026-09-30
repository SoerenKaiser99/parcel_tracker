# Paket Tracker

Home-Assistant-Integration, die Pakete von DHL, DPD, Hermes und (optional) UPS verfolgt und Amazon-, eBay-, Hermes- und UPS-Pakete aus E-Mails übernimmt: eigene Sensoren, ein Sammelsensor für "heute", ein Lieferkalender, ein Status-Event und eine eigene Dashboard-Karte.

## Was es kann

- **DHL**: Abfrage über die offizielle API "Shipment Tracking – Unified". Der API-Key ist optional; ohne Key zeigt ein DHL-Paket den Status "DHL-API-Key fehlt". Mit Key und hinterlegter PLZ liefert DHL zusätzliche Details (z. B. Standort).
- **DPD**: Abfrage über die öffentliche DPD-Sendungsverfolgung, nur mit der Sendungsnummer. DPD liefert Status und die fünf Meilenstein-Termine, aber keinen Standort und kein Zeitfenster. Die detailliertere DPD-Seite braucht eine Postleitzahl und ist durch ein Captcha geschützt, deshalb nutzt die Integration sie nicht.
- **Hermes**: Abfrage über die öffentliche Hermes-Sendungsverfolgung, nur mit der Sendungsnummer (`H…` mit 19 Ziffern oder 14 Ziffern), ohne Zugangsdaten und ohne PLZ. Hermes liefert Status und Verlauf, aber keinen Liefertag – den übernimmt die Integration aus den Hermes-Mails.
- **UPS**: Status aus den UPS-Mails; mit eigener Client-ID und eigenem Secret zusätzlich Live-Status über die offizielle UPS Track API, mit Monatsbudget (siehe [UPS-Live-Status](#ups-live-status-optional)).
- **E-Mail-Import** (optional): Liest ein eigenes Paket-Postfach per IMAP und legt Pakete aus Amazon-, eBay-, DHL-, Hermes- und UPS-Mails automatisch an (siehe [E-Mail-Import](#e-mail-import)).
- **Karte**: `custom:parcel-tracker-card`, direkt von der Integration ausgeliefert, erscheint im Karten-Auswahldialog als "Paket Tracker". Pakete lassen sich dort hinzufügen, umbenennen und entfernen.
- **Sensoren**: `sensor.paket_<nummer>` pro Paket (Zustand = Status, mit Attributen wie Carrier, ETA, Standort, Abholpunkt, Zustellzeitpunkt `delivered_at`, Verlauf) sowie `sensor.pakete_heute` für die Anzahl der heute erwarteten Pakete.
- **Kalender**: `calendar.pakete` zeigt die erwarteten Zustelltermine.
- **Event**: `parcel_tracker_status_changed` feuert bei jedem Statuswechsel eines Pakets.
- **Dienste**: `parcel_tracker.add_parcel`, `remove_parcel`, `rename_parcel`, `refresh`.

Was (noch) nicht geht: siehe [Roadmap & Status](#roadmap--status). Amazon- und eBay-Bestellungen kennt die Integration nur aus Mails; abgefragt wird dort nur die Sendungsnummer des Carriers, sobald eine Mail sie verrät.

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

## UPS-Live-Status (optional)

Ohne Zugangsdaten kommen UPS-Pakete nur aus den UPS-Mails. Mit einer eigenen UPS-App fragt die Integration zusätzlich die offizielle UPS Track API ab – auch für von Hand eingetragene `1Z…`-Nummern.

1. Auf [developer.ups.com](https://developer.ups.com) ein Konto anlegen oder anmelden.
2. Eine App anlegen und als Produkt **Tracking** wählen (nicht „Track Alert“).
3. Warten, bis UPS die App freischaltet – solange steht sie auf „Pending“.
4. **Client-ID** und **Client-Secret** nur in Home Assistant eintragen: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → UPS-Live-Status**. Speichern holt testweise einen Token (zählt nicht aufs Budget). Ein leeres Secret-Feld behält das gespeicherte Secret, eine leere Client-ID schaltet die UPS-API aus.

**Monatsbudget** (Standard 100, Bereich 0–10000): So viele UPS-Abfragen macht die Integration höchstens pro Kalendermonat, damit nie Kosten entstehen. Token-Abrufe zählen nicht, jede Sendungsabfrage zählt – auch die über „Aktualisieren“. Ist das Budget verbraucht, kommen UPS-Pakete bis Monatsende nur aus Mails, und unter **Einstellungen → Reparaturen** erscheint ein Hinweis, der am Monatsanfang von selbst verschwindet. 0 schaltet die API aus.

Die UPS-API wird sparsam gefragt: beim Anlegen einmal, danach alle 4 Stunden, am Zustelltag („In Zustellung“) alle 30 Minuten, nach der Zustellung nie mehr; nachts (22–6 Uhr) höchstens stündlich. Lehnt UPS die Zugangsdaten ab, erscheint ebenfalls ein Reparatur-Hinweis.

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
   - **Zustell-Codes (Einmalpasswörter) mitlesen** (Standard: aus),
   - **Postfach abfragen alle (Minuten)** (1–60, Standard: 5).
4. Speichern prüft die Anmeldung sofort.

Der Import schaut im eingestellten Intervall (1–60 Minuten, Standard 5) nach ungelesenen Mails im Posteingang. Der Dienst `parcel_tracker.refresh` (auf der Karte „Aktualisieren“) fragt zusätzlich das Postfach sofort ab. Ist das Postfach nicht erreichbar, wartet der Import unabhängig vom Intervall länger (5 → 10 → 20 → 40 → 60 Minuten). Lehnt der Server die Anmeldung ab, erscheint unter **Einstellungen → Reparaturen** ein Hinweis.

### Welche Absender

Diese Absender in die Filterregel aufnehmen:

- `bestellbestaetigung@amazon.de`
- `versandbestaetigung@amazon.de`
- `shipment-tracking@amazon.de`
- `order-update@amazon.de`
- `noreply@dhl.de`
- `noreply@service.dpd.de`
- `pkginfo@ups.com`
- `noreply@paketankuendigung.myhermes.de`
- `ebay@ebay.com`

Beispiel als Sieve-Regel (z. B. mailbox.org → Einstellungen → Filter → Sieve), die eine Kopie ins Paket-Postfach schickt:

```sieve
require ["copy"];
if address :is "from" [
  "bestellbestaetigung@amazon.de", "versandbestaetigung@amazon.de",
  "shipment-tracking@amazon.de", "order-update@amazon.de",
  "noreply@dhl.de", "noreply@service.dpd.de", "pkginfo@ups.com",
  "noreply@paketankuendigung.myhermes.de", "ebay@ebay.com"
] {
  redirect :copy "pakete@example.org";
}
```

In Gmail, Outlook & Co. heißt das „Filter" bzw. „Regel": Bedingung „Absender ist …", Aktion „Weiterleiten an pakete@…".

### Von Hand weiterleiten

Statt einer Filterregel lassen sich einzelne Mails auch von Hand an das Paket-Postfach weiterleiten. Amazon-Mails erkennt der Import auch weitergeleitet (Betreff mit „WG:" oder „Fwd:"). „Heute" und „morgen" rechnet er dann ab dem Zeitpunkt der Weiterleitung – leite also am selben Tag weiter. Aus allen anderen Mails übernimmt er nur eindeutige Sendungsnummern (DHL `00340…` und `JJD…`, UPS `1Z…`, Hermes `H…`; DPD-Nummern nur, wenn „DPD" in der Mail steht und die Nummer direkt nach „Paketnummer", „Sendungsnummer" o. Ä. folgt, oder die Mail direkt von DPD kommt). Solche Pakete tragen keinen Namen aus dem Absender, sondern heißen „<Carrier> <Nummer>" – umbenennen geht auf der Karte. Mails, die älter als 14 Tage sind, markiert der Import nur als gelesen.

### Was mit den Mails passiert

- Erkannte Mails landen im Ordner `Paket-Tracker-Verarbeitet`, nicht erkannte im Ordner `Paket-Tracker-Nicht-erkannt`. Beide Ordner legt der Import bei Bedarf an. Mit ausgeschalteter Option bleiben die Mails im Posteingang und werden nur als gelesen markiert.
- Werbung und Konto-Mails von Amazon (`promotion…@amazon.de`, `no-reply@amazon.de`, `account-update@amazon.de`, `rueckgabe@amazon.de`, `no-reply@primevideo.com`) markiert der Import nur als gelesen.
- Jede Mail zählt nur einmal (erkannt an ihrer Message-ID).
- Erkennt der Import fünf Amazon-Mails in Folge nicht, erscheint ein Reparatur-Hinweis – meist hat Amazon dann das Mail-Format geändert.

### Amazon-Pakete

- Pro Bestellung entsteht ein Paket mit der Nummer `AMZ` + Bestellnummer (z. B. `sensor.paket_amz99991565342587125`), benannt nach dem Artikel. Kommt eine Bestellung in mehreren Sendungen, heißt das nächste Paket „… (2)".
- Der Status geht nur vorwärts: Eine ältere Mail setzt ein Paket nie zurück.
- Kündigt DHL eine „Amazon Sendung" an und passt genau ein offenes Amazon-Paket dazu (gleicher Liefertag), übernimmt das Amazon-Paket die DHL-Nummer und fragt ab dann DHL ab. Ist die Zuordnung nicht eindeutig, entsteht ein eigenes Paket „Amazon-Sendung (DHL)".

### eBay-Pakete

- Pro eBay-Bestellung entsteht ein Paket mit der Nummer `EBAY` + Bestellnummer (z. B. `sensor.paket_ebay990000000001`), benannt nach dem Artikel. eBay-Mails enthalten keine Sendungsnummer; die 12-stelligen Artikelnummern werden nie als Sendungsnummer gelesen.
- „Ihre Sendung ist jetzt beim Versanddienstleister!“ setzt „Versendet“ samt Lieferzeitraum („Lieferung ca.: Mi, 28. Jan - Do, 29. Jan“), „BESTELLUNG ZUGESTELLT“ setzt „Zugestellt“. Andere eBay-Mails landen in „Nicht erkannt“.
- Nennt die Mail den Versanddienstleister, zeigt die Karte ihn an („eBay · Versendet · via Hermes“, Attribut `shipping_carrier_hint`).

### Hermes-Pakete

- „Information zur Zustellung an den gebuchten WunschAblageort“ (die Sendung wurde gerade angekündigt) setzt „Angekündigt“, „Ihre Hermes Sendung ist auf dem Weg“ setzt „Unterwegs“ samt Liefertag und Zeitfenster, „… wurde an deinen WunschAblageort zugestellt“ setzt „Zugestellt“. Mails über einen gescheiterten Zustellversuch („… konnte nicht zugestellt werden“, „nicht zugestellt“, „Zustellversuch“) setzen keinen Status; den liefert dann die Hermes-Abfrage. Der Shop aus der Mail wird nur dann zum Namen, wenn es ein bekannter Shop ist (z. B. Amazon, eBay, Otto, Zalando) und das Paket noch keinen Namen hat – Namen privater Absender übernimmt die Integration nie.
- Den Text des Wunsch-Ablageorts übernimmt die Integration nie – weder in Attribute noch ins Log.
- Alte Amazon-Versandmails mit Hermes-Nummer hängen die Nummer an das Amazon-Paket; ab dann fragt es Hermes ab.

### Zusammenführen

Eine Carrier-Mail (DHL „Amazon Sendung“, Hermes, UPS) gehört zu **genau einem** offenen Amazon- oder eBay-Paket ohne Sendungsnummer, wenn die Mail den Shop nennt (Amazon, eBay) oder die Shop-Mail diesen Versanddienstleister genannt hat, und der Liefertag passt (gleicher Tag oder innerhalb des Lieferzeitraums; ohne Tag: genau ein Paket unterwegs). Das Shop-Paket übernimmt dann die Sendungsnummer und fragt ab da den Carrier ab (Attribute `tracking_ref` und `tracking_carrier`). Passt es nicht eindeutig, entsteht ein eigenes Paket.

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

Sendungsnummern gehen nur an den jeweiligen Carrier (DHL, DPD, Hermes bzw. – mit eigenen Zugangsdaten – UPS). Die PLZ geht ausschließlich an DHL.

Aus Mails übernimmt der Import nur Bestellnummer, einen auf 60 Zeichen gekürzten Artikeltitel, Status, Liefertag und Zeitfenster, den Versanddienstleister sowie – nur mit eingeschalteter Option und nur im Arbeitsspeicher – den Zustell-Code. Adresse, Name, eBay-Käufer- und Verkäufernamen, Wunsch-Ablageort, Preise und Mail-Inhalte landen weder in Attributen noch im Log. Das IMAP-Passwort und die UPS-Zugangsdaten liegen wie der DHL-Key in der Konfiguration von Home Assistant.

## Markenhinweis

DHL, DPD, Hermes, UPS, Amazon und eBay sind Marken ihrer Inhaber. Die Logos (Simple Icons, CC0) dienen nur zur Kennzeichnung des Carriers; Hermes erscheint als blauer Punkt mit „H“. Dieses Projekt ist nicht mit den Unternehmen verbunden.

## Roadmap & Status

- DHL (offizielle API): umgesetzt
- DPD (öffentliche Sendungsverfolgung): umgesetzt
- E-Mail-Import Amazon, DHL, UPS: umgesetzt
- Hermes Live-Abfrage: umgesetzt; mit einer aktuellen Sendung noch nicht live getestet
- Hermes-Mails: umgesetzt
- eBay-Mails: umgesetzt
- UPS Live-Status (offizielle API): umgesetzt, noch nicht mit echten Zugangsdaten getestet (UPS-Freischaltung ausstehend)
- 17track für DPD-Orte: geplant
- Amazon per Konto-Anmeldung: verworfen zugunsten des Mail-Imports

---

## English summary

Paket Tracker is a Home Assistant custom integration that tracks parcels from DHL, DPD, Hermes and, optionally, UPS. DHL uses the official "Shipment Tracking – Unified" API (an API key is optional; without one, DHL parcels show a "key missing" status), while DPD uses DPD's public tracking page with only the tracking number, which yields status and the five milestone dates but no location or delivery window. The integration creates one sensor per parcel (`sensor.paket_<number>`), a summary sensor for today's expected parcels, a delivery calendar, and fires a `parcel_tracker_status_changed` event on every status change. It ships its own Lovelace card (`custom:parcel-tracker-card`, listed as "Paket Tracker" in the card picker) for adding, renaming, and removing parcels. Install it through HACS as a custom repository, then set up an optional DHL API key, a postcode, and how long delivered parcels stay visible. An optional mail import reads a dedicated parcel mailbox via IMAP (never enter your main mailbox: the IMAP password grants full access) and creates parcels from Amazon, DHL and UPS mails, including Amazon's own deliveries; a DHL "Amazon Sendung" mail is merged into the matching Amazon order when unambiguous. Delivery one-time codes are read only when enabled, shown on the card after a tap and a confirmation (hidden only on the card: anyone with access to the entity attributes or the Home Assistant API can read it), never stored and never recorded. Hermes uses the keyless public tracking endpoint (number only). UPS status comes from UPS mails and, with your own Client ID and Secret from developer.ups.com (product "Tracking"), from the official UPS Track API, capped by a monthly request budget (default 100) so it never costs money. The mail import also reads Hermes and eBay mails (one parcel per eBay order, never using eBay item numbers as tracking numbers) and merges a carrier mail into exactly one matching open Amazon or eBay order. Roadmap & Status: the UPS API is implemented but not yet tested with real credentials (UPS approval pending), the Hermes live lookup is implemented but not yet tested with a current parcel, 17track for DPD locations is planned, and an Amazon account login was dropped in favour of the mail import. Tracking numbers are sent only to the matching carrier, and the postcode is sent only to DHL.

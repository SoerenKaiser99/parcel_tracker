# Paket Tracker

Home-Assistant-Integration, die Pakete von DHL, DPD, GLS, Hermes und (optional) UPS verfolgt, auf Wunsch über 17track ergänzt oder weitere Carrier verfolgt und Amazon-, eBay-, GLS-, Hermes- und UPS-Pakete aus E-Mails übernimmt: eigene Sensoren, ein Sammelsensor für "heute", ein Lieferkalender, ein Status-Event, Benachrichtigungen aufs Handy und eine eigene Dashboard-Karte.

**Für Deutschland gebaut:** Die Integration ist für Deutschland gebaut (deutsche Carrier und deutsche Mail-Formate). Im Ausland funktionieren schon DHL (offizielle API, weltweit), UPS (offizielle API) und jeder Carrier über 17track; der Mail-Import versteht nur deutsche Mails (amazon.de sowie deutsche DHL-, Hermes-, UPS-, GLS- und eBay-Mails).

<p>
  <img src="https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/docs/images/karte-hell.png" width="260" alt="Die Paket-Tracker-Karte im hellen Design: zehn Pakete von DHL, DPD, GLS, Hermes, UPS, Amazon, eBay und 17track mit Status, Fortschrittsbalken und Liefertermin">
  <img src="https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/docs/images/karte-detail.png" width="260" alt="Die Karte mit einem aufgeklappten DHL-Paket: Verlauf der Sendung und die Knöpfe „Details über 17track holen“, „Umbenennen“ und „Löschen“">
  <img src="https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/docs/images/karte-dunkel.png" width="260" alt="Die Paket-Tracker-Karte im dunklen Design">
</p>

Die Bilder zeigen erfundene Pakete: Namen, Orte und Sendungsnummern sind ausgedacht. Sie stammen aus der Demo-Seite [`docs/demo/`](docs/demo/index.html), die die echte Karte ohne Home Assistant im Browser zeigt (Repository-Ordner mit `python3 -m http.server` ausliefern und `docs/demo/index.html` öffnen; `?theme=dark` für das dunkle Design, `?open=1` klappt das erste Paket auf).

## Warum?

Ich war es leid, ständig in verschiedenen Apps Zustelltage und -zeiten zu checken. Ich wollte in Home Assistant an einer Stelle sehen: „Kommt heute ein Paket, und wann?“ – für alle Carrier zusammen, statt in fünf Apps und einem Stapel Mails zu suchen.

- **Pakete erscheinen von selbst**: Die Integration liest die Versandmails und legt die Pakete an – auch Amazons eigene Lieferungen, für die es keine öffentliche Sendungsverfolgung gibt.
- **Benachrichtigung aufs Handy**: sobald ein Paket in Zustellung geht oder zugestellt ist – ohne eigene Automation.
- **Für Automationen gemacht**: Status-Event, Kalender mit den Lieferterminen, Sensor „Pakete heute“ und ein Blueprint für eigene Benachrichtigungen.
- **Lokal und datensparsam**: kein Cloud-Konto, kein fremder Tracking-Dienst nötig; die Zugangsdaten bleiben in Home Assistant, gelesen wird nur ein eigenes Paket-Postfach.
- **Offen**: Open Source, gebaut für deutsche Carrier.

## Was es kann

- **DHL**: Abfrage über die offizielle API "Shipment Tracking – Unified". Der API-Key ist optional; ohne Key zeigt ein DHL-Paket den Status "DHL-API-Key fehlt". Mit Key und hinterlegter PLZ liefert DHL zusätzliche Details (z. B. Standort).
- **DPD**: Abfrage über die öffentliche DPD-Sendungsverfolgung, nur mit der Sendungsnummer. DPD liefert Status und die fünf Meilenstein-Termine, aber keinen Standort und kein Zeitfenster. Die detailliertere DPD-Seite braucht eine Postleitzahl und ist durch ein Captcha geschützt, deshalb nutzt die Integration sie nicht.
- **GLS**: Abfrage über die offene Sendungsverfolgung der GLS-Webseite, nur mit der Paketnummer (11 Ziffern), ohne Zugangsdaten. Mit hinterlegter PLZ liefert GLS zusätzlich den Verlauf. Die Abfrage ist kein offizieller Zugang und kann wegfallen – dann bleiben die GLS-Mails und 17track (siehe [GLS](#gls)).
- **Hermes**: Abfrage über die öffentliche Hermes-Sendungsverfolgung, nur mit der Sendungsnummer (`H…` mit 19 Ziffern oder 14 Ziffern), ohne Zugangsdaten und ohne PLZ. Hermes liefert Status und Verlauf, aber keinen Liefertag – den übernimmt die Integration aus den Hermes-Mails.
- **UPS**: Status aus den UPS-Mails; mit eigener Client-ID und eigenem Secret zusätzlich Live-Status über die offizielle UPS Track API, mit Monatsbudget (siehe [UPS-Live-Status](#ups-live-status-optional)).
- **17track** (optional): Auf Knopfdruck ergänzt 17track Ort, Zeitfenster und Verlauf; „Andere (über 17track)“ verfolgt Carrier ohne eigene Anbindung, z. B. FedEx (siehe [17track](#17track-optional)).
- **E-Mail-Import** (optional): Liest ein eigenes Paket-Postfach per IMAP und legt Pakete aus Amazon-, eBay-, DHL-, GLS-, Hermes- und UPS-Mails automatisch an (siehe [E-Mail-Import](#e-mail-import)).
- **Karte**: `custom:parcel-tracker-card`, direkt von der Integration ausgeliefert, erscheint im Karten-Auswahldialog als "Paket Tracker". Pakete lassen sich dort hinzufügen, umbenennen und entfernen.
- **Sensoren**: `sensor.paket_<nummer>` pro Paket (Zustand = Status, mit Attributen wie Carrier, `carrier_name`, ETA, Standort, `location_source`, Abholpunkt, Zustellzeitpunkt `delivered_at`, Verlauf, `track17`, `track17_carrier`), `sensor.pakete_heute` für die Anzahl der heute erwarteten Pakete und – mit 17track-Key – `sensor.paket_tracker_17track_kontingent` für die verbleibenden 17track-Nummern.
- **Kalender**: `calendar.pakete` zeigt die erwarteten Zustelltermine.
- **Event**: `parcel_tracker_status_changed` feuert bei jedem Statuswechsel eines Pakets.
- **Benachrichtigungen** (optional): Bei „in Zustellung“, „zugestellt“, „abholbereit“ oder einem Problem geht eine Benachrichtigung an die gewählten Ziele, ohne eigene Automation; für eigene Texte und Bedingungen gibt es einen Blueprint (siehe [Benachrichtigungen](#benachrichtigungen)).
- **Dienste**: `parcel_tracker.add_parcel`, `remove_parcel`, `rename_parcel`, `refresh`, `track_17track`.

Was (noch) nicht geht: siehe [Roadmap & Status](#roadmap--status). Amazon- und eBay-Bestellungen kennt die Integration nur aus Mails; abgefragt wird dort nur die Sendungsnummer des Carriers, sobald eine Mail sie verrät.

## Installation

1. HACS öffnen → Menü (⋮) → **Benutzerdefinierte Repositories**.
2. Repository `https://github.com/SoerenKaiser99/parcel_tracker` eintragen, Kategorie **Integration** wählen.
3. Paket Tracker installieren.
4. Home Assistant neu starten.
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → "Paket Tracker" suchen und einrichten.

### Einrichtungsfelder

- **DHL-API-Key** (optional): Wird beim Speichern geprüft. Leer lassen, wenn nur DPD genutzt wird oder der Key später ergänzt werden soll.
- **PLZ** (optional, z. B. 10115): Lässt DHL zusätzliche Details und GLS den Verlauf liefern.
- **Zugestellte Pakete ausblenden nach (Tagen)** (Standard: 3, Bereich 1–30): Nach dieser Zeit verschwindet ein zugestelltes Paket aus der Übersicht.

Alle drei Felder lassen sich später über **Konfigurieren** an der Integration ändern. Wird das Key-Feld beim Ändern leer gelassen, bleibt der vorhandene Key erhalten.

## DHL-API-Key anlegen

1. Auf [developer.dhl.com](https://developer.dhl.com) ein Konto anlegen oder anmelden.
2. Zu **Meine Apps** wechseln und eine neue App anlegen.
3. Als API **"Shipment Tracking – Unified"** auswählen (nicht "Parcel DE …").
4. Als Environment **"Production (Europe)"** wählen.
5. Nur der **API Key** wird gebraucht, das Secret nicht.
6. Die Freischaltung dauert bis zu 24 Stunden.

## GLS

GLS-Pakete fragt die Integration über die offene Sendungsverfolgung von gls-group.com ab – ohne Zugangsdaten und ohne Anmeldung.

- **Nummern**: 11 Ziffern erkennt „Automatisch“ als GLS. 12-stellige Nummern gelten nie automatisch als GLS (so sehen eBay-Artikelnummern aus). Die achtstelligen Track-IDs aus Buchstaben und Ziffern trägst du mit der Carrier-Wahl „GLS“ ein.
- **PLZ**: Ist in den Einstellungen eine PLZ hinterlegt, schickt die Integration sie mit, und GLS liefert zusätzlich den Verlauf (bis zu 20 Ereignisse). Ohne PLZ – oder wenn die PLZ nicht zur Sendung passt – gibt es nur den Status.
- **Liefertag**: Nennt die Abfrage keinen eindeutigen Tag, bleiben Liefertag und Zeitfenster aus der GLS-Mail erhalten.
- **Abfragen**: höchstens alle 30 Minuten, nachts (22–6 Uhr) stündlich, nach der Zustellung nie mehr.
- **Kein offizieller Zugang**: Die offene Abfrage ist keine dokumentierte API. GLS kann sie jederzeit ändern oder schließen; nach 24 Stunden ohne Antwort erscheint ein Hinweis unter **Einstellungen → Reparaturen**. GLS-Pakete kommen dann weiter aus den GLS-Mails, und „Details über 17track holen“ ergänzt Status und Verlauf über 17track.

## UPS-Live-Status (optional)

Ohne Zugangsdaten kommen UPS-Pakete nur aus den UPS-Mails. Mit einer eigenen UPS-App fragt die Integration zusätzlich die offizielle UPS Track API ab – auch für von Hand eingetragene `1Z…`-Nummern.

1. Auf [developer.ups.com](https://developer.ups.com) ein Konto anlegen oder anmelden.
2. Eine App anlegen und als Produkt **Tracking** wählen (nicht „Track Alert“).
3. Warten, bis UPS die App freischaltet – solange steht sie auf „Pending“.
4. **Client-ID** und **Client-Secret** nur in Home Assistant eintragen: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → UPS-Live-Status**. Speichern holt testweise einen Token (zählt nicht aufs Budget). Leere Felder für Client-ID und Secret behalten die gespeicherten Werte. Ausschalten geht nur über den Schalter **UPS-API aktiv**: Ausgeschaltet gespeichert, entfernt er Client-ID und Secret.

**Monatsbudget** (Standard 100, Bereich 0–10000): So viele UPS-Abfragen macht die Integration höchstens pro Kalendermonat, damit nie Kosten entstehen. Token-Abrufe zählen nicht, jede Sendungsabfrage zählt – auch die über „Aktualisieren“. Ist das Budget verbraucht, kommen UPS-Pakete bis Monatsende nur aus Mails, und unter **Einstellungen → Reparaturen** erscheint ein Hinweis, der am Monatsanfang von selbst verschwindet. 0 schaltet die API aus.

Die UPS-API wird sparsam gefragt: beim Anlegen einmal, danach alle 4 Stunden, am Zustelltag („In Zustellung“) alle 30 Minuten, nach der Zustellung nie mehr; nachts (22–6 Uhr) höchstens stündlich. Lehnt UPS die Zugangsdaten ab, erscheint ebenfalls ein Reparatur-Hinweis.

## 17track (optional)

17track ergänzt Pakete um Ort, Zeitfenster und Verlauf und verfolgt Carrier ohne eigene Anbindung (z. B. FedEx). Angemeldet wird nur auf ausdrücklichen Wunsch, nie automatisch.

1. Auf [api.17track.net](https://api.17track.net) ein kostenloses Konto anlegen und den API-Key kopieren.
2. Den Key nur in Home Assistant eintragen: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → 17track-API-Key**. Speichern prüft den Key über das Kontingent (verbraucht nichts). Ein leeres Feld behält den gespeicherten Key.

**Kontingent**: Das kostenlose Konto hat einmalig 200 Nummern. Jede Anmeldung einer neuen Nummer verbraucht eine, Abfragen danach sind kostenlos. Die Integration löscht Nummern bei 17track nie, denn neu anmelden würde erneut kosten. `sensor.paket_tracker_17track_kontingent` zeigt die verbleibenden Nummern (Attribute `total` und `used`) und wird beim Start, nach jeder Anmeldung und einmal täglich aktualisiert. Bei höchstens 10 übrigen Nummern und bei leerem Kontingent erscheint ein Hinweis unter **Einstellungen → Reparaturen**.

**Anmelden**: Auf der Karte im aufgeklappten Paket „Details über 17track holen“ antippen; die Rückfrage „Verbraucht 1 von … verbleibenden 17track-Nummern. Fortfahren?“ bestätigen. Für Automationen gibt es den Dienst `parcel_tracker.track_17track` (`number`). Nicht möglich bei zugestellten Paketen und bei Amazon- und eBay-Bestellungen, solange keine Sendungsnummer des Carriers bekannt ist. Angemeldet wird die Sendungsnummer des Carriers samt Carrier-Code; ist der Carrier unbekannt, erkennt 17track ihn selbst.

**Andere (über 17track)**: Für Carrier ohne eigene Anbindung in der Karte „Andere (über 17track)“ wählen (oder `add_parcel` mit `carrier: other`). Hinzufügen meldet die Nummer sofort an, mit derselben Rückfrage. Erkennt 17track den Carrier nicht, wird das Paket nicht angelegt. Status, Text, Ort und Verlauf kommen dann nur von 17track; der erkannte Carrier (z. B. FedEx) erscheint im Namen.

**Ergänzen statt ersetzen**: Bei DHL, DPD, GLS, Hermes und UPS bleibt der Carrier maßgeblich. 17track füllt nur Lücken: Ort, Liefertag und Zeitfenster sowie den Verlauf (nur wenn der Carrier keinen liefert). Liefert der Carrier gar nichts (z. B. DHL ohne API-Key, UPS ohne API-Zugang), zeigt das Paket den Status von 17track, bis der Carrier selbst antwortet. Stammt der Ort von 17track, zeigt die Karte „· Ort via 17track“ (Attribut `location_source: 17track`).

**Abfragen**: Die erste Abfrage kommt 2 Minuten nach der Anmeldung, danach alle 6 Stunden (17track aktualisiert selbst nur alle 6–12 Stunden), gebündelt zu höchstens 40 Nummern pro Aufruf. Schluss ist bei Zustellung oder wenn 17track die Sendung als abgelaufen meldet. Ist 17track nicht erreichbar, wartet die Integration länger und meldet nie neu an. Lehnt 17track den Key ab, fragt die Integration bis zum Neuladen nicht mehr ab und zeigt einen Reparatur-Hinweis.

## E-Mail-Import

Amazon liefert viele Pakete selbst aus und bietet dafür keine öffentliche Sendungsverfolgung. Der E-Mail-Import liest deshalb die Versandmails: Bestellt, Versendet, In Zustellung, Zugestellt – samt Liefertag und Zeitfenster.

> **Wichtig: Nur ein eigenes Paket-Postfach eintragen, nie das Hauptpostfach.**
> Das IMAP-Passwort gibt Vollzugriff auf das Postfach. Leg bei deinem Mailanbieter ein zusätzliches Postfach an (z. B. `pakete@…`), das ausschließlich Paketmails bekommt, und trag nur dieses ein.

### Einrichten

1. Paket-Postfach anlegen (z. B. bei mailbox.org).
2. Im Hauptpostfach eine Filterregel anlegen, die Paketmails an das Paket-Postfach weiterleitet (siehe unten).
3. In Home Assistant: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → E-Mail-Import**:
   - **IMAP-Server** (Standard `imap.mailbox.org`, Port 993 mit SSL),
   - **Benutzername** und **Passwort** des Paket-Postfachs (leere Felder behalten die gespeicherten Werte),
   - **Verarbeitete Mails in Ordner verschieben** (Standard: an),
   - **Zustell-Codes (Einmalpasswörter) mitlesen** (Standard: aus),
   - **Postfach abfragen alle (Minuten)** (1–60, Standard: 5).
4. Speichern prüft die Anmeldung sofort.

Ausschalten geht nur über den Schalter **E-Mail-Import aktiv**: Ausgeschaltet gespeichert, entfernt er Benutzername und Passwort.

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
- `no-reply@gls-pakete.de`

Beispiel als Sieve-Regel (z. B. mailbox.org → Einstellungen → Filter → Sieve), die eine Kopie ins Paket-Postfach schickt:

```sieve
require ["copy"];
if address :is "from" [
  "bestellbestaetigung@amazon.de", "versandbestaetigung@amazon.de",
  "shipment-tracking@amazon.de", "order-update@amazon.de",
  "noreply@dhl.de", "noreply@service.dpd.de", "pkginfo@ups.com",
  "noreply@paketankuendigung.myhermes.de", "ebay@ebay.com",
  "no-reply@gls-pakete.de"
] {
  redirect :copy "pakete@example.org";
}
```

In Gmail, Outlook & Co. heißt das „Filter" bzw. „Regel": Bedingung „Absender ist …", Aktion „Weiterleiten an pakete@…".

### Von Hand weiterleiten

Statt einer Filterregel lassen sich einzelne Mails auch von Hand an das Paket-Postfach weiterleiten. Amazon- und GLS-Mails erkennt der Import auch weitergeleitet (Betreff mit „WG:" oder „Fwd:"); den Versender einer weitergeleiteten GLS-Mail übernimmt er nie als Namen. „Heute" und „morgen" rechnet er dann ab dem Zeitpunkt der Weiterleitung – leite also am selben Tag weiter. Aus allen anderen Mails übernimmt er nur eindeutige Sendungsnummern (DHL `00340…` und `JJD…`, UPS `1Z…`, Hermes `H…`; DPD-Nummern nur, wenn „DPD" in der Mail steht und die Nummer direkt nach „Paketnummer", „Sendungsnummer" o. Ä. folgt, oder die Mail direkt von DPD kommt). Solche Pakete tragen keinen Namen aus dem Absender, sondern heißen „<Carrier> <Nummer>" – umbenennen geht auf der Karte. Mails, die älter als 14 Tage sind, markiert der Import nur als gelesen.

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

### GLS-Pakete

- „Dein Paket wird in wenigen Tagen zugestellt“ setzt „Unterwegs“ samt Liefertag und Zeitfenster, „Dein GLS Paket kommt heute!“ setzt „In Zustellung“ für den Tag der Mail, „Dein Paket wurde … zugestellt“ setzt „Zugestellt“ – liegt das Paket im PaketShop zur Abholung bereit, „Abholbereit“. „Dein Paket wird an dem gewünschten Ort abgestellt“ legt das Paket nur an („Angekündigt“) und setzt nie einen Status zurück.
- Die Paketnummer liest der Import nur direkt nach „Paketnummer“ bzw. „Sendungsnummer“ (11 Ziffern).
- Der Versender wird nur dann zum Namen, wenn es ein bekannter Shop ist oder der Name eine Rechtsform trägt (z. B. GmbH, AG, KG, e.K.) – Namen privater Absender übernimmt die Integration nie.
- Abstellort, Zustelladresse, Empfängername, Telefonnummer und Referenzen übernimmt die Integration nie – weder in Attribute noch ins Log.
- Versandmails von Shops ohne Paketnummer (z. B. „Versand Ihrer Bestellung“) landen in „Nicht erkannt“.

### Zusammenführen

Eine Carrier-Mail (DHL „Amazon Sendung“, GLS, Hermes, UPS) gehört zu **genau einem** offenen Amazon- oder eBay-Paket ohne Sendungsnummer, wenn die Mail den Shop nennt (Amazon, eBay) oder die Shop-Mail diesen Versanddienstleister genannt hat, und der Liefertag passt (gleicher Tag oder innerhalb des Lieferzeitraums; ohne Tag: genau ein Paket unterwegs). Das Shop-Paket übernimmt dann die Sendungsnummer und fragt ab da den Carrier ab (Attribute `tracking_ref` und `tracking_carrier`). Passt es nicht eindeutig, entsteht ein eigenes Paket.

### Zustell-Code (Einmalpasswort)

Manche Amazon-Lieferungen gibt der Fahrer nur gegen einen Code heraus. Mit eingeschalteter Option liest der Import den Code aus der Mail. Die Karte zeigt ihn verdeckt: erst „Code anzeigen", dann die Rückfrage „Zustell-Code anzeigen?". Beim Zuklappen verschwindet er wieder. Der Code steht im Attribut `delivery_code`, wird nie gespeichert, landet nie im Verlauf (Recorder) und verfällt nach dem Liefertag. Verdeckt ist er nur auf der Karte: Wer Zugriff auf die Entitäts-Attribute oder die API von Home Assistant hat (Entwicklerwerkzeuge, Automationen, andere Dashboards, Apps), kann ihn im Klartext lesen.

## Karte hinzufügen

Dashboard bearbeiten → Karte hinzufügen → "Paket Tracker" auswählen. Alternativ per YAML:

```yaml
type: custom:parcel-tracker-card
```

Die Integration kopiert die Karte beim Start nach `www/parcel_tracker/` und trägt sie automatisch als Dashboard-Ressource ein (`/local/parcel_tracker/parcel-tracker-card.js`). Falls der Ordner `www` vorher nicht existierte, wird die Karte zunächst direkt von der Integration ausgeliefert; ein weiterer Neustart von Home Assistant aktiviert dann den `/local`-Pfad.

### Karte wird nicht gefunden?

Erscheint „Paket Tracker" nicht in der Kartenauswahl oder meldet das Dashboard „Custom element doesn't exist: parcel-tracker-card", hat der Browser die Karte noch nicht geladen. Das passiert direkt nach dem Einrichten, weil ein schon geöffnetes Home Assistant neue Ressourcen erst nach dem Neuladen kennt:

1. Seite neu laden (am Rechner Strg+F5 bzw. Cmd+Shift+R). In der Home-Assistant-App: App schließen und neu öffnen, notfalls unter Einstellungen → Companion-App → Debugging den Frontend-Cache leeren.
2. Unter Einstellungen → Dashboards → ⋮ → Ressourcen prüfen, ob `/local/parcel_tracker/parcel-tracker-card.js?v=…` eingetragen ist.
3. Dashboards im YAML-Modus tragen Ressourcen nicht automatisch ein. Dort die Ressource von Hand ergänzen (`url: /local/parcel_tracker/parcel-tracker-card.js`, `type: module`).

Die Kartendatei selbst zu ändern ist nicht nötig; Änderungen daran überschreibt die Integration beim nächsten Start.

## Benachrichtigungen

Die Integration schickt bei einem Statuswechsel selbst eine Benachrichtigung – über den Benachrichtigungsweg von Home Assistant, also an alles, was dort als Benachrichtigungs-Entität (`notify.…`) existiert: die Home-Assistant-App, Telegram, Pushover und andere. Eine Automation ist dafür nicht nötig.

### Einrichten

1. **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren** öffnen und den Bereich „Benachrichtigungen“ aufklappen.
2. **Ziele**: eine oder mehrere Benachrichtigungs-Entitäten wählen, z. B. `notify.mobile_app_mein_handy`. Ohne Ziel wird nichts gesendet.
3. **Ereignisse**: ankreuzen, wobei benachrichtigt wird – in Zustellung, zugestellt, abholbereit, Problem. Voreingestellt sind „in Zustellung“ und „zugestellt“.

Der Schalter „Benachrichtigungen aktiv“ schaltet sich mit dem ersten Ziel von selbst ein; wer ihn einschaltet, ohne ein Ziel zu wählen, bekommt einen Hinweis im Formular. Ausschalten (oder alle Ziele entfernen) beendet die Benachrichtigungen. Beim Speichern prüft die Integration nichts nach außen; ein Ziel, das es nicht mehr gibt oder das gerade nicht verfügbar ist, wird beim Senden übersprungen.

In aktuellen Home-Assistant-Versionen (geprüft mit 2026.9) bringt die Home-Assistant-App eine solche Entität mit. Taucht dein Handy in der Auswahl nicht auf, nimm den [Blueprint](#blueprint) mit dem klassischen Dienst `notify.mobile_app_<gerät>`.

### Wann und was

Gesendet wird genau dann, wenn auch das Event `parcel_tracker_status_changed` feuert – egal, ob der neue Status vom Carrier oder aus einer Mail kommt. Also nicht doppelt für denselben Status und nicht, wenn ein Carrier nach 17track mit einem älteren Stand antwortet.

Wechselt ein Paket den Status, während Home Assistant neu startet oder die Integration neu lädt (etwa nach dem Speichern der Optionen), geht nichts verloren: Event und Benachrichtigung folgen genau einmal, sobald Home Assistant fertig gestartet ist – nach einem Neuladen im laufenden Betrieb sofort. Mehrere Wechsel in dieser Zeit werden zu einer Meldung vom alten zum neuesten Status. Der allererste Status eines neuen Pakets wird nie gemeldet.

Der Titel ist „Paket Tracker“, der Text eine Zeile:

- `📦 Kopfhörer (DHL) ist in Zustellung – heute 14:00–16:00 Uhr` (das Zeitfenster nur, wenn eines für heute bekannt ist)
- `✅ Kopfhörer (DHL) wurde zugestellt`
- `📍 Kopfhörer (DHL) liegt zur Abholung bereit – Bonn bis 06.10.` (Ort der Filiale und letzter Abholtag nur, wenn der Carrier sie nennt)
- `⚠️ Kopfhörer (DHL): Problem bei der Zustellung`

Genannt wird der Name des Pakets (bei Paketen aus Mails der Artikeltitel, höchstens 40 Zeichen). Hat ein Paket keinen Namen, steht dort `Paket …2557` mit den letzten vier Stellen der Nummer.

**Nie im Text:** der Zustell-Code, die vollständige Sendungsnummer, eine Adresse, ein Ablageort und die Ereignistexte des Carriers. Eine Benachrichtigung verlässt Home Assistant (bei der App über den Push-Dienst von Apple oder Google), deshalb bleibt sie so knapp.

Schlägt das Senden fehl, steht eine Warnung ohne Paketdaten im Log; die Paketabfrage läuft unverändert weiter.

Was dieser Weg nicht kann: Der Dienst `notify.send_message` von Home Assistant kennt nur Titel und Text. Dass sich beim Antippen ein Dashboard öffnet oder eine neue Meldung die frühere zum selben Paket ersetzt, geht darüber nicht – dafür ist der Blueprint da.

### Blueprint

Für eigene Texte, eigene Bedingungen und die Extras der Home-Assistant-App gibt es einen Blueprint:

[![Blueprint in Home Assistant importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FSoerenKaiser99%2Fparcel_tracker%2Fmain%2Fblueprints%2Fautomation%2Fparcel_tracker%2Fpaket_benachrichtigung.yaml)

Der Knopf importiert [`blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml`](blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml) aus diesem Repository (HACS installiert Blueprints nicht mit). Danach unter **Einstellungen → Automationen & Szenen → Blueprints** eine Automation daraus anlegen:

- **Status**: bei welchen neuen Status benachrichtigt wird (alle Status wählbar, voreingestellt „in Zustellung“ und „zugestellt“).
- **Benachrichtigungsdienst**: ein klassischer Dienst als Text, z. B. `notify.mobile_app_mein_handy`; Standard `notify.notify`.
- **Titel** und **Text**: Der Text ist eine Vorlage mit den Variablen `name`, `carrier`, `new_status`, `old_status` und `text` (der fertige Standardsatz), z. B. `{{ name }} kommt mit {{ carrier }}`.
- **Dashboard-Pfad** (nur Home-Assistant-App): z. B. `/lovelace/pakete`. Beim Antippen öffnet sich dieses Dashboard (`data.url` für iOS, `data.clickAction` für Android).
- **Frühere Meldung ersetzen** (nur Home-Assistant-App): Eine neue Meldung ersetzt die frühere zum selben Paket (`data.tag`, ein Hash der Sendungsnummer, nie die Nummer selbst).
- **Zusätzliche Bedingungen**: z. B. nur tagsüber oder nur, wenn jemand zu Hause ist.

Sind Dashboard-Pfad und Ersetzen nicht gesetzt, schickt der Blueprint nur Titel und Text und passt damit zu jedem Benachrichtigungsdienst. Wer Benachrichtigungen in den Optionen und zusätzlich über den Blueprint einschaltet, bekommt jede Meldung zweimal.

## Beispiel-Automation

Wer lieber ganz von Hand baut – das Event `parcel_tracker_status_changed` trägt `number`, `name`, `carrier` (Kürzel, z. B. `dhl`), `carrier_name` (Anzeigename wie am Sensor, z. B. `DHL`), `old_status`, `new_status`, `eta_date`, `eta_from`, `eta_to` und `location`. Benachrichtigung, sobald ein Paket in Zustellung geht:

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
      message: "{{ trigger.event.data.name or trigger.event.data.number }} ({{ trigger.event.data.carrier_name }}) ist in Zustellung."
```

## Datenschutz

Sendungsnummern gehen nur an den jeweiligen Carrier (DHL, DPD, GLS, Hermes bzw. – mit eigenen Zugangsdaten – UPS). Die PLZ geht nur an DHL und GLS (an GLS zusammen mit der Paketnummer, damit GLS den Verlauf liefert); ohne hinterlegte PLZ geht an GLS nur die Paketnummer. An 17track geht nur auf ausdrücklichen Wunsch die Sendungsnummer samt Carrier-Code, keine PLZ und kein Name; Adressen aus der 17track-Antwort verwirft die Integration, ohne sie zu speichern oder zu loggen.

Aus Mails übernimmt der Import nur Bestellnummer, einen auf 60 Zeichen gekürzten Artikeltitel, Status, Liefertag und Zeitfenster, den Versanddienstleister sowie – nur mit eingeschalteter Option und nur im Arbeitsspeicher – den Zustell-Code. Adresse, Name, Telefonnummer, eBay-Käufer- und Verkäufernamen, Wunsch-Ablageort bzw. Abstellort, Referenzen, Preise und Mail-Inhalte landen weder in Attributen noch im Log. Das IMAP-Passwort, die UPS-Zugangsdaten und der 17track-Key liegen wie der DHL-Key in der Konfiguration von Home Assistant.

Benachrichtigungen gehen an die gewählten Benachrichtigungs-Ziele und damit an deren Dienst. Sie enthalten nur den Namen bzw. Artikeltitel des Pakets (ohne Namen die letzten vier Stellen der Nummer), den Carrier, den Status und – wenn bekannt – das heutige Zeitfenster oder Ort und letzten Abholtag der Filiale; nie den Zustell-Code, die vollständige Sendungsnummer, eine Adresse oder einen Ablageort. Der Diagnose-Download nennt nur die Anzahl der Ziele und die gewählten Ereignisse.

## Markenhinweis

DHL, DPD, Hermes, UPS, GLS, 17track, Amazon und eBay sind Marken ihrer Inhaber. Die Logos (Simple Icons, CC0) dienen nur zur Kennzeichnung des Carriers; DHL als gelbes Schild mit rotem Schriftzug, UPS in der Textfarbe des Themes, Hermes erscheint als blauer Punkt mit „H“, GLS als blauer Punkt mit „G“ (Simple Icons hat kein GLS-Logo), „Andere (über 17track)“ als grauer Punkt mit „17“. Dieses Projekt ist nicht mit den Unternehmen verbunden.

## Fehler melden

1. In Home Assistant die Diagnose herunterladen: **Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen**.
2. Die Datei kurz ansehen (JSON, jeder Texteditor zeigt sie an).
3. Auf GitHub ein Issue mit der Vorlage [„Fehler melden“](https://github.com/SoerenKaiser99/parcel_tracker/issues/new?template=fehler.yml) öffnen: Version der Integration, Home-Assistant-Version, Carrier, was passiert ist und was du erwartet hast. Die Diagnose-Datei ins Feld „Diagnose-Datei“ ziehen; ein Log-Auszug ist freiwillig.

**Die Diagnose enthält:** die Version der Integration, die Einstellungen ohne Geheimnisse, je Paket Carrier, Modus, Status, Fehler und Zähler sowie den Zustand des Mail-Imports (Zeitpunkt des letzten Laufs, Wartezeit nach Fehlern, Zähler für erkannte und nicht erkannte Mails). Zu den letzten zehn nicht erkannten Mails steht nur die Absender-Domain (bei unbekannten Absendern nur `other`) und ob die Mail weitergeleitet war. Der IMAP-Server wird nur genannt, wenn er zu einem öffentlichen Mailanbieter gehört (z. B. mailbox.org, GMX, Gmail); ein eigener Server steht nur als `custom` drin. Home Assistant ergänzt die Datei selbst um Systeminformationen (Version, Installationsart, Betriebssystem) und die Liste der installierten benutzerdefinierten Integrationen.

**Die Diagnose enthält nie:** API-Keys, Passwörter, das UPS-Secret, den 17track-Key, den IMAP-Benutzer, die PLZ, Paketnamen und Artikeltitel, Zustell-Codes, Orte, Ereignistexte, Betreffzeilen und Mail-Inhalte. Sendungs- und Bestellnummern stehen nur maskiert drin: Ziffern werden zu `9`, Buchstaben zu `A`, Länge und Präfix bleiben (z. B. `JJD999999999999999999`), damit sich Erkennungsfehler trotzdem nachvollziehen lassen.

Geht es um eine Mail, die der Import nicht erkennt, hilft zusätzlich eine anonymisierte Beispielmail: siehe [Beispielmails einreichen](#beispielmails-einreichen).

## Beispielmails einreichen

Landet eine Paketmail im Ordner `Paket-Tracker-Nicht-erkannt` oder fehlt ein Shop oder Carrier, lässt sich das nur mit einer Beispielmail beheben. Eingereicht werden ausschließlich anonymisierte Mails als ZIP an einem GitHub-Issue.

**Nie rohe Mails hochladen.** **Nie Mails privat an den Autor schicken.**

1. Die Original-Mail als `.eml` speichern – nicht weiterleiten, denn eine Weiterleitung verändert Absender und Aufbau. Thunderbird: Rechtsklick auf die Mail → „Speichern als“. Gmail im Browser: ⋮ an der Mail → „Nachricht herunterladen“. Apple Mail: die Mail aus der Liste in einen Ordner ziehen. Alle Mails in einen eigenen Ordner legen.
2. Das Skript [`anonymize_mail.py`](https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/scripts/anonymize_mail.py) herunterladen (im Browser „Speichern unter“) und neben den Ordner legen. Es ist eine einzelne Datei, braucht nur Python 3 und läuft lokal, ohne Netzwerkzugriff und ohne Installation der Integration.
3. Im Terminal starten (unter Windows `py` statt `python3`):

   ```
   python3 anonymize_mail.py <Ordner> --zip
   ```

   Das Skript fragt nach Name, Straße und Hausnummer, Postleitzahl, Ort, Telefonnummer und Mail-Adresse (leer lassen überspringt eine Angabe) und ersetzt diese Angaben überall. Die Angaben lassen sich auch als Optionen übergeben: `--name "Vorname Nachname" --street "Straße 1" --postcode 12345 --city Ort --phone … --email …`. Mindestens eine Angabe ist nötig. Ganz ohne Angaben arbeitet das Skript nur mit `--ohne-angaben`: Es fragt dann nicht und bereinigt nur allgemein – Namen und Orte können dann stehen bleiben.

   Unabhängig von den Angaben ersetzt es alle Mail-Adressen außer dem Absender des Shops oder Carriers, Telefonnummern, Links (nur der Servername bleibt), Sendungs- und Bestellnummern (gleiche Form, erfundene Ziffern), Ablageorte, Anreden, Adressblöcke, Zeilen mit Postleitzahl und Ort sowie Namen von Nachbarn, Empfängern und privaten Absendern; technische Kopfzeilen und Anhänge entfallen. Bei weitergeleiteten oder beantworteten Mails (Betreff mit „WG:“, „Fwd:“, „AW:“, „Re:“) ersetzt es auch den Absender. Frühere Ergebnisse des Skripts im Ordner `anonymisiert/` löscht es vor dem Schreiben.
4. Die Ergebnisse lesen: Sie liegen in `<Ordner>/anonymisiert/`. Jede Datei im Texteditor öffnen und durchlesen – das Skript erkennt nicht alles. Steht noch etwas Privates drin, die Stelle von Hand ersetzen oder die Mail weglassen und das ZIP neu packen.
5. Ein Issue mit der Vorlage [„Mail wird nicht erkannt“](https://github.com/SoerenKaiser99/parcel_tracker/issues/new?template=mail-nicht-erkannt.yml) öffnen und `paket-tracker-beispiele.zip` aus dem Ordner `anonymisiert/` anhängen.

## Roadmap & Status

- DHL (offizielle API): umgesetzt
- DPD (öffentliche Sendungsverfolgung): umgesetzt
- E-Mail-Import Amazon, DHL, UPS: umgesetzt
- Hermes Live-Abfrage: umgesetzt; mit einer aktuellen Sendung noch nicht live getestet
- Hermes-Mails: umgesetzt
- eBay-Mails: umgesetzt
- UPS Live-Status (offizielle API): umgesetzt, noch nicht mit echten Zugangsdaten getestet (UPS-Freischaltung ausstehend)
- 17track: Anmeldung live getestet, Anreicherung noch ohne Live-Fall
- GLS-Live-Abfrage: umgesetzt, Live-Test ausstehend
- GLS-Mails: umgesetzt
- Benachrichtigungen (Optionen und Blueprint): umgesetzt; Antippen öffnet ein Dashboard und Ersetzen der früheren Meldung nur über den Blueprint
- Amazon per Konto-Anmeldung: verworfen zugunsten des Mail-Imports
- **International**: Karte auch auf Englisch, weitere Amazon-Länder im Mail-Import, nationale Carrier (Beispiele: Royal Mail, PostNL, USPS) – erst sinnvoll mit anonymisierten Beispielmails von Testern aus den jeweiligen Ländern

---

## English summary

Paket Tracker is a Home Assistant custom integration, built for Germany, that tracks parcels from DHL, DPD, GLS, Hermes and, optionally, UPS. Why: one place in Home Assistant that answers "is a parcel coming today, and when?" across all carriers instead of five apps and a pile of mails – parcels appear by themselves from shipping mails, can be used in automations, and everything runs locally with no cloud account and no third-party tracking service. DHL uses the official "Shipment Tracking – Unified" API (an API key is optional; without one, DHL parcels show a "key missing" status), while DPD uses DPD's public tracking page with only the tracking number, which yields status and the five milestone dates but no location or delivery window. The integration creates one sensor per parcel (`sensor.paket_<number>`), a summary sensor for today's expected parcels, a delivery calendar, and fires a `parcel_tracker_status_changed` event on every status change. Optional push notifications (options section "Benachrichtigungen": pick notify entities and the events out for delivery, delivered, ready for pickup, problem) need no automation; their one-line text never contains the delivery code, the full tracking number or an address, and a blueprint (`blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml`) covers custom texts, extra conditions and, for the Home Assistant app, opening a dashboard on tap and replacing the earlier notification. It ships its own Lovelace card (`custom:parcel-tracker-card`, listed as "Paket Tracker" in the card picker) for adding, renaming, and removing parcels. Install it through HACS as a custom repository, then set up an optional DHL API key, a postcode, and how long delivered parcels stay visible. An optional mail import reads a dedicated parcel mailbox via IMAP (never enter your main mailbox: the IMAP password grants full access) and creates parcels from Amazon, DHL and UPS mails, including Amazon's own deliveries; a DHL "Amazon Sendung" mail is merged into the matching Amazon order when unambiguous. Delivery one-time codes are read only when enabled, shown on the card after a tap and a confirmation (hidden only on the card: anyone with access to the entity attributes or the Home Assistant API can read it), never stored and never recorded. Hermes uses the keyless public tracking endpoint (number only). UPS status comes from UPS mails and, with your own Client ID and Secret from developer.ups.com (product "Tracking"), from the official UPS Track API, capped by a monthly request budget (default 100) so it never costs money. The mail import also reads Hermes and eBay mails (one parcel per eBay order, never using eBay item numbers as tracking numbers) and merges a carrier mail into exactly one matching open Amazon or eBay order. Roadmap & Status: the UPS API is implemented but not yet tested with real credentials (UPS approval pending), the Hermes live lookup is implemented but not yet tested with a current parcel, 17track registration has been tested live while its enrichment has not yet seen a live case, the GLS live lookup is implemented (live test pending), and an Amazon account login was dropped in favour of the mail import; an International roadmap item (English card, more Amazon countries, national carriers such as Royal Mail, PostNL and USPS) waits for anonymised sample mails from testers abroad. With an optional free 17track API key, a parcel can be sent to 17track on request (each new number uses one of the account's 200 one-time numbers; polls are free, every 6 hours, at most 40 numbers per call) to fill in place, time window and history without overriding the carrier, and carriers without their own connection (e.g. FedEx) can be added as "other"; a quota sensor and repairs warn when numbers run low. Tracking numbers are sent only to the matching carrier (or, on request, to 17track with the carrier code), and the postcode is sent only to DHL and GLS. GLS uses the open tracking lookup of gls-group.com (11-digit parcel number; with a stored postcode GLS also returns the history) and GLS notification mails; the lookup is no official API and may be closed at any time, in which case GLS mails and 17track remain.

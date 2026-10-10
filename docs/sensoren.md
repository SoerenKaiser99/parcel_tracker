# Sensoren, Kalender und Dienste

Diese Seite ist zum Nachschlagen: jede Entität mit Zustand und Attributen, der Kalender, die Dienste und der Inhalt der Diagnose.

## Übersicht

| Entität | Zustand |
|---|---|
| [`sensor.paket_<nummer>`](#sensorpaket_nummer) | Status eines Pakets, ein Sensor pro Paket |
| [`sensor.pakete_heute`](#sensorpakete_heute) | Anzahl der Pakete, die heute sicher kommen |
| [`sensor.pakete_unterwegs`](#die-vier-zahlsensoren) | Anzahl der Pakete, die noch nicht zugestellt sind |
| [`sensor.pakete_moeglich`](#die-vier-zahlsensoren) | Anzahl der Pakete, die heute möglich sind |
| [`sensor.pakete_zugestellt_heute`](#die-vier-zahlsensoren) | Anzahl der heute zugestellten Pakete |
| [`sensor.pakete_abholbereit`](#die-vier-zahlsensoren) | Anzahl der abholbereiten Pakete |
| [`sensor.paket_tracker_17track_kontingent`](#sensorpaket_tracker_17track_kontingent) | verbleibende 17track-Nummern |
| [`calendar.pakete`](#kalender) | Kalender mit den erwarteten Zustellterminen |

Die Entitäts-IDs sind fest. Die ID eines Paket-Sensors entsteht aus der Nummer des Pakets und ändert sich auch mit „Namen ausblenden“ nicht.

## `sensor.paket_<nummer>`

Ein Sensor pro Paket. `<nummer>` ist die Nummer des Pakets in Kleinbuchstaben. Bei Shop-Bestellungen beginnt sie mit `amz`, `ebay` oder `ali`, z. B. `sensor.paket_ebay990000000001`.

Verschwindet ein Paket aus der Liste (gelöscht oder nach der eingestellten Zahl von Tagen nach der Zustellung), verschwindet auch sein Sensor.

### Zustand

| Zustand | Anzeige |
|---|---|
| `pre_transit` | Angekündigt |
| `in_transit` | Unterwegs |
| `at_delivery_depot` | Im Zustelldepot |
| `out_for_delivery` | In Zustellung |
| `awaiting_pickup` | Abholbereit |
| `delivered` | Zugestellt |
| `exception` | Problem |
| `unknown` | Unbekannt |

### Attribute

| Attribut | Inhalt |
|---|---|
| `carrier` | Kürzel des Paketdienstes oder Shops: `dhl`, `dpd`, `gls`, `hermes`, `ups`, `amazon`, `ebay`, `aliexpress`, `other` |
| `carrier_name` | Anzeigename, z. B. `DHL` |
| `number` | Nummer des Pakets |
| `name` | Name, wie er angezeigt wird (mit „Namen ausblenden“ der neutrale Name) |
| `eta_date` | erwarteter Liefertag (bei einer Lieferspanne ihr erster Tag) |
| `eta_latest` | letzter Tag einer Lieferspanne |
| `eta_from`, `eta_to` | Beginn und Ende des Zeitfensters |
| `days_until` | Tage bis zum Liefertag (0 = heute) |
| `location` | Standort, wenn bekannt |
| `location_source` | `17track`, wenn der Ort von 17track stammt, sonst leer |
| `pickup_point` | Abholpunkt (Packstation, Filiale, PaketShop), wenn bekannt |
| `pickup_until` | letzter Abholtag, wenn bekannt |
| `status_text` | Statustext des Paketdienstes |
| `last_update` | Zeitpunkt der letzten Abfrage |
| `stale` | `true`, wenn die letzte Abfrage fehlschlug und ein älterer Stand gezeigt wird |
| `last_error` | Kürzel des letzten Fehlers, sonst leer |
| `progress` | Schritt des Fortschrittsbalkens (0 = nicht gezeigt) |
| `delivered_at` | Zustellzeitpunkt |
| `assumed_delivered` | `true` bei einer Bestellung, die ohne Zustellmail abgeschlossen wurde, sonst `false` |
| `events` | Verlauf: Liste aus `timestamp`, `text` und `location` |
| `tracking_ref` | Sendungsnummer des Paketdienstes, die eine Shop-Bestellung übernommen hat |
| `tracking_carrier` | Paketdienst zu `tracking_ref` |
| `tracking_url` | Adresse der Sendungsverfolgung beim Paketdienst; leer, wenn es keine gibt |
| `shipping_carrier_hint` | Versanddienstleister, den eine Shop-Mail genannt hat |
| `delivery_code` | Zustell-Code, nur mit eingeschalteter Option und nur bis zum Liefertag |
| `track17` | `true`, wenn das Paket bei 17track angemeldet ist |
| `track17_carrier` | Paketdienst, den 17track erkannt hat |

!!! info "Nicht im Verlauf von Home Assistant"
    Die Attribute `events`, `status_text` und `delivery_code` zeichnet der Recorder nicht auf.

!!! warning "Der Zustell-Code ist als Attribut lesbar"
    Verdeckt ist der Code nur auf der Karte. Wer Zugriff auf die Entitäts-Attribute oder die API von Home Assistant hat, kann ihn im Klartext lesen. Siehe [Zustell-Codes](datenschutz.md#zustell-codes).

## `sensor.pakete_heute`

Zählt die Pakete, die **heute sicher** kommen: Status „In Zustellung“ oder ein fester Liefertag heute.

- Nennt der Versender nur eine Spanne, in der heute liegt (z. B. „2.–5. Okt.“), zählt das Paket nicht mit, sondern steht als „möglich“ in `possible`. Meldet eine Mail oder der Paketdienst „In Zustellung“ oder einen festen Tag heute, wechselt es von selbst zu den sicheren.
- Was heute schon zugestellt wurde, zählt nicht mehr mit und steht in `delivered_today`.
- Was zur Abholung bereitliegt, steht in `awaiting_pickup`. An der Zählung ändert das nichts.

| Attribut | Inhalt |
|---|---|
| `parcels` | Liste der Pakete, die heute sicher kommen |
| `possible` | Liste der Pakete, deren Lieferspanne heute einschließt |
| `possible_count` | Anzahl dazu |
| `delivered_today` | Liste der heute zugestellten Pakete |
| `delivered_today_count` | Anzahl dazu |
| `awaiting_pickup` | Liste der abholbereiten Pakete (Packstation, Filiale, PaketShop) |
| `awaiting_pickup_count` | Anzahl dazu |
| `integration_version` | installierte Version der Integration (für den Neuladen-Hinweis der Karte; nicht im Verlauf gespeichert) |

**Aufbau der Listen:** Jeder Eintrag hat `number`, `name`, `carrier`, `eta_from` und `eta_to`.

**„Heute zugestellt“ heißt:** Status „Zugestellt“, und der Zustellzeitpunkt `delivered_at` liegt heute – gerechnet in der Zeitzone von Home Assistant. Nennt der Paketdienst keinen Zeitpunkt, gilt der Tag des Statuswechsels. Eine Bestellung, die ohne Zustellmail abgeschlossen wurde, zählt nicht mit.

In Templates:

```jinja
{{ state_attr('sensor.pakete_heute', 'possible_count') }}
{{ state_attr('sensor.pakete_heute', 'delivered_today_count') }}
{{ state_attr('sensor.pakete_heute', 'awaiting_pickup_count') }}
```

## Die vier Zählsensoren

Vier weitere Sensoren liefern je eine Zahl als Zustand (0, wenn nichts da ist) und die Pakete im Attribut `parcels` (aufgebaut wie bei `sensor.pakete_heute`). Sie eignen sich für Bedingungen in Dashboards und Automationen.

| Sensor | Zählt | Entspricht |
|---|---|---|
| `sensor.pakete_unterwegs` | alle Pakete, die noch nicht zugestellt sind – auch abholbereite, solche mit Problem oder unbekanntem Status | – |
| `sensor.pakete_moeglich` | die heute möglichen Pakete | `possible` |
| `sensor.pakete_zugestellt_heute` | die heute zugestellten Pakete | `delivered_today` |
| `sensor.pakete_abholbereit` | die abholbereiten Pakete; sie zählen weiter bei `sensor.pakete_unterwegs` mit | `awaiting_pickup` |

## `sensor.paket_tracker_17track_kontingent`

Zeigt die verbleibenden 17track-Nummern. Ohne 17track-Key ist der Sensor nicht verfügbar.

| Attribut | Inhalt |
|---|---|
| `total` | Gesamtzahl der Nummern des Kontos |
| `used` | verbrauchte Nummern |

Der Sensor wird beim Start, nach jeder Anmeldung und einmal täglich aktualisiert. Mehr unter [17track](dienste.md#17track-optional).

## Kalender

`calendar.pakete` zeigt die erwarteten Zustelltermine.

- Einen Termin bekommt jedes Paket mit Liefertag, das noch nicht zugestellt ist und dessen Liefertag nicht in der Vergangenheit liegt.
- Der Titel ist „Paket: “ und der Name des Pakets; ohne Namen die Nummer.
- Mit Zeitfenster dauert der Termin von dessen Beginn bis zu dessen Ende. Ohne Zeitfenster ist es ein ganztägiger Termin am Liefertag.
- Der Ort des Termins ist der Standort des Pakets, wenn er bekannt ist.
- Mit „Namen ausblenden“ tragen die Termine die neutralen Namen.

## Dienste

Alle Dienste beginnen mit `parcel_tracker.`.

### `parcel_tracker.add_parcel`

Ein Paket verfolgen.

| Feld | Pflicht | Inhalt |
|---|---|---|
| `number` | ja | Sendungsnummer, wie aufgedruckt; Leerzeichen erlaubt |
| `carrier` | nein | `auto` (Standard), `dhl`, `dpd`, `gls`, `hermes`, `ups` oder `other` (über 17track, braucht einen 17track-API-Key) |
| `name` | nein | Bezeichnung |

```yaml
action: parcel_tracker.add_parcel
data:
  number: "00340999999999999901"
  carrier: dhl
  name: "Druckerpatronen"
```

Die Nummer im Beispiel ist erfunden.

### `parcel_tracker.remove_parcel`

Ein Paket nicht mehr verfolgen.

| Feld | Pflicht | Inhalt |
|---|---|---|
| `number` | ja | Nummer des Pakets |

### `parcel_tracker.rename_parcel`

Bezeichnung eines Pakets ändern.

| Feld | Pflicht | Inhalt |
|---|---|---|
| `number` | ja | Nummer des Pakets |
| `name` | nein | neue Bezeichnung; leer entfernt sie |

### `parcel_tracker.refresh`

Jetzt abfragen – auch das Postfach, falls der E-Mail-Import eingerichtet ist.

| Feld | Pflicht | Inhalt |
|---|---|---|
| `number` | nein | Nummer eines Pakets; leer für alle Pakete |

Bei UPS zählt jede Abfrage auf das Monatsbudget, auch die über diesen Dienst.

### `parcel_tracker.track_17track`

Schickt ein Paket an 17track, um Ort, Zeitfenster und Verlauf zu ergänzen. **Verbraucht eine deiner 17track-Nummern.**

| Feld | Pflicht | Inhalt |
|---|---|---|
| `number` | ja | Nummer eines Pakets aus der Liste |

Nicht möglich bei zugestellten Paketen und bei Bestellungen, solange keine Sendungsnummer des Paketdienstes bekannt ist.

### Fehlermeldungen der Dienste

| Meldung | Wann |
|---|---|
| „Dieses Paket ist schon in der Liste.“ | die Nummer wird schon verfolgt |
| „Amazon-Nummern (TBA…) lassen sich nicht direkt verfolgen. Leite die Amazon-Mails ins Paket-Postfach weiter.“ | eine `TBA…`-Nummer wurde eingetragen |
| „Gib eine Sendungsnummer ein.“ | die Nummer ist leer |
| „Unbekannter Carrier.“ | der Wert in `carrier` ist nicht bekannt |
| „Dieses Paket ist nicht in der Liste.“ | die Nummer wird nicht verfolgt |
| „Kein 17track-API-Key eingetragen. Trag ihn in den Optionen von Paket Tracker ein.“ | 17track ohne Key |
| „17track hat den Carrier dieser Nummer nicht erkannt.“ | „Andere (über 17track)“ ohne Treffer |
| „Das 17track-Kontingent ist erschöpft.“ | keine 17track-Nummer mehr übrig |
| „Dieses Paket lässt sich nicht an 17track schicken (zugestellt oder noch keine Sendungsnummer).“ | siehe oben |

## Event und Auslöser

Das Event `parcel_tracker_status_changed` und die Auslöser im Automations-Editor stehen unter [Automationen](automationen.md).

## HTTP-Endpunkt

`POST /api/parcel_tracker/import_mail` nimmt eine einzelne Mail entgegen. Siehe [Mail per HTTP übergeben](mail-import.md#ohne-postfach-mail-per-http-ubergeben).

## Diagnose

Die Diagnose lädst du unter **Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen** herunter.

**Die Diagnose enthält:**

- die Version der Integration und das eingestellte Land,
- ob „Namen ausblenden“ eingeschaltet ist (und je Paket, ob sein Name von Hand vergeben wurde – nie den Namen selbst),
- die Einstellungen ohne Geheimnisse,
- je Paket Carrier, Modus, Status (auch, ob eine Bestellung ohne Zustellmail abgeschlossen wurde), Fehler und Zähler,
- den Zustand des Mail-Imports: Zeitpunkt des letzten Laufs, Wartezeit nach Fehlern, Zähler für erkannte und nicht erkannte Mails,
- zu den letzten zehn nicht erkannten Mails nur die Absender-Domain (bei unbekannten Absendern nur `other`) und ob die Mail weitergeleitet war,
- den IMAP-Server nur, wenn er zu einem öffentlichen Mailanbieter gehört (z. B. mailbox.org, GMX, Gmail); ein eigener Server steht nur als `custom` drin,
- bei Benachrichtigungen nur die Anzahl der Ziele (getrennt nach Entitäten und klassischen Diensten, nie ihre Namen) und die gewählten Ereignisse.

Home Assistant ergänzt die Datei selbst um Systeminformationen (Version, Installationsart, Betriebssystem) und die Liste der installierten benutzerdefinierten Integrationen.

**Die Diagnose enthält nie:** API-Keys, Passwörter, das UPS-Secret, den 17track-Key, den IMAP-Benutzer, die PLZ, Paketnamen und Artikeltitel, Zustell-Codes, Orte, Ereignistexte, Betreffzeilen und Mail-Inhalte.

Sendungs- und Bestellnummern stehen nur maskiert drin: Ziffern werden zu `9`, Buchstaben zu `A`, Länge und Präfix bleiben (z. B. `JJD999999999999999999`). So lassen sich Erkennungsfehler trotzdem nachvollziehen.

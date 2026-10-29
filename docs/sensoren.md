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
| [`switch.paket_tracker_geschenkmodus`](#switchpaket_tracker_geschenkmodus) | Geschenkmodus an oder aus |

Die Entitäts-IDs sind fest. Die ID eines Paket-Sensors entsteht aus der Nummer des Pakets und ändert sich auch mit „Namen ausblenden“ nicht.

## `sensor.paket_<nummer>`

Ein Sensor pro Paket. `<nummer>` ist die Nummer des Pakets in Kleinbuchstaben. Bei Shop-Bestellungen beginnt sie mit `amz`, `ebay`, `ali` oder `evt`, z. B. `sensor.paket_ebay990000000001`.

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
| `cancelled` | Storniert (nur Shop-Bestellungen) |
| `unknown` | Unbekannt |

### Attribute

| Attribut | Inhalt |
|---|---|
| `carrier` | Kürzel des Paketdienstes oder Shops: `dhl`, `dpd`, `gls`, `hermes`, `ups`, `amazon`, `ebay`, `aliexpress`, `eventim`, `other` |
| `carrier_name` | Anzeigename, z. B. `DHL` |
| `number` | Nummer des Pakets |
| `name` | Name, wie er angezeigt wird (mit „Namen ausblenden“ der neutrale Name, bei einem Geschenk `Geschenk · …`) |
| `gift` | `true`, wenn das Paket ein Geschenk ist (siehe [Geschenkmodus](datenschutz.md#geschenkmodus)), sonst `false` |
| `owner` | die Person, der das Paket gehört, als Entität (z. B. `person.anna`); leer, wenn es allen gehört. Das ist der geltende Besitzer, bei einem Paket ohne eigenen Besitzer also die Person aus **Unklare Pakete gehören**. Ein Besitzer, der nicht mehr unter Personen eingerichtet ist (entfernt oder umbenannt), zählt wie kein eigener Besitzer |
| `owner_detected` | `true`, wenn eine eingerichtete Person aus einer Mail erkannt oder von Hand gesetzt wurde. `false`, wenn der Besitzer aus der Standard-Person kommt oder von Hand „allen“ gesetzt wurde |
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
| `manual_delivered` | `true`, wenn das Paket von Hand als erhalten markiert wurde (Knopf „Erhalten“ oder Dienst `parcel_tracker.mark_delivered`), sonst `false` |
| `events` | Verlauf: Liste aus `timestamp`, `text` und `location` |
| `tracking_ref` | Sendungsnummer des Paketdienstes, die eine Shop-Bestellung übernommen hat |
| `tracking_carrier` | Paketdienst zu `tracking_ref` |
| `tracking_url` | Adresse der Sendungsverfolgung beim Paketdienst, bei einer Amazon-Bestellung ohne dessen Nummer bei Amazon; leer, wenn es keine gibt und bei einem Geschenk |
| `amazon_shipment` | Amazons Kennung der neuesten Sendung einer Amazon-Bestellung (aus den Mails ab „Versendet“); leer ohne und bei einem Geschenk |
| `shipping_carrier_hint` | Versanddienstleister, den eine Shop-Mail genannt hat |
| `has_delivery_code` | `true`, wenn ein gültiger Zustell-Code bekannt ist (nur mit eingeschalteter Option, nur bis zum Liefertag), sonst `false`. Den Code selbst liefert nur die Karte, siehe unten |
| `customs_amount` | Betrag der Einfuhrabgaben (Zoll), die bei der Zustellung zu zahlen sind, als Zahl (z. B. `12.34`). Er stammt aus der DHL-Mail am Zustelltag und steht nur bis zur Zustellung da, sonst leer |
| `customs_currency` | Währung zu `customs_amount`, z. B. `EUR`; leer, wenn kein Betrag bekannt ist |
| `customs_cash` | `true`, wenn die Mail Barzahlung verlangt („in bar zu bezahlen“), sonst `false` |
| `track17` | `true`, wenn das Paket bei 17track angemeldet ist |
| `track17_carrier` | Paketdienst, den 17track erkannt hat |

!!! info "Nicht im Verlauf von Home Assistant"
    Die Attribute `events`, `status_text`, `name`, `tracking_url`, `amazon_shipment`, `customs_amount`, `customs_currency` und `customs_cash` zeichnet der Recorder nicht auf.

!!! warning "Der Zustell-Code ist kein Attribut mehr"
    Bis v0.3.41 stand er als `delivery_code` am Sensor. Seit v0.3.42 gibt es nur noch `has_delivery_code`. Automationen und Templates, die das Attribut `delivery_code` lesen (z. B. mit `state_attr`), bekommen den Code nicht mehr. Die Karte holt ihn erst beim Aufdecken. Siehe [Zustell-Codes](datenschutz.md#zustell-codes).

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
| `persons` | die unter [Personen](mail-import.md#pakete-personen-zuordnen) eingerichteten Personen als Entitäten (z. B. `person.anna`), ohne Adressen; leere Liste ohne Personen. Die Karte bietet „Gehört“ nur damit an (nicht im Verlauf gespeichert) |
| `default_owner` | die Person bei **Unklare Pakete gehören** als Entität; leer, wenn unklare Pakete allen gehören (nicht im Verlauf gespeichert) |

**Aufbau der Listen:** Jeder Eintrag hat `number`, `name`, `carrier`, `eta_from`, `eta_to` und `gift`. `gift` ist `true` bei einem Geschenk, `name` ist dann der Geschenk-Name. So lassen eigene Anzeigen Geschenke weg, z. B. `{{ state_attr('sensor.pakete_heute', 'parcels') | rejectattr('gift') | list | count }}`.

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

## `switch.paket_tracker_geschenkmodus`

Der Geschenkmodus: Eingeschaltet, werden neue Pakete als Geschenk gekennzeichnet. Der Schalter heißt „Geschenkmodus“, hat das Symbol `mdi:gift` und gehört zu keinem Gerät. Er ist eine Konfigurations-Entität und wird Sprachassistenten nicht von selbst freigegeben.

- Einschalten darf jeder.
- Ausschalten darf nur, wer Geschenke sehen darf, und ein Aufruf ohne Benutzer, also eine Automation. Alle anderen bekommen die Meldung „Nur wer Geschenke sehen darf, kann den Geschenkmodus ausschalten.“. Auch `switch.toggle` und `homeassistant.turn_off` unterliegen dem.
- Der Zustand bleibt über Neustarts erhalten.
- Gib den Schalter nicht für Assist, Alexa oder Google frei: Sie rufen ihn ohne Benutzer oder als Besitzer des Kontos auf.

Wie du ihn per Automation schaltest: [Geschenkmodus per Automation schalten](automationen.md#geschenkmodus-per-automation-schalten). Alles zum Modus: [Geschenkmodus](datenschutz.md#geschenkmodus).

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
| `owner` | nein | Besitzer: eine Personen-Entität wie `person.anna` oder `all`; ohne Angabe gilt die Standard-Person |

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

### `parcel_tracker.mark_delivered`

Ein Paket von Hand als erhalten markieren – dasselbe wie der Knopf [„Erhalten“](karte.md#erhalten) auf der Karte.

| Feld | Pflicht | Inhalt |
|---|---|---|
| `number` | ja | Nummer des Pakets |

```yaml
action: parcel_tracker.mark_delivered
data:
  number: "00340999999999999901"
```

Die Nummer im Beispiel ist erfunden.

- Das Paket ist ab jetzt zugestellt: `delivered_at` ist der Zeitpunkt des Aufrufs, `status_text` „Erhalten (von Hand markiert)“, `manual_delivered` ist `true`.
- Die Markierung gilt: Der Paketdienst wird nicht mehr abgefragt, und keine spätere Mail und keine Antwort von 17track ändert Status, Zeitpunkt oder Text. Zurücknehmen lässt sie sich nicht.
- Die Markierung gilt für genau diesen Eintrag: Eine Bestellung, zu der das Paket gehören könnte, schließt sie nicht.
- Das Event feuert mit `manual: true`, eine Benachrichtigung gibt es nicht.
- Fehler: „Dieses Paket ist nicht in der Liste.“ bei einer unbekannten Nummer, „Dieses Paket ist schon zugestellt.“ bei einem zugestellten Paket, „Diese Bestellung ist storniert, es kommt nichts mehr.“ bei einer stornierten Bestellung (wie auf der Karte, wo ihr der Knopf fehlt). Eine Bestellung, die nur „Abgeschlossen ohne Zustellbestätigung“ ist, lässt sich markieren: Sie wird damit bestätigt, `delivered_at` bleibt leer, und sie zählt nicht als heute zugestellt.

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

### `parcel_tracker.set_gift`

Markiert ein Paket oder alle offenen Pakete (weder zugestellt noch storniert) als Geschenk oder macht sie wieder sichtbar.

| Feld | Pflicht | Inhalt |
|---|---|---|
| `number` | nein | Nummer eines Pakets; nicht zusammen mit `open_parcels` |
| `open_parcels` | nein | `true` für alle offenen Pakete, also weder zugestellt noch storniert (Standard `false`) |
| `gift` | ja | `true` markiert als Geschenk, `false` macht es wieder sichtbar |
| `gift_for` | nein | Personen, für die das Geschenk ist (z. B. `person.b`), nur mit `gift: true`. `[]` entfernt nur die Personen, das Paket bleibt Geschenk |

Markieren darf jeder. Wieder sichtbar machen dürfen nur Personen, die Geschenke sehen dürfen, und Aufrufe ohne Benutzer (Automationen). Ohne `number` und ohne `open_parcels` oder mit beidem gibt es einen Fehler.

Mit `gift_for` sehen die genannten Personen das Geschenk auf der Karte wie jemand, der Geschenke nicht sehen darf, auch wenn sie sonst Geschenk-Seher sind. Meldungen zum Paket gehen nicht an ihre Ziele. `gift_for` setzen oder leeren dürfen nur Geschenk-Seher, die selbst nicht in `gift_for` stehen, und Aufrufe ohne Benutzer. `gift: false` leert `gift_for`. Wer in `gift_for` steht, darf das Geschenk auch nicht umbenennen, löschen oder einem anderen geben. Mit `open_parcels` überspringt der Dienst solche Geschenke ohne Hinweis. Für wen ein Geschenk ist, steht in keinem Attribut und keinem Event. Mehr unter [Geschenk für bestimmte Personen](datenschutz.md#geschenk-fur-bestimmte-personen-gift_for).

### `parcel_tracker.set_owner`

Gibt ein Paket einer Person (`person` als Entität wie `person.anna`) oder allen (`all`). Eine Mail ändert einen so gesetzten Besitzer nie. Der Dienst gilt für die ganze Box: Alle Einträge mit derselben Sendungsnummer beim selben Paketdienst (z. B. mehrere Amazon-Bestellungen in einem Paket) wechseln zusammen den Besitzer. Bei einem Geschenk dürfen nur Geschenk-Seher und Aufrufe ohne Benutzer den Besitzer ändern. Liegt in der Box ein Geschenk, das der Aufrufer nicht ändern darf, wechseln nur die übrigen Einträge den Besitzer, ohne Fehler und ohne Hinweis auf das Geschenk. Eine Person, die nicht unter [Personen](mail-import.md#pakete-personen-zuordnen) eingerichtet ist, lehnt der Dienst ab.

| Feld | Pflicht | Inhalt |
|---|---|---|
| `number` | ja | Nummer eines Pakets aus der Liste |
| `person` | ja | Personen-Entität oder `all` |

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
| „Nur wer Geschenke sehen darf, kann ein Geschenk wieder sichtbar machen.“ | `set_gift` mit `gift: false` von jemandem, der Geschenke nicht sehen darf |
| „Gib entweder eine Sendungsnummer an oder wähle alle offenen Pakete.“ | `set_gift` ohne `number` und `open_parcels` oder mit beidem |
| „Nur wer Geschenke sehen darf, kann ein Geschenk wieder sichtbar machen.“ | außerdem: `set_gift` mit `gift_for` von jemandem, der Geschenke nicht sehen darf oder selbst in `gift_for` steht |
| „Wähle bei gift_for vorhandene Personen.“ | `set_gift` mit einer Person in `gift_for`, die es nicht gibt |
| „gift_for geht nur mit eingeschaltetem gift.“ | `set_gift` mit `gift: false` und Personen in `gift_for` |
| „Diese Person ist im Paket Tracker nicht eingerichtet.“ | `set_owner` oder `add_parcel` mit einer Person, die unter **Personen** nicht eingerichtet ist oder die es nicht gibt |
| „Nur wer Geschenke sehen darf, kann ändern, wem ein Geschenk gehört.“ | `set_owner` für ein Geschenk (das gewählte Paket selbst) von jemandem, der Geschenke nicht sehen darf |
| „Dieses Paket lässt sich nicht an 17track schicken (zugestellt oder noch keine Sendungsnummer).“ | siehe oben |

## Event und Auslöser

Das Event `parcel_tracker_status_changed` und die Auslöser im Automations-Editor stehen unter [Automationen](automationen.md). Es trägt seit v0.3.45 auch `gift` (`true` bei einem Geschenk), siehe [Felder des Events](automationen.md#felder-des-events). Für neue Pakete gibt es ein eigenes Event: [Event beim Anlegen](#event-beim-anlegen-parcel_tracker_parcel_added).

## Event beim Anlegen: `parcel_tracker_parcel_added`

Feuert einmal, sobald ein Paket neu angelegt ist: aus einer Mail (auch ein weiterer Karton einer Bestellung), über den Dienst `parcel_tracker.add_parcel` oder über die Karte. Es feuert nicht beim Neustart oder Neuladen, nicht bei weiteren Mails zum selben Paket und nicht, wenn eine Mail in einen bestehenden Eintrag zusammengeführt wird. Übernimmt eine neue Bestellung ein schon gemeldetes Paket des Paketdienstes, feuert es auch nicht: ein Event pro Karton.

| Feld | Inhalt |
|---|---|
| `entry_id` | der Eintrag der Integration |
| `number` | Sendungs- oder Bestellnummer |
| `name` | der angezeigte Name; bei einem Geschenk der Geschenk-Name („Geschenk · DHL-Paket …2557“), nie der echte |
| `carrier` | Paketdienst oder Shop (`dhl`, `amazon` …), leer, solange er nicht erkannt ist |
| `owner` | wem das Paket gehört (z. B. `person.anna`), leer für alle |
| `gift` | `true`, wenn das Paket schon beim Anlegen ein Geschenk ist: Geschenkmodus an oder weiterer Karton einer Bestellung, die ein Geschenk ist (auch bei ausgeschaltetem Modus) |

Beispiel: Push mit Knopf „Geschenk?“ an die Home-Assistant-App. Ein Tipp macht das Paket zum Geschenk. `notify.mobile_app_handy` ersetzt du durch dein Gerät.

```yaml
alias: Neues Paket – Geschenk?
triggers:
  - trigger: event
    event_type: parcel_tracker_parcel_added
conditions:
  - condition: template
    value_template: "{{ not trigger.event.data.gift }}"
actions:
  - variables:
      number: "{{ trigger.event.data.number }}"
  - action: notify.mobile_app_handy
    data:
      message: "Neues Paket: {{ trigger.event.data.name }}. Ist es ein Geschenk?"
      data:
        actions:
          - action: "GESCHENK_{{ number }}"
            title: Geschenk
  - wait_for_trigger:
      - trigger: event
        event_type: mobile_app_notification_action
        event_data:
          action: "GESCHENK_{{ number }}"
    timeout: "02:00:00"
    continue_on_timeout: false
  - action: parcel_tracker.set_gift
    data:
      number: "{{ number }}"
      gift: true
mode: parallel
```

Danach kannst du mit `parcel_tracker.set_owner` auch den Besitzer setzen. Ist das Geschenk für eine bestimmte Person, gib sie im letzten Schritt mit an, dann sieht sie es nicht:

```yaml
action: parcel_tracker.set_gift
data:
  number: "{{ number }}"
  gift: true
  gift_for:
    - person.b
```

## HTTP-Endpunkt

`POST /api/parcel_tracker/import_mail` nimmt eine einzelne Mail entgegen. Siehe [Mail per HTTP übergeben](mail-import.md#ohne-postfach-mail-per-http-ubergeben).

## Diagnose

Die Diagnose lädst du unter **Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen** herunter.

**Die Diagnose enthält:**

- die Version der Integration und das eingestellte Land,
- ob „Namen ausblenden“ eingeschaltet ist und ob „Absendernamen aus DHL-Mails übernehmen“ eingeschaltet ist (und je Paket, ob sein Name von Hand vergeben wurde – nie den Namen selbst),
- die Einstellungen ohne Geheimnisse,
- je Paket Carrier, Modus, Status (auch, ob eine Bestellung ohne Zustellmail abgeschlossen wurde), Fehler und Zähler,
- den Zustand des Mail-Imports: Zeitpunkt des letzten Laufs, Wartezeit nach Fehlern, Zähler für erkannte und nicht erkannte Mails,
- ob ein eigener Ordner statt des Posteingangs gelesen wird – nie seinen Namen,
- ob ein anderer Port als 993 eingestellt ist – nie den Port selbst – und die gewählte Verbindung zum Mailserver,
- wie der Mail-Import Mails ablegt (Abschnitt `filing`): ob der Server MOVE und UIDPLUS kann, ob er NAMESPACE meldet, sein Präfix für eigene Ordner und das Trennzeichen (nur in den üblichen Schreibweisen wie `INBOX.` oder `INBOX/`, jede andere als `other`), ob die beiden Ablage-Ordner gefunden oder angelegt wurden und wo (oberste Ebene oder unter dem Posteingang), ob das Ablegen gerade scheitert und in welchem der beiden Ordner, welcher Fehler zuletzt auftrat (z. B. `folder_unavailable`, `move_refused`) – nie Ordnernamen oder Inhalte,
- ob der Mail-Import alte erkannte Mails löscht und wie viele zuletzt gelöscht wurden (Abschnitt `delete_processed`) – nie die eingestellten Tage oder Ordnernamen,
- zu den letzten zehn nicht erkannten Mails nur die Absender-Domain (bei unbekannten Absendern nur `other`; bei einer Weiterleitung die Domain des ursprünglichen Absenders, wenn der Import ihn kennt) und ob die Mail weitergeleitet war,
- den IMAP-Server nur, wenn er zu einem öffentlichen Mailanbieter gehört (z. B. mailbox.org, GMX, Gmail); ein eigener Server steht nur als `custom` drin,
- bei Benachrichtigungen nur die Anzahl der Ziele (getrennt nach Entitäten und klassischen Diensten, nie ihre Namen) und die gewählten Ereignisse.

Home Assistant ergänzt die Datei selbst um Systeminformationen (Version, Installationsart, Betriebssystem) und die Liste der installierten benutzerdefinierten Integrationen.

**Die Diagnose enthält nie:** API-Keys, Passwörter, das UPS-Secret, den 17track-Key, den IMAP-Benutzer, den Namen des gelesenen Ordners, die PLZ, Paketnamen und Artikeltitel, Zustell-Codes, Orte, Ereignistexte, Betreffzeilen und Mail-Inhalte.

Sendungs- und Bestellnummern stehen nur maskiert drin: Ziffern werden zu `9`, Buchstaben zu `A`, Länge und Präfix bleiben (z. B. `JJD999999999999999999`). So lassen sich Erkennungsfehler trotzdem nachvollziehen.

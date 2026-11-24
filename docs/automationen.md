# Automationen

Für eigene Automationen gibt dir die Integration drei Bausteine:

- **Auslöser im Automations-Editor** – ohne YAML, für die wichtigsten Statuswechsel.
- **Die Events** `parcel_tracker_status_changed` und `parcel_tracker_arriving_soon` – für alles, was du von Hand baust.
- **Sensoren** – für Bedingungen wie „nur wenn heute ein Paket kommt“.

Fertige Beispiele zum Kopieren stehen unter [Rezepte](rezepte.md).

!!! warning "Doppelte Meldungen vermeiden"
    Hast du [Benachrichtigungen](benachrichtigungen.md) in den Optionen eingeschaltet und lässt zusätzlich eine Automation mit diesen Auslösern benachrichtigen, bekommst du die Meldung zweimal.

## Auslöser ohne YAML

Seit v0.3.27 gibt es fertige Auslöser im Automations-Editor. Du musst das Event nicht von Hand eintragen.

### Wo du sie findest

1. **Einstellungen → Automationen & Szenen → Automation erstellen**.
2. **Auslöser hinzufügen** → „Gerät“.
3. Als Gerät „Paket Tracker“ wählen.
4. Den Auslöser wählen.

Derselbe Weg geht über **Einstellungen → Geräte & Dienste → Paket Tracker**: Dort steht der Dienst „Paket Tracker“ mit dem Abschnitt „Automationen“.

Dieser Dienst ist seit v0.3.27 da. Sensoren und Kalender hängen bewusst nicht an ihm; ihre Namen und Entitäts-IDs sind unverändert.

### Die Auslöser

| Auslöser | Feuert, wenn |
|---|---|
| **Paket wurde bestellt** | ein Shop die Bestellung bestätigt hat (neuer Status `pre_transit` bei einer Shop-Bestellung) |
| **Paket wurde angekündigt** | ein Paketdienst das Paket kennt (neuer Status `pre_transit` bei einem Paketdienst) |
| **Paket ist unterwegs** | der neue Status „Unterwegs“ ist |
| **Paket ist im Zustelldepot** | der neue Status „Im Zustelldepot“ ist |
| **Paket ist in Zustellung** | der neue Status „In Zustellung“ ist |
| **Paket kommt gleich** | der Paketdienst die Zustellung in den nächsten Minuten ankündigt (DHL „wird gleich zugestellt“, Event [`parcel_tracker_arriving_soon`](#das-event-parcel_tracker_arriving_soon)) |
| **Paket wurde zugestellt** | der neue Status „Zugestellt“ ist und der Paketdienst oder eine Mail die Zustellung gemeldet hat |
| **Paket liegt zur Abholung bereit** | das Paket in Packstation, Filiale oder PaketShop liegt |
| **Problem bei einem Paket** | der Paketdienst ein Problem meldet |
| **Bestellung wurde storniert** | der Shop die Bestellung storniert hat |
| **Paketstatus hat sich geändert** | bei jedem Statuswechsel |

Die Auslöser feuern genau dann, wenn auch das Event `parcel_tracker_status_changed` feuert (bzw. für „Paket kommt gleich“ `parcel_tracker_arriving_soon`), und gelten für alle Pakete. Meldet eine Bestellung einen Status, der für ihr Paket schon gemeldet war (Feld `repeat`), feuert nur „Paketstatus hat sich geändert“.

### Daten des Pakets nutzen

Was das Event mitbringt, steht in der Automation unter `trigger.event.data` bereit. Zum Beispiel im Text einer Benachrichtigung:

```jinja
{{ trigger.event.data.name }} ({{ trigger.event.data.carrier_name }}) ist in Zustellung.
```

Meinst du nur bestimmte Pakete, ergänzt du eine Template-Bedingung, z. B.:

```jinja
{{ trigger.event.data.carrier == 'dhl' }}
```

Alle Felder stehen [weiter unten](#felder-des-events).

### Angenommene Zustellung (`assumed`)

Schließt die Integration eine Bestellung, für die keine „Zugestellt“-Mail kam (siehe [Bestellungen ohne Zustellmail](mail-import.md#bestellungen-ohne-zustellmail)), ist das Feld `assumed` auf `true`. Dasselbe gilt, wenn AliExpress eine Lieferung nur per Mail bestätigt („Lieferung bestätigt (laut AliExpress)“).

- **„Paket wurde zugestellt“ feuert dann nicht.** Niemand weiß, ob und wann das Paket ankam.
- **„Paketstatus hat sich geändert“ feuert auch dann.** `{{ trigger.event.data.assumed }}` sagt, ob es so ein Fall ist.

### Von Hand erhalten (`manual`)

Markierst du ein Paket von Hand als erhalten – mit dem Knopf [„Erhalten“](karte.md#erhalten) oder dem Dienst [`parcel_tracker.mark_delivered`](sensoren.md#parcel_trackermark_delivered) –, ist das Feld `manual` auf `true`.

- **„Paket wurde zugestellt“ feuert dann nicht.** Niemand hat geliefert, du hast es selbst gesagt.
- **„Paketstatus hat sich geändert“ feuert auch dann.** `{{ trigger.event.data.manual }}` sagt, ob es so ein Fall ist.
- Eine Benachrichtigung schickt die Integration dafür nicht, auch der Blueprint nicht – wenn er aktuell ist, siehe unten.

!!! warning "Blueprint nach dem Update einmal neu importieren"
    Home Assistant aktualisiert einen importierten Blueprint nicht von selbst. Der [Blueprint](benachrichtigungen.md#blueprint) prüft `assumed` seit v0.3.20 und `manual` seit v0.3.30.

    Hast du ihn vorher importiert, meldet deine Automation eine Markierung von Hand als „wurde zugestellt“ – bei einer Fassung vor v0.3.20 auch eine Bestellung, die ohne Zustellmail abgeschlossen wurde.

    Importier den Blueprint nach dem Update auf 0.3.30 oder neuer deshalb einmal neu: **Einstellungen → Automationen & Szenen → Blueprints**, im Menü des Blueprints **Blueprint erneut importieren**. Deine Automationen daraus bleiben und nutzen danach die neue Fassung.

    Eigene Automationen, die auf `new_status == delivered` filtern, brauchen dieselbe Prüfung als Bedingung:

    ```jinja
    {{ not trigger.event.data.assumed and not trigger.event.data.manual }}
    ```

## Das Event `parcel_tracker_status_changed`

Das Event feuert bei jedem Statuswechsel eines Pakets – egal, ob der neue Status vom Paketdienst oder aus einer Mail kommt.

- Legt eine Mail ein neues Paket an, feuert das Event mit seinem ersten Status und `old_status` gleich `unknown` (z. B. „Bestellt“ aus der Bestellbestätigung). Ein erster Status „Zugestellt“ feuert nur, wenn eine „Zugestellt“-Mail eines Paketdienstes ein neues Paket anlegt, einen Shop oder eine Firma nennt und höchstens 24 Stunden alt ist. Ein Paket, das du selbst anlegst, feuert für seinen ersten Status kein Event. Für neue Pakete gibt es zusätzlich das eigene Event [`parcel_tracker_parcel_added`](sensoren.md#event-beim-anlegen-parcel_tracker_parcel_added).
- Wechsel während eines Neustarts gehen nicht verloren: Das Event folgt genau einmal, sobald Home Assistant fertig gestartet ist, spätestens zwei Minuten nachdem die Integration geladen wurde. Mehrere Wechsel in dieser Zeit werden zu einem Event vom alten zum neuesten Status.

### Felder des Events

| Feld | Inhalt | Beispiel |
|---|---|---|
| `number` | Nummer des Pakets, wie sie die Integration führt | |
| `name` | Name des Pakets, wie er angezeigt wird, weitere Artikel als „(+2)“ dahinter (mit „Namen ausblenden“ der neutrale Name); kann leer sein | `Kopfhörer` |
| `carrier` | Kürzel des Paketdienstes oder Shops | `dhl` |
| `carrier_name` | Anzeigename wie am Sensor | `DHL` |
| `old_status` | vorheriger Status | `in_transit` |
| `new_status` | neuer Status | `out_for_delivery` |
| `event` | Ereignis wie in den Optionen und Auslösern: der neue Status, für `pre_transit` aber `ordered` (Shop-Bestellung) oder `announced` (Paketdienst); leer bei `unknown` | `ordered` |
| `eta_date` | Liefertag (ISO-Datum) oder leer | |
| `eta_from` | Beginn des Zeitfensters (ISO-Zeitpunkt) oder leer | |
| `eta_to` | Ende des Zeitfensters (ISO-Zeitpunkt) oder leer | |
| `location` | Ort, wenn bekannt | |
| `entry_id` | ID des Paket-Tracker-Eintrags (ab v0.3.27) | |
| `assumed` | `true`, wenn eine Bestellung ohne Zustellmail abgeschlossen wurde. Der neue Status ist dann `delivered`, zugestellt ist aber nur angenommen | `false` |
| `manual` | `true`, wenn das Paket von Hand als erhalten markiert wurde (ab v0.3.30). Der neue Status ist dann `delivered` | `false` |
| `owner` | Person, der das Paket gehört (Entität wie `person.anna`), oder leer, wenn es allen gehört (ab v0.3.41). Das ist der geltende Besitzer, auch die Standard-Person aus **Unklare Pakete gehören** | `person.anna` |
| `outgoing` | `true`, wenn du das Paket verschickt hast (ab v0.3.48, siehe [Versendete Pakete](mail-import.md#versendete-pakete-einlieferungsbelege)). `new_status` ist dann z. B. `delivered` oder `awaiting_pickup` beim Empfänger | `false` |
| `gift` | `true`, wenn das Paket ein Geschenk ist (ab v0.3.45). `name` ist dann der Geschenk-Name. Für wen es ist, steht nicht im Event | `false` |
| `repeat` | `true`, wenn der Status für das Paket schon gemeldet war: eine Bestellung hat ein gemeldetes Paket übernommen, oder eine weitere Bestellung liegt im selben Paket. Der Blueprint lässt sie aus, die eingebaute Benachrichtigung auch (außer für eine zweite Person mit eigenen Zielen, die ihre Bestellung im selben Paket hat). `repeat` gilt für das Paket, nicht für die Person: Filtert deine Automation nach `owner`, lass `repeat` dort unbeachtet, sonst fehlt die Bestellung der zweiten Person | `false` |

Kürzel in `carrier`: `dhl`, `dpd`, `gls`, `hermes`, `ups`, `amazon`, `ebay`, `aliexpress`, `eventim`, `other` (über 17track).

### Die Status

`old_status` und `new_status` tragen einen dieser Werte. Dieselben Werte sind der Zustand von `sensor.paket_<nummer>`.

| Wert | Anzeige |
|---|---|
| `pre_transit` | Angekündigt (bei Shop-Bestellungen zeigt die Karte „Bestellt“) |
| `in_transit` | Unterwegs |
| `at_delivery_depot` | Im Zustelldepot |
| `out_for_delivery` | In Zustellung |
| `awaiting_pickup` | Abholbereit |
| `delivered` | Zugestellt |
| `exception` | Problem |
| `cancelled` | Storniert (nur Shop-Bestellungen) |
| `unknown` | Unbekannt |

### Beispiel von Hand

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
      message: "{{ trigger.event.data.name or trigger.event.data.number }} ({{ trigger.event.data.carrier_name }}) ist in Zustellung."
```

Baust du selbst etwas auf „zugestellt“, prüf die angenommene Zustellung mit:

```jinja
{{ not trigger.event.data.assumed }}
```

## Das Event `parcel_tracker_arriving_soon`

Feuert, wenn der Paketdienst die Zustellung in den nächsten Minuten ankündigt (DHL-Mail „wird gleich zugestellt“), höchstens einmal am Tag pro Paket. Das ist kein Statuswechsel: Das Paket bleibt „In Zustellung“, `parcel_tracker_status_changed` feuert dafür nicht. Die Felder sind die des Status-Events ohne `old_status`, `new_status`, `eta_date`, `location`, `assumed`, `manual` und `repeat`; `event` ist `arriving_soon`, `eta_from` und `eta_to` sind das Zeitfenster aus der Mail (z. B. 14:02 bis 14:17 Uhr).

## Sensoren für Bedingungen

Diese Sensoren liefern je eine Zahl. Sie eignen sich für Bedingungen in Automationen und Dashboards (Zustand über 0).

| Sensor | Zählt |
|---|---|
| `sensor.pakete_heute` | Pakete, die heute sicher kommen: „In Zustellung“ oder fester Liefertag heute |
| `sensor.pakete_moeglich` | Pakete, deren Lieferspanne heute einschließt |
| `sensor.pakete_zugestellt_heute` | heute zugestellte Pakete |
| `sensor.pakete_abholbereit` | abholbereite Pakete (Packstation, Filiale, PaketShop) |
| `sensor.pakete_unterwegs` | alle Pakete, die noch nicht zugestellt sind – auch abholbereite, solche mit Problem oder unbekanntem Status |

Eine Bedingung „heute kommt etwas“ sieht so aus:

```yaml
conditions:
  - condition: numeric_state
    entity_id: sensor.pakete_heute
    above: 0
```

Welche Pakete es sind, steht im Attribut `parcels` jedes Sensors. Jeder Eintrag hat `number`, `name`, `carrier`, `eta_from` und `eta_to`. So liest du die Namen in einem Template:

```jinja
{{ state_attr('sensor.pakete_heute', 'parcels') | map(attribute='name') | select | join(', ') }}
```

Den Status eines einzelnen Pakets liest du aus `sensor.paket_<nummer>`. Alle Entitäten und Attribute stehen unter [Sensoren, Kalender und Dienste](sensoren.md).

## Geschenkmodus per Automation schalten

Ein Aufruf ohne Benutzer, wie ihn eine Automation macht, darf den Geschenkmodus ein- und ausschalten und Geschenke wieder sichtbar machen. Das ist der Weg, wenn niemand die Option „Wer darf Geschenke sehen?“ gewählt hat: Über die Oberfläche kann den Modus dann keiner mehr ausschalten. Wähle die Personen besser vorher. Hintergrund und Grenzen: [Geschenkmodus](datenschutz.md#geschenkmodus).

Beispiel: Vom 15. November bis zum 26. Dezember ist der Modus an, danach wieder aus. Pakete, die in dieser Zeit angelegt wurden, bleiben Geschenke.

```yaml
automation:
  - alias: "Geschenkmodus an (15. November)"
    triggers:
      - trigger: time
        at: "06:00:00"
    actions:
      - condition: template
        value_template: "{{ now().month == 11 and now().day == 15 }}"
      - action: switch.turn_on
        target:
          entity_id: switch.paket_tracker_geschenkmodus

  - alias: "Geschenkmodus aus (27. Dezember)"
    triggers:
      - trigger: time
        at: "06:00:00"
    actions:
      - condition: template
        value_template: "{{ now().month == 12 and now().day == 27 }}"
      - action: switch.turn_off
        target:
          entity_id: switch.paket_tracker_geschenkmodus
```

!!! warning "Jeder Benutzer kann eine Automation starten"
    Über „Aktionen ausführen“ oder `automation.trigger` startet jeder Benutzer eine Automation, ohne Auslöser und ohne die Bedingungen der Automation. Sie läuft dann ohne Benutzer und darf den Modus ausschalten. Deshalb steht die Datumsprüfung oben **in den `actions:`** (ein `condition`-Schritt: ein manueller Start bricht dort ab). Halte jede Automation, die den Modus ausschaltet oder Geschenke wieder sichtbar macht, mit einer solchen Prüfung in den Aktionen ab.

Auch alle schon offenen Pakete lassen sich per Automation verbergen:

```yaml
actions:
  - action: parcel_tracker.set_gift
    data:
      open_parcels: true
      gift: true
```

## Kalender

`calendar.pakete` zeigt die erwarteten Zustelltermine. Du kannst ihn wie jeden Kalender in Home Assistant als Auslöser nutzen. Was in den Terminen steht, findest du unter [Kalender](sensoren.md#kalender).

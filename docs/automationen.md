# Automationen

Für eigene Automationen gibt dir die Integration drei Bausteine:

- **Auslöser im Automations-Editor** – ohne YAML, für die wichtigsten Statuswechsel.
- **Das Event** `parcel_tracker_status_changed` – für alles, was du von Hand baust.
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

### Die fünf Auslöser

| Auslöser | Feuert, wenn |
|---|---|
| **Paket ist in Zustellung** | der neue Status „In Zustellung“ ist |
| **Paket wurde zugestellt** | der neue Status „Zugestellt“ ist und die Zustellung bestätigt ist |
| **Paket liegt zur Abholung bereit** | das Paket in Packstation, Filiale oder PaketShop liegt |
| **Problem bei einem Paket** | der Paketdienst ein Problem meldet |
| **Paketstatus hat sich geändert** | bei jedem Statuswechsel, auch denen ohne eigenen Auslöser (z. B. „Unterwegs“) |

Die Auslöser feuern genau dann, wenn auch das Event `parcel_tracker_status_changed` feuert, und gelten für alle Pakete.

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

Schließt die Integration eine Bestellung, für die keine „Zugestellt“-Mail kam (siehe [Bestellungen ohne Zustellmail](mail-import.md#bestellungen-ohne-zustellmail)), ist das Feld `assumed` auf `true`.

- **„Paket wurde zugestellt“ feuert dann nicht.** Niemand weiß, ob und wann das Paket ankam.
- **„Paketstatus hat sich geändert“ feuert auch dann.** `{{ trigger.event.data.assumed }}` sagt, ob es so ein Fall ist.

## Das Event `parcel_tracker_status_changed`

Das Event feuert bei jedem Statuswechsel eines Pakets – egal, ob der neue Status vom Paketdienst oder aus einer Mail kommt.

- Der allererste Status eines neuen Pakets feuert kein Event.
- Wechsel während eines Neustarts gehen nicht verloren: Das Event folgt genau einmal, sobald Home Assistant fertig gestartet ist, spätestens zwei Minuten nachdem die Integration geladen wurde. Mehrere Wechsel in dieser Zeit werden zu einem Event vom alten zum neuesten Status.

### Felder des Events

| Feld | Inhalt | Beispiel |
|---|---|---|
| `number` | Nummer des Pakets, wie sie die Integration führt | |
| `name` | Name des Pakets, wie er angezeigt wird (mit „Namen ausblenden“ der neutrale Name); kann leer sein | `Kopfhörer` |
| `carrier` | Kürzel des Paketdienstes oder Shops | `dhl` |
| `carrier_name` | Anzeigename wie am Sensor | `DHL` |
| `old_status` | vorheriger Status | `in_transit` |
| `new_status` | neuer Status | `out_for_delivery` |
| `eta_date` | Liefertag (ISO-Datum) oder leer | |
| `eta_from` | Beginn des Zeitfensters (ISO-Zeitpunkt) oder leer | |
| `eta_to` | Ende des Zeitfensters (ISO-Zeitpunkt) oder leer | |
| `location` | Ort, wenn bekannt | |
| `entry_id` | ID des Paket-Tracker-Eintrags (ab v0.3.27) | |
| `assumed` | `true`, wenn eine Bestellung ohne Zustellmail abgeschlossen wurde. Der neue Status ist dann `delivered`, zugestellt ist aber nur angenommen | `false` |

Kürzel in `carrier`: `dhl`, `dpd`, `gls`, `hermes`, `ups`, `amazon`, `ebay`, `aliexpress`, `other` (über 17track).

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

## Kalender

`calendar.pakete` zeigt die erwarteten Zustelltermine. Du kannst ihn wie jeden Kalender in Home Assistant als Auslöser nutzen. Was in den Terminen steht, findest du unter [Kalender](sensoren.md#kalender).

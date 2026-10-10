# Rezepte

Zehn fertige Beispiele zum Kopieren. Jedes Rezept sagt, wofür es gut ist, zeigt das YAML und nennt, was du anpassen musst.

## So benutzt du ein Rezept

**Automation:**

1. **Einstellungen → Automationen & Szenen → Automation erstellen** → neue, leere Automation.
2. Im Editor über das Menü (⋮) oben rechts auf die YAML-Ansicht umschalten.
3. Das YAML aus dem Rezept einfügen.
4. Die Platzhalter ersetzen (siehe „Anpassen“ beim Rezept) und speichern.

**Dashboard-Karte:** Dashboard bearbeiten → Karte hinzufügen → ganz unten „Manuell“ wählen und das YAML einfügen.

!!! info "Platzhalter"
    Diese Namen gibt es bei dir nicht. Ersetz sie durch deine eigenen Entitäten und Dienste:

    | Platzhalter | Ersetzen durch |
    |---|---|
    | `notify.mobile_app_dein_handy` | den Benachrichtigungsdienst deines Handys |
    | `binary_sensor.paketbox_klappe` | den Kontakt an deiner Paketbox oder deinem Briefkasten |
    | `binary_sensor.einfahrt_lieferwagen` | deinen eigenen Sensor, der ein Lieferfahrzeug erkennt |
    | `light.paket_led` | dein Licht oder deine LED |
    | `tts.dein_tts_dienst` | deine Sprachausgabe |
    | `media_player.dein_lautsprecher` | deinen Lautsprecher |

    Alles, was mit `sensor.pakete_`, `calendar.pakete` oder `parcel_tracker` beginnt, kommt von der Integration und bleibt, wie es ist.

!!! warning "Doppelte Meldungen"
    Hast du die [eingebauten Benachrichtigungen](benachrichtigungen.md) eingeschaltet, melden sie „in Zustellung“, „zugestellt“ und „abholbereit“ schon von selbst. Ein Rezept, das dasselbe meldet, verdoppelt die Meldung.

Die Namen von Entitäten, Attributen, Diensten und Event-Feldern in den Rezepten sind gegen den Code der Integration geprüft. Als ganze Automation mit echten Paketen ist nicht jedes Rezept durchgelaufen – probier ein Rezept aus, bevor du dich darauf verlässt.

## 1. Morgens ansagen, was heute kommt

**Wofür:** Du bekommst jeden Morgen eine Nachricht (oder eine Ansage), wie viele Pakete heute kommen und welche.

=== "Nachricht aufs Handy"

    ```yaml
    alias: "Pakete: Meldung am Morgen"
    triggers:
      - trigger: time
        at: "07:30:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.pakete_heute
        above: 0
    actions:
      - action: notify.mobile_app_dein_handy
        data:
          title: "Pakete heute"
          message: >-
            {% set pakete = state_attr('sensor.pakete_heute', 'parcels') or [] %}
            Heute {{ 'kommt 1 Paket' if pakete | count == 1 else 'kommen ' ~ (pakete | count) ~ ' Pakete' }}:
            {{ pakete | map(attribute='name') | map('default', 'Paket ohne Namen', true) | join(', ') }}
    mode: single
    ```

=== "Ansage über einen Lautsprecher"

    ```yaml
    alias: "Pakete: Ansage am Morgen"
    triggers:
      - trigger: time
        at: "07:30:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.pakete_heute
        above: 0
    actions:
      - action: tts.speak
        target:
          entity_id: tts.dein_tts_dienst
        data:
          media_player_entity_id: media_player.dein_lautsprecher
          message: >-
            {% set pakete = state_attr('sensor.pakete_heute', 'parcels') or [] %}
            Heute {{ 'kommt ein Paket' if pakete | count == 1 else 'kommen ' ~ (pakete | count) ~ ' Pakete' }}:
            {{ pakete | map(attribute='name') | map('default', 'ein Paket ohne Namen', true) | join(', ') }}
    mode: single
    ```

**Anpassen:**

- `07:30:00`: deine Uhrzeit.
- `notify.mobile_app_dein_handy` bzw. `tts.dein_tts_dienst` und `media_player.dein_lautsprecher`: deine eigenen.
- `sensor.pakete_heute` zählt nur, was heute **sicher** kommt („In Zustellung“ oder fester Liefertag heute). Morgens ist ein Paket oft noch nicht „In Zustellung“. Willst du auch die möglichen Pakete nennen, nimm zusätzlich `state_attr('sensor.pakete_heute', 'possible_count')`.
- Mit eingeschaltetem „Namen ausblenden“ nennt die Meldung nur neutrale Namen wie „DHL-Paket …2557“.

## 2. Paketbox geht auf: welches Paket war das?

**Wofür:** Die Klappe deiner Paketbox oder deines Briefkastens geht auf. Ist genau ein Paket „In Zustellung“, nennt die Meldung dieses Paket. Sonst kommt eine allgemeine Meldung.

```yaml
alias: "Paketbox: Klappe geöffnet"
triggers:
  - trigger: state
    entity_id: binary_sensor.paketbox_klappe
    from: "off"
    to: "on"
variables:
  in_zustellung: >-
    {{ integration_entities('parcel_tracker')
       | select('is_state', 'out_for_delivery') | list }}
actions:
  - choose:
      - conditions:
          - condition: template
            value_template: "{{ in_zustellung | count == 1 }}"
        sequence:
          - action: notify.mobile_app_dein_handy
            data:
              title: "Paketbox"
              message: >-
                Die Paketbox wurde geöffnet – vermutlich für
                {{ state_attr(in_zustellung[0], 'name') or 'dein Paket' }}
                ({{ state_attr(in_zustellung[0], 'carrier_name') }}).
    default:
      - action: notify.mobile_app_dein_handy
        data:
          title: "Paketbox"
          message: "Die Paketbox wurde geöffnet."
mode: single
```

**Anpassen:**

- `binary_sensor.paketbox_klappe`: dein Kontakt. Meldet er „offen“ anders als mit `on`, pass `from` und `to` an.
- `notify.mobile_app_dein_handy`: dein Benachrichtigungsdienst.

**So funktioniert es:** Die Variable `in_zustellung` sammelt alle Paket-Sensoren der Integration mit dem Zustand `out_for_delivery`. Die Meldung ist eine Vermutung: Ob wirklich dieses Paket in der Box liegt, weiß die Integration nicht. „Zugestellt“ meldet der Paketdienst oft erst später.

## 3. Abends an die Abholung erinnern

**Wofür:** Liegt abends noch etwas in der Packstation, der Filiale oder im PaketShop, bekommst du eine Erinnerung.

```yaml
alias: "Pakete: Erinnerung an die Abholung"
triggers:
  - trigger: time
    at: "18:00:00"
conditions:
  - condition: numeric_state
    entity_id: sensor.pakete_abholbereit
    above: 0
actions:
  - action: notify.mobile_app_dein_handy
    data:
      title: "Paket abholen"
      message: >-
        Abholbereit ({{ states('sensor.pakete_abholbereit') }}):
        {{ state_attr('sensor.pakete_abholbereit', 'parcels')
           | map(attribute='name') | map('default', 'Paket ohne Namen', true) | join(', ') }}
mode: single
```

**Anpassen:**

- `18:00:00`: deine Uhrzeit.
- `notify.mobile_app_dein_handy`: dein Benachrichtigungsdienst.
- Nur an bestimmten Tagen? Ergänz unter `conditions` eine Zeit-Bedingung mit Wochentagen.

Wo das Paket liegt und bis wann, steht – wenn der Paketdienst es nennt – in den Attributen `pickup_point` und `pickup_until` von `sensor.paket_<nummer>`.

## 4. Licht als Anzeige: heute kommt noch etwas

**Wofür:** Eine LED oder ein Licht leuchtet, solange heute noch ein Paket erwartet wird. Ist alles zugestellt, geht es aus.

```yaml
alias: "Pakete: Anzeige-Licht"
triggers:
  - trigger: state
    entity_id: sensor.pakete_heute
  - trigger: homeassistant
    event: start
actions:
  - if:
      - condition: numeric_state
        entity_id: sensor.pakete_heute
        above: 0
    then:
      - action: light.turn_on
        target:
          entity_id: light.paket_led
        data:
          color_name: orange
          brightness_pct: 40
    else:
      - action: light.turn_off
        target:
          entity_id: light.paket_led
mode: restart
```

**Anpassen:**

- `light.paket_led`: dein Licht. Kann es keine Farbe, lösch die Zeile `color_name`.
- Für einen Schalter oder die LED eines Tasters nimmst du `switch.turn_on` und `switch.turn_off` mit deiner Entität und ohne den Block `data`.
- Soll das Licht auch bei „möglichen“ Paketen leuchten, bau dieselbe Automation mit `sensor.pakete_moeglich`.

**So funktioniert es:** Ein zugestelltes Paket zählt bei `sensor.pakete_heute` nicht mehr mit. Der Sensor fällt auf 0, das Licht geht aus.

## 5. Karte nur zeigen, wenn etwas unterwegs ist

**Wofür:** Die Karte steht nur auf dem Dashboard, solange es etwas zu sehen gibt.

=== "Option der Karte (am einfachsten)"

    ```yaml
    type: custom:parcel-tracker-card
    show: active
    ```

    `active` zeigt die Karte, solange ein Paket noch nicht zugestellt ist. Mit `today` erscheint sie nur, wenn heute sicher etwas kommt oder schon zugestellt wurde, mit `today_possible` zusätzlich bei möglichen Paketen. Alle Werte: [Die Karte](karte.md#show-wann-die-karte-sichtbar-ist).

=== "Sichtbarkeit von Home Assistant"

    ```yaml
    type: custom:parcel-tracker-card
    visibility:
      - condition: numeric_state
        entity: sensor.pakete_unterwegs
        above: 0
    ```

=== "Bedingte Karte"

    ```yaml
    type: conditional
    conditions:
      - condition: numeric_state
        entity: sensor.pakete_unterwegs
        above: 0
    card:
      type: custom:parcel-tracker-card
    ```

**Anpassen:**

- Statt `sensor.pakete_unterwegs` passt auch `sensor.pakete_heute`, `sensor.pakete_moeglich`, `sensor.pakete_zugestellt_heute` oder `sensor.pakete_abholbereit`.
- Die beiden Wege über Home Assistant funktionieren auch für jede andere Karte, z. B. eine Kamera-Karte, die nur an Liefertagen erscheint.

## 6. Meldung nur für einen Paketdienst oder ein bestimmtes Paket

**Wofür:** Du willst nicht jede Meldung, sondern nur die für DHL – oder nur die für das eine Paket, auf das du wartest.

```yaml
alias: "Pakete: nur DHL in Zustellung"
triggers:
  - trigger: event
    event_type: parcel_tracker_status_changed
    event_data:
      new_status: out_for_delivery
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.carrier == 'dhl' }}"
actions:
  - action: notify.mobile_app_dein_handy
    data:
      title: "DHL kommt heute"
      message: >-
        {{ trigger.event.data.name or 'Ein Paket' }} ist in Zustellung.
mode: queued
```

**Anpassen:**

- `notify.mobile_app_dein_handy`: dein Benachrichtigungsdienst.
- Anderer Paketdienst: `dhl` ersetzen durch `dpd`, `gls`, `hermes` oder `ups`. Shop-Bestellungen tragen `amazon`, `ebay` oder `aliexpress`.
- Anderer Status: `new_status` ändern, z. B. `delivered` oder `awaiting_pickup`. Alle Werte: [Die Status](automationen.md#die-status).
- Ein bestimmtes Paket nach Namen – ersetz die Bedingung durch:

    ```jinja
    {{ 'kopfhörer' in (trigger.event.data.name or '') | lower }}
    ```

- Ein bestimmtes Paket nach Nummer (hier eine erfundene):

    ```jinja
    {{ trigger.event.data.number == '00340999999999999901' }}
    ```

**Ohne YAML:** Statt des Event-Auslösers kannst du im Editor den Geräte-Auslöser „Paket ist in Zustellung“ wählen (siehe [Auslöser ohne YAML](automationen.md#ausloser-ohne-yaml)). Die Template-Bedingung bleibt dieselbe.

Bei „zugestellt“ von Hand: Ergänz die Bedingung `{{ not trigger.event.data.assumed }}`, damit eine nur angenommene Zustellung nichts meldet.

## 7. Lieferwagen vor dem Haus und ein Paket dieses Dienstes ist in Zustellung

**Wofür:** Deine Kamera erkennt ein Lieferfahrzeug. Die Meldung kommt nur, wenn wirklich ein Paket dieses Paketdienstes „In Zustellung“ ist.

!!! note "Die Erkennung musst du selbst mitbringen"
    Paket Tracker erkennt keine Fahrzeuge. Du brauchst eine eigene Erkennung, z. B. mit Frigate, die einen Sensor wie `binary_sensor.einfahrt_lieferwagen` liefert. Wie der Sensor bei dir heißt und ob er Paketdienste unterscheidet, hängt von deiner Einrichtung ab.

```yaml
alias: "Pakete: Lieferwagen erkannt"
triggers:
  - trigger: state
    entity_id: binary_sensor.einfahrt_lieferwagen
    to: "on"
conditions:
  - condition: template
    value_template: >-
      {% set ids = integration_entities('parcel_tracker')
         | select('is_state', 'out_for_delivery') | list %}
      {{ ids | select('is_state_attr', 'carrier', 'dhl') | list | count > 0
         or ids | select('is_state_attr', 'tracking_carrier', 'dhl') | list | count > 0 }}
actions:
  - action: notify.mobile_app_dein_handy
    data:
      title: "DHL ist da"
      message: "Ein Lieferwagen steht vor dem Haus, und ein DHL-Paket ist in Zustellung."
mode: single
```

**Anpassen:**

- `binary_sensor.einfahrt_lieferwagen`: der Sensor deiner eigenen Erkennung.
- `dhl` (zweimal): das Kürzel des Paketdienstes, den dein Sensor erkennt – `dhl`, `dpd`, `gls`, `hermes` oder `ups`.
- `notify.mobile_app_dein_handy`: dein Benachrichtigungsdienst.
- Erkennt dein Sensor nur „irgendein Lieferwagen“, nimm die einfachere Bedingung: `sensor.pakete_heute` über 0.

**So funktioniert es:** `carrier` ist der Paketdienst eines Pakets. Bei einer Shop-Bestellung, die eine Sendungsnummer übernommen hat, steht der Paketdienst in `tracking_carrier`. Die Bedingung prüft deshalb beide.

## 8. Geschenke: Namen ausblenden und einzelne Pakete umbenennen

**Wofür:** Auf dem Familien-Dashboard soll niemand lesen, was im Paket ist.

**Schritt 1 – Namen ausblenden:**

1. **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren**.
2. Den Schalter **Namen ausblenden** einschalten und speichern.

Jedes Paket heißt jetzt nur noch nach dem Paketdienst und den letzten vier Stellen seiner Nummer, z. B. `DHL-Paket …2557` oder `Amazon-Bestellung …4321` – auf der Karte, in den Sensoren, im Kalender, im Event und in den Benachrichtigungen.

**Schritt 2 – einzelne Pakete selbst benennen:** Ein Name, den du selbst vergibst, bleibt sichtbar. So erkennst du dein Paket wieder, ohne dass der Inhalt dasteht. Auf der Karte: Paket aufklappen → „Umbenennen“. Oder als Aktion:

```yaml
action: parcel_tracker.rename_parcel
data:
  number: "00340999999999999901"
  name: "Überraschung"
```

**Anpassen:**

- `number`: die Nummer deines Pakets (im Beispiel eine erfundene). Sie steht im Attribut `number` von `sensor.paket_<nummer>`.
- `name`: dein Name für das Paket.

**Grenzen:** Der Verlauf von Home Assistant behält, was er vor dem Einschalten aufgezeichnet hat. Der Knopf „Bestellung“ auf der Karte öffnet weiterhin die Bestellseite beim Shop. Der Schalter ist für den Blick aufs Dashboard gedacht, kein Schutz vor jemandem mit Admin-Zugang. Mehr unter [Namen ausblenden](datenschutz.md#namen-ausblenden).

## 9. Mail aus n8n übergeben

**Wofür:** Du hast Paketmails schon in n8n (oder Node-RED, einem Skript) und willst sie ohne eigenes Paket-Postfach an Paket Tracker geben.

**Vorbereitung:** In Home Assistant unter **Profil → Sicherheit** ein **langlebiges Zugriffstoken** anlegen.

**Einstellungen des HTTP-Request-Nodes:**

- **Methode:** `POST`
- **URL:** `http://homeassistant.local:8123/api/parcel_tracker/import_mail`
- **Kopfzeile:** Name `Authorization`, Wert `Bearer <Token>`
- **Body:** die komplette Mail als Binärdaten – der unveränderte Quelltext der Mail (RFC 822, `.eml`)
- **Kein Formular-Upload:** nicht als „Form-Data“ bzw. „multipart“ senden. Darauf antwortet Home Assistant mit 415.

**Was zurückkommt:** JSON mit `result` und `parcels`, z. B. `{"result": "recognized", "parcels": ["00340999999999999911"]}`. In n8n kannst du danach auf `result` verzweigen:

- `recognized`: gelesen und angewendet
- `unrecognized`: keine Sendung erkannt
- `ignored`: Werbung oder Konto-Mail
- `stale`: älter als 14 Tage
- `duplicate`: diese Mail wurde schon gelesen

**Anpassen:**

- `homeassistant.local:8123`: die Adresse deines Home Assistant, wie n8n ihn erreicht.
- `<Token>`: dein langlebiges Zugriffstoken. Leg es in n8n als Zugangsdaten ab, nicht im Klartext im Workflow.
- Dein Mail-Node muss die **rohe** Mail liefern, nicht nur Betreff und Text. Der Import braucht die Kopfzeilen (Absender, Datum, Message-ID).

Zum Testen ohne n8n:

```sh
curl -H "Authorization: Bearer <Token>" --data-binary @mail.eml \
  http://homeassistant.local:8123/api/parcel_tracker/import_mail
```

Alle Einzelheiten und Fehlercodes: [Mail per HTTP übergeben](mail-import.md#ohne-postfach-mail-per-http-ubergeben).

## 10. Markdown-Karte: die Pakete von heute als Liste

**Wofür:** Eine schlichte Liste der heutigen Pakete, z. B. für ein Wand-Tablet oder als Zeile in einer bestehenden Übersicht.

```yaml
type: markdown
title: Pakete heute
content: |
  {% set heute = state_attr('sensor.pakete_heute', 'parcels') or [] %}
  {% set moeglich = state_attr('sensor.pakete_heute', 'possible') or [] %}
  {% set zugestellt = state_attr('sensor.pakete_heute', 'delivered_today') or [] %}
  {% if heute %}
  **Kommt heute:**
  {% for p in heute %}
  - {{ p.name or 'Paket' }}{% if p.eta_from and p.eta_to %} – {{ as_timestamp(p.eta_from) | timestamp_custom('%H:%M') }}–{{ as_timestamp(p.eta_to) | timestamp_custom('%H:%M') }} Uhr{% endif %}
  {% endfor %}
  {% else %}
  Heute kommt sicher kein Paket.
  {% endif %}
  {% if moeglich %}

  **Möglich:** {{ moeglich | map(attribute='name') | map('default', 'Paket', true) | join(', ') }}
  {% endif %}
  {% if zugestellt %}

  **Schon zugestellt:** {{ zugestellt | map(attribute='name') | map('default', 'Paket', true) | join(', ') }}
  {% endif %}
```

**Anpassen:**

- `title`: deine Überschrift, oder die Zeile löschen.
- Die Blöcke „Möglich“ und „Schon zugestellt“ kannst du löschen, wenn du nur die sicheren Pakete willst.
- Das Zeitfenster erscheint nur, wenn der Paketdienst eines nennt.

**So funktioniert es:** Die Listen `parcels`, `possible` und `delivered_today` sind Attribute von `sensor.pakete_heute`. Jeder Eintrag hat `number`, `name`, `carrier`, `eta_from` und `eta_to`. Alle Attribute: [Sensoren, Kalender und Dienste](sensoren.md#sensorpakete_heute).

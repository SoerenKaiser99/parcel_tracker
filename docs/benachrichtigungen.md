# Benachrichtigungen

Die Integration schickt bei einem Statuswechsel selbst eine Benachrichtigung – über die Benachrichtigungswege von Home Assistant. Eine Automation brauchst du dafür nicht.

Es gibt zwei Wege:

- **Eingebaut (Optionen):** Ziele und Ereignisse ankreuzen, fertig. Der Text ist fest.
- **Blueprint:** für eigene Texte, eigene Bedingungen und die Extras der Home-Assistant-App.

!!! warning "Nur einen Weg einschalten"
    Schaltest du Benachrichtigungen in den Optionen ein und zusätzlich über den Blueprint oder eine eigene Automation, bekommst du jede Meldung zweimal.

## Eingebaute Benachrichtigungen

### Einrichten

1. **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren** öffnen und den Bereich „Benachrichtigungen“ aufklappen.
2. **Ziele:** ein oder mehrere Ziele aus der Liste wählen. Ohne Ziel wird nichts gesendet.
3. **Ereignisse:** ankreuzen, wobei benachrichtigt wird.

Der Schalter „Benachrichtigungen aktiv“ schaltet sich mit dem ersten Ziel von selbst ein. Schaltest du ihn ein, ohne ein Ziel zu wählen, bekommst du einen Hinweis im Formular. Ausschalten (oder alle Ziele entfernen) beendet die Benachrichtigungen.

### Ziele

Home Assistant kennt zwei Arten von Zielen. Beide stehen in derselben Auswahl und lassen sich mischen:

- **Benachrichtigungs-Entitäten** (`notify.…`): der neuere Weg. In der Auswahl stehen sie mit ihrem Namen, z. B. „Tablet Wohnzimmer“. Sie stehen oben in der Liste.
- **Klassische Dienste:** der ältere Weg, den viele Integrationen weiterhin nutzen – zum Beispiel Pushover. In der Auswahl stehen sie als „Dienst notify.…“, z. B. „Dienst notify.pushover“. Der Sammeldienst `notify.notify` steht am Ende der Liste.

**Home-Assistant-App:** Das Handy steht als „Dienst notify.mobile_app_&lt;gerät&gt;“ in der Auswahl, je nach Home-Assistant-Version zusätzlich als Entität. Gibt es für dasselbe Gerät beides, wähl nur eines von beiden – sonst kommt jede Meldung doppelt. Über den klassischen Dienst ersetzt eine neue Meldung die frühere zum selben Paket (siehe [Frühere Meldung ersetzen](#fruhere-meldung-ersetzen)).

**Pushover:** Richte Pushover zuerst in Home Assistant als Integration ein (**Einstellungen → Geräte & Dienste → Integration hinzufügen → Pushover**). Erst danach gibt es den Dienst. Er erscheint in der Auswahl als „Dienst notify.&lt;name&gt;“ – mit dem Namen, den du der Pushover-Integration gegeben hast. Dasselbe gilt für andere Integrationen, die nur einen klassischen Dienst mitbringen.

**Ziel verschwunden:** Ein gewähltes Ziel, das es in Home Assistant nicht mehr gibt (Gerät entfernt, Integration gelöscht oder gerade nicht geladen), bleibt gewählt und steht mit dem Zusatz „nicht mehr vorhanden“ in der Auswahl, bis du es abwählst. Beim Senden wird es übersprungen, ebenso ein Ziel, das gerade nicht verfügbar ist.

### Ereignisse

| Ereignis | Voreingestellt (ab v0.3.26) |
|---|---|
| In Zustellung | ja |
| Zugestellt | ja |
| Abholbereit | ja |
| Problem | nein |

Hast du die Benachrichtigungen schon vor v0.3.26 eingerichtet, behältst du deine Auswahl.

### So sehen die Texte aus

Der Titel ist „Paket Tracker“, der Text eine Zeile:

| Ereignis | Beispiel |
|---|---|
| In Zustellung | `📦 Kopfhörer (DHL) ist in Zustellung – heute 14:00–16:00 Uhr` |
| Zugestellt | `✅ Kopfhörer (DHL) wurde zugestellt` |
| Abholbereit | `📍 Kopfhörer (DHL) liegt zur Abholung bereit – Bonn bis 06.10.` |
| Problem | `⚠️ Kopfhörer (DHL): Problem bei der Zustellung` |

- Das Zeitfenster steht nur da, wenn eines für heute bekannt ist.
- Ort der Filiale und letzter Abholtag stehen nur da, wenn der Paketdienst sie nennt.
- Genannt wird der Name des Pakets (bei Paketen aus Mails der Artikeltitel, höchstens 40 Zeichen).
- Hat ein Paket keinen Namen, steht dort `Paket …2557` mit den letzten vier Stellen der Nummer.
- Mit [Namen ausblenden](datenschutz.md#namen-ausblenden) steht dort statt eines Namens aus einer Mail `DHL-Paket …2557`, ohne den Paketdienst dahinter.

!!! info "Nie im Text"
    Der Zustell-Code, die vollständige Sendungsnummer, eine Adresse, ein Ablageort und die Ereignistexte des Paketdienstes stehen nie in einer Benachrichtigung. Eine Benachrichtigung verlässt Home Assistant (bei der App über den Push-Dienst von Apple oder Google), deshalb bleibt sie so knapp.

### Wann wird gesendet?

Gesendet wird genau dann, wenn auch das Event `parcel_tracker_status_changed` feuert – egal, ob der neue Status vom Paketdienst oder aus einer Mail kommt. Also nicht doppelt für denselben Status und nicht, wenn ein Paketdienst nach 17track mit einem älteren Stand antwortet.

- **Der allererste Status** eines neuen Pakets wird nie gemeldet.
- **Während eines Neustarts** geht nichts verloren: Wechselt ein Paket den Status, während Home Assistant neu startet oder die Integration neu lädt, folgen Event und Benachrichtigung genau einmal, sobald Home Assistant fertig gestartet ist – spätestens zwei Minuten nachdem die Integration geladen wurde. Nach einem Neuladen im laufenden Betrieb sofort.
- **Mehrere Wechsel** in dieser Zeit werden zu einer Meldung vom alten zum neuesten Status.
- **Angenommene Zustellung:** Schließt die Integration eine Amazon-, eBay- oder AliExpress-Bestellung, für die keine „Zugestellt“-Mail kam, feuert das Event mit dem Feld `assumed` auf `true`. Es geht aber keine Benachrichtigung raus – weder über die Optionen noch über den Blueprint.

Schlägt das Senden fehl, steht eine Warnung ohne Paketdaten im Log. Die Paketabfrage läuft unverändert weiter.

### Frühere Meldung ersetzen

Über den klassischen Dienst der Home-Assistant-App („Dienst notify.mobile_app_&lt;gerät&gt;“) ersetzt eine neue Meldung die frühere zum selben Paket. Auf dem Handy steht dann nur der neueste Stand statt „in Zustellung“ und „zugestellt“ untereinander.

Dafür schickt die Integration ein Kennzeichen mit (`data.tag`, ein Hash der Sendungsnummer, nie die Nummer selbst). Alle anderen Ziele bekommen nur Titel und Text.

### Was dieser Weg nicht kann

- Der Dienst `notify.send_message` für Benachrichtigungs-Entitäten kennt nur Titel und Text. Ersetzen geht darüber nicht.
- Dass sich beim Antippen ein Dashboard öffnet, geht nur über den Blueprint.
- Eigene Texte und eigene Bedingungen gehen nur über den Blueprint oder eine eigene Automation.

## Blueprint

Für eigene Texte, eigene Bedingungen und die Extras der Home-Assistant-App gibt es einen Blueprint.

### Importieren

[![Blueprint in Home Assistant importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FSoerenKaiser99%2Fparcel_tracker%2Fmain%2Fblueprints%2Fautomation%2Fparcel_tracker%2Fpaket_benachrichtigung.yaml)

Der Knopf importiert [`paket_benachrichtigung.yaml`](https://github.com/SoerenKaiser99/parcel_tracker/blob/main/blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml) aus dem Repository. HACS installiert Blueprints nicht mit.

Danach legst du unter **Einstellungen → Automationen & Szenen → Blueprints** eine Automation daraus an.

### Eingaben

| Eingabe | Bedeutung | Standard |
|---|---|---|
| **Status** | Bei welchen neuen Status benachrichtigt wird. Wählbar: Angekündigt, Unterwegs, Im Zustelldepot, In Zustellung, Abholbereit, Zugestellt, Problem. | In Zustellung, Zugestellt, Abholbereit |
| **Benachrichtigungsdienst** | Ein klassischer Dienst als Text, z. B. `notify.mobile_app_mein_handy`. | `notify.notify` |
| **Titel** | Überschrift der Benachrichtigung. | Paket Tracker |
| **Text** | Vorlage für den Text, siehe unten. | `{{ text }}` |
| **Dashboard-Pfad** (nur Home-Assistant-App) | Öffnet sich beim Antippen, z. B. `/lovelace/pakete` (`data.url` für iOS, `data.clickAction` für Android). Für andere Dienste leer lassen. | leer |
| **Frühere Meldung ersetzen** (nur Home-Assistant-App) | Eine neue Meldung ersetzt die frühere zum selben Paket (`data.tag`, ein Hash der Sendungsnummer, nie die Nummer selbst). | aus |
| **Zusätzliche Bedingungen** | Z. B. nur tagsüber oder nur, wenn jemand zu Hause ist. | keine |

Sind Dashboard-Pfad und Ersetzen nicht gesetzt, schickt der Blueprint nur Titel und Text und passt damit zu jedem Benachrichtigungsdienst.

### Variablen für den Text

| Variable | Inhalt |
|---|---|
| `name` | Name des Pakets; ohne Namen „Paket …“ und die letzten vier Stellen der Nummer |
| `carrier` | Anzeigename des Paketdienstes, z. B. DHL |
| `new_status` | neuer Status, z. B. `out_for_delivery` |
| `old_status` | vorheriger Status |
| `text` | der fertige Standardsatz, z. B. „Kopfhörer (DHL) ist in Zustellung“ |

Ein Beispiel für das Feld **Text**:

```jinja
{{ name }} kommt mit {{ carrier }}
```

Die Sendungsnummer, der Zustell-Code und der Ort stehen in keinem der voreingestellten Texte. Bestellungen, die ohne Zustellmail abgeschlossen wurden (`assumed`), meldet der Blueprint nicht.

Der Blueprint braucht Home Assistant 2024.10 oder neuer.

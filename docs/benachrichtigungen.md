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

### An wen geht die Meldung?

Sind [Personen eingerichtet](mail-import.md#pakete-personen-zuordnen), hängt das Ziel vom Besitzer des Pakets ab:

- Hat der Besitzer eigene Ziele (**Benachrichtigungen an** im Formular der Person), geht die Meldung nur dorthin.
- Hat er keine, oder gehört das Paket allen, gehen die Meldungen an die oben gewählten Ziele, wie ohne Personen.
- Liegen Bestellungen zweier Personen in einem Paket (gleiche Sendungsnummer), bekommt jede Person die Meldung einmal. Dieselbe Person bekommt sie nicht doppelt.

Welche Ereignisse gemeldet werden, gilt für alle gleich.

### Ereignisse

| Ereignis | Wann | Voreingestellt |
|---|---|---|
| Bestellt | Ein Shop hat die Bestellung bestätigt (Amazon, eBay, AliExpress, Eventim). | nein |
| Angekündigt | Ein Paketdienst kennt das Paket, es ist aber noch nicht unterwegs. | nein |
| Unterwegs | Das Paket ist verschickt oder auf dem Weg. Auch ein Zustellversuch oder eine Verspätung führt oft zurück auf „Unterwegs“. | nein |
| Im Zustelldepot | Das Paket liegt im Depot, aus dem zugestellt wird (nur über die Abfrage bei DHL, Hermes, GLS und DPD). | nein |
| In Zustellung | | ja |
| Kommt gleich | Der Paketdienst stellt in den nächsten Minuten zu (DHL-Mail „wird gleich zugestellt“). Kein eigener Status: Das Paket bleibt „In Zustellung“. Höchstens einmal am Tag pro Paket. | ja |
| Abholbereit | | ja |
| Zugestellt | | ja |
| Problem | | nein |
| Storniert | Der Shop hat die ganze Bestellung storniert. | ja |

Die Namen sind dieselben wie auf der Karte. „Bestellt“ und „Angekündigt“ sind derselbe Status (`pre_transit`): „Bestellt“ gilt für Bestellungen bei einem Shop, „Angekündigt“ für Pakete eines Paketdienstes.

Die frühen Ereignisse (Bestellt bis Im Zustelldepot) kommen oft, manche Paketdienste springen zwischen „Unterwegs“ und „Im Zustelldepot“ hin und her. Sind es dir zu viele Meldungen, nimm den Haken dort einfach wieder heraus.

„Kommt gleich“ kommt auch ohne Haken bei „In Zustellung“. Bringt erst diese Mail das Paket in Zustellung, kommt mit beiden Haken nur „Kommt gleich“, nicht zwei Meldungen hintereinander. DHL schickt die Mail oft zweimal innerhalb weniger Minuten: Die zweite verschiebt nur das Zeitfenster. Wird die Mail erst gelesen, wenn ihre Minuten schon vorbei sind (Postfach spät abgerufen, Home Assistant war aus), kommt keine Meldung.

Hast du die Benachrichtigungen schon früher eingerichtet, behältst du deine Auswahl: Die neuen Ereignisse (auch „Storniert“ und „Kommt gleich“) sind dann nicht angehakt.

Für ein **versendetes Paket** (Einlieferungsbeleg, siehe [Versendete Pakete](mail-import.md#versendete-pakete-einlieferungsbelege)) kommt genau eine Meldung, wenn es beim Empfänger zugestellt ist oder zur Abholung bereitliegt, und nur, wenn „Zugestellt“ gewählt ist. Sie lautet „✅ Dein verschicktes Paket … wurde zugestellt“ bzw. „✅ Dein verschicktes Paket … liegt beim Empfänger zur Abholung bereit“. Andere Meldungen gibt es für versendete Pakete nicht. Die Ankunft sieht die Integration nur mit [DHL-API-Key](dienste.md#dhl-api-key-anlegen) oder nach „Details über 17track holen“ auf der Karte. Ohne beides bleibt das Paket auf „unterwegs“, und die Meldung kommt nie.

### So sehen die Texte aus

Der Titel ist „Paket Tracker“, der Text eine Zeile:

| Ereignis | Beispiel |
|---|---|
| Bestellt | `🛒 Kopfhörer (Amazon) wurde bestellt` |
| Angekündigt | `📋 Kopfhörer (DHL) ist angekündigt` |
| Unterwegs | `🚚 Kopfhörer (DHL) ist unterwegs` |
| Im Zustelldepot | `🏭 Kopfhörer (DHL) ist im Zustelldepot` |
| In Zustellung | `📦 Kopfhörer (DHL) ist in Zustellung – heute 14:00–16:00 Uhr` |
| In Zustellung, mit Zoll | `📦 Kopfhörer (DHL) ist in Zustellung – Einfuhrabgaben 12,34 € bar bereithalten` |
| Kommt gleich | `🔔 Kopfhörer (DHL) wird gleich zugestellt – bis 14:17 Uhr` |
| Abholbereit | `📍 Kopfhörer (DHL) liegt zur Abholung bereit – Bonn bis 06.10.` |
| Zugestellt | `✅ Kopfhörer (DHL) wurde zugestellt` |
| Problem | `⚠️ Kopfhörer (DHL): Problem bei der Zustellung` |
| Storniert | `❌ Kopfhörer (Amazon) wurde storniert` |

Hat die Mail eigene Worte für den Status, stehen sie statt des Satzes da, z. B. `🚚 Kopfhörer (Amazon): Zustellung versucht`. Das gilt nur für diese festen Begriffe: „Zustellung versucht“, „Lieferung verspätet“, „Lieferprobleme“ (Amazon, eBay), „Versandbereit“, „Dem Versandunternehmen übergeben“, „Zollabfertigung beendet“ (AliExpress) und „Verpackung beschädigt“ (DHL). Der Betreff einer Mail oder der Text eines Paketdienstes steht nie in einer Benachrichtigung.

- Das Zeitfenster steht nur da, wenn eines für heute bekannt ist.
- Einfuhrabgaben (Zoll) stehen nur bei „In Zustellung“ und „Kommt gleich“ da, und nur wenn eine DHL-Mail den Betrag genannt hat: `Einfuhrabgaben 12,34 € bar bereithalten`, bei einer anderen Zahlart `Einfuhrabgaben 12,34 € bei Zustellung`. Sie stehen nach dem Zeitfenster. Ohne bekannten Betrag steht nichts da. Meldet die DHL-Abfrage (mit API-Key) „In Zustellung“, bevor die Mail mit dem Betrag da ist, geht die Meldung ohne Zoll raus, und die spätere Mail löst keine zweite aus; der Betrag steht dann trotzdem auf der Karte und in den Attributen.
- Abholort und letzter Abholtag stehen da, wenn der Paketdienst oder eine Abholmail sie nennt (Amazon „Paket zur Abholung bereit“, bei DHL nur der Abholort). Der Ort ist höchstens 40 Zeichen lang.
- Genannt wird der Name des Pakets (bei Paketen aus Mails der Artikeltitel, höchstens 40 Zeichen).
- Hat ein Paket keinen Namen, steht dort `Paket …2557` mit den letzten vier Stellen der Nummer.
- Mit [Namen ausblenden](datenschutz.md#namen-ausblenden) steht dort statt eines Namens aus einer Mail `DHL-Paket …2557`, ohne den Paketdienst dahinter.

!!! info "Nie im Text"
    Der Zustell-Code, die vollständige Sendungsnummer, eine Adresse, ein Ablageort und die Ereignistexte des Paketdienstes stehen nie in einer Benachrichtigung. Eine Benachrichtigung verlässt Home Assistant (bei der App über den Push-Dienst von Apple oder Google), deshalb bleibt sie so knapp.

### Wann wird gesendet?

Gesendet wird genau dann, wenn auch das Event `parcel_tracker_status_changed` feuert – egal, ob der neue Status vom Paketdienst oder aus einer Mail kommt. Also nicht doppelt für denselben Status und nicht, wenn ein Paketdienst nach 17track mit einem älteren Stand antwortet.

- **Ein neues Paket aus einer Mail** meldet seinen ersten Status, als Wechsel von `unknown`: Die Bestellbestätigung meldet „Bestellt“, die Versandmail eines Paketdienstes „Angekündigt“ oder „Unterwegs“. Das gilt auch beim ersten Lesen des Postfachs für alle Mails darin (höchstens 14 Tage alt); sind dann schon Ziele gewählt, kommt für jedes dieser Pakete eine Meldung.
- **Ein erster Status „Zugestellt“** wird nur gemeldet, wenn eine „Zugestellt“-Mail eines Paketdienstes ein neues Paket anlegt, einen Shop oder eine Firma nennt und höchstens 24 Stunden alt ist. Eine Mail über eine Zustellung von vor Tagen ist keine Neuigkeit.
- **Ein Paket, das du selbst anlegst** (auf der Karte oder über den Dienst `parcel_tracker.add_parcel`), meldet seinen ersten Status nicht. Eine Mail, die über den HTTP-Endpunkt kommt, zählt wie eine aus dem Postfach.
- **Während eines Neustarts** geht nichts verloren: Wechselt ein Paket den Status, während Home Assistant neu startet oder die Integration neu lädt, folgen Event und Benachrichtigung genau einmal, sobald Home Assistant fertig gestartet ist – spätestens zwei Minuten nachdem die Integration geladen wurde. Nach einem Neuladen im laufenden Betrieb sofort. Eine noch ausstehende Meldung wird mit dem Paket gespeichert: Sie übersteht auch ein erneutes Neuladen und einen weiteren Neustart, bevor sie gesendet wurde.
- **Mehrere Wechsel** in dieser Zeit werden zu einer Meldung vom alten zum neuesten Status.
- **Angenommene Zustellung:** Schließt die Integration eine Amazon-, eBay-, AliExpress- oder Eventim-Bestellung, für die keine „Zugestellt“-Mail kam („Abgeschlossen ohne Zustellbestätigung“, siehe [Bestellungen ohne Zustellmail](mail-import.md#bestellungen-ohne-zustellmail)), feuert das Event mit dem Feld `assumed` auf `true`. Es geht aber keine Benachrichtigung raus – weder über die Optionen noch über den Blueprint.
- **Von Hand erhalten:** Markierst du ein Paket mit [„Erhalten“](karte.md#erhalten) selbst als erhalten, feuert das Event mit dem Feld `manual` auf `true`. Eine Benachrichtigung gibt es auch dafür nicht.
- **Storniert:** Storniert ein Shop eine ganze Bestellung oder bringt der Paketdienst einen Amazon-Karton zurück („Zurück an Amazon“), feuert das Event mit `new_status` `cancelled`, und mit „Storniert“ kommt eine Benachrichtigung. Werden nur einzelne Artikel storniert (siehe [E-Mail-Import](mail-import.md#was-aus-welcher-mail-wird)), gibt es keine.
- **Mehrere Bestellungen in einem Paket** (AliExpress, Amazon): Das Event feuert für jede Bestellung, die Benachrichtigung aus den Optionen geht für das Paket einmal raus, an jede Person einmal. Dasselbe gilt, wenn eine Bestellung ein Paket übernimmt, dessen Status schon gemeldet war. Eine solche Wiederholung trägt im Event das Feld `repeat` auf `true`; der Blueprint und die [Geräte-Auslöser](automationen.md) der einzelnen Ereignisse lassen sie aus.
- **Kommt gleich** ist kein Statuswechsel und hat ein eigenes Event, `parcel_tracker_arriving_soon`, siehe [Automationen](automationen.md#das-event-parcel_tracker_arriving_soon). Kommt die Mail, während Home Assistant startet, folgen Event und Meldung nach dem Start, wenn das Zeitfenster dann noch läuft.

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
| **Status** | Bei welchen neuen Status benachrichtigt wird. Wählbar wie in den Optionen: Bestellt, Angekündigt, Unterwegs, Im Zustelldepot, In Zustellung, Kommt gleich, Abholbereit, Zugestellt, Problem, Storniert. | In Zustellung, Kommt gleich, Abholbereit, Zugestellt, Storniert |
| **Benachrichtigungsdienst** | Ein klassischer Dienst als Text, z. B. `notify.mobile_app_mein_handy`. | `notify.notify` |
| **Titel** | Überschrift der Benachrichtigung. | Paket Tracker |
| **Text** | Vorlage für den Text, siehe unten. | `{{ text }}` |
| **Dashboard-Pfad** (nur Home-Assistant-App) | Öffnet sich beim Antippen, z. B. `/lovelace/pakete` (`data.url` für iOS, `data.clickAction` für Android). Für andere Dienste leer lassen. | leer |
| **Frühere Meldung ersetzen** (nur Home-Assistant-App) | Eine neue Meldung ersetzt die frühere zum selben Paket (`data.tag`, ein Hash der Sendungsnummer, nie die Nummer selbst). | aus |
| **Zusätzliche Bedingungen** | Z. B. nur tagsüber oder nur, wenn jemand zu Hause ist. | keine |

Sind Dashboard-Pfad und Ersetzen nicht gesetzt, schickt der Blueprint nur Titel und Text und passt damit zu jedem Benachrichtigungsdienst.

Hast du unter **Status** nie etwas geändert, gilt nach dem erneuten Import der neue Standard: Dann meldet die Automation auch „Storniert“ und „Kommt gleich“. Willst du das nicht, nimm den Haken dort heraus. Eine Automation mit „Angekündigt“ aus einer älteren Fassung meldet weiterhin Bestellt und Angekündigt.

### Variablen für den Text

| Variable | Inhalt |
|---|---|
| `name` | Name des Pakets, weitere Artikel als „(+2)“ dahinter; ohne Namen „Paket …“ und die letzten vier Stellen der Nummer |
| `carrier` | Anzeigename des Paketdienstes, z. B. DHL |
| `new_status` | neuer Status, z. B. `out_for_delivery`; leer bei „Kommt gleich“ |
| `event` | das Ereignis wie unter **Status**: der neue Status, für `pre_transit` aber `ordered` (Bestellt) oder `announced` (Angekündigt), `arriving_soon` für „Kommt gleich“ |
| `old_status` | vorheriger Status; leer bei „Kommt gleich“ |
| `text` | der fertige Standardsatz, z. B. „Kopfhörer (DHL) ist in Zustellung“ oder „Kopfhörer (DHL) wird gleich zugestellt – bis 14:17 Uhr“ |
| `outgoing` | `true` bei einem versendeten Paket, sonst `false` |

Ein Beispiel für das Feld **Text**:

```jinja
{{ name }} kommt mit {{ carrier }}
```

Die Sendungsnummer, der Zustell-Code und der Ort stehen in keinem der voreingestellten Texte. Bestellungen, die ohne Zustellmail abgeschlossen wurden (`assumed`), Pakete, die von Hand als erhalten markiert wurden (`manual`), und Wiederholungen für ein schon gemeldetes Paket (`repeat`) meldet der Blueprint nicht.

Ein **versendetes Paket** (`outgoing`) meldet der Blueprint wie die Benachrichtigungen aus den Optionen nur bei der Ankunft und nur, wenn unter **Status** „Zugestellt“ gewählt ist: „✅ Dein verschicktes Paket … wurde zugestellt“ bzw. „✅ Dein verschicktes Paket … liegt beim Empfänger zur Abholung bereit“. Liegt es erst zur Abholung bereit und wird dann abgeholt, kommt nur die erste Meldung. Andere Status meldet er für versendete Pakete nicht.

!!! warning "Nach dem Update einmal neu importieren"
    Home Assistant aktualisiert einen importierten Blueprint nicht von selbst. Der Blueprint prüft `assumed` seit v0.3.20, `manual` seit v0.3.30 und `outgoing` seit v0.3.48. Eine Automation aus einer älteren Fassung meldet eine Markierung von Hand als „wurde zugestellt“ – vor v0.3.20 auch eine abgeschlossene Bestellung.

    Eine Automation aus einer Fassung vor v0.3.48 meldet ein versendetes Paket wie ein empfangenes, mit jedem gewählten Status.

    Importier den Blueprint nach dem Update auf 0.3.48 oder neuer einmal neu: **Einstellungen → Automationen & Szenen → Blueprints**, im Menü des Blueprints **Blueprint erneut importieren**. Deine Automationen daraus bleiben und nutzen danach die neue Fassung. Für eigene Automationen, die auf `new_status == delivered` filtern, steht die Bedingung unter [Automationen](automationen.md#von-hand-erhalten-manual).

Der Blueprint braucht Home Assistant 2024.10 oder neuer.

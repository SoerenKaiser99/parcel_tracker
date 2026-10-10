# Datenschutz

Paket Tracker läuft lokal in deinem Home Assistant. Es gibt kein Cloud-Konto und keinen fremden Tracking-Dienst, den du nicht selbst einschaltest. Diese Seite sagt, welche Angabe wohin geht und was nie gespeichert wird.

## Was geht wohin?

| Angabe | Geht an | Wann |
|---|---|---|
| Sendungsnummer | den jeweiligen Paketdienst (DHL, DPD, GLS, Hermes, mit eigenen Zugangsdaten UPS) | bei jeder Abfrage dieses Pakets |
| PLZ | nur DHL und GLS | zusammen mit der Sendungsnummer; ohne hinterlegte PLZ geht an GLS nur die Paketnummer |
| Sendungsnummer samt Carrier-Code | 17track | nur auf ausdrücklichen Wunsch („Details über 17track holen“, „Andere (über 17track)“, Dienst `parcel_tracker.track_17track`) |
| Text der Benachrichtigung | den Dienst des gewählten Benachrichtigungs-Ziels | nur mit eingeschalteten Benachrichtigungen |

An 17track gehen keine PLZ und kein Name. Adressen aus der 17track-Antwort verwirft die Integration, ohne sie zu speichern oder zu loggen.

Amazon-, eBay- und AliExpress-Bestellungen fragt die Integration nirgends ab. Es gibt keine Anmeldung beim Shop.

### Die eine Ausnahme: 12 Ziffern mit „Automatisch“

Eine 12-stellige Nummer, die du mit „Automatisch“ einträgst, kann zu DHL oder zu GLS gehören.

1. Mit DHL-Key geht sie zuerst an DHL.
2. Kennt DHL sie nicht – oder ist kein DHL-Key hinterlegt –, geht sie **einmal an GLS** (alle 12 Ziffern, ohne PLZ). Das passiert auch, wenn sie am Ende zu keinem GLS-Paket gehört.

Nummern aus Mails und Shop-Bestellungen gehen auf diesem Weg nie an GLS.

Willst du das vermeiden, wähl beim Hinzufügen den Paketdienst selbst statt „Automatisch“.

### Unbekannte Nummer mit DHL-Key

Passt eine mit „Automatisch“ eingetragene Nummer zu keinem Paketdienst, fragt die Integration mit DHL-Key einmal bei DHL nach. Kennt DHL die Sendung, wird sie ein DHL-Paket. Sonst bleibt der Paketdienst unbekannt.

## Zugangsdaten

Der DHL-Key, das IMAP-Passwort, die UPS-Zugangsdaten und der 17track-Key liegen in der Konfiguration von Home Assistant.

!!! danger "Nie das Hauptpostfach eintragen"
    Das IMAP-Passwort gibt Vollzugriff auf das Postfach. Trag nur ein eigenes Paket-Postfach ein, das ausschließlich Paketmails bekommt. Siehe [E-Mail-Import](mail-import.md).

## Was aus Mails übernommen wird – und was nie

**Übernommen wird nur:**

- Bestell- bzw. Sendungsnummer,
- ein auf 60 Zeichen gekürzter Artikeltitel,
- der Name eines Shops oder einer Firma – nur bis zur Rechtsform, nie der einer Privatperson und nie der Anzeigename eines Paketdienstes. Statt eines Händlernamens bei Amazon oder eBay steht nur „Amazon“ bzw. „eBay“,
- Status, Liefertag und Zeitfenster,
- der Versanddienstleister,
- nur mit eingeschalteter Option und nur im Arbeitsspeicher: der Zustell-Code.

**Nie in Attributen und nie im Log:**

- Adresse, Name, Telefonnummer,
- eBay-Käufer- und Verkäufernamen,
- Wunsch-Ablageort bzw. Abstellort,
- Referenzen und Preise,
- Mail-Inhalte.

Links in AliExpress-Mails (sie sagen, zu welcher Bestellung ein Packstück gehört) werden gelesen, nie aufgerufen.

Eine Mail, die du [per HTTP übergibst](mail-import.md#ohne-postfach-mail-per-http-ubergeben), geht nur an den Import und wird nicht gespeichert. Deshalb gibt es dafür bewusst keinen Dienst: Ein Dienstaufruf stünde samt Mail in der Recorder-Datenbank.

## Benachrichtigungen

Benachrichtigungen gehen an die gewählten Ziele und damit an deren Dienst (bei der Home-Assistant-App über den Push-Dienst von Apple oder Google).

**Sie enthalten nur:**

- den Namen bzw. Artikeltitel des Pakets (ohne Namen die letzten vier Stellen der Nummer),
- den Paketdienst,
- den Status,
- wenn bekannt: das heutige Zeitfenster oder Ort und letzten Abholtag der Filiale.

**Nie enthalten:** der Zustell-Code, die vollständige Sendungsnummer, eine Adresse, ein Ablageort.

Das Kennzeichen zum Ersetzen einer früheren Meldung (`data.tag`) ist ein Hash der Sendungsnummer, nie die Nummer selbst.

## Namen ausblenden

Für Geschenke auf einem gemeinsamen Dashboard: Unter **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren** gibt es den Schalter **Namen ausblenden** (Standard: aus).

Eingeschaltet heißt jedes Paket nur noch nach dem Paketdienst und den letzten vier Stellen seiner Nummer:

- `DHL-Paket …2557`
- `GLS-Paket …9977`
- `Amazon-Bestellung …4321`
- `eBay-Bestellung …0001`
- `AliExpress-Bestellung …0001`
- `Paket …2557`, wenn kein Paketdienst bekannt ist

Was im Paket ist und von wem es kommt, nennt die Integration dann nirgends mehr.

### Wo das gilt

| Stelle | Was neutral wird |
|---|---|
| Karte | Sie zeigt das Attribut `name` der Sensoren und braucht keine eigene Einstellung |
| Sensoren | der Name der Entität und das Attribut `name` von `sensor.paket_<nummer>`; die Listen `parcels`, `possible`, `delivered_today` und `awaiting_pickup` von `sensor.pakete_heute`; die Liste `parcels` der vier Zählsensoren |
| Kalender | die Termine in `calendar.pakete` |
| Event | das Feld `name` von `parcel_tracker_status_changed` – und damit auch der Blueprint und eigene Automationen |
| Benachrichtigungen | z. B. `✅ DHL-Paket …2557 wurde zugestellt` |

### Was sichtbar bleibt

- Der Paketdienst (auch der, den eine Shop-Mail nennt, z. B. „via Hermes“), die Nummer, Status, Liefertag, Ort und der Verlauf des Paketdienstes. Darin steht kein Artikel.
- Der Knopf „Bestellung“ auf der Karte öffnet weiterhin die Bestellseite beim Shop. Die zeigt den Artikel nur dem, der dort angemeldet ist.
- „Sendung verfolgen“ und das Attribut `tracking_url`: Darin steht nur die Nummer.

### Selbst eingetippte Namen bleiben sichtbar

Ein Name, den du über „Umbenennen“ auf der Karte, über den Dienst `parcel_tracker.rename_parcel` oder beim Hinzufügen eines Pakets vergibst, ist deine eigene Wahl (z. B. „Überraschung“). Er wird auch mit eingeschaltetem Schalter gezeigt. Ausgeblendet werden nur die Namen, die aus Mails stammen (Artikeltitel, Shop, Versender).

Bei Namen, die vor v0.3.24 vergeben wurden, weiß die Integration nicht, wer sie vergeben hat: Sie gelten als Namen aus Mails und werden ausgeblendet, bis du das Paket mit einem anderen Text neu benennst. „Umbenennen“ unverändert zu speichern ändert nichts.

### Die gespeicherten Daten bleiben

- Namen, Artikeltitel und alles, was das [Zusammenführen](mail-import.md#zusammenfuhren-carrier-mail-und-bestellung) braucht, stehen unverändert im Speicher der Integration. Mails werden weiter genauso zugeordnet.
- Schaltest du den Schalter wieder aus, sind die echten Namen sofort zurück.
- Beim Speichern lädt die Integration neu. Ein Neustart von Home Assistant ist nicht nötig.
- Die Entitäts-IDs entstehen aus der Nummer und ändern sich durch den Schalter nicht.

### Grenzen

!!! warning "Kein Schutz vor jemandem mit Admin-Zugang"
    - Der Verlauf von Home Assistant (Logbuch, Historie) behält, was er vor dem Einschalten aufgezeichnet hat – also auch die früheren Namen der Pakete, bis diese Einträge ablaufen oder du sie löschst.
    - Wer die Dateien von Home Assistant lesen kann, sieht dort auch die gespeicherten Namen.
    - Der Schalter ist für den Blick aufs Dashboard gedacht.

## Zustell-Codes

Manche Amazon-Lieferungen gibt der Fahrer nur gegen einen Code heraus (Einmalpasswort). Die Option **Zustell-Codes (Einmalpasswörter) mitlesen** im Bereich E-Mail-Import ist von Haus aus **aus**.

Mit eingeschalteter Option:

- Der Import liest den Code aus der Mail.
- Die Karte zeigt ihn verdeckt: erst „Code anzeigen“, dann die Rückfrage „Zustell-Code anzeigen?“. Beim Zuklappen verschwindet er wieder.
- Der Code steht im Attribut `delivery_code`.
- Er wird nie gespeichert, landet nie im Verlauf (Recorder) und verfällt nach dem Liefertag.
- Er steht nie in einer Benachrichtigung.

!!! warning "Verdeckt ist er nur auf der Karte"
    Wer Zugriff auf die Entitäts-Attribute oder die API von Home Assistant hat (Entwicklerwerkzeuge, Automationen, andere Dashboards, Apps), kann den Code im Klartext lesen.

Abholcodes aus DHL-Mails liest der Import nie.

## Diagnose

Der Diagnose-Download enthält keine Geheimnisse und keine Namen. Sendungs- und Bestellnummern stehen nur maskiert drin. Die vollständige Liste steht unter [Diagnose](sensoren.md#diagnose).

## Markenhinweis

DHL, DPD, Hermes, UPS, GLS, 17track, Amazon, eBay und AliExpress sind Marken ihrer Inhaber. Die Logos dienen nur zur Kennzeichnung des Paketdienstes. Dieses Projekt ist nicht mit den Unternehmen verbunden.

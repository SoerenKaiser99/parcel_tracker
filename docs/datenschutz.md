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

Amazon-, eBay-, AliExpress- und Eventim-Bestellungen fragt die Integration nirgends ab. Es gibt keine Anmeldung beim Shop.

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
- der Name eines Shops oder einer Firma – nur bis zur Rechtsform, nie der einer Privatperson und nie der Anzeigename eines Paketdienstes. Das gilt auch für die Absenderzeile „Von:“ einer UPS-Mail und den Versender in der Ankündigung von DPD. Statt eines Händlernamens bei Amazon oder eBay steht nur „Amazon“ bzw. „eBay“. Einzige Ausnahme ist die Option [Absendernamen aus DHL-Mails übernehmen](#absendernamen-aus-dhl-mails-ubernehmen), die du selbst einschalten musst,
- Status, Liefertag und Zeitfenster,
- bei einem abholbereiten Paket aus der Amazon-Mail „Paket zur Abholung bereit“: Name und Straße der Abholstelle (ohne Postleitzahl, Ort und interne Nummer des Shops) und der letzte Abholtag,
- bei einem abholbereiten Paket aus der Abholmail von DHL: Filiale bzw. Packstation und Straße (ohne Postleitzahl und Ort),
- der Versanddienstleister,
- nur mit eingeschalteter Option und nur im Arbeitsspeicher: der Zustell-Code.

**Nie in Attributen und nie im Log:**

- Adresse, Name, Telefonnummer,
- eBay-Käufer- und Verkäufernamen,
- Wunsch-Ablageort bzw. Abstellort,
- Referenzen und Preise,
- Mail-Inhalte.

Links in AliExpress-Mails (sie sagen, zu welcher Bestellung ein Packstück gehört) werden gelesen, nie aufgerufen. Aus Eventim-Mails nimmt der Import nur die Bestellnummer, den Namen der Veranstaltung, die Liefermethode und den Lieferzeitraum; Käufer, Adresse, Veranstaltungsort, Plätze und Preise liest er nicht.

Eine Mail, die du [per HTTP übergibst](mail-import.md#ohne-postfach-mail-per-http-ubergeben), geht nur an den Import und wird nicht gespeichert. Deshalb gibt es dafür bewusst keinen Dienst: Ein Dienstaufruf stünde samt Mail in der Recorder-Datenbank.

### Absendernamen aus DHL-Mails übernehmen

DHL nennt im Betreff den Absender: „Ihre <Name> Sendung kommt heute“. Von Haus aus wird dieser Name nur Name des Pakets, wenn er ein bekannter Shop ist oder eine Rechtsform trägt (GmbH, AG, OHG …). Ein kleiner Shop („Ihre Beispielshop .. Sendung …“) oder eine Privatperson bleibt ohne Namen: Das Paket heißt dann `DHL <Nummer>`.

Im Bereich **E-Mail-Import** gibt es dafür den Schalter **Absendernamen aus DHL-Mails ohne Firmenprüfung übernehmen** (Standard: **aus**). Eingeschaltet wird der Name aus dem Betreff genommen, auch bei kleinen Shops und Privatpersonen. Ein „..“ oder „…“, mit dem DHL einen langen Namen abschneidet, entfällt.

Was das für deine Daten heißt:

- Der Name einer **Privatperson** kann dann auf der Karte, im Kalender, in den Sensoren und in Benachrichtigungen stehen. Schalte ihn nur ein, wenn das für dein Dashboard in Ordnung ist.
- Gelesen wird **nur der Betreff** „Ihre … Sendung“. Nie die Anrede, nie eine Adresse, nie der Absender oder Namen aus anderen Stellen der Mail.
- Ein Name aus einer **von Hand weitergeleiteten** Mail wird nie übernommen, auch nicht mit dem Schalter.
- Ein Name, der einen Paketdienst nennt („DHL“, „DHL Paket“) oder keine Buchstaben enthält, wird nie übernommen.
- [Namen ausblenden](#namen-ausblenden) gilt weiter und geht vor: Dann zeigt auch ein so gewonnener Name nichts, es steht nur der neutrale Name da.
- Der Schalter ändert keine gespeicherten Namen. Er wirkt auf Mails, die danach gelesen werden.

## Benachrichtigungen

Benachrichtigungen gehen an die gewählten Ziele und damit an deren Dienst (bei der Home-Assistant-App über den Push-Dienst von Apple oder Google).

**Sie enthalten nur:**

- den Namen bzw. Artikeltitel des Pakets (ohne Namen die letzten vier Stellen der Nummer),
- den Paketdienst,
- den Status,
- wenn bekannt: das heutige Zeitfenster oder Ort und letzten Abholtag der Abholstelle (bei der Amazon-Abholmail Name und Straße des Shops, bei der DHL-Abholmail Filiale bzw. Packstation und Straße).

**Nie enthalten:** der Zustell-Code, die vollständige Sendungsnummer, deine Adresse, ein Ablageort.

Das Kennzeichen zum Ersetzen einer früheren Meldung (`data.tag`) ist ein Hash der Sendungsnummer, nie die Nummer selbst.

## Namen ausblenden

Für Geschenke auf einem gemeinsamen Dashboard: Unter **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren** gibt es den Schalter **Namen ausblenden** (Standard: aus).

Eingeschaltet heißt jedes Paket nur noch nach dem Paketdienst und den letzten vier Stellen seiner Nummer:

- `DHL-Paket …2557`
- `GLS-Paket …9977`
- `Amazon-Bestellung …4321`
- `eBay-Bestellung …0001`
- `AliExpress-Bestellung …0001`
- `Eventim-Bestellung …9901`
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

- Der Paketdienst (auch der, den eine Shop-Mail nennt, z. B. „via Hermes“), die Nummer (auf der Karte aufgeklappt als Sendungs- oder Bestellnummer), Status, Liefertag, Ort und der Verlauf des Paketdienstes. Darin steht kein Artikel.
- Das Symbol „Bestellung öffnen“ auf der Karte öffnet weiterhin die Bestellseite beim Shop. Die zeigt den Artikel nur dem, der dort angemeldet ist.
- „Sendung verfolgen“ und das Attribut `tracking_url`: Darin steht nur die Nummer, bei Amazon die Bestellnummer und Amazons Kennung der Sendung.

### Selbst eingetippte Namen bleiben sichtbar

Ein Name, den du über „Umbenennen“ auf der Karte, über den Dienst `parcel_tracker.rename_parcel` oder beim Hinzufügen eines Pakets vergibst, ist deine eigene Wahl (z. B. „Überraschung“). Er wird auch mit eingeschaltetem Schalter gezeigt. Ausgeblendet werden nur die Namen, die aus Mails stammen (Artikeltitel, Shop, Versender).

Bei Namen, die vor v0.3.24 vergeben wurden, weiß die Integration nicht, wer sie vergeben hat: Sie gelten als Namen aus Mails und werden ausgeblendet, bis du das Paket mit einem anderen Text neu benennst. „Umbenennen“ unverändert zu speichern ändert nichts.

### Die gespeicherten Daten bleiben

- Namen, Artikeltitel und alles, was das [Zusammenführen](mail-import.md#zusammenfuhren-carrier-mail-und-bestellung) braucht, stehen unverändert im Speicher der Integration. Mails werden weiter genauso zugeordnet.
- Schaltest du den Schalter wieder aus, sind die echten Namen sofort zurück.
- Beim Speichern lädt die Integration neu. Ein Neustart von Home Assistant ist nicht nötig.
- Die Entitäts-IDs (`sensor.paket_<nummer>`) entstehen aus der Nummer und ändern sich durch den Schalter nicht.
- Der Diagnose-Download enthielt noch nie Namen. Er nennt nur, ob der Schalter eingeschaltet ist.

### Grenzen

!!! warning "Kein Schutz vor jemandem mit Admin-Zugang"
    - Der Verlauf von Home Assistant (Logbuch, Historie) behält, was er vor dem Einschalten aufgezeichnet hat – also auch die früheren Namen der Pakete, bis diese Einträge ablaufen oder du sie löschst.
    - Wer die Dateien von Home Assistant lesen kann, sieht dort auch die gespeicherten Namen.
    - Der Schalter ist für den Blick aufs Dashboard gedacht.

## Geschenkmodus

Für Familien in der Weihnachtszeit: Während der Geschenkmodus läuft, zeigt das Dashboard nicht, was in einem neuen Paket steckt. Anders als „Namen ausblenden“ (alle Pakete, immer) gilt der Modus nur für Pakete, die man als Geschenk kennzeichnet, und nur bestimmte Personen sehen, was drin ist. Die Karte und ihre Bedienung stehen unter [Die Karte](karte.md#geschenkmodus).

### Wer was darf

Wer Geschenke sehen darf, legst du unter **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren** im Bereich **Geschenkmodus (optional)** fest: Das sind Personen von Home Assistant (`person`-Entitäten), die ein Benutzerkonto haben.

| Aktion | Wer darf das |
|---|---|
| Geschenkmodus einschalten, Pakete als Geschenk kennzeichnen | jeder |
| Geschenkmodus ausschalten | nur wer Geschenke sehen darf – und ein Aufruf ohne Benutzer (Automation) |
| Den echten Namen auf der Karte ansehen, ein Geschenk wieder sichtbar machen, umbenennen oder löschen | nur wer Geschenke sehen darf – und Aufrufe ohne Benutzer |

!!! warning "Wähle zuerst, wer Geschenke sehen darf"
    Ist niemand gewählt, kann den Modus über die Oberfläche **niemand** mehr ausschalten – nur eine Automation, siehe [Geschenkmodus per Automation schalten](automationen.md#geschenkmodus-per-automation-schalten). Lege die Personen deshalb fest, bevor du den Modus einschaltest.

!!! warning "Wandtablets und Kinder-Handys brauchen einen eigenen Benutzer"
    Home Assistant erkennt, wer die Karte öffnet, nur am angemeldeten Benutzer. Ein Wandtablet oder das Handy eines Kindes, das mit dem Konto der Eltern angemeldet ist, gilt als dieser Elternteil. Gib solchen Geräten einen **eigenen Benutzer** in Home Assistant, der nicht zu den Personen gehört, die Geschenke sehen dürfen.

### Was ein Geschenk verbirgt

Ein Geschenk heißt überall `Geschenk · DHL-Paket …2557` (der neutrale Name wie bei „Namen ausblenden“, mit dem Vorsatz „Geschenk · “). Das gilt für Karte, Sensoren, Kalender, Event und Benachrichtigungen. Das Kennzeichen gewinnt gegen „Namen ausblenden“ und gegen einen von Hand eingetippten Namen.

- **Verborgen:** der Name (auch ein von Hand vergebener), der Mail-Titel, die Links zur Sendungsverfolgung und zur Bestellung und Amazons Kennung der Sendung (`amazon_shipment`).
- **Sichtbar:** Status, Liefertag, Zeitfenster, Ort, Abholort und der Verlauf des Paketdienstes. Darin steht kein Artikel.
- **Benachrichtigungen** gehen an alle eingerichteten Ziele, mit dem Namen des Geschenks.

Einmal Geschenk, immer Geschenk: Das Kennzeichen bleibt, auch wenn der Modus ausgeschaltet wird und das Paket zugestellt ist. Es geht nur von Hand weg, über „Nicht mehr verbergen“ auf der Karte oder den Dienst [`parcel_tracker.set_gift`](sensoren.md#parcel_trackerset_gift), und das darf nur, wer Geschenke sehen darf.

Der echte Name kommt nur über eine Abfrage, die den angemeldeten Benutzer prüft, auf die Karte dieses einen Geräts. Er wird nicht gespeichert und nicht an andere Geräte geschickt.

### Der Schalter

Der Schalter `switch.paket_tracker_geschenkmodus` ist eine Konfigurations-Entität. Home Assistant gibt solche Entitäten Sprachassistenten nicht von selbst frei, und das soll so bleiben.

!!! danger "Den Schalter nicht für Assist, Alexa oder Google freigeben"
    Diese Assistenten rufen Schalter ohne Benutzer oder als Besitzer des Kontos auf. Beides darf den Modus ausschalten. Ein Kind könnte ihn per Sprache ausschalten. Gib den Schalter nicht von Hand frei.

### Grenzen

!!! warning "Es geht um das Offensichtliche auf dem Dashboard, nicht um Admins"
    - Was der Verlauf von Home Assistant (Logbuch, Historie) schon aufgezeichnet hat, bleibt dort. Kennzeichnest du ein Paket erst später als Geschenk, löscht das die alten Einträge nicht. Von dieser Version an zeichnet der Recorder die Attribute `name`, `tracking_url` und `amazon_shipment` und die Listen der Zusammenfassungs- und Zählsensoren nicht mehr auf. Der Anzeigename der Entität (`sensor.paket_<nummer>`) und der Eintrag in `calendar.pakete` bleiben aber im Verlauf: Ein Paket, das du erst später als Geschenk kennzeichnest, behält dort seinen früheren Namen. Schalte den Modus am besten ein, bevor du bestellst. Ältere Einträge bleiben, bis sie ablaufen oder du sie löschst.
    - Der echte Name bleibt im Speicher der Integration. Wer die Dateien von Home Assistant lesen kann (Admins), findet ihn dort.
    - Wer das Paket-Postfach lesen kann, liest alles.

## Personen

Die Personen-Zuordnung ist optional. Sie legt fest, wem ein Paket gehört, nicht wer es sehen darf.

- Der Besitzer steht für **jeden Benutzer** von Home Assistant im Attribut `owner` des Paket-Sensors und im Feld `owner` des Ereignisses `parcel_tracker_status_changed`. `owner_detected` ist `true`, wenn eine Person aus einer Mail erkannt oder von Hand gesetzt wurde, und `false`, wenn der Besitzer aus der Standard-Person kommt oder von Hand „allen“ gesetzt wurde.
- Der Filter `person` der Karte ist nur eine Anzeige. Die Sensoren aller Pakete bleiben für jeden Benutzer lesbar.
- Ein Wandtablet oder das Handy eines Kindes braucht einen **eigenen Benutzer** in Home Assistant, wie beim [Geschenkmodus](#geschenkmodus). Sonst gilt es als der Benutzer, mit dem es angemeldet ist.
- Die Mailadressen, die du einer Person einträgst, stehen in den Optionen der Integration. Die Adressen aus den Mails werden nur verglichen, nie gespeichert oder ins Log geschrieben. Der Diagnose-Download nennt nur, wie viele Personen und Adressen eingerichtet sind.

## Zustell-Codes

Manche Amazon-Lieferungen gibt der Fahrer nur gegen einen Code heraus (Einmalpasswort). Die Option **Zustell-Codes (Einmalpasswörter) mitlesen** im Bereich E-Mail-Import ist von Haus aus **aus**.

Mit eingeschalteter Option:

- Der Import liest den Code aus der Mail.
- Die Karte zeigt ihn verdeckt: erst „Code anzeigen“, dann die Rückfrage „Zustell-Code anzeigen?“. Beim Zuklappen verschwindet er wieder.
- Der Code steht in keinem Attribut. Der Sensor zeigt nur `has_delivery_code` (`true` oder `false`). Die Karte holt den Code erst, wenn du „Code anzeigen“ tippst und das bestätigst.
- Er wird nie gespeichert, landet nie im Verlauf (Recorder) und verfällt nach dem Liefertag.
- Er steht nie in einer Benachrichtigung.

!!! warning "Jeder angemeldete Benutzer kann ihn abrufen"
    Der Code steht nicht mehr in den Entitäts-Attributen. Die Karte fragt ihn aber über die Schnittstelle von Home Assistant ab (WebSocket-Befehl `parcel_tracker/delivery_code`). Das kann jeder angemeldete Benutzer, auch ohne die Karte. Der Code gilt auch bei einem Geschenk. Wer den Code nicht teilen will, lässt die Option aus.

Abholcodes aus DHL-Mails liest der Import nie.

## Diagnose

Der Diagnose-Download enthält keine Geheimnisse und keine Namen. Sendungs- und Bestellnummern stehen nur maskiert drin. Die vollständige Liste steht unter [Diagnose](sensoren.md#diagnose).

## Markenhinweis

DHL, DPD, Hermes, UPS, GLS, 17track, Amazon, eBay, AliExpress und Eventim sind Marken ihrer Inhaber. Die Logos (Simple Icons, CC0) dienen nur zur Kennzeichnung des Paketdienstes: DHL als gelbes Schild mit rotem Schriftzug, UPS in der Textfarbe des Themes, Hermes als blauer Punkt mit „H“, GLS als blauer Punkt mit „G“ (Simple Icons hat kein GLS-Logo), AliExpress als roter Punkt mit „A“, Eventim als dunkelblauer Punkt mit „E“, „Andere (über 17track)“ als grauer Punkt mit „17“. Dieses Projekt ist nicht mit den Unternehmen verbunden.

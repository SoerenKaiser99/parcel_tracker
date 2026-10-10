# Was brauche ich für welchen Dienst?

Die kurze Antwort: DPD, GLS und Hermes funktionieren sofort. DHL und UPS brauchen für den Live-Status eigene Zugangsdaten, kommen aber auch ohne sie aus Mails. Amazon, eBay und AliExpress kommen nur aus Mails.

| Dienst | Live-Status direkt | Aus Mails (Mail-Import) | Voraussetzung |
|---|---|---|---|
| DHL | nur mit DHL-API-Key | ja, aus den DHL-Mails | kostenloser [DHL-API-Key](#dhl-api-key-anlegen); ohne Key kommt der Status nur aus den DHL-Mails |
| DPD | ja, ohne Key (nur Status, kein Ort) | optional: eine DPD-Mail legt das Paket an, den Status liefert die Abfrage | keine |
| GLS | ja, ohne Key (mit PLZ auch der Verlauf) | ja, aus den GLS-Mails | keine; die PLZ für den Verlauf |
| Hermes | ja, ohne Key | ja, aus den Hermes-Mails (sie nennen den Liefertag) | keine |
| UPS | nur mit eigenem UPS-Entwicklerzugang | ja, aus den UPS-Mails | ohne Zugang nur aus den UPS-Mails; für den Live-Status [Client-ID und Secret](#ups) |
| Amazon | nein (keine Anmeldung bei Amazon) | ja, nur aus Mails | [E-Mail-Import](mail-import.md) |
| eBay | nein | ja, nur aus Mails | [E-Mail-Import](mail-import.md) |
| AliExpress | nein (über die Sendungsnummer des Paketdienstes, sobald eine Mail sie nennt) | ja, nur aus Mails | [E-Mail-Import](mail-import.md) |
| andere Paketdienste | über „Andere (über 17track)“ | nein | eigener [17track-Key](#17track-optional), 200 Nummern einmalig |

„Aus Mails“ setzt den [E-Mail-Import](mail-import.md) mit einem eigenen Paket-Postfach voraus.

!!! warning "DHL oder UPS ohne Zugangsdaten und ohne Mail-Import"
    Ein von Hand eingetragenes DHL-Paket bleibt dann ohne Status. Die Karte zeigt „Kein Live-Status“ und sagt das gleich beim Hinzufügen. Für UPS ohne Zugangsdaten gilt dasselbe.

## DHL

Abgefragt wird über die offizielle API „Shipment Tracking – Unified“. Die Schnittstelle kennt alle DHL-Sendungen: DHL Paket in Deutschland, aber auch Express und eCommerce. Mit Key und hinterlegter PLZ liefert DHL zusätzliche Details, z. B. den Standort.

**Der Key ist optional – nicht darauf versteifen.** DHL prüft jeden Antrag selbst. Ohne passende Angaben wird er manchmal abgelehnt. Wer keinen Key bekommt, verliert wenig: siehe [Kein Key? Dann die DHL-Mails](#kein-key-dann-die-dhl-mails).

### DHL-API-Key anlegen

1. Auf [developer.dhl.com](https://developer.dhl.com) ein Konto anlegen oder anmelden – am besten mit einer E-Mail-Adresse unter eigener Domain (siehe unten).
2. Zu **Meine Apps** wechseln und eine neue App anlegen.
3. Das Feld **Firma / Company** ausfüllen. Es ist ein **Pflichtfeld**: Bleibt es leer, lehnt DHL den Key ab. Trag auch als Privatperson etwas ein, das zur E-Mail-Adresse des Kontos passt, z. B. die eigene Domain.
4. Als API **„Shipment Tracking – Unified“** auswählen (nicht „Parcel DE …“).
5. Als Environment **„Production (Europe)“** wählen.
6. Du brauchst nur den **API Key**, das Secret nicht.
7. Die Freischaltung dauert bis zu 24 Stunden.

Den Key trägst du bei der Einrichtung ein oder später unter **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren**.

!!! tip "Wichtig beim Antrag"
    Gib als Zweck an, dass du deine eigenen Sendungen verfolgen möchtest – am besten wörtlich **„I want to track my own shipments“**. Laut einem Hinweis aus dem DHL-API-Team bekommt grundsätzlich jeder Zugriff, der seine eigenen Sendungen verfolgen will. Dafür ist die Tracking-API gedacht.

### Welche E-Mail-Adresse?

Laut DHL werden die Anträge von Hand geprüft, weil Bots die Schnittstelle missbrauchen.

- Am zuverlässigsten klappt es bisher mit einer Adresse unter eigener Domain, die zum angegebenen Firmennamen passt.
- Adressen bei gmx.de und web.de haben laut DHL bessere Chancen als Gmail, hotmail.com und outlook.com. Sie wurden bei Testern aber ebenfalls abgelehnt.
- Eine Garantie gibt es bei Freemail-Adressen nicht.

Klappt es nicht: Der Key ist kein Muss, die DHL-Mails reichen.

### Key abgelehnt?

DHL nennt in der Ablehnungsmail als Bedingung einen gültigen Firmennamen **und eine dazu passende Domain-E-Mail-Adresse**. Es reicht also nicht, nur das Feld **Firma / Company** auszufüllen: Das DHL-Konto selbst sollte auf eine Adresse unter eigener Domain laufen (eigene Domain oder Arbeitsadresse), und der Firmenname sollte dazu passen. Ohne eigene Domain helfen die Hinweise unter [Welche E-Mail-Adresse?](#welche-e-mail-adresse). Danach beantragst du den Key erneut.

### Zeitfenster

Liefertag und Zeitfenster zeigt die Integration, wenn DHL eines nennt. DHL berechnet beides laufend neu. Ein Zeitfenster kann deshalb im Lauf des Tages erscheinen und wieder verschwinden. Nimmt DHL die Angabe zwischendurch zurück, bleibt die zuletzt genannte stehen, solange das Paket unterwegs und der Tag nicht vorbei ist.

### Kein Key? Dann die DHL-Mails

Ohne DHL-Key läuft die Integration trotzdem: DPD, GLS und Hermes brauchen keine Zugangsdaten, DHL-Pakete kommen aus den DHL-Mails, und „Details über 17track holen“ liefert Status und Verlauf über [17track](#17track-optional).

So kommen DHL-Pakete ohne Key von selbst in die Übersicht:

1. Im (kostenlosen) DHL-Kundenkonto die E-Mail-Benachrichtigungen zu Sendungen einschalten.
2. Die DHL-Absender `noreply@dhl.de`, `paketankuendigung@dhl.de`, `zustellung@dhl.de` und `sendungsupdate@dhl.de` (oder gleich die ganze Domain `dhl.de`) in die Filterregel zum Paket-Postfach aufnehmen. Siehe [E-Mail-Import](mail-import.md#filterregel-anlegen).
3. Fertig: Die Integration legt die Pakete aus den Mails an und führt den Status mit – samt Liefertag, wenn die Mail ihn nennt. Mit Key kämen nur Ort und Verlauf dazu.

Den Status liest der Import nur aus dem Betreff der DHL-Mail:

| Betreff enthält | Status |
|---|---|
| „ist unterwegs“ | „Unterwegs“, samt Liefertag, wenn die Mail ihn nennt |
| „kommt morgen“ | „Unterwegs“ mit dem Tag nach der Mail |
| „kommt heute“, „wird heute zugestellt“ | „In Zustellung“ für den Tag der Mail |
| „wurde zugestellt“, auch „wurde an den gewünschten Ablageort zugestellt“ | „Zugestellt“ |
| „Liegt zur Abholung bereit“, „wurde an Packstation … / in die Filiale … zugestellt“ | „Abholbereit“ |
| jede andere Mail, deren Betreff von einer „Sendung“ spricht (Zustellfoto, gescheiterter Zustellversuch, Neuigkeiten) | nur „Unterwegs“ ohne Tag; nie einen Status zurück |
| Umfrage (Betreff mit Fragezeichen) oder Betreff ohne „Sendung“ | legt das Paket nur an |

Abholcodes liest der Import nie.

Ein DHL-Paket, zu dem es weder eine Mail noch 17track-Daten gibt, zeigt ohne Key „Kein Live-Status“ statt eines Termins. Die Integration kann eine solche Nummer nicht prüfen: Ob sie stimmt, vertippt oder längst zugestellt ist, erfährt sie ohne Key nicht.

??? note "Warum es keinen anderen Weg gibt"
    - **Nutzungsbedingungen:** DHL erlaubt automatische Abfragen nur über die offizielle Schnittstelle. Die Sendungsverfolgung der Webseite ist laut DHL ausdrücklich nur für Menschen gedacht. Automatisches Auslesen ist untersagt und wird technisch geblockt. Das umgeht diese Integration nicht.
    - **Kein Login mit dem DHL-Kundenkonto:** Dafür gibt es keine offizielle Schnittstelle. Eine Integration müsste sich als DHL-App ausgeben, würde bei jeder Änderung von DHL ausfallen, und in Home Assistant läge ein Zugang zum ganzen Konto (Adresse, Packstation, Sendungen). Das ist bewusst nicht eingebaut.

## DPD

- Abgefragt wird die öffentliche DPD-Sendungsverfolgung, nur mit der Sendungsnummer. Zugangsdaten brauchst du nicht.
- DPD liefert den Status und die fünf Meilenstein-Termine, aber keinen Standort und kein Zeitfenster.
- Die detailliertere DPD-Seite braucht eine Postleitzahl und ist durch ein Captcha geschützt. Deshalb nutzt die Integration sie nicht.
- Mails von DPD sind optional: Eine DPD-Mail legt das Paket an, den Status liefert die Abfrage. Die Ankündigung „Bald ist Ihr DPD Paket da“ nennt dazu den Versender und eine Lieferschätzung.

## GLS

GLS-Pakete fragt die Integration über die offene Sendungsverfolgung von gls-group.com ab – ohne Zugangsdaten und ohne Anmeldung.

**Nummern:**

- **11 Ziffern** erkennt „Automatisch“ als GLS.
- **12 Ziffern** (so steht die Nummer in den GLS-Mails und im Link zur Sendungsverfolgung) funktionieren mit der Carrier-Wahl „GLS“ und beim Import der GLS-Mails. Die letzte Ziffer ist eine Prüfziffer, GLS wird mit den ersten 11 Ziffern gefragt.
- **12 Ziffern mit „Automatisch“:** So sehen auch DHL-Nummern und eBay-Artikelnummern aus. Die Integration fragt die Nummer einmal mit allen 12 Ziffern bei GLS an. Bei einem Treffer wird sie ein GLS-Paket. Mit DHL-Key wird zuerst DHL gefragt und GLS nur, wenn DHL die Nummer nicht kennt. Kennt GLS die Nummer nicht, bleibt alles wie zuvor, und GLS wird für dieses Paket nicht noch einmal gefragt. Ist GLS nicht erreichbar, gibt es höchstens drei Versuche.
- **Achtstellige Track-IDs** aus Buchstaben und Ziffern trägst du mit der Carrier-Wahl „GLS“ ein.

**PLZ:** Ist in den Einstellungen eine PLZ hinterlegt, schickt die Integration sie mit, und GLS liefert zusätzlich den Verlauf (bis zu 20 Ereignisse). Ohne PLZ – oder wenn die PLZ nicht zur Sendung passt – gibt es nur den Status.

**Liefertag:** Nennt die Abfrage keinen eindeutigen Tag, bleiben Liefertag und Zeitfenster aus der GLS-Mail erhalten.

**Abfragen:** höchstens alle 30 Minuten, nachts (22–6 Uhr) stündlich, nach der Zustellung nie mehr.

!!! warning "Kein offizieller Zugang"
    Die offene Abfrage ist keine dokumentierte API. GLS kann sie jederzeit ändern oder schließen. Nach 24 Stunden ohne Antwort erscheint ein Hinweis unter **Einstellungen → Reparaturen**. GLS-Pakete kommen dann weiter aus den GLS-Mails, und „Details über 17track holen“ ergänzt Status und Verlauf über 17track.

## Hermes

- Abgefragt wird die öffentliche Hermes-Sendungsverfolgung, nur mit der Sendungsnummer (`H…` mit 19 Ziffern oder 14 Ziffern). Zugangsdaten und PLZ brauchst du nicht.
- Hermes liefert Status und Verlauf, aber keinen Liefertag. Den übernimmt die Integration aus den Hermes-Mails.

## UPS

Ohne Zugangsdaten kommen UPS-Pakete nur aus den UPS-Mails. Eine von Hand eingetragene `1Z…`-Nummer zeigt dann „Kein Live-Status“, bis eine UPS-Mail zu ihr kommt.

Mit einer eigenen UPS-App fragt die Integration zusätzlich die offizielle UPS Track API ab – auch für von Hand eingetragene `1Z…`-Nummern.

1. Auf [developer.ups.com](https://developer.ups.com) ein Konto anlegen oder anmelden.
2. Eine App anlegen und als Produkt **Tracking** wählen (nicht „Track Alert“).
3. Warten, bis UPS die App freischaltet. Solange steht sie auf „Pending“.
4. **Client-ID** und **Client-Secret** nur in Home Assistant eintragen: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → UPS-Live-Status**. Speichern holt testweise einen Token (zählt nicht aufs Budget).

Leere Felder für Client-ID und Secret behalten die gespeicherten Werte. Ausschalten geht nur über den Schalter **UPS-API aktiv**: Ausgeschaltet gespeichert, entfernt er Client-ID und Secret.

**Monatsbudget** (Standard 100, Bereich 0–10000): So viele UPS-Abfragen macht die Integration höchstens pro Kalendermonat, damit nie Kosten entstehen.

- Token-Abrufe zählen nicht. Jede Sendungsabfrage zählt – auch die über „Aktualisieren“.
- Ist das Budget verbraucht, kommen UPS-Pakete bis Monatsende nur aus Mails. Unter **Einstellungen → Reparaturen** erscheint ein Hinweis, der am Monatsanfang von selbst verschwindet.
- 0 schaltet die API aus.

**Abfragen:** beim Anlegen einmal, danach alle 4 Stunden, am Zustelltag („In Zustellung“) alle 30 Minuten, nach der Zustellung nie mehr; nachts (22–6 Uhr) höchstens stündlich. Lehnt UPS die Zugangsdaten ab, erscheint ebenfalls ein Reparatur-Hinweis.

!!! note "Stand"
    Die UPS-Abfrage ist umgesetzt, aber noch nicht mit echten Zugangsdaten getestet (UPS-Freischaltung ausstehend). Siehe [Roadmap & Status](stand.md).

## 17track (optional)

17track ergänzt Pakete um Ort, Zeitfenster und Verlauf und verfolgt Paketdienste ohne eigene Anbindung (z. B. FedEx). Angemeldet wird nur auf ausdrücklichen Wunsch, nie automatisch.

1. Auf [api.17track.net](https://api.17track.net) ein kostenloses Konto anlegen und den API-Key kopieren.
2. Den Key nur in Home Assistant eintragen: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → 17track-API-Key**. Speichern prüft den Key über das Kontingent (verbraucht nichts). Ein leeres Feld behält den gespeicherten Key.

### Kontingent

- Das kostenlose Konto hat **einmalig 200 Nummern**.
- Jede Anmeldung einer neuen Nummer verbraucht eine. Abfragen danach sind kostenlos.
- Die Integration löscht Nummern bei 17track nie, denn neu anmelden würde erneut kosten.
- `sensor.paket_tracker_17track_kontingent` zeigt die verbleibenden Nummern (Attribute `total` und `used`). Er wird beim Start, nach jeder Anmeldung und einmal täglich aktualisiert.
- Bei höchstens 10 übrigen Nummern und bei leerem Kontingent erscheint ein Hinweis unter **Einstellungen → Reparaturen**.

### Ein Paket anmelden

Auf der Karte das Paket aufklappen und „Details über 17track holen“ antippen. Die Rückfrage „Verbraucht 1 von … verbleibenden 17track-Nummern. Fortfahren?“ bestätigen.

Für Automationen gibt es den Dienst `parcel_tracker.track_17track` mit dem Feld `number`.

Nicht möglich ist das bei zugestellten Paketen und bei Amazon-, eBay- und AliExpress-Bestellungen, solange keine Sendungsnummer des Paketdienstes bekannt ist. Angemeldet wird die Sendungsnummer des Paketdienstes samt Carrier-Code. Ist der Paketdienst unbekannt, erkennt 17track ihn selbst.

### Andere (über 17track)

Für Paketdienste ohne eigene Anbindung wählst du in der Karte „Andere (über 17track)“ (oder rufst `parcel_tracker.add_parcel` mit `carrier: other` auf).

- Hinzufügen meldet die Nummer sofort an, mit derselben Rückfrage.
- Erkennt 17track den Paketdienst nicht, wird das Paket nicht angelegt.
- Status, Text, Ort und Verlauf kommen dann nur von 17track. Der erkannte Paketdienst (z. B. FedEx) erscheint im Namen.

### Ergänzen statt ersetzen

Bei DHL, DPD, GLS, Hermes und UPS bleibt der Paketdienst maßgeblich. 17track füllt nur Lücken: Ort, Liefertag und Zeitfenster sowie den Verlauf (nur wenn der Paketdienst keinen liefert).

Liefert der Paketdienst gar nichts (z. B. DHL ohne API-Key, UPS ohne API-Zugang), zeigt das Paket den Status von 17track, bis der Paketdienst selbst antwortet. Stammt der Ort von 17track, zeigt die Karte „· Ort via 17track“ (Attribut `location_source: 17track`).

### Wie oft wird abgefragt?

- Die erste Abfrage kommt 2 Minuten nach der Anmeldung, danach alle 6 Stunden (17track aktualisiert selbst nur alle 6–12 Stunden).
- Gebündelt werden höchstens 40 Nummern pro Aufruf.
- Schluss ist bei Zustellung oder wenn 17track die Sendung als abgelaufen meldet.
- Ist 17track nicht erreichbar, wartet die Integration länger und meldet nie neu an.
- Lehnt 17track den Key ab, fragt die Integration bis zum Neuladen nicht mehr ab und zeigt einen Reparatur-Hinweis.

## Amazon, eBay und AliExpress

Diese drei kennt die Integration **nur aus Mails**. Eine Anmeldung beim Shop gibt es nicht. Abgefragt wird nur die Sendungsnummer des Paketdienstes, sobald eine Mail sie verrät.

- **Amazon:** Pro Bestellung entsteht ein Paket mit der Nummer `AMZ` + Bestellnummer, benannt nach dem Artikel. Amazon-Nummern (`TBA…`) lassen sich nicht direkt verfolgen.
- **eBay:** Pro Bestellung entsteht ein Paket mit der Nummer `EBAY` + Bestellnummer. eBay-Mails enthalten keine Sendungsnummer. Die 12-stelligen Artikelnummern werden nie als Sendungsnummer gelesen.
- **AliExpress:** Pro Bestellung entsteht ein Paket mit der Nummer `ALI` + Bestellnummer. Nennt eine „Packstück“-Mail eine DHL- oder Hermes-Nummer, übernimmt die Bestellung sie und wird ab dann live beim Paketdienst abgefragt (DHL mit API-Key).

Die Einzelheiten stehen unter [E-Mail-Import](mail-import.md#was-aus-welcher-mail-wird).

## Österreich und Schweiz

Die Integration ist für Deutschland gebaut. Die Einstellung **Land** ist die Grundlage für die Nutzung in Österreich und der Schweiz. Stand heute:

**Funktioniert mit der Einstellung:**

- PLZ mit 4 Ziffern,
- DHL mit API-Key über die offizielle API (die PLZ geht so an DHL, wie sie eingetragen ist),
- UPS über die offizielle API,
- jeder Paketdienst über 17track.

**GLS:**

- Für Österreich fragt die Integration die österreichische Variante der offenen GLS-Abfrage. Eine Probe mit einer ungültigen Nummer hat gezeigt, dass sie genauso antwortet wie die deutsche. **Mit echten Paketen ist das noch nicht getestet.**
- Für die Schweiz bleibt die GLS-Abfrage auf der deutschen Variante, weil die Schweizer Variante ihre Texte auf Englisch liefert.
- Der Mail-Import liest die Mails von `noreply@gls-group.eu` und `noreply@gls-rtt.com`, egal welches Land eingestellt ist. Zustelladresse, Empfängername und Referenz übernimmt er nie.

**DPD Österreich:**

- Mails von `no_reply@dpd.at` legen das Paket an („Ein DPD Paket für dich“) und melden die Zustellung mit Uhrzeit („Neuigkeiten zu deinem Paket“).
- Der Status kommt bei DPD Österreich derzeit nur aus diesen Mails. Die DPD-Abfrage bleibt die deutsche Seite.
- mydpd.at hat zwar eine eigene offene Abfrage. Sie antwortet aber in einem anderen Format und ließ sich nur mit einer ungültigen Nummer prüfen. Ohne echte Antwort wird daraus keine Abfrage gebaut.
- Den Abstellort übernimmt der Import nie.

**DHL international:** Nummern internationaler DHL-Sendungen (zwei Buchstaben, neun Ziffern, „DE“, z. B. `CQ…DE`) erkennt „Automatisch“ als DHL (Live-Status mit DHL-API-Key), und der Mail-Import liest sie aus den DHL-Mails.

**Noch nicht:**

- DPD-Live-Abfrage für Österreich, DPD Schweiz,
- Österreichische Post und Schweizerische Post als eigene Paketdienste (bis dahin über „Andere (über 17track)“),
- „Automatisch“ erkennt andere ausländische Nummernformate nicht,
- Mails aus der Schweiz kennt der Mail-Import noch nicht.

Damit daraus mehr wird, helfen anonymisierte Beispielmails der Paketdienste und Shops aus Österreich und der Schweiz. Siehe [Beispielmails einreichen](hilfe.md#beispielmails-einreichen).

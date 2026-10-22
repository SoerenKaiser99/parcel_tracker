# Wie ihr helfen könnt

Paket Tracker ist eine öffentliche Beta. Vieles ist gebaut und automatisch getestet, aber längst nicht alles ist mit echten Paketen und echten Mails bestätigt. Diese Seite sagt, **was gerade am meisten hilft**.

*Stand: 22. Oktober 2026, Version 0.3.43. Die Liste wird mit jeder Version aktualisiert.*

!!! tip "Die schnellste Hilfe"
    Du nutzt eine der Funktionen unten und sie läuft? Dann reicht ein Satz: **Was** du genutzt hast, **mit welcher Version**, und **ob es gepasst hat**. Auch „läuft einfach“ ist eine Rückmeldung, die zählt.

## 1. Bestätigen: Läuft das bei dir?

Diese Funktionen sind fertig, aber im Alltag noch von niemandem oder nur von einer Person bestätigt.

### Paketdienste

| Was | Was wir wissen wollen | Wohin |
|---|---|---|
| **UPS mit eigenem Entwicklerzugang** | Kommt der Live-Status? Stimmt das Monatsbudget? Bisher hatte niemand echte Zugangsdaten. | [Fehler melden](hilfe.md#fehler-melden) oder im Forum |
| **DHL mit API-Key: Zeitfenster** | Zeigt die Karte „Heute 14:00–16:00 Uhr“, wenn DHL ein Zeitfenster nennt? | im Forum |
| **DHL mit API-Key: Verlauf ohne HTML** | Liegt ein Paket in der Packstation, schickte DHL den Text mit einem Link, und die Karte zeigte ihn roh. Steht jetzt nur noch „Die Sendung liegt in der Packstation … zur Abholung bereit.“ da, auch bei einem Paket, das schon vor dem Update so in der Liste stand? Neu seit v0.3.34. | [Issue #18](https://github.com/SoerenKaiser99/parcel_tracker/issues/18) |
| **Hermes: Paket im PaketShop** | Wechselt das Paket auf „Abholbereit“, sobald es im PaketShop liegt, und kommt die Benachrichtigung? Springt es nach dem Abholen auf „Zugestellt“? Neu seit v0.3.29, ohne echtes Paket gebaut. | [Issue #18](https://github.com/SoerenKaiser99/parcel_tracker/issues/18) |
| **GLS in Österreich** | Liefert die Abfrage mit Land „Österreich“ Status und Verlauf? | [Issue #3](https://github.com/SoerenKaiser99/parcel_tracker/issues/3) |
| **GLS: 12-stellige Nummer mit „Automatisch“** | Wird die Nummer aus der GLS-Mail erkannt, ohne dass du „GLS“ auswählst? | im Forum |
| **17track bei DPD und GLS** | Füllt „Details über 17track holen“ Ort und Verlauf nach? Bisher nur bei DHL gesehen. | im Forum |
| **Symbol „Sendung verfolgen“** | Führt es bei GLS, Hermes und UPS direkt zu deinem Paket? Bei DHL ist das bestätigt. | im Forum |

### E-Mail-Import

| Was | Was wir wissen wollen | Wohin |
|---|---|---|
| **AliExpress** | Erscheint die Bestellung mit Artikelname und Zustelltag? Wird nach der „Packstück“-Mail live beim Paketdienst abgefragt? Werden die Mails „Vom Kurier abgeholt“ und „Packstück … hat eine Aktualisierung“ erkannt? Landet eine Mail bei den nicht erkannten? |
| **Eventim** | Erscheint eine Ticketbestellung mit Postversand als „Bestellt“ mit dem Namen der Veranstaltung? Setzt die Versandbenachrichtigung „Versendet“ und den Lieferzeitraum? Bleiben Bestellungen mit print@home, ticketdirect oder Mobile Ticket draußen? Neu seit v0.3.30. | im Forum |
| **Eigener Mailserver im Heimnetz (Port, ohne Zertifikatsprüfung)** | Klappt die Verbindung mit eigenem Port und „Verschlüsselt, Zertifikat nicht prüfen“ oder „Unverschlüsselt“? Welcher Server läuft bei dir (dovecot, ein NAS, …)? Neu seit v0.3.32, ohne echten Mailserver gebaut. | im Forum |
| **Apple „E-Mail-Adresse verbergen“** | Werden so weitergereichte Mails von Amazon, DHL, DPD, GLS, Hermes, UPS oder eBay erkannt? Mit echten Mails geprüft ist bisher nur AliExpress. | im Forum |
| **DHL: „liegt am gewünschten Ablageort“** | Springt das Paket mit dieser Mail auf „Zugestellt“? | [Issue #9](https://github.com/SoerenKaiser99/parcel_tracker/issues/9) |
| **DHL: „wird gleich zugestellt“** | Zählt das Paket mit dieser Mail als heute, und steht „Wird gleich zugestellt“ als eigene Zeile im Verlauf? | im Forum |
| **DHL: „Sendungs-Update“ nach einer Verzögerung** | Übernimmt das Paket den neuen Zustelltag? | [Issue #11](https://github.com/SoerenKaiser99/parcel_tracker/issues/11) |
| **DPD: „Bald ist Ihr DPD Paket da“** | Stimmen Name und Liefertage? | [Issue #6](https://github.com/SoerenKaiser99/parcel_tracker/issues/6) |
| **Amazon: „Versuchte Zustellung“** | Verschwindet die Bestellung danach aus „heute“? | im Forum |
| **Bestellungen ohne Zustellmail** | Schließt sich eine überfällige Bestellung nach drei Tagen als „Abgeschlossen (ohne Zustellbestätigung)“? Verschwindet ein Doppel, wenn das Paket des Paketdienstes zugestellt wird? | im Forum |
| **Mail per HTTP übergeben** (n8n, Node-RED) | Kommt die Mail an, und stimmt die Antwort? | im Forum |
| **DPD: die Mails nach der Ankündigung** | Setzen „Zwischen … und … Uhr kommt Ihr DPD Paket“, „Ihr Paket ist da!“ und „Im Pickup Paketshop wartet Ihr DPD Paket auf Sie“ „In Zustellung“ mit Zeitfenster, „Zugestellt“ und „Abholbereit“? Neu seit v0.3.34 (Beitrag von benep). | im Forum |
| **eBay: „Update zur Bestellung“ und „Zustellversuch“** | Übernimmt die Bestellung die Sendungsnummer aus der Mail und wird danach live beim Paketdienst abgefragt? Neu seit v0.3.34 (Beitrag von benep). | im Forum |
| **Hermes: „Deine Sendung kommt heute.“ und neuer Zustelltermin** | Steht das Paket mit Zeitfenster auf „In Zustellung“? Übernimmt es nach einem gescheiterten Zustellversuch den neuen Tag? Neu seit v0.3.34 (Beitrag von benep). | im Forum |
| **Nicht erkannte Mails erneut einlesen** | Liest der Import eine Mail aus `Paket-Tracker-Nicht-erkannt` nach einem Update noch einmal, wenn du sie ungelesen zurück in den gelesenen Ordner schiebst ([so geht's](hilfe.md#eine-mail-wird-nicht-erkannt))? Gilt für Mails, die ab v0.3.34 gelesen wurden. Neu seit v0.3.34 (Beitrag von benep). | im Forum |
| **eBay: „Paket zugestellt“** | Steht die Bestellung nach der Mail „📦PAKET ZUGESTELLT: …“ auf „Zugestellt“, mit dem Artikel aus dem Betreff als Namen? Neu seit v0.3.35. | [Issue #32](https://github.com/SoerenKaiser99/parcel_tracker/issues/32) |
| **DPD Österreich: „Ihr DPD Paket kommt zwischen … Uhr“** | Steht das Paket mit dieser Mail auf „In Zustellung“, heute mit dem Zeitfenster aus dem Betreff? Neu seit v0.3.35. | [Issue #31](https://github.com/SoerenKaiser99/parcel_tracker/issues/31) |
| **Amazon: „Paket zur Abholung bereit“** | Steht die Bestellung nach der Mail von `pickup-point@amazon.de` auf „Abholbereit“, mit Abholort und letztem Abholtag auf der Karte und in der Benachrichtigung? Ist „Abholung am …“ in deiner Mail wirklich der letzte Abholtag? Gilt das auch für Amazon Locker und Counter? Neu seit v0.3.36. | [Issue #33](https://github.com/SoerenKaiser99/parcel_tracker/issues/33) |
| **DHL: Sendungsnummern aus anderen Ländern** | Entsteht aus einer DHL-Mail mit einer Nummer des Absenderlands (z. B. `LE…BE`, `LW…NL`) ein Paket, und zeigt es mit DHL-Key den Live-Status? Neu seit v0.3.37. | [Issue #34](https://github.com/SoerenKaiser99/parcel_tracker/issues/34) |
| **DHL eCommerce (Niederlande)** | Legen Mails von `noreply@dhlecommerce.nl` ein DHL-Paket mit der 20-stelligen Nummer an und setzen „Unterwegs“? Zeigt es mit DHL-Key den Live-Status? Neu seit v0.3.42 ([Issue #62](https://github.com/SoerenKaiser99/parcel_tracker/issues/62)). | [Issue #62](https://github.com/SoerenKaiser99/parcel_tracker/issues/62) |
| **DHL Express („DHL On Demand Delivery“)** | Setzen die Mails von `noreply.odd@dhl.com` „Unterwegs“, „In Zustellung“ für heute und „Zugestellt“ mit der Uhrzeit aus der Mail? Bekommt das Paket den Namen des Absenders (bei Amazon „Amazon-Sendung (DHL)“)? Neu seit v0.3.38 (Beitrag von benep). | im Forum |
| **AliExpress: Mails der letzten Meile** | Setzt „Paket … wird zugestellt“ die Bestellung heute auf „In Zustellung“ und „Paket … wurde zugestellt“ auf „Zugestellt“? Steht nach „Lieferprobleme für Packstück …“ „Versendet“ mit dem Text „Lieferprobleme“? Neu seit v0.3.38 (Beitrag von benep). | im Forum |
| **Amazon: „Sendung verfolgen“ führt zu Amazon** | Öffnet das Symbol bei einer Amazon-Bestellung ohne Nummer eines Paketdienstes Amazons Sendungsverfolgung mit der richtigen Sendung? Steht dort „Amazon-Sendung: …“? Neu seit v0.3.38 (Beitrag von benep). | im Forum |

### Karte, Benachrichtigungen, Automationen

| Was | Was wir wissen wollen | Wohin |
|---|---|---|
| **Knopf „Erhalten“** | Steht er im aufgeklappten Paket, kommt die Rückfrage „Wirklich erhalten?“, und zählt das Paket danach als heute zugestellt? Bleibt es dabei, auch wenn später noch eine Mail oder eine Antwort des Paketdienstes kommt? Neu seit v0.3.30. | im Forum |
| **„Namen ausblenden“** | Taucht irgendwo doch noch ein echter Name auf – Karte, Kalender, Benachrichtigung, Sprachassistent? | [Fehler melden](hilfe.md#fehler-melden) |
| **Einfuhrabgaben (Zoll) bei DHL** | Zeigt die Karte bei einer DHL-Sendung aus dem Ausland den Betrag („Einfuhrabgaben: … € in bar bei Zustellung“), kommt er in die Benachrichtigung „In Zustellung“, und verschwindet er nach der Zustellung? Stimmt der Betrag mit der Mail überein, auch bei Beträgen ab 1.000 €? | [Fehler melden](hilfe.md#fehler-melden) |
| **„Absendernamen aus DHL-Mails übernehmen“** | Heißt ein Paket nach dem Namen aus dem DHL-Betreff „Ihre <Name> Sendung …“, auch bei einem kleinen Shop oder einer Privatperson? Fehlt das „..“ am Ende? Blendet „Namen ausblenden“ den Namen weiterhin aus? | [Fehler melden](hilfe.md#fehler-melden) |
| **Benachrichtigung „Abholbereit“** | Kommt die Meldung, wenn ein Paket in Packstation, Filiale oder PaketShop liegt? | im Forum |
| **Auslöser im Automations-Editor** | Findest du die fünf Auslöser unter dem Gerät „Paket Tracker“, und lösen sie aus? | im Forum |
| **eBay: Kaufbestätigung** | Legt „Bestellung bestätigt: …“ bzw. „Ihre Bestellung wurde bestätigt“ die Bestellung als „Bestellt“ an, mit Artikel und Lieferzeitraum? Übernimmt die spätere Versandmail dieselbe Bestellung, ohne dass ein zweiter Eintrag entsteht? Neu seit v0.3.39 (Beitrag von benep). | im Forum |
| **DHL: Abholort aus der Abholmail** | Steht bei „… ist in der Filiale abholbereit“ bzw. „Ihr DHL Paket ist ab sofort abholbereit“ die Filiale oder Packstation mit Straße als Abholort auf der Karte, aber nie deine eigene Adresse? Neu seit v0.3.39 (Beitrag von benep). | [Fehler melden](hilfe.md#fehler-melden) |
| **Amazon: Versand durch Verkäufer** | Landet eine DHL- oder Hermes-Mail „von Amazon“ bei der richtigen Bestellung, wenn eine andere Bestellung vom Verkäufer selbst verschickt wird? Neu seit v0.3.39 (Beitrag von benep). | im Forum |
| **Symbole hinter den Nummern** | Öffnet der Lieferwagen hinter der Sendungsnummer die Sendungsverfolgung und der Beleg hinter der Bestellnummer die Bestellseite? Lassen sich die kleinen Symbole am Handy gut treffen? Neu seit v0.3.38 (Beitrag von benep). | im Forum |
| **Symbol „Bestellung öffnen“ bei eBay** | Öffnet es die richtige Bestellseite? Bei Amazon ist das bestätigt. | im Forum |
| **Sendungs- und Bestellnummer im aufgeklappten Paket** | Steht unter dem Verlauf „Sendungsnummer: …“, bei einer Bestellung „Bestellnummer: …“ so wie beim Shop? Lässt sich die Nummer am Handy markieren und kopieren? Neu seit v0.3.34. | im Forum |
| **Personen zuordnen: Erkennung** | Landet ein Paket bei der richtigen Person, wenn die Weiterleitung an eine Plus-Adresse, einen Alias oder die eigene Adresse geht? Bei welchem Anbieter und welcher Weiterleitung? Neu seit v0.3.41. | im Forum |
| **Personen zuordnen: Karte und Meldungen** | Zeigt die Karte mit `person: person.…` nur die Pakete dieser Person? Wirkt die Auswahl „Gehört“, und geht die Meldung nur an die Ziele des Besitzers? Neu seit v0.3.41. | im Forum |
| **Geschenkmodus: Karte** | Fragt der Schalter neben „Pakete“ beim Einschalten, ob die offenen Pakete auch verborgen werden sollen? Heißen neue Pakete danach „Geschenk · …“, ohne Links, und zeigt ein Tipp auf die Geschenkbox (nur für Geschenk-Seher) den echten Namen? Neu seit v0.3.40. | im Forum |
| **Geschenkmodus: Schalter** | Wird `switch.paket_tracker_geschenkmodus` angelegt und bleibt nach einem Neustart in seinem Zustand? Neu seit v0.3.40. | im Forum |
| **Geschenkmodus: wer darf ausschalten** | Kann mit der Option „Wer darf Geschenke sehen?“ nur eine gewählte Person den Modus ausschalten, auch mit `switch.toggle`, und ein Wandtablet mit eigenem Benutzer nicht? Klappt es per Automation? Neu seit v0.3.40. | im Forum |
| **Geschenkmodus: Sprachassistent** | Lässt sich der Modus mit Assist, Alexa oder Google nicht schalten, solange du den Schalter nicht freigegeben hast? Taucht ein Geschenk-Name in einer Antwort auf? Neu seit v0.3.40. | im Forum |
| **Storniert (Bestellung vom Shop abgebrochen)** | Steht eine von Amazon, eBay oder AliExpress stornierte Bestellung auf „Storniert“, ohne als zugestellt zu zählen? Neu seit v0.3.40 ([PR #23](https://github.com/SoerenKaiser99/parcel_tracker/pull/23)). | im Forum |
| **Mail-Abfrage bis 1440 Minuten** | Nimmt die Option „Postfach abfragen alle (Minuten)“ jetzt Werte bis 1440 an, und holt der Import die Mails danach im neuen Abstand? Neu seit v0.3.40. | im Forum |
| **Die [Rezepte](rezepte.md)** | Läuft ein Rezept bei dir so, wie es dasteht? Was musstest du ändern? | im Forum |

## 2. Beispielmails: Diese fehlen uns

Der Mail-Import kann nur lesen, was er schon einmal als Beispiel gesehen hat. Von diesen Mails haben wir keine oder zu wenige:

| Absender | Welche Mail |
|---|---|
| **DHL** | Paket liegt in der Packstation (aus Filialen gibt es Beispiele); Zustellung nicht möglich; beim Nachbarn abgegeben |
| **DHL Express** | „ist unterwegs“ und „wird voraussichtlich … ausgeliefert“ (bisher nur „zugestellt“ als Beispiel); Zustellung nicht möglich; Service Point |
| **DPD Österreich** | laufende Sendung mit Zustelltag, aber ohne Zeitfenster; zugestellt; im Pickup Paketshop abholbereit; Zustellung nicht möglich |
| **GLS** | im PaketShop abholbereit; Zustellung verschoben |
| **Hermes** | im PaketShop abholbereit |
| **UPS** | jede Mail hilft, bisher gibt es nur wenige Beispiele |
| **Amazon** | Mails von Amazon in Österreich |
| **AliExpress** | englische Mails; „Paket … wird zugestellt“ und „Lieferprobleme für Packstück …“ (bisher nur „Paket … wurde zugestellt“ als Beispiel); Mails, die bei dir unter „Nicht erkannt“ landen |
| **Eventim** | Versandbenachrichtigungen und Bestellbestätigungen mit einer anderen Liefermethode als „Standardversand (Deutschland)“, z. B. Einschreiben oder Express; Mails von `bestellstatus@eventim.de`, die bei dir unter „Nicht erkannt“ landen |
| **Österreichische Post, Schweizer Post** | Ankündigung, in Zustellung, zugestellt – damit diese Dienste überhaupt dazukommen können |

**Für die Personen-Zuordnung:** Gesucht ist je Anbieter (Gmail, Outlook, Posteo, mailbox.org, GMX, web.de, eigener Server) eine anonymisierte, weitergeleitete Mail. Gemeint ist die Kopie, die im Paket-Postfach ankommt, nicht die Mail aus dem Hauptpostfach. Nur daran sehen wir, welche Kopfzeilen die Weiterleitung setzt (`Delivered-To`, `X-Original-To`, `X-Forwarded-For` …). Das Skript behält diese Kopfzeilen, ersetzt aber jede Adresse durch eine erfundene (`adresse1@example.org`, ein Plus-Teil bleibt als `+person1`). Dazu im Issue kurz schreiben: Anbieter, Weiterleitung per Regel oder von Hand, und ob du eine Plus-Adresse, einen Alias oder deine eigene Adresse genutzt hast.

!!! danger "Nie eine rohe Mail hochladen"
    In jeder Paketmail stehen dein Name, deine Adresse und Nummern. Dafür gibt es ein kleines Skript, das alles ersetzt. Die fünf Schritte stehen unter [Beispielmails einreichen](hilfe.md#beispielmails-einreichen). Lies die fertigen Dateien einmal selbst durch, bevor du sie anhängst.

Hat eine Mail gar keine Sendungsnummer und keinen Status, sondern nur einen Knopf „Sendung verfolgen“? Dann kann die Integration nichts daraus lesen. Solche Mails brauchen wir nicht.

## 3. Fehler melden

Etwas läuft anders als beschrieben? Dann hilft am meisten:

1. **Erst aktualisieren.** Viele Meldungen betreffen Dinge, die in der neuesten Version schon behoben sind.
2. **Die Diagnose-Datei anhängen.** Sendungsnummern sind darin unkenntlich, Namen und Mail-Inhalte stehen nicht drin.
3. **Sagen, was auf der Karte stand** und was du erwartet hast. Bei Mails: den Betreff der Mail, ohne Nummern.

Der genaue Weg steht unter [Fehler melden](hilfe.md#fehler-melden).

Eine Meldung ist noch ohne Antwort des Einsenders: Bei jemandem öffnen sich die Einstellungen der Integration nicht ([Issue #5](https://github.com/SoerenKaiser99/parcel_tracker/issues/5)). Passiert dir das auch, hilft ein Eintrag aus dem Protokoll von Home Assistant.

## 4. Für später: Barcode-Scan

Geplant ist, die Sendungsnummer mit der Handykamera vom Paketlabel zu erfassen ([Issue #2](https://github.com/SoerenKaiser99/parcel_tracker/issues/2)). Auf den Labels steht aber meist mehr als die Sendungsnummer. Was dafür hilft: je Paketdienst die Information, **welche Zeichenfolge** der Barcode oder QR-Code liefert und **wie viele Stellen** davon die Sendungsnummer sind. Die Nummer selbst brauchen wir nicht – ersetze die Ziffern durch `9`.

## 5. Mitentwickeln

Pull Requests sind willkommen; fünf Beiträge von außen sind schon eingeflossen. Was es leichter macht:

- Eine Änderung pro Pull Request, mit Test.
- Beispielmails nur anonymisiert, erzeugt mit dem Skript des Projekts.
- Kurz beschreiben, was du selbst ausprobiert hast und was nicht.

## Wo du dich meldest

- **GitHub:** [Issues](https://github.com/SoerenKaiser99/parcel_tracker/issues) – für Fehler, Beispielmails und die oben verlinkten Themen.
- **Forum:** die Threads in der [simon42-Community](https://community.simon42.com/t/93418) und bei [community-smarthome.com](https://community-smarthome.com/t/11806) – für kurze Bestätigungen und Fragen.

Was schon bestätigt ist und was noch offen ist, steht unter [Roadmap & Status](stand.md).

# Wie ihr helfen könnt

Paket Tracker ist eine öffentliche Beta. Vieles ist gebaut und automatisch getestet, aber längst nicht alles ist mit echten Paketen und echten Mails bestätigt. Diese Seite sagt, **was gerade am meisten hilft**.

*Stand: 11. Oktober 2026, Version 0.3.28. Die Liste wird mit jeder Version aktualisiert.*

!!! tip "Die schnellste Hilfe"
    Du nutzt eine der Funktionen unten und sie läuft? Dann reicht ein Satz: **Was** du genutzt hast, **mit welcher Version**, und **ob es gepasst hat**. Auch „läuft einfach“ ist eine Rückmeldung, die zählt.

## 1. Bestätigen: Läuft das bei dir?

Diese Funktionen sind fertig, aber im Alltag noch von niemandem oder nur von einer Person bestätigt.

### Paketdienste

| Was | Was wir wissen wollen | Wohin |
|---|---|---|
| **UPS mit eigenem Entwicklerzugang** | Kommt der Live-Status? Stimmt das Monatsbudget? Bisher hatte niemand echte Zugangsdaten. | [Fehler melden](hilfe.md#fehler-melden) oder im Forum |
| **DHL mit API-Key: Zeitfenster** | Zeigt die Karte „Heute 14:00–16:00 Uhr“, wenn DHL ein Zeitfenster nennt? | im Forum |
| **Hermes: Umleitung in den PaketShop** | Steht das Paket im PaketShop auf „Abholbereit“ oder schon auf „Zugestellt“? Was ist der oberste Eintrag im Verlauf? | [Issue #18](https://github.com/SoerenKaiser99/parcel_tracker/issues/18) |
| **GLS in Österreich** | Liefert die Abfrage mit Land „Österreich“ Status und Verlauf? | [Issue #3](https://github.com/SoerenKaiser99/parcel_tracker/issues/3) |
| **GLS: 12-stellige Nummer mit „Automatisch“** | Wird die Nummer aus der GLS-Mail erkannt, ohne dass du „GLS“ auswählst? | im Forum |
| **17track bei DPD und GLS** | Füllt „Details über 17track holen“ Ort und Verlauf nach? Bisher nur bei DHL gesehen. | im Forum |
| **Link „Sendung verfolgen“** | Führt er bei GLS, Hermes und UPS direkt zu deinem Paket? Bei DHL ist das bestätigt. | im Forum |

### E-Mail-Import

| Was | Was wir wissen wollen | Wohin |
|---|---|---|
| **AliExpress** | Erscheint die Bestellung mit Artikelname und Zustelltag? Wird nach der „Packstück“-Mail live beim Paketdienst abgefragt? Landet eine Mail bei den nicht erkannten? | [Issue #15](https://github.com/SoerenKaiser99/parcel_tracker/issues/15) |
| **Apple „E-Mail-Adresse verbergen“** | Werden so weitergereichte Mails von Amazon, DHL, DPD, GLS, Hermes, UPS oder eBay erkannt? Mit echten Mails geprüft ist bisher nur AliExpress. | im Forum |
| **DHL: „liegt am gewünschten Ablageort“** | Springt das Paket mit dieser Mail auf „Zugestellt“? | [Issue #9](https://github.com/SoerenKaiser99/parcel_tracker/issues/9) |
| **DHL: „Sendungs-Update“ nach einer Verzögerung** | Übernimmt das Paket den neuen Zustelltag? | [Issue #11](https://github.com/SoerenKaiser99/parcel_tracker/issues/11) |
| **DPD: „Bald ist Ihr DPD Paket da“** | Stimmen Name und Liefertage? | [Issue #6](https://github.com/SoerenKaiser99/parcel_tracker/issues/6) |
| **Amazon: „Versuchte Zustellung“** | Verschwindet die Bestellung danach aus „heute“? | im Forum |
| **Bestellungen ohne Zustellmail** | Schließt sich eine überfällige Bestellung nach drei Tagen als „Abgeschlossen (ohne Zustellbestätigung)“? Verschwindet ein Doppel, wenn das Paket des Paketdienstes zugestellt wird? | im Forum |
| **Mail per HTTP übergeben** (n8n, Node-RED) | Kommt die Mail an, und stimmt die Antwort? | im Forum |

### Karte, Benachrichtigungen, Automationen

| Was | Was wir wissen wollen | Wohin |
|---|---|---|
| **„Namen ausblenden“** | Taucht irgendwo doch noch ein echter Name auf – Karte, Kalender, Benachrichtigung, Sprachassistent? | [Fehler melden](hilfe.md#fehler-melden) |
| **Benachrichtigung „Abholbereit“** | Kommt die Meldung, wenn ein Paket in Packstation, Filiale oder PaketShop liegt? | im Forum |
| **Auslöser im Automations-Editor** | Findest du die fünf Auslöser unter dem Gerät „Paket Tracker“, und lösen sie aus? | im Forum |
| **Knopf „Bestellung“ bei eBay** | Öffnet er die richtige Bestellseite? Bei Amazon ist das bestätigt. | im Forum |
| **Die [Rezepte](rezepte.md)** | Läuft ein Rezept bei dir so, wie es dasteht? Was musstest du ändern? | im Forum |

## 2. Beispielmails: Diese fehlen uns

Der Mail-Import kann nur lesen, was er schon einmal als Beispiel gesehen hat. Von diesen Mails haben wir keine oder zu wenige:

| Absender | Welche Mail |
|---|---|
| **DHL** | Paket liegt in der Packstation oder Filiale; Zustellung nicht möglich; beim Nachbarn abgegeben |
| **DPD Deutschland** | alles nach der Ankündigung: in Zustellung, zugestellt, im Pickup-Paketshop |
| **DPD Österreich** | laufende Sendung mit Zustelltag oder Zeitfenster |
| **GLS** | im PaketShop abholbereit; Zustellung verschoben |
| **Hermes** | im PaketShop abholbereit; Zustellversuch |
| **UPS** | jede Mail hilft, bisher gibt es nur wenige Beispiele |
| **Amazon** | Lieferung verspätet; Bestellung storniert; Mails von Amazon in Österreich |
| **eBay** | Versandmail mit Sendungsnummer; Artikel zugestellt |
| **AliExpress** | englische Mails; Mails, die bei dir unter „Nicht erkannt“ landen |
| **Österreichische Post, Schweizer Post** | Ankündigung, in Zustellung, zugestellt – damit diese Dienste überhaupt dazukommen können |

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

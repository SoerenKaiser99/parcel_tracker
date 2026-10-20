# Paket Tracker

[![Version](https://img.shields.io/github/v/release/SoerenKaiser99/parcel_tracker?label=Version)](https://github.com/SoerenKaiser99/parcel_tracker/releases/latest) [![Downloads](https://img.shields.io/github/downloads/SoerenKaiser99/parcel_tracker/total?label=Downloads)](https://github.com/SoerenKaiser99/parcel_tracker/releases) [![Doku](https://img.shields.io/badge/Doku-Anleitung-blue)](https://soerenkaiser99.github.io/parcel_tracker/)

**Ausführliche Anleitung mit Rezepten:** [soerenkaiser99.github.io/parcel_tracker](https://soerenkaiser99.github.io/parcel_tracker/) · **Alle Versionen:** [CHANGELOG](https://github.com/SoerenKaiser99/parcel_tracker/blob/main/CHANGELOG.md)

Home-Assistant-Integration, die Pakete von DHL, DPD, GLS, Hermes und (optional) UPS verfolgt, Amazon-, eBay- und AliExpress-Bestellungen sowie Eventim-Tickets mit Postversand aus E-Mails übernimmt und alles auf einer eigenen Dashboard-Karte zeigt.

<p>
  <img src="https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/docs/images/karte-hell.png" width="260" alt="Die Paket-Tracker-Karte im hellen Design: zwölf Pakete von DHL, DPD, GLS, Hermes, UPS, Amazon, eBay, AliExpress und 17track mit Status, Fortschrittsbalken und Liefertermin, im Kopf der Schalter „Geschenkmodus“ und ein Paket als Geschenk mit Geschenkbox">
  <img src="https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/docs/images/karte-detail.png" width="260" alt="Die Karte mit geöffneter Eingabe für eine neue Sendung und einem aufgeklappten DHL-Paket: Verlauf der Sendung, die Sendungsnummer mit dem Symbol „Sendung verfolgen“ dahinter und die Knöpfe „Details über 17track holen“, „Erhalten“, „Umbenennen“ und „Löschen“">
  <img src="https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/docs/images/karte-dunkel.png" width="260" alt="Die Paket-Tracker-Karte im dunklen Design">
</p>

Die Bilder zeigen erfundene Pakete: Namen, Orte und Sendungsnummern sind ausgedacht. Die Karte lässt sich ohne Home Assistant im Browser ausprobieren: [Demo-Karte öffnen](https://soerenkaiser99.github.io/parcel_tracker/demo/index.html).

## Warum?

Ich war es leid, ständig in verschiedenen Apps Zustelltage und -zeiten zu checken. Ich wollte in Home Assistant an einer Stelle sehen: „Kommt heute ein Paket, und wann?“ – für alle Carrier zusammen, statt in fünf Apps und einem Stapel Mails zu suchen.

- **Pakete erscheinen von selbst**: Die Integration liest die Versandmails und legt die Pakete an – auch Amazons eigene Lieferungen, für die es keine öffentliche Sendungsverfolgung gibt.
- **Benachrichtigung aufs Handy**: sobald ein Paket in Zustellung geht oder zugestellt ist – ohne eigene Automation.
- **Für Automationen gemacht**: Status-Event, Kalender mit den Lieferterminen, Sensor „Pakete heute“ und ein Blueprint für eigene Benachrichtigungen.
- **Lokal und datensparsam**: kein Cloud-Konto, kein fremder Tracking-Dienst nötig; die Zugangsdaten bleiben in Home Assistant, gelesen wird nur ein eigenes Paket-Postfach.
- **Offen**: Open Source, gebaut für deutsche Carrier.

## Was es kann

- **Live-Status vom Paketdienst**: DPD, GLS und Hermes ohne Zugangsdaten, DHL mit kostenlosem API-Key, UPS mit eigenem Entwicklerzugang – [Was brauche ich für welchen Dienst?](https://soerenkaiser99.github.io/parcel_tracker/dienste/)
- **E-Mail-Import** (optional): liest ein eigenes Paket-Postfach per IMAP und legt Pakete aus Shop- und Carrier-Mails an – [E-Mail-Import](https://soerenkaiser99.github.io/parcel_tracker/mail-import/)
- **Karte** `custom:parcel-tracker-card`: Pakete hinzufügen, umbenennen, als erhalten markieren und entfernen – [Die Karte](https://soerenkaiser99.github.io/parcel_tracker/karte/)
- **Benachrichtigungen** (optional): bei „in Zustellung“, „zugestellt“, „abholbereit“ oder einem Problem, ohne eigene Automation, auf Wunsch nur an die Person, der das Paket gehört ([Pakete Personen zuordnen](https://soerenkaiser99.github.io/parcel_tracker/mail-import/#pakete-personen-zuordnen)) – [Benachrichtigungen](https://soerenkaiser99.github.io/parcel_tracker/benachrichtigungen/)
- **Automationen**: fünf Auslöser im Automations-Editor ohne YAML und das Event `parcel_tracker_status_changed` – [Automationen](https://soerenkaiser99.github.io/parcel_tracker/automationen/)
- **Rezepte**: elf Beispiele für Automationen und Karten zum Kopieren – [Rezepte](https://soerenkaiser99.github.io/parcel_tracker/rezepte/)
- **Sensoren und Kalender**: `sensor.paket_<nummer>` pro Paket, `sensor.pakete_heute`, vier Zählsensoren und `calendar.pakete` – [Sensoren, Kalender und Dienste](https://soerenkaiser99.github.io/parcel_tracker/sensoren/)
- **Dienste**: `parcel_tracker.add_parcel`, `remove_parcel`, `rename_parcel`, `mark_delivered`, `refresh`, `track_17track`, `set_gift`, `set_owner` – [Dienste](https://soerenkaiser99.github.io/parcel_tracker/sensoren/#dienste)
- **17track** (optional): ergänzt Ort, Zeitfenster und Verlauf und verfolgt Carrier ohne eigene Anbindung, z. B. FedEx – [17track](https://soerenkaiser99.github.io/parcel_tracker/dienste/#17track-optional)
- **Namen ausblenden** (optional): Pakete heißen überall nur nach dem Paketdienst, für Geschenke auf einem gemeinsamen Dashboard; dazu der Geschenkmodus, in dem nur festgelegte Personen sehen, was in einem Paket steckt – [Namen ausblenden](https://soerenkaiser99.github.io/parcel_tracker/datenschutz/#namen-ausblenden)

## Für Deutschland gebaut

Die Integration ist für Deutschland gebaut (deutsche Carrier und deutsche Mail-Formate). Im Ausland funktionieren DHL (offizielle API, weltweit), UPS (offizielle API) und jeder Carrier über 17track; der Mail-Import versteht nur deutsche Mails (amazon.de sowie deutsche DHL-, Hermes-, UPS-, GLS-, eBay- und AliExpress-Mails). Was in Österreich und der Schweiz geht: [Österreich und Schweiz](https://soerenkaiser99.github.io/parcel_tracker/dienste/#osterreich-und-schweiz).

## Installation

Voraussetzung: [HACS](https://hacs.xyz/docs/use/) ist in Home Assistant installiert. Der Knopf öffnet HACS im eigenen Home Assistant und trägt das Repository als Quelle ein (Schritt 1):

[![Repository in HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=SoerenKaiser99&repository=parcel_tracker&category=integration)

1. Das Repository in HACS als benutzerdefiniertes Repository eintragen – mit dem Knopf oder von Hand: HACS → Menü (⋮) → **Benutzerdefinierte Repositories** → `https://github.com/SoerenKaiser99/parcel_tracker`, Typ **Integration**.
2. In HACS nach „Paket Tracker“ suchen, **Herunterladen** wählen und Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → „Paket Tracker“ einrichten, die Seite einmal neu laden und im Dashboard die Karte „Paket Tracker“ hinzufügen.

HACS lädt die Integration nur herunter; ohne Schritt 3 passiert nichts. Installation ohne HACS, die Einrichtungsfelder und die Schritte nach einem Update: [Installation](https://soerenkaiser99.github.io/parcel_tracker/installation/).

## Anleitung

- [Installation](https://soerenkaiser99.github.io/parcel_tracker/installation/) – herunterladen, einrichten, Karte hinzufügen
- [Was brauche ich für welchen Dienst?](https://soerenkaiser99.github.io/parcel_tracker/dienste/) – DHL-API-Key, GLS, UPS, 17track, Österreich und Schweiz
- [E-Mail-Import](https://soerenkaiser99.github.io/parcel_tracker/mail-import/) – Paket-Postfach, Absender für die Filterregel, was aus welcher Mail wird
- [Die Karte](https://soerenkaiser99.github.io/parcel_tracker/karte/) – Pakete hinzufügen, „Erhalten“, die Optionen `add_form` und `show`
- [Benachrichtigungen](https://soerenkaiser99.github.io/parcel_tracker/benachrichtigungen/) – Ziele, Ereignisse, Texte und der Blueprint
- [Automationen](https://soerenkaiser99.github.io/parcel_tracker/automationen/) – Auslöser ohne YAML und die Felder des Events
- [Rezepte](https://soerenkaiser99.github.io/parcel_tracker/rezepte/) – Beispiele zum Kopieren
- [Sensoren, Kalender und Dienste](https://soerenkaiser99.github.io/parcel_tracker/sensoren/) – alle Entitäten, Attribute, Dienste und der Inhalt der Diagnose
- [Datenschutz](https://soerenkaiser99.github.io/parcel_tracker/datenschutz/) – welche Angabe wohin geht, Namen ausblenden, Zustell-Codes
- [Hilfe](https://soerenkaiser99.github.io/parcel_tracker/hilfe/) – häufige Fragen, Fehler melden, Beispielmails einreichen
- [Roadmap & Status](https://soerenkaiser99.github.io/parcel_tracker/stand/) – was umgesetzt, bestätigt und offen ist
- [Mithelfen](https://soerenkaiser99.github.io/parcel_tracker/mithelfen/) – was gerade am meisten hilft

## Mithelfen und Fehler melden

Paket Tracker ist eine öffentliche Beta. Welche Funktionen noch eine Bestätigung aus dem Alltag brauchen und welche Beispielmails fehlen, steht unter [Wie ihr helfen könnt](https://soerenkaiser99.github.io/parcel_tracker/mithelfen/); häufige Fragen beantwortet die [Hilfe](https://soerenkaiser99.github.io/parcel_tracker/hilfe/).

## Fehler melden

Die Diagnose herunterladen (**Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen**) und an ein Issue mit der Vorlage [„Fehler melden“](https://github.com/SoerenKaiser99/parcel_tracker/issues/new?template=fehler.yml) hängen. Die Schritte und was die Diagnose enthält: [Fehler melden](https://soerenkaiser99.github.io/parcel_tracker/hilfe/#fehler-melden). Geht es um eine Mail, die der Import nicht erkennt: siehe [Beispielmails einreichen](#beispielmails-einreichen).

## Beispielmails einreichen

Landet eine Paketmail im Ordner `Paket-Tracker-Nicht-erkannt` oder fehlt ein Shop oder Carrier, lässt sich das nur mit einer Beispielmail beheben. Eingereicht werden ausschließlich anonymisierte Mails als ZIP an einem GitHub-Issue, erzeugt mit dem Skript `anonymize_mail.py`.

**Nie rohe Mails hochladen.** **Nie Mails privat an den Autor schicken.**

Die fünf Schritte stehen in der Anleitung: [Beispielmails einreichen](https://soerenkaiser99.github.io/parcel_tracker/hilfe/#beispielmails-einreichen).

## Datenschutz

Sendungsnummern gehen nur an den jeweiligen Carrier, die PLZ nur an DHL und GLS, und an 17track geht eine Nummer nur auf ausdrücklichen Wunsch. Aus Mails übernimmt der Import nur Nummer, Artikeltitel, Shop- oder Firmenname, Status und Liefertermin; Adressen, Namen von Personen und Mail-Inhalte landen weder in Attributen noch im Log. Die Einzelheiten und die eine Ausnahme: [Datenschutz](https://soerenkaiser99.github.io/parcel_tracker/datenschutz/).

## Markenhinweis

DHL, DPD, Hermes, UPS, GLS, 17track, Amazon, eBay, AliExpress und Eventim sind Marken ihrer Inhaber. Die Logos (Simple Icons, CC0) dienen nur zur Kennzeichnung des Carriers; DHL als gelbes Schild mit rotem Schriftzug, UPS in der Textfarbe des Themes, Hermes erscheint als blauer Punkt mit „H“, GLS als blauer Punkt mit „G“ (Simple Icons hat kein GLS-Logo), AliExpress als roter Punkt mit „A“, Eventim als dunkelblauer Punkt mit „E“, „Andere (über 17track)“ als grauer Punkt mit „17“. Dieses Projekt ist nicht mit den Unternehmen verbunden.

## Roadmap & Status

Was umgesetzt, von Testern bestätigt, noch ungetestet oder offen ist, steht unter [Roadmap & Status](https://soerenkaiser99.github.io/parcel_tracker/stand/).

---

## English summary

Paket Tracker is a Home Assistant custom integration, built for Germany, that tracks parcels from DHL, DPD, GLS, Hermes and, optionally, UPS. Why: one place in Home Assistant that answers "is a parcel coming today, and when?" across all carriers – parcels appear by themselves from shipping mails (Amazon, eBay, AliExpress, the carriers, and Eventim tickets sent by post), and everything runs locally with no cloud account and no third-party tracking service. It ships its own Lovelace card (`custom:parcel-tracker-card`), one sensor per parcel plus summary sensors, a delivery calendar, a `parcel_tracker_status_changed` event with device triggers for automations without YAML, and optional push notifications (notify entities or classic notify services such as Pushover) with a blueprint for custom texts. Install it through HACS as a custom repository. Tracking numbers are sent only to the matching carrier (or, on request, to 17track), and the postcode is sent only to DHL and GLS. A country setting (Germany, Austria, Switzerland) sets the postcode length; abroad, DHL, UPS and 17track work, while the mail import reads German mails only. The card and the documentation are in German: see the [documentation](https://soerenkaiser99.github.io/parcel_tracker/) and [Roadmap & Status](https://soerenkaiser99.github.io/parcel_tracker/stand/).

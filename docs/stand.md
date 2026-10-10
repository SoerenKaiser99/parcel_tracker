# Roadmap & Status

Was ist umgesetzt, was ist von Testern bestätigt, was ist noch ungetestet? Diese Seite sagt es offen.

Die Änderungen jeder Version stehen auf der [Release-Seite](https://github.com/SoerenKaiser99/parcel_tracker/releases).

!!! info "HACS-Standardkatalog"
    Die Aufnahme in den Standardkatalog von HACS ist beantragt ([hacs/default#11781](https://github.com/hacs/default/pull/11781)) und liegt dort in der Warteschlange. Bis dahin installierst du Paket Tracker als benutzerdefiniertes Repository, siehe [Installation](installation.md).

## Von Testern bestätigt

| Funktion | Stand |
|---|---|
| Hermes Live-Abfrage | umgesetzt; von einem Tester mit einer aktuellen Sendung bestätigt |
| GLS-Live-Abfrage | umgesetzt; von einem Tester mit einem echten Paket bestätigt |
| 17track | umgesetzt; Abfrage von einem Tester bestätigt (das Kontingent wird einmal belastet, die Karte füllt sich) |
| Von Hand weitergeleitete Mails | umgesetzt; von einem Tester bestätigt |

## Umgesetzt

| Funktion | Stand |
|---|---|
| DHL (offizielle API) | umgesetzt |
| DPD (öffentliche Sendungsverfolgung) | umgesetzt |
| E-Mail-Import Amazon, DHL, UPS | umgesetzt |
| Hermes-Mails | umgesetzt |
| eBay-Mails | umgesetzt |
| GLS-Mails | umgesetzt |
| DPD-Ankündigung „Bald ist Ihr DPD Paket da“ (Versender als Name, Lieferschätzung in Werktagen) | umgesetzt nach anonymisierten Beispielmails eines Testers |
| Mails von GLS Österreich und DPD Österreich, internationale DHL-Nummern (`CQ…DE`) | umgesetzt nach anonymisierten Beispielmails von Testern |
| Benachrichtigungen (Optionen und Blueprint) | umgesetzt, an Benachrichtigungs-Entitäten und klassische Dienste (z. B. Pushover) |
| Land (Deutschland, Österreich, Schweiz) | umgesetzt für PLZ-Länge und GLS-Abfrage |
| Bestellungen ohne Zustellmail (Amazon, eBay, AliExpress) | umgesetzt: Ein zugestelltes Carrier-Paket schließt die passende Bestellung, überfällige Bestellungen ohne Sendungsnummer werden „Abgeschlossen ohne Zustellbestätigung“ |

## Umgesetzt, aber noch nicht bestätigt

!!! warning "Hier fehlt noch die Bestätigung aus dem Alltag"
    Diese Funktionen sind gebaut und durch automatische Tests abgedeckt. Mit echten Paketen oder echten Zugangsdaten hat sie noch niemand bestätigt. Läuft dabei etwas anders als beschrieben: [Fehler melden](hilfe.md#fehler-melden).

| Funktion | Was fehlt |
|---|---|
| UPS Live-Status (offizielle API) | noch nicht mit echten Zugangsdaten getestet (UPS-Freischaltung ausstehend) |
| AliExpress-Mails (Bestellungen, Sendungsnummer des Paketdienstes aus den „Packstück“-Mails) und Mails über Apples „E-Mail-Adresse verbergen“ | umgesetzt nach Beispielmails ([Issue #15](https://github.com/SoerenKaiser99/parcel_tracker/issues/15)); im Alltag noch nicht bestätigt |
| 17track: Anreicherung bei DPD und GLS | noch ohne Live-Fall (bei einem DHL-Paket live gesehen) |
| Land Österreich: GLS-Abfrage | mit echten Paketen noch nicht getestet |

## Offen

| Vorhaben | Stand |
|---|---|
| DPD-Live-Abfrage für Österreich | offen |
| Push-Schnittstelle von DHL (DHL meldet Statusänderungen von sich aus) | geprüft, wartet auf Klärung des Zugangs für Privatnutzer |
| **Barcode-Scan** (Wunsch aus [Issue #2](https://github.com/SoerenKaiser99/parcel_tracker/issues/2)) | Sendungsnummer mit der Handykamera vom Label erfassen – geplant über den Scanner der Home-Assistant-App bzw. die Barcode-Erkennung des Browsers, ohne Fremdbibliothek. Braucht Beispiel-Scans je Paketdienst, weil auf den Labels oft mehr als die Sendungsnummer steht |
| **International** | Karte auch auf Englisch, weitere Amazon-Länder im Mail-Import, nationale Paketdienste (Beispiele: Österreichische Post, Royal Mail, PostNL, USPS) – erst sinnvoll mit anonymisierten Beispielmails von Testern aus den jeweiligen Ländern |

Was in Österreich und der Schweiz heute geht und was nicht, steht unter [Österreich und Schweiz](dienste.md#osterreich-und-schweiz).

## Verworfen

| Vorhaben | Grund |
|---|---|
| Amazon per Konto-Anmeldung | verworfen zugunsten des Mail-Imports |
| DHL ohne offizielle Schnittstelle (Webseite auslesen, Login mit dem Kundenkonto) | bewusst nicht eingebaut, siehe [DHL](dienste.md#kein-key-dann-die-dhl-mails) |

## Mithelfen

Was gerade am meisten hilft – welche Funktionen eine Bestätigung brauchen und welche Beispielmails fehlen –, steht auf der Seite [Wie ihr helfen könnt](mithelfen.md).

- **Fehler gefunden?** [Fehler melden](hilfe.md#fehler-melden) – mit der Diagnose-Datei.
- **Eine Mail wird nicht erkannt?** [Beispielmails einreichen](hilfe.md#beispielmails-einreichen) – nur anonymisiert.

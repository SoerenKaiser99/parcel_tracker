# Hilfe

Häufige Fragen und was du prüfen kannst. Findest du hier nichts, steht am Ende, wie du einen [Fehler meldest](#fehler-melden).

## Erst einmal: die drei Schritte nach einem Update

Viele Probleme verschwinden damit:

1. Das Update in HACS installieren.
2. Home Assistant neu starten.
3. Die Seite im Browser neu laden oder die Home-Assistant-App schließen und wieder öffnen.

Die Integration zu entfernen und neu hinzuzufügen ist nie nötig. Dabei gingen nur die Pakete und Einstellungen verloren.

## Installation

### „Paket Tracker“ taucht unter „Integration hinzufügen“ nicht auf

- Prüf in HACS, ob die Integration unter den heruntergeladenen steht.
- Starte Home Assistant noch einmal neu.
- Dass das Repository nach dem Herunterladen nicht mehr im Dialog „Benutzerdefinierte Repositories“ erscheint, ist kein Fehler.

### Karte wird nicht gefunden?

Das Dashboard meldet „Custom element doesn't exist: parcel-tracker-card“, oder „Paket Tracker“ fehlt in der Kartenauswahl.

1. Integration auf v0.3.6 oder neuer aktualisieren, Home Assistant neu starten und die Seite einmal neu laden.
2. Unter **Einstellungen → Dashboards → ⋮ → Ressourcen** prüfen, ob `/local/parcel_tracker/parcel-tracker-card.js?v=…` (oder `/parcel_tracker/parcel-tracker-card.js?v=…`) eingetragen ist.
3. Verwaltest du die Dashboard-Ressourcen per YAML (`resource_mode: yaml` oder `mode: yaml` unter `lovelace:`), kann die Integration die Karte nicht selbst eintragen. Ab v0.3.6 erscheint dann unter **Einstellungen → Reparaturen** ein Hinweis mit der genauen URL. Ergänz sie von Hand unter `lovelace:` → `resources:` und starte Home Assistant neu:

    ```yaml title="configuration.yaml (Ausschnitt)"
    lovelace:
      resources:
        - url: /local/parcel_tracker/parcel-tracker-card.js?v=…
          type: module
    ```

    Die genaue URL samt dem Teil hinter `?v=` steht im Reparatur-Hinweis.

??? note "Hintergrund und ältere Versionen (bis v0.3.5)"
    Bis v0.3.5 lag der Fehler meist an der Integration selbst: Sie lud die Karte zusätzlich als Frontend-Modul, gleichzeitig mit der Oberfläche von Home Assistant. War die Karte schneller, ging ihre Anmeldung verloren. Behoben in v0.3.6, die Karte kommt seitdem nur noch als Dashboard-Ressource.

    Bis v0.3.5 gilt: normal neu laden (F5; in der Home-Assistant-App: App schließen und neu öffnen). Kein hartes Neuladen (Strg+F5 bzw. Cmd+Shift+R) und nicht den Cache leeren – beides löst den Fehler dort erst aus.

Die Kartendatei selbst zu ändern ist nicht nötig. Änderungen daran überschreibt die Integration beim nächsten Start.

### Die Karte zeigt nach einem Update noch das Alte

Der Browser behält die alte Karte, bis die Seite neu geladen wird. Ab v0.3.9 zeigt die Karte dann selbst die Zeile „Neue Version installiert – Seite neu laden, um die Karte zu aktualisieren.“ mit dem Knopf „Neu laden“. Kommst du von einer älteren Version, lädst du die Seite einmal von Hand neu.

## Optionen („Konfigurieren“)

### Die Optionen öffnen sich nicht oder lassen sich nicht speichern

Die Optionen findest du unter **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren**. Das prüfst du der Reihe nach:

1. **Nach einem Update neu gestartet?** Ohne Neustart von Home Assistant läuft noch die alte Version. Danach die Seite im Browser neu laden.
2. **Home-Assistant-Version:** Paket Tracker setzt Home Assistant 2025.10.0 oder neuer voraus.
3. **Meldung im Formular?** Speichern prüft die Zugangsdaten sofort. Lehnt ein Dienst sie ab, bleibt das Formular offen und nennt den Grund:

    | Meldung | Was zu tun ist |
    |---|---|
    | „DHL hat diesen API-Key abgelehnt.“ | siehe [DHL-Key wird abgelehnt](#dhl-key-wird-abgelehnt) |
    | „DHL ist gerade nicht erreichbar. Versuch es später noch einmal.“ | später erneut speichern |
    | „Gib eine 5-stellige PLZ ein.“ / „Gib eine 4-stellige PLZ ein.“ | PLZ passend zum Land eintragen (Deutschland 5, Österreich und Schweiz 4 Ziffern) |
    | „Der Mailserver hat Benutzername oder Passwort abgelehnt.“ | siehe [App-Passwörter](mail-import.md#app-passworter) |
    | „Der Mailserver ist nicht erreichbar. Prüf den Servernamen.“ | IMAP-Server prüfen |
    | „Gib das Passwort des Postfachs ein.“ | Passwort des Paket-Postfachs eintragen |
    | „UPS hat Client-ID oder Secret abgelehnt.“ | Zugangsdaten prüfen; steht die UPS-App noch auf „Pending“? |
    | „Gib das UPS-Client-Secret ein.“ | Client-Secret eintragen |
    | „17track hat diesen API-Key abgelehnt.“ | Key auf api.17track.net prüfen |
    | „Wähl mindestens ein Ziel für die Benachrichtigungen.“ | ein Ziel wählen oder den Schalter ausschalten |

4. **Immer noch nichts?** Dann ist es ein Fehler, den ich kennen sollte: [Fehler melden](#fehler-melden) – mit der Diagnose-Datei und, wenn du magst, dem passenden Auszug aus dem Log von Home Assistant.

Leere Felder für Keys, Benutzername, Passwort und Secret behalten beim Speichern die gespeicherten Werte. Du musst sie nicht jedes Mal neu eintragen.

## DHL

### DHL-Key wird abgelehnt

**Beim Antrag (DHL schickt eine Ablehnungsmail):** DHL nennt als Bedingung einen gültigen Firmennamen **und eine dazu passende Domain-E-Mail-Adresse**. Es reicht nicht, nur das Feld **Firma / Company** auszufüllen. Das DHL-Konto selbst sollte auf eine Adresse unter eigener Domain laufen, und der Firmenname sollte dazu passen. Alle Hinweise: [DHL-API-Key anlegen](dienste.md#dhl-api-key-anlegen).

**Beim Eintragen in Home Assistant („DHL hat diesen API-Key abgelehnt.“):**

- Ist die Freischaltung schon durch? Sie dauert bis zu 24 Stunden.
- Hast du die API **„Shipment Tracking – Unified“** gewählt (nicht „Parcel DE …“) und das Environment **„Production (Europe)“**?
- Hast du den **API Key** eingetragen, nicht das Secret?

**Später, im laufenden Betrieb:** Akzeptiert DHL den Key nicht mehr, erscheint unter **Einstellungen → Reparaturen** der Hinweis „DHL-API-Key abgelehnt“. Öffne die Integration und gib einen neuen Key ein.

**Kein Key zu bekommen?** Der Key ist kein Muss. Die DHL-Mails reichen: [Kein Key? Dann die DHL-Mails](dienste.md#kein-key-dann-die-dhl-mails).

### Ein DHL-Paket zeigt „Kein Live-Status“

Der DHL-API-Key fehlt. Trag ihn unter „Konfigurieren“ ein, oder lass den Status aus den DHL-Mails über den Mail-Import kommen. Für UPS ohne Zugangsdaten gilt dasselbe.

### Ein Paket zeigt „Noch keine Daten vom Carrier“

Der Paketdienst kennt die Nummer nicht oder noch nicht. Bleibt es so, prüf die Nummer auf Tippfehler.

### Das DHL-Zeitfenster ist wieder verschwunden

DHL berechnet Liefertag und Zeitfenster laufend neu. Ein Zeitfenster kann im Lauf des Tages erscheinen und wieder verschwinden. Nimmt DHL die Angabe zurück, bleibt die zuletzt genannte stehen, solange das Paket unterwegs und der Tag nicht vorbei ist.

## E-Mail-Import

### Die Anmeldung am Postfach wird abgelehnt

Viele Anbieter verlangen für IMAP ein eigenes App-Passwort oder eine Freigabe: siehe [App-Passwörter](mail-import.md#app-passworter).

### Eine Mail wird nicht erkannt

Das prüfst du der Reihe nach:

1. **Ist die Mail im Paket-Postfach angekommen?** Wenn nicht, greift die Filterregel im Hauptpostfach nicht. Steht der Absender in der [Liste der Absender](mail-import.md#filterregel-anlegen)?
2. **In welchem Ordner liegt sie?** Erkannte Mails landen in `Paket-Tracker-Verarbeitet`, nicht erkannte in `Paket-Tracker-Nicht-erkannt`.
3. **Ist es eine deutsche Mail von einem der unterstützten Absender?** Der Import versteht nur deutsche Mails (amazon.de sowie deutsche DHL-, Hermes-, UPS-, GLS-, eBay- und AliExpress-Mails).
4. **Ist die Mail älter als 14 Tage?** Dann wird sie nur als gelesen markiert.
5. **Von Hand weitergeleitet?** Der Kopfzeilen-Block der Original-Mail („Von: … / Gesendet: … / An: … / Betreff: …“) muss stehen bleiben. Siehe [Von Hand weiterleiten](mail-import.md#von-hand-weiterleiten).
6. **Apple „E-Mail-Adresse verbergen“?** Die Filterregel braucht die Relay-Adresse, so wie sie in der Mail steht.
7. **Werbung oder Konto-Mail?** Solche Mails markiert der Import absichtlich nur als gelesen.

Liegt eine echte Paketmail in `Paket-Tracker-Nicht-erkannt`, lässt sich das nur mit einer Beispielmail beheben: [Beispielmails einreichen](#beispielmails-einreichen).

### Reparatur-Hinweis „Amazon-Mails nicht erkannt“

Der Import konnte fünf Amazon-Mails in Folge nicht lesen. Meist hat Amazon dann das Mail-Format geändert. Prüf, ob es ein Update für Paket Tracker gibt. Die Mails liegen im Ordner `Paket-Tracker-Nicht-erkannt`.

### Ein Paket steht doppelt in der Liste

Kam die Mail des Paketdienstes vor der Mail des Shops oder war die Zuordnung nicht eindeutig, entstehen zwei Einträge. Wann die Integration zusammenführt und wann nicht, steht unter [Zusammenführen](mail-import.md#zusammenfuhren-carrier-mail-und-bestellung). Einen überzähligen Eintrag kannst du auf der Karte löschen.

### Eine Bestellung steht auf „Abgeschlossen (ohne Zustellbestätigung)“

Für diese Bestellung kam keine „Zugestellt“-Mail. Die Integration hat sie nach Ablauf der Frist selbst geschlossen. Siehe [Bestellungen ohne Zustellmail](mail-import.md#bestellungen-ohne-zustellmail).

## Paketdienste

### Reparatur-Hinweis „…-Sendungsverfolgung funktioniert nicht“

Seit 24 Stunden schlagen alle Abfragen bei diesem Paketdienst fehl. Vermutlich hat er seine Seite geändert. Prüf, ob es ein Update für Paket Tracker gibt. Bei GLS kommen die Pakete so lange weiter aus den GLS-Mails.

### Reparatur-Hinweis „UPS-Monatsbudget verbraucht“

Alle für diesen Monat erlaubten UPS-Abfragen sind verbraucht. UPS-Pakete kommen bis Monatsende nur aus Mails. Der Hinweis verschwindet am 1. des nächsten Monats. Bei Bedarf erhöhst du das Budget in den Optionen.

### Reparatur-Hinweise zu 17track

- **„17track-Kontingent fast verbraucht“ / „verbraucht“:** Bereits angemeldete Pakete werden weiter aktualisiert. Neue lassen sich bei leerem Kontingent nicht mehr anmelden.
- **„17track-API-Key abgelehnt“:** Bis du in den Optionen einen gültigen Key einträgst oder die Integration neu lädst, fragt Paket Tracker 17track nicht mehr ab.

## Benachrichtigungen

### Jede Meldung kommt doppelt

- Du hast Benachrichtigungen in den Optionen **und** über den Blueprint oder eine eigene Automation eingeschaltet. Schalte einen der Wege aus.
- Oder du hast für dasselbe Handy die Entität **und** den „Dienst notify.mobile_app_…“ gewählt. Wähl nur eines von beiden.

### Es kommt keine Meldung

- Ist ein Ziel gewählt? Ohne Ziel wird nichts gesendet.
- Ist das Ereignis angekreuzt? „Problem“ ist von Haus aus nicht angekreuzt.
- Der allererste Status eines neuen Pakets wird nie gemeldet.
- Für eine Bestellung, die ohne Zustellmail abgeschlossen wurde, gibt es keine Meldung.
- Steht ein Ziel mit dem Zusatz „nicht mehr vorhanden“ in der Auswahl, wird es übersprungen.

## Fehler melden

1. In Home Assistant die Diagnose herunterladen: **Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen**.
2. Die Datei kurz ansehen (JSON, jeder Texteditor zeigt sie an).
3. Auf GitHub ein Issue mit der Vorlage [„Fehler melden“](https://github.com/SoerenKaiser99/parcel_tracker/issues/new?template=fehler.yml) öffnen: Version der Integration, Home-Assistant-Version, Carrier, was passiert ist und was du erwartet hast.
4. Die Diagnose-Datei ins Feld „Diagnose-Datei“ ziehen. Ein Log-Auszug ist freiwillig.

!!! info "Was in der Diagnose steht"
    Keine API-Keys, keine Passwörter, keine PLZ, keine Paketnamen, keine Mail-Inhalte. Sendungs- und Bestellnummern stehen nur maskiert drin (Ziffern werden zu `9`, Buchstaben zu `A`). Die vollständige Liste: [Diagnose](sensoren.md#diagnose).

!!! warning "Nicht ins Issue"
    Keine Zugangsdaten, keine API-Keys und keine rohen Mails. Sendungsnummern nur gekürzt oder mit erfundenen Ziffern nennen.

Geht es um eine Mail, die der Import nicht erkennt, hilft zusätzlich eine anonymisierte Beispielmail – siehe unten.

## Beispielmails einreichen

Landet eine Paketmail im Ordner `Paket-Tracker-Nicht-erkannt` oder fehlt ein Shop oder Paketdienst, lässt sich das nur mit einer Beispielmail beheben. Eingereicht werden ausschließlich anonymisierte Mails als ZIP an einem GitHub-Issue.

!!! danger "Nie rohe Mails hochladen. Nie Mails privat an den Autor schicken."
    In einer Paketmail stehen dein Name, deine Adresse und oft deine Telefonnummer. Ein GitHub-Issue ist öffentlich. Lade nur hoch, was das Skript anonymisiert hat **und** was du danach selbst gelesen hast.

### Schritt 1: Die Mail als `.eml` speichern

Speicher die Original-Mail – leite sie nicht weiter. Eine Weiterleitung verändert Absender und Aufbau.

- **Thunderbird:** Rechtsklick auf die Mail → „Speichern als“.
- **Gmail im Browser:** ⋮ an der Mail → „Nachricht herunterladen“.
- **Apple Mail:** die Mail aus der Liste in einen Ordner ziehen.

Leg alle Mails in einen eigenen Ordner.

??? note "Wenn du nur eine weitergeleitete Mail hast"
    Weitergeleitete Mails helfen deutlich weniger als Originale und müssen besonders genau gelesen werden. Steht in der Weiterleitung der Kopfzeilen-Block der Original-Mail („Von: … / Gesendet: … / An: … / Betreff: …“), übernimmt das Skript nur diesen Block und die Mail darunter. Alles darüber (eigene Zeilen, die eigene Signatur) lässt es weg, den ursprünglichen Absender im Block lässt es stehen, die Empfänger ersetzt es. Ohne diesen Block und für eigene Zeilen unter dem Block kann das Skript eine Signatur nicht als solche erkennen.

### Schritt 2: Das Skript herunterladen

Lade [`anonymize_mail.py`](https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/scripts/anonymize_mail.py) herunter (im Browser „Speichern unter“) und leg es neben den Ordner.

Es ist eine einzelne Datei, braucht nur Python 3 und läuft lokal – ohne Netzwerkzugriff und ohne Installation der Integration.

### Schritt 3: Das Skript starten

Im Terminal (unter Windows `py` statt `python3`):

```sh
python3 anonymize_mail.py <Ordner> --zip
```

Das Skript fragt nach Name, Straße und Hausnummer, Postleitzahl, Ort, Telefonnummer und Mail-Adresse und ersetzt diese Angaben überall. Leer lassen überspringt eine Angabe. Mindestens eine Angabe ist nötig.

Die Angaben lassen sich auch als Optionen übergeben:

```sh
python3 anonymize_mail.py <Ordner> --zip --name "Vorname Nachname" --street "Straße 1" --postcode 12345 --city Ort
```

Dazu gibt es `--phone` und `--email`. Ganz ohne Angaben arbeitet das Skript nur mit `--ohne-angaben`: Es fragt dann nicht und bereinigt nur allgemein – Namen und Orte können dann stehen bleiben.

??? note "Was das Skript unabhängig von deinen Angaben ersetzt"
    - alle Mail-Adressen außer dem Absender des Shops oder Paketdienstes,
    - Telefonnummern,
    - Links (nur der Servername bleibt),
    - Sendungs- und Bestellnummern (gleiche Form, erfundene Ziffern),
    - Ablageorte, Anreden, Adressblöcke, Zeilen mit Postleitzahl und Ort,
    - Namen von Nachbarn, Empfängern und privaten Absendern.

    Technische Kopfzeilen und Anhänge entfallen. Bei weitergeleiteten oder beantworteten Mails (Betreff mit „WG:“, „Fwd:“, „AW:“, „Re:“) ersetzt es auch den Absender. Sieht eine Mail weitergeleitet aus, nennt das Skript die Datei am Ende in einer „ACHTUNG“-Zeile – eine Signatur kann darin stehen geblieben sein.

    Frühere Ergebnisse im Ordner `anonymisiert/` löscht das Skript vor dem Schreiben.

### Schritt 4: Die Ergebnisse lesen

Die Ergebnisse liegen in `<Ordner>/anonymisiert/`.

**Öffne jede Datei im Texteditor und lies sie durch.** Das Skript erkennt nicht alles. Steht noch etwas Privates drin, ersetz die Stelle von Hand oder lass die Mail weg und pack das ZIP neu.

### Schritt 5: Das Issue öffnen

Öffne ein Issue mit der Vorlage [„Mail wird nicht erkannt“](https://github.com/SoerenKaiser99/parcel_tracker/issues/new?template=mail-nicht-erkannt.yml) und häng `paket-tracker-beispiele.zip` aus dem Ordner `anonymisiert/` an.

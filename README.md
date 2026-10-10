# Paket Tracker

[![Version](https://img.shields.io/github/v/release/SoerenKaiser99/parcel_tracker?label=Version)](https://github.com/SoerenKaiser99/parcel_tracker/releases/latest) [![Downloads](https://img.shields.io/github/downloads/SoerenKaiser99/parcel_tracker/total?label=Downloads)](https://github.com/SoerenKaiser99/parcel_tracker/releases)

Home-Assistant-Integration, die Pakete von DHL, DPD, GLS, Hermes und (optional) UPS verfolgt, auf Wunsch über 17track ergänzt oder weitere Carrier verfolgt und Amazon-, eBay-, AliExpress-, GLS-, Hermes- und UPS-Pakete aus E-Mails übernimmt: eigene Sensoren, ein Sammelsensor für "heute", ein Lieferkalender, ein Status-Event, Benachrichtigungen aufs Handy und eine eigene Dashboard-Karte.

**Für Deutschland gebaut:** Die Integration ist für Deutschland gebaut (deutsche Carrier und deutsche Mail-Formate). Im Ausland funktionieren schon DHL (offizielle API, weltweit), UPS (offizielle API) und jeder Carrier über 17track; der Mail-Import versteht nur deutsche Mails (amazon.de sowie deutsche DHL-, Hermes-, UPS-, GLS-, eBay- und AliExpress-Mails).

<p>
  <img src="https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/docs/images/karte-hell.png" width="260" alt="Die Paket-Tracker-Karte im hellen Design: zwölf Pakete von DHL, DPD, GLS, Hermes, UPS, Amazon, eBay und 17track mit Status, Fortschrittsbalken und Liefertermin">
  <img src="https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/docs/images/karte-detail.png" width="260" alt="Die Karte mit geöffneter Eingabe für eine neue Sendung und einem aufgeklappten DHL-Paket: Verlauf der Sendung und die Knöpfe „Details über 17track holen“, „Umbenennen“ und „Löschen“">
  <img src="https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/docs/images/karte-dunkel.png" width="260" alt="Die Paket-Tracker-Karte im dunklen Design">
</p>

Die Bilder zeigen erfundene Pakete: Namen, Orte und Sendungsnummern sind ausgedacht. Sie stammen aus der Demo-Seite [`docs/demo/`](docs/demo/index.html), die die echte Karte ohne Home Assistant im Browser zeigt (Repository-Ordner mit `python3 -m http.server` ausliefern und `docs/demo/index.html` öffnen; `?theme=dark` für das dunkle Design, `?open=1` klappt das erste Paket auf, `?add=open` öffnet die Eingabe hinter dem Plus-Knopf, `?add=always` zeigt sie dauerhaft).

## Warum?

Ich war es leid, ständig in verschiedenen Apps Zustelltage und -zeiten zu checken. Ich wollte in Home Assistant an einer Stelle sehen: „Kommt heute ein Paket, und wann?“ – für alle Carrier zusammen, statt in fünf Apps und einem Stapel Mails zu suchen.

- **Pakete erscheinen von selbst**: Die Integration liest die Versandmails und legt die Pakete an – auch Amazons eigene Lieferungen, für die es keine öffentliche Sendungsverfolgung gibt.
- **Benachrichtigung aufs Handy**: sobald ein Paket in Zustellung geht oder zugestellt ist – ohne eigene Automation.
- **Für Automationen gemacht**: Status-Event, Kalender mit den Lieferterminen, Sensor „Pakete heute“ und ein Blueprint für eigene Benachrichtigungen.
- **Lokal und datensparsam**: kein Cloud-Konto, kein fremder Tracking-Dienst nötig; die Zugangsdaten bleiben in Home Assistant, gelesen wird nur ein eigenes Paket-Postfach.
- **Offen**: Open Source, gebaut für deutsche Carrier.

## Was es kann

- **DHL**: Abfrage über die offizielle API "Shipment Tracking – Unified". Der API-Key ist optional; ohne Key fragt die Integration DHL nicht ab, und ein DHL-Paket ohne Mail zeigt auf der Karte „Kein Live-Status“ (siehe [DHL-API-Key anlegen](#dhl-api-key-anlegen)). Mit Key und hinterlegter PLZ liefert DHL zusätzliche Details (z. B. Standort).
- **DPD**: Abfrage über die öffentliche DPD-Sendungsverfolgung, nur mit der Sendungsnummer. DPD liefert Status und die fünf Meilenstein-Termine, aber keinen Standort und kein Zeitfenster. Die detailliertere DPD-Seite braucht eine Postleitzahl und ist durch ein Captcha geschützt, deshalb nutzt die Integration sie nicht.
- **GLS**: Abfrage über die offene Sendungsverfolgung der GLS-Webseite, nur mit der Paketnummer (11 Ziffern), ohne Zugangsdaten. Mit hinterlegter PLZ liefert GLS zusätzlich den Verlauf. Die Abfrage ist kein offizieller Zugang und kann wegfallen – dann bleiben die GLS-Mails und 17track (siehe [GLS](#gls)).
- **Hermes**: Abfrage über die öffentliche Hermes-Sendungsverfolgung, nur mit der Sendungsnummer (`H…` mit 19 Ziffern oder 14 Ziffern), ohne Zugangsdaten und ohne PLZ. Hermes liefert Status und Verlauf, aber keinen Liefertag – den übernimmt die Integration aus den Hermes-Mails.
- **UPS**: Status aus den UPS-Mails; mit eigener Client-ID und eigenem Secret zusätzlich Live-Status über die offizielle UPS Track API, mit Monatsbudget (siehe [UPS-Live-Status](#ups-live-status-optional)).
- **17track** (optional): Auf Knopfdruck ergänzt 17track Ort, Zeitfenster und Verlauf; „Andere (über 17track)“ verfolgt Carrier ohne eigene Anbindung, z. B. FedEx (siehe [17track](#17track-optional)).
- **E-Mail-Import** (optional): Liest ein eigenes Paket-Postfach per IMAP und legt Pakete aus Amazon-, eBay-, AliExpress-, DHL-, GLS-, Hermes- und UPS-Mails automatisch an (siehe [E-Mail-Import](#e-mail-import)).
- **Karte**: `custom:parcel-tracker-card`, direkt von der Integration ausgeliefert, erscheint im Karten-Auswahldialog als "Paket Tracker". Pakete lassen sich dort hinzufügen (über den Plus-Knopf oben rechts), umbenennen und entfernen.
- **Sensoren**: `sensor.paket_<nummer>` pro Paket (Zustand = Status, mit Attributen wie Carrier, `carrier_name`, ETA, Standort, `location_source`, Abholpunkt, Zustellzeitpunkt `delivered_at`, `assumed_delivered` – wahr bei einer Bestellung, die ohne Zustellmail abgeschlossen wurde, siehe [Amazon-Pakete](#amazon-pakete) –, Verlauf, `track17`, `track17_carrier`), `sensor.pakete_heute` und – mit 17track-Key – `sensor.paket_tracker_17track_kontingent` für die verbleibenden 17track-Nummern. `sensor.pakete_heute` zählt die Pakete, die heute sicher kommen: Status „In Zustellung“ oder ein fester Liefertag heute; sie stehen im Attribut `parcels`. Nennt der Versender nur eine Spanne, in der heute liegt (z. B. „2.–5. Okt.“), zählt das Paket nicht mit, sondern steht als „möglich“ in den Attributen `possible` (Liste, aufgebaut wie `parcels`) und `possible_count` (Anzahl) – beide lassen sich in Automationen und Templates nutzen, z. B. `{{ state_attr('sensor.pakete_heute', 'possible_count') }}`. Meldet eine Mail oder der Carrier „In Zustellung“ oder einen festen Tag heute, wechselt es von selbst zu den sicheren. Was heute schon zugestellt wurde, zählt nicht mehr mit und steht in `delivered_today` (Liste, aufgebaut wie `parcels`) und `delivered_today_count` (Anzahl, z. B. `{{ state_attr('sensor.pakete_heute', 'delivered_today_count') }}`): Pakete mit Status „Zugestellt“, deren Zustellzeitpunkt `delivered_at` heute liegt, gerechnet in der Zeitzone von Home Assistant; nennt der Carrier keinen Zeitpunkt, gilt der Tag des Statuswechsels. Was zur Abholung bereitliegt (Status „Abholbereit“: Packstation, Filiale, PaketShop), steht in `awaiting_pickup` (Liste, aufgebaut wie `parcels`) und `awaiting_pickup_count` (Anzahl, z. B. `{{ state_attr('sensor.pakete_heute', 'awaiting_pickup_count') }}`); an der Zählung von `sensor.pakete_heute` ändert das nichts. Das Attribut `integration_version` nennt die installierte Version der Integration (für den Neuladen-Hinweis der Karte, nicht im Verlauf gespeichert). Vier weitere Sensoren liefern je eine Zahl als Zustand (0, wenn nichts da ist) und die Pakete im Attribut `parcels` (aufgebaut wie bei `sensor.pakete_heute`): `sensor.pakete_unterwegs` zählt alle Pakete, die noch nicht zugestellt sind (auch abholbereite, solche mit Problem oder unbekanntem Status), `sensor.pakete_moeglich` die heute möglichen (wie `possible`), `sensor.pakete_zugestellt_heute` die heute zugestellten (wie `delivered_today`) und `sensor.pakete_abholbereit` die abholbereiten (wie `awaiting_pickup`; sie zählen weiter bei `sensor.pakete_unterwegs` mit). Sie eignen sich für Bedingungen in Dashboards und Automationen, siehe [Karte hinzufügen](#karte-hinzufügen).
- **Kalender**: `calendar.pakete` zeigt die erwarteten Zustelltermine.
- **Event**: `parcel_tracker_status_changed` feuert bei jedem Statuswechsel eines Pakets.
- **Benachrichtigungen** (optional): Bei „in Zustellung“, „zugestellt“, „abholbereit“ oder einem Problem geht eine Benachrichtigung an die gewählten Ziele, ohne eigene Automation; für eigene Texte und Bedingungen gibt es einen Blueprint (siehe [Benachrichtigungen](#benachrichtigungen)).
- **Namen ausblenden** (optional): Ein Schalter in den Optionen lässt Pakete überall nur nach dem Paketdienst heißen (`DHL-Paket …2557`, `Amazon-Bestellung …4321`) – für Geschenke auf einem gemeinsamen Dashboard (siehe [Namen ausblenden](#namen-ausblenden)).
- **Dienste**: `parcel_tracker.add_parcel`, `remove_parcel`, `rename_parcel`, `refresh`, `track_17track`.

Was (noch) nicht geht: siehe [Roadmap & Status](#roadmap--status). Amazon-, eBay- und AliExpress-Bestellungen kennt die Integration nur aus Mails; abgefragt wird dort nur die Sendungsnummer des Carriers, sobald eine Mail sie verrät.

## Installation

### Mit HACS (empfohlen)

Voraussetzung: [HACS](https://hacs.xyz/docs/use/) ist in Home Assistant installiert. HACS lädt die Integration nur herunter. Eingerichtet wird sie danach in Home Assistant selbst (Schritt 5) – ohne diesen Schritt passiert nichts.

Am schnellsten geht es mit diesem Knopf – er öffnet HACS im eigenen Home Assistant und trägt das Repository als Quelle ein. Danach weiter bei Schritt 3:

[![Repository in HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=SoerenKaiser99&repository=parcel_tracker&category=integration)

Oder von Hand:

1. HACS öffnen → Menü (⋮) oben rechts → **Benutzerdefinierte Repositories**.
2. Repository `https://github.com/SoerenKaiser99/parcel_tracker` eintragen, Typ **Integration** wählen, hinzufügen.
3. In HACS nach „Paket Tracker" suchen, öffnen und **Herunterladen** wählen.
4. Home Assistant neu starten.
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → „Paket Tracker" suchen und einrichten.
6. Seite einmal neu laden, dann im Dashboard die Karte „Paket Tracker" hinzufügen (siehe [Karte hinzufügen](#karte-hinzufügen)).

Taucht „Paket Tracker" in Schritt 5 nicht auf: In HACS prüfen, ob die Integration unter den heruntergeladenen steht, und Home Assistant noch einmal neu starten. Dass das Repository nach dem Herunterladen nicht mehr im Dialog „Benutzerdefinierte Repositories" erscheint, ist kein Fehler.

### Ohne HACS (von Hand)

1. Auf der [Release-Seite](https://github.com/SoerenKaiser99/parcel_tracker/releases/latest) die Datei `parcel_tracker.zip` herunterladen.
2. Im Konfigurationsordner von Home Assistant den Ordner `custom_components/parcel_tracker` anlegen und den Inhalt der ZIP-Datei dort hinein entpacken (die Datei `manifest.json` liegt dann direkt in diesem Ordner).
3. Home Assistant neu starten.
4. Weiter wie oben ab Schritt 5.

Updates kommen auf diesem Weg nicht von selbst: Für eine neue Version die ZIP-Datei erneut herunterladen, den Ordnerinhalt ersetzen und Home Assistant neu starten.

### Einrichtungsfelder

- **DHL-API-Key** (optional): Wird beim Speichern geprüft. Leer lassen, wenn nur DPD genutzt wird oder der Key später ergänzt werden soll.
- **Land** (Deutschland, Österreich oder Schweiz; vorbelegt mit dem Land aus den Home-Assistant-Einstellungen, sonst Deutschland): Bestimmt, wie viele Ziffern die PLZ hat und welche GLS-Abfrage gefragt wird (siehe [Österreich und Schweiz](#österreich-und-schweiz)).
- **PLZ** (optional; Deutschland 5 Ziffern, z. B. 10115, Österreich und Schweiz 4 Ziffern, z. B. 1010): Lässt DHL zusätzliche Details und GLS den Verlauf liefern.
- **Zugestellte Pakete ausblenden nach (Tagen)** (Standard: 3, Bereich 1–30): Nach dieser Zeit verschwindet ein zugestelltes Paket aus der Übersicht.

Alle vier Felder lassen sich später über **Konfigurieren** an der Integration ändern. Dort gibt es zusätzlich den Schalter [Namen ausblenden](#namen-ausblenden). Wird das Key-Feld beim Ändern leer gelassen, bleibt der vorhandene Key erhalten. Bestehende Einrichtungen bleiben ohne Zutun auf Deutschland. Wer das Land wechselt, trägt die PLZ im selben Formular neu ein: Passt die gespeicherte PLZ nicht zur Länge des neuen Landes, meldet das Formular das, statt sie zu verwerfen.

### Österreich und Schweiz

Die Integration ist für Deutschland gebaut; die Einstellung **Land** ist die Grundlage für die Nutzung in Österreich und der Schweiz. Stand heute:

- **Funktioniert mit der Einstellung**: PLZ mit 4 Ziffern, DHL mit API-Key über die offizielle API (die PLZ geht so an DHL, wie sie eingetragen ist), UPS über die offizielle API, jeder Carrier über 17track.
- **GLS**: Für Österreich fragt die Integration die österreichische Variante der offenen GLS-Abfrage. Eine Probe mit einer ungültigen Nummer hat gezeigt, dass sie genauso antwortet wie die deutsche; mit echten Paketen noch nicht getestet. Für die Schweiz bleibt die GLS-Abfrage auf der deutschen Variante, weil die Schweizer Variante ihre Texte auf Englisch liefert. Der Mail-Import liest die Mails von `noreply@gls-group.eu` („Ihr Paket von … ist unterwegs“; „… wurde durch GLS am gewünschten Ort abgestellt“ oder „zugestellt“ mit der Uhrzeit; auch mehrere Pakete in einer Mail: nennt eine Mail mehrere Paketnummern, legt der Import für jede Nummer ein eigenes Paket an) und von `noreply@gls-rtt.com` („Ihr Paket ist auf dem Weg!“ bedeutet: heute in Zustellung), egal welches Land eingestellt ist. Zustelladresse, Empfängername und Referenz übernimmt er nie.
- **DPD Österreich**: Mails von `no_reply@dpd.at` legen das Paket an („Ein DPD Paket für dich“) und melden die Zustellung mit Uhrzeit („Neuigkeiten zu deinem Paket“). Als zugestellt gilt ein Paket nur, wenn es laut Mail „zugestellt“, „abgestellt“ oder am gewünschten Abstellort bzw. Wunschort „hinterlegt“ wurde; auch „beim Nachbarn abgegeben“ gilt als zugestellt (wer der Nachbar ist, wird nicht gelesen). „Abholbereit“ zeigt es nur, wenn die Mail einen Pickup Paketshop bzw. eine Abholstation nennt und das Paket dort liegt („hinterlegt“, „zugestellt“, „abholbereit“, „bereit“) – „auf dem Weg in den Paketshop“ oder „umgeleitet“ reicht nicht. Jede andere Meldung (an DPD übergeben, im Depot, „wird morgen zugestellt“, nicht zugestellt) setzt keinen Status. Gelesen werden nur die Sätze von `no_reply@dpd.at`; Mails anderer Absender bei dpd.at legen das Paket nur an. Den Abstellort übernimmt der Import nie. Der Status kommt bei DPD Österreich derzeit nur aus diesen Mails: Die DPD-Abfrage bleibt die deutsche Seite. mydpd.at hat zwar eine eigene offene Abfrage, sie antwortet aber in einem anderen Format als die deutsche Seite und ließ sich nur mit einer ungültigen Nummer prüfen – ohne echte Antwort wird daraus keine Abfrage gebaut. Ein per Mail als zugestellt gemeldetes Paket wird nicht mehr abgefragt und bleibt zugestellt.
- **DHL international**: Nummern internationaler DHL-Sendungen (zwei Buchstaben, neun Ziffern, „DE“, z. B. `CQ…DE`) erkennt „Automatisch“ als DHL (Live-Status mit DHL-API-Key), und der Mail-Import liest sie aus den DHL-Mails. Die Mail „… in den nächsten 2 Werktagen von der Österreichischen Post zugestellt“ ergibt „Unterwegs“ ohne Liefertag, weil sie keinen festen Tag nennt.
- **Noch nicht**: DPD-Live-Abfrage für Österreich, DPD Schweiz, Österreichische Post und Schweizerische Post als eigene Carrier (bis dahin über „Andere (über 17track)“), und „Automatisch“ erkennt andere ausländische Nummernformate nicht automatisch. Mails aus der Schweiz kennt der Mail-Import noch nicht.

Damit daraus mehr wird, helfen anonymisierte Beispielmails der Carrier und Shops aus Österreich und der Schweiz (siehe [Beispielmails einreichen](#beispielmails-einreichen)) und bei Fehlern die Diagnose-Datei (siehe [Fehler melden](#fehler-melden)).

## Was brauche ich für welchen Dienst?

| Dienst | Live-Status direkt | aus Mails (Mail-Import) | Voraussetzung |
|---|---|---|---|
| DHL | nur mit DHL-API-Key | ja, aus den DHL-Mails | kostenloser [DHL-API-Key](#dhl-api-key-anlegen); ohne Key kommt der Status nur aus den DHL-Mails |
| DPD | ja, ohne Key (nur Status, kein Ort) | optional: eine DPD-Mail legt das Paket an, den Status liefert die Abfrage; die Ankündigung „Bald ist Ihr DPD Paket da“ nennt dazu Versender und Lieferschätzung (DPD Österreich: Zustellung aus der Mail) | keine |
| GLS | ja, ohne Key (offene Abfrage, mit PLZ auch der Verlauf) | ja, aus den GLS-Mails | keine; die PLZ für den Verlauf |
| Hermes | ja, ohne Key | ja, aus den Hermes-Mails (sie nennen den Liefertag) | keine |
| UPS | nur mit eigenem UPS-Entwicklerzugang | ja, aus den UPS-Mails | ohne Zugang nur aus den UPS-Mails; für den Live-Status [Client-ID und Secret](#ups-live-status-optional) |
| Amazon | nein (keine Anmeldung bei Amazon) | ja, nur aus Mails | [E-Mail-Import](#e-mail-import) |
| eBay | nein | ja, nur aus Mails | [E-Mail-Import](#e-mail-import) |
| AliExpress | nein (über die Sendungsnummer des Carriers, sobald eine Mail sie nennt) | ja, nur aus Mails | [E-Mail-Import](#e-mail-import) |
| andere Carrier | über den optionalen 17track-Knopf: „Andere (über 17track)“ | nein | eigener [17track-Key](#17track-optional), 200 Nummern einmalig |

„Aus Mails“ setzt den [E-Mail-Import](#e-mail-import) mit einem eigenen Paket-Postfach voraus. Ohne DHL-API-Key und ohne Mail-Import bleibt ein von Hand eingetragenes DHL-Paket ohne Status: Die Karte zeigt „Kein Live-Status“ und sagt das gleich beim Hinzufügen (siehe [Karte hinzufügen](#karte-hinzufügen)). Für UPS ohne Zugangsdaten gilt dasselbe.

## DHL-API-Key anlegen

**Der Key ist optional – nicht darauf versteifen.** DHL prüft jeden Antrag selbst; ohne passende Angaben (siehe unten) wird er manchmal abgelehnt. Wer keinen Key bekommt, verliert wenig: siehe [Kein Key? Dann die DHL-Mails](#kein-key-dann-die-dhl-mails).

1. Auf [developer.dhl.com](https://developer.dhl.com) ein Konto anlegen oder anmelden – am besten mit einer E-Mail-Adresse unter eigener Domain (siehe Hinweise unten).
2. Zu **Meine Apps** wechseln und eine neue App anlegen.
3. Das Feld **Firma / Company** ausfüllen – **Pflichtfeld**: Bleibt es leer, lehnt DHL den Key ab. Auch als Privatperson etwas eintragen, das zur E-Mail-Adresse des Kontos passt, z. B. die eigene Domain.
4. Als API **"Shipment Tracking – Unified"** auswählen (nicht "Parcel DE …").
5. Als Environment **"Production (Europe)"** wählen.
6. Nur der **API Key** wird gebraucht, das Secret nicht.
7. Die Freischaltung dauert bis zu 24 Stunden.

**Wichtig beim Antrag:** Als Zweck angeben, dass du deine eigenen Sendungen verfolgen möchtest – am besten wörtlich **„I want to track my own shipments“**. Laut einem Hinweis aus dem DHL-API-Team bekommt grundsätzlich jeder Zugriff, der seine eigenen Sendungen verfolgen will; dafür ist die Tracking-API gedacht.

**Welche E-Mail-Adresse?** Laut DHL werden die Anträge von Hand geprüft, weil Bots die Schnittstelle missbrauchen. Am zuverlässigsten klappt es bisher mit einer Adresse unter eigener Domain, die zum angegebenen Firmennamen passt. Adressen bei gmx.de und web.de haben laut DHL bessere Chancen als Gmail, hotmail.com und outlook.com, wurden bei Testern aber ebenfalls abgelehnt – eine Garantie gibt es bei Freemail-Adressen nicht. Klappt es nicht: Der Key ist kein Muss, die DHL-Mails reichen (siehe unten).

Die Schnittstelle kennt alle DHL-Sendungen, nicht nur DHL Paket in Deutschland, sondern auch Express und eCommerce. Mit hinterlegter Postleitzahl des Empfängers liefert sie mehr Details. Passt eine mit „Automatisch“ eingetragene Nummer zu keinem Carrier, fragt die Integration deshalb mit Key einmal bei DHL nach: Kennt DHL die Sendung, wird sie ein DHL-Paket, sonst bleibt der Carrier wie ohne Key unbekannt.

**Zeitfenster:** Liefertag und Zeitfenster der Zustellung zeigt die Integration, wenn DHL eines nennt. DHL berechnet beides laufend neu; ein Zeitfenster kann deshalb im Lauf des Tages erscheinen und wieder verschwinden. Nimmt DHL die Angabe zwischendurch zurück, bleibt die zuletzt genannte stehen, solange das Paket unterwegs und der Tag nicht vorbei ist.

**Key abgelehnt?** DHL nennt in der Ablehnungsmail als Bedingung einen gültigen Firmennamen **und eine dazu passende Domain-E-Mail-Adresse**. Es reicht also nicht, nur das Feld **Firma / Company** auszufüllen: Das DHL-Konto selbst sollte auf eine Adresse unter eigener Domain laufen (eigene Domain oder Arbeitsadresse), und der Firmenname sollte dazu passen. Ohne eigene Domain helfen die Hinweise unter „Welche E-Mail-Adresse?“ weiter. Danach den Key erneut beantragen.

### Kein Key? Dann die DHL-Mails

Ohne DHL-Key läuft die Integration trotzdem: DPD, GLS und Hermes brauchen keine Zugangsdaten, DHL-Pakete kommen weiter aus den DHL-Mails, und „Details über 17track holen“ liefert Status und Verlauf über [17track](#17track-optional).

So kommen DHL-Pakete ohne Key von selbst in die Übersicht:

1. Im (kostenlosen) DHL-Kundenkonto die E-Mail-Benachrichtigungen zu Sendungen einschalten.
2. Die DHL-Absender `noreply@dhl.de`, `paketankuendigung@dhl.de`, `zustellung@dhl.de` und `sendungsupdate@dhl.de` (oder gleich die ganze Domain `dhl.de`) in die Filterregel zum Paket-Postfach aufnehmen (siehe [E-Mail-Import](#e-mail-import)).
3. Fertig: Die Integration legt die Pakete aus den Mails an und führt den Status mit – samt Liefertag, wenn die Mail ihn nennt. Mit Key kämen nur Ort und Verlauf dazu.

Den Status liest der Import nur aus dem Betreff: „ist unterwegs“ setzt „Unterwegs“ (samt Liefertag, wenn die Mail ihn nennt), „kommt morgen“ setzt „Unterwegs“ mit dem Tag nach der Mail, „kommt heute“ bzw. „wird heute zugestellt“ setzt „In Zustellung“ für den Tag der Mail, „wurde zugestellt“ – auch „wurde an den gewünschten Ablageort zugestellt“ – setzt „Zugestellt“. „Liegt zur Abholung bereit“ und „wurde an Packstation … / in die Filiale … zugestellt“ setzen „Abholbereit“. Jede andere DHL-Mail, deren Betreff von einer „Sendung“ spricht (Zustellfoto, gescheiterter Zustellversuch, Neuigkeiten), setzt nur „Unterwegs“ ohne Tag und nie einen Status zurück; eine Umfrage (Betreff mit Fragezeichen) und ein Betreff ohne „Sendung“ legen das Paket nur an. Abholcodes liest der Import nie. Neben den langen DHL-Nummern (`00340…`, `JJD…`, `CQ…DE`) liest er aus DHL-Mails auch Nummern mit 12 Ziffern – nur direkt nach „Ihre Sendungsnummer“ bzw. „Sendungsnummer“, weil 12 Ziffern allein auch eine eBay-Artikelnummer sein können. Mit DHL-Key fragt die Integration auch diese Nummern bei DHL ab.

DHL-Mails nennen im Betreff den Shop („Ihre Beispiel GmbH Sendung ist unterwegs“): Er wird der Name des Pakets, wenn er ein bekannter Shop ist oder eine Rechtsform trägt (GmbH, AG, OHG …) – nie der Name einer Privatperson. Der Name endet an der Rechtsform; was dahinter steht (ein Kürzel, eine Ansprechperson), wird nicht übernommen. Der Anzeigename eines Carriers („DHL Paketankündigung“, „DHL Zustell-Update“) wird nie zum Namen: Ohne Shop heißt das Paket „DHL <Nummer>“. Trägt ein Paket aus einer älteren Version noch so einen Namen, ersetzt ihn die nächste Mail, die einen Shop nennt – aber nur, wenn der Name aus einem Carrier (DHL, DPD, GLS, Hermes, UPS, Deutsche Post) und Wörtern einer Benachrichtigung besteht und sonst nichts enthält („DHL Paketankündigung“, „DHL Zustell-Update“, „DPD Versandinfo“, „DHL Paket“). Jeder andere Name bleibt, auch „Hermes“, „DHL Express“ oder „Paket“: Er kann selbst vergeben sein. Nennt der Betreff eine Firma des Carriers selbst („Ihre DHL Paket (Austria) GmbH c/o … Sendung“), gibt es ebenfalls keinen Namen. Eine „Amazon Sendung“ landet wie bisher beim passenden Amazon-Paket (siehe [Amazon-Pakete](#amazon-pakete)).

**Warum es keinen anderen Weg gibt:**

- **Nutzungsbedingungen:** DHL erlaubt automatische Abfragen nur über die offizielle Schnittstelle. Die Sendungsverfolgung der Webseite ist laut DHL ausdrücklich nur für Menschen gedacht; automatisches Auslesen ist untersagt und wird technisch geblockt. Das umgeht diese Integration nicht.
- **Kein Login mit dem DHL-Kundenkonto:** Dafür gibt es keine offizielle Schnittstelle. Eine Integration müsste sich als DHL-App ausgeben, würde bei jeder Änderung von DHL ausfallen, und in Home Assistant läge ein Zugang zum ganzen Konto (Adresse, Packstation, Sendungen). Das bauen wir bewusst nicht ein.

Ein DHL-Paket, zu dem es weder eine Mail noch 17track-Daten gibt, zeigt ohne Key auf der Karte „Kein Live-Status“ statt eines Termins; aufgeklappt steht dort „Kein Live-Status: DHL-API-Key fehlt (unter „Konfigurieren“ eintragen).“ Die Integration kann eine solche Nummer nicht prüfen: Ob sie stimmt, vertippt oder längst zugestellt ist, erfährt sie ohne Key nicht. Erst mit Key meldet DHL bei einer unbekannten Nummer „Noch keine Daten vom Carrier“.

## GLS

GLS-Pakete fragt die Integration über die offene Sendungsverfolgung von gls-group.com ab – ohne Zugangsdaten und ohne Anmeldung.

- **Nummern**: 11 Ziffern erkennt „Automatisch“ als GLS. Die 12-stellige Nummer aus den GLS-Mails und dem Link zur Sendungsverfolgung funktioniert mit der Carrier-Wahl „GLS“ und beim Import der GLS-Mails ebenfalls: Die letzte Ziffer ist eine Prüfziffer, GLS wird mit den ersten 11 Ziffern gefragt. Mit „Automatisch“ fragt die Integration eine 12-stellige Nummer einmal mit allen 12 Ziffern bei GLS an (so sehen auch DHL-Nummern und eBay-Artikelnummern aus; GLS findet ein Paket nur mit der richtigen Prüfziffer): Bei einem Treffer wird sie ein GLS-Paket. Mit DHL-Key wird zuerst DHL gefragt und GLS nur, wenn DHL die Nummer nicht kennt. Kennt GLS die Nummer nicht, bleibt alles wie zuvor, und danach wird GLS für dieses Paket nicht noch einmal gefragt; ist GLS nicht erreichbar, gibt es höchstens drei Versuche. Die achtstelligen Track-IDs aus Buchstaben und Ziffern trägst du mit der Carrier-Wahl „GLS“ ein.
- **PLZ**: Ist in den Einstellungen eine PLZ hinterlegt, schickt die Integration sie mit, und GLS liefert zusätzlich den Verlauf (bis zu 20 Ereignisse). Ohne PLZ – oder wenn die PLZ nicht zur Sendung passt – gibt es nur den Status.
- **Liefertag**: Nennt die Abfrage keinen eindeutigen Tag, bleiben Liefertag und Zeitfenster aus der GLS-Mail erhalten.
- **Abfragen**: höchstens alle 30 Minuten, nachts (22–6 Uhr) stündlich, nach der Zustellung nie mehr.
- **Kein offizieller Zugang**: Die offene Abfrage ist keine dokumentierte API. GLS kann sie jederzeit ändern oder schließen; nach 24 Stunden ohne Antwort erscheint ein Hinweis unter **Einstellungen → Reparaturen**. GLS-Pakete kommen dann weiter aus den GLS-Mails, und „Details über 17track holen“ ergänzt Status und Verlauf über 17track.

## UPS-Live-Status (optional)

Ohne Zugangsdaten kommen UPS-Pakete nur aus den UPS-Mails; eine von Hand eingetragene `1Z…`-Nummer zeigt dann „Kein Live-Status“, aufgeklappt „Kein Live-Status: UPS-Zugangsdaten fehlen (unter „Konfigurieren“ eintragen).“, bis eine UPS-Mail zu ihr kommt. Mit einer eigenen UPS-App fragt die Integration zusätzlich die offizielle UPS Track API ab – auch für von Hand eingetragene `1Z…`-Nummern.

1. Auf [developer.ups.com](https://developer.ups.com) ein Konto anlegen oder anmelden.
2. Eine App anlegen und als Produkt **Tracking** wählen (nicht „Track Alert“).
3. Warten, bis UPS die App freischaltet – solange steht sie auf „Pending“.
4. **Client-ID** und **Client-Secret** nur in Home Assistant eintragen: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → UPS-Live-Status**. Speichern holt testweise einen Token (zählt nicht aufs Budget). Leere Felder für Client-ID und Secret behalten die gespeicherten Werte. Ausschalten geht nur über den Schalter **UPS-API aktiv**: Ausgeschaltet gespeichert, entfernt er Client-ID und Secret.

**Monatsbudget** (Standard 100, Bereich 0–10000): So viele UPS-Abfragen macht die Integration höchstens pro Kalendermonat, damit nie Kosten entstehen. Token-Abrufe zählen nicht, jede Sendungsabfrage zählt – auch die über „Aktualisieren“. Ist das Budget verbraucht, kommen UPS-Pakete bis Monatsende nur aus Mails, und unter **Einstellungen → Reparaturen** erscheint ein Hinweis, der am Monatsanfang von selbst verschwindet. 0 schaltet die API aus.

Die UPS-API wird sparsam gefragt: beim Anlegen einmal, danach alle 4 Stunden, am Zustelltag („In Zustellung“) alle 30 Minuten, nach der Zustellung nie mehr; nachts (22–6 Uhr) höchstens stündlich. Lehnt UPS die Zugangsdaten ab, erscheint ebenfalls ein Reparatur-Hinweis.

## 17track (optional)

17track ergänzt Pakete um Ort, Zeitfenster und Verlauf und verfolgt Carrier ohne eigene Anbindung (z. B. FedEx). Angemeldet wird nur auf ausdrücklichen Wunsch, nie automatisch.

1. Auf [api.17track.net](https://api.17track.net) ein kostenloses Konto anlegen und den API-Key kopieren.
2. Den Key nur in Home Assistant eintragen: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → 17track-API-Key**. Speichern prüft den Key über das Kontingent (verbraucht nichts). Ein leeres Feld behält den gespeicherten Key.

**Kontingent**: Das kostenlose Konto hat einmalig 200 Nummern. Jede Anmeldung einer neuen Nummer verbraucht eine, Abfragen danach sind kostenlos. Die Integration löscht Nummern bei 17track nie, denn neu anmelden würde erneut kosten. `sensor.paket_tracker_17track_kontingent` zeigt die verbleibenden Nummern (Attribute `total` und `used`) und wird beim Start, nach jeder Anmeldung und einmal täglich aktualisiert. Bei höchstens 10 übrigen Nummern und bei leerem Kontingent erscheint ein Hinweis unter **Einstellungen → Reparaturen**.

**Anmelden**: Auf der Karte im aufgeklappten Paket „Details über 17track holen“ antippen; die Rückfrage „Verbraucht 1 von … verbleibenden 17track-Nummern. Fortfahren?“ bestätigen. Für Automationen gibt es den Dienst `parcel_tracker.track_17track` (`number`). Nicht möglich bei zugestellten Paketen und bei Amazon- und eBay-Bestellungen, solange keine Sendungsnummer des Carriers bekannt ist. Angemeldet wird die Sendungsnummer des Carriers samt Carrier-Code; ist der Carrier unbekannt, erkennt 17track ihn selbst.

**Andere (über 17track)**: Für Carrier ohne eigene Anbindung in der Karte „Andere (über 17track)“ wählen (oder `add_parcel` mit `carrier: other`). Hinzufügen meldet die Nummer sofort an, mit derselben Rückfrage. Erkennt 17track den Carrier nicht, wird das Paket nicht angelegt. Status, Text, Ort und Verlauf kommen dann nur von 17track; der erkannte Carrier (z. B. FedEx) erscheint im Namen.

**Ergänzen statt ersetzen**: Bei DHL, DPD, GLS, Hermes und UPS bleibt der Carrier maßgeblich. 17track füllt nur Lücken: Ort, Liefertag und Zeitfenster sowie den Verlauf (nur wenn der Carrier keinen liefert). Liefert der Carrier gar nichts (z. B. DHL ohne API-Key, UPS ohne API-Zugang), zeigt das Paket den Status von 17track, bis der Carrier selbst antwortet. Stammt der Ort von 17track, zeigt die Karte „· Ort via 17track“ (Attribut `location_source: 17track`).

**Abfragen**: Die erste Abfrage kommt 2 Minuten nach der Anmeldung, danach alle 6 Stunden (17track aktualisiert selbst nur alle 6–12 Stunden), gebündelt zu höchstens 40 Nummern pro Aufruf. Schluss ist bei Zustellung oder wenn 17track die Sendung als abgelaufen meldet. Ist 17track nicht erreichbar, wartet die Integration länger und meldet nie neu an. Lehnt 17track den Key ab, fragt die Integration bis zum Neuladen nicht mehr ab und zeigt einen Reparatur-Hinweis.

## E-Mail-Import

Amazon liefert viele Pakete selbst aus und bietet dafür keine öffentliche Sendungsverfolgung. Der E-Mail-Import liest deshalb die Versandmails: Bestellt, Versendet, In Zustellung, Zugestellt – samt Liefertag und Zeitfenster.

> **Wichtig: Nur ein eigenes Paket-Postfach eintragen, nie das Hauptpostfach.**
> Das IMAP-Passwort gibt Vollzugriff auf das Postfach. Leg bei deinem Mailanbieter ein zusätzliches Postfach an (z. B. `pakete@…`), das ausschließlich Paketmails bekommt, und trag nur dieses ein.

### Einrichten

1. Paket-Postfach anlegen (z. B. bei mailbox.org).
2. Im Hauptpostfach eine Filterregel anlegen, die Paketmails an das Paket-Postfach weiterleitet (siehe unten).
3. In Home Assistant: **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → E-Mail-Import**:
   - **IMAP-Server** (Standard `imap.mailbox.org`, Port 993 mit SSL),
   - **Benutzername** und **Passwort** des Paket-Postfachs (leere Felder behalten die gespeicherten Werte),
   - **Verarbeitete Mails in Ordner verschieben** (Standard: an),
   - **Zustell-Codes (Einmalpasswörter) mitlesen** (Standard: aus),
   - **Postfach abfragen alle (Minuten)** (1–60, Standard: 5).
4. Speichern prüft die Anmeldung sofort.

**Anmeldung abgelehnt?** Viele Anbieter verlangen für IMAP nicht das normale Passwort, sondern ein eigenes **App-Passwort** (auch „Anwendungspasswort“ genannt), das man in den Einstellungen des Mail-Kontos erzeugt und hier als Passwort einträgt:

- **mailbox.org:** je nach Kontoeinstellung (z. B. mit Zwei-Faktor-Anmeldung) ein Anwendungspasswort für IMAP anlegen.
- **Gmail** und **iCloud:** immer ein App-Passwort; das normale Passwort funktioniert für IMAP nicht.
- **GMX** und **web.de:** den Zugriff per IMAP in den Einstellungen des Postfachs erst erlauben.

Ausschalten geht nur über den Schalter **E-Mail-Import aktiv**: Ausgeschaltet gespeichert, entfernt er Benutzername und Passwort.

Der Import schaut im eingestellten Intervall (1–60 Minuten, Standard 5) nach ungelesenen Mails im Posteingang. Der Dienst `parcel_tracker.refresh` (auf der Karte „Aktualisieren“) fragt zusätzlich das Postfach sofort ab. Ist das Postfach nicht erreichbar, wartet der Import unabhängig vom Intervall länger (5 → 10 → 20 → 40 → 60 Minuten). Lehnt der Server die Anmeldung ab, erscheint unter **Einstellungen → Reparaturen** ein Hinweis.

### Welche Absender

Diese Absender in die Filterregel aufnehmen:

- `bestellbestaetigung@amazon.de`
- `versandbestaetigung@amazon.de`
- `shipment-tracking@amazon.de`
- `order-update@amazon.de`
- `noreply@dhl.de`
- `paketankuendigung@dhl.de`
- `zustellung@dhl.de`
- `sendungsupdate@dhl.de` (meldet einen verschobenen Zustelltag; der neue Tag wird übernommen)
- `noreply@service.dpd.de`
- `no_reply@dpd.at` (DPD Österreich)
- `pkginfo@ups.com`
- `noreply@paketankuendigung.myhermes.de`
- `ebay@ebay.com`
- `transaction@notice.aliexpress.com`
- `no-reply@gls-pakete.de`
- `noreply@gls-group.eu` und `noreply@gls-rtt.com` (GLS Österreich)

DHL schreibt von mehreren Adressen (`noreply@`, `paketankuendigung@`, `zustellung@` und `sendungsupdate@dhl.de`). Am einfachsten ist dafür eine Regel auf die ganze Domain `dhl.de`, wenn der Mail-Anbieter das kann: Der Import liest jeden Absender unter `dhl.de`.

DPD Deutschland (`noreply@service.dpd.de`): Die Ankündigung „Bald ist Ihr DPD Paket da“ liefert neben der Paketnummer den Versender als Namen des Pakets – nur eine Firma mit Rechtsform oder einen bekannten Shop, nie eine Privatperson – und die Lieferschätzung: Aus „Ihre Sendung stellen wir in 1-2 Werktagen zu“ wird eine Lieferspanne, gerechnet ab dem Tag der Mail (Werktage sind Montag bis Samstag; Feiertage kennt der Import nicht). Das Paket steht damit auf „Angekündigt“, bis die DPD-Abfrage den Status liefert; die Schätzung bleibt, bis die DPD-Abfrage selbst einen Tag nennt oder das Paket zugestellt bzw. abholbereit ist. Der Empfänger aus der Mail wird nie gelesen. Alle anderen Mails von DPD Deutschland legen wie bisher nur das Paket an.

Beispiel als Sieve-Regel (z. B. mailbox.org → Einstellungen → Filter → Sieve), die eine Kopie ins Paket-Postfach schickt:

```sieve
require ["copy"];
if address :is "from" [
  "bestellbestaetigung@amazon.de", "versandbestaetigung@amazon.de",
  "shipment-tracking@amazon.de", "order-update@amazon.de",
  "noreply@dhl.de", "paketankuendigung@dhl.de", "zustellung@dhl.de",
  "sendungsupdate@dhl.de",
  "noreply@service.dpd.de", "pkginfo@ups.com",
  "noreply@paketankuendigung.myhermes.de", "ebay@ebay.com",
  "no_reply@dpd.at", "noreply@gls-group.eu", "noreply@gls-rtt.com",
  "transaction@notice.aliexpress.com",
  "no-reply@gls-pakete.de"
] {
  redirect :copy "pakete@example.org";
}
```

In Gmail, Outlook & Co. heißt das „Filter" bzw. „Regel": Bedingung „Absender ist …", Aktion „Weiterleiten an pakete@…".

**Apple „E-Mail-Adresse verbergen“**: Wer sich bei einem Shop mit einer verborgenen Adresse angemeldet hat, bekommt dessen Mails über Apples Relay – als Absender steht dann z. B. `transaction_at_notice_aliexpress_com_…@privaterelay.appleid.com`. Der Import erkennt solche Mails wie die des ursprünglichen Absenders, bei allen Shops und Paketdiensten aus der Liste oben. In der Filterregel braucht es dafür die Relay-Adresse, so wie sie in der Mail steht (sie ist bei jedem anders), oder eine Regel auf den Betreff.

### Von Hand weiterleiten

Statt einer Filterregel lassen sich einzelne Mails auch von Hand an das Paket-Postfach weiterleiten. Eine Weiterleitung erkennt der Import wie die Original-Mail, wenn im weitergeleiteten Block der ursprüngliche Absender steht – also die Kopfzeilen „Von: … / Gesendet: … / An: … / Betreff: …" über dem Mailtext. Alle gängigen Mailprogramme setzen diesen Block von selbst (Outlook, Apple Mail, Gmail, Thunderbird; deutsch und englisch) – lass ihn beim Weiterleiten einfach stehen. Auch „Als Anhang weiterleiten" funktioniert. Kennt der Import den ursprünglichen Absender (dieselben Shops und Paketdienste wie in der Filterliste oben), liest er die Mail genau so, als wäre sie direkt gekommen: mit Status, Zustelltag und Namen. „Heute" und „morgen" rechnet er ab dem Datum der Original-Mail, das im Block steht; lässt sich dieses Datum nicht sicher lesen, zählt der Zeitpunkt der Weiterleitung. Was du selbst über den Block schreibst (ein Gruß, deine Signatur), liest er nie mit, und dein eigener Name wird nie zum Paketnamen. Am zuverlässigsten bleibt trotzdem die automatische Filterregel: Sie leitet die Mail unverändert um.

Fehlt der Block oder ist der ursprüngliche Absender unbekannt, gilt wie bisher: Amazon- und GLS-Mails erkennt der Import am Betreff (mit „WG:" oder „Fwd:"), ohne den Versender einer GLS-Mail als Namen zu übernehmen, und rechnet „heute" und „morgen" ab dem Zeitpunkt der Weiterleitung. Aus allen anderen Mails übernimmt er nur eindeutige Sendungsnummern (DHL `00340…` und `JJD…`, UPS `1Z…`, Hermes `H…`; DPD-Nummern nur, wenn „DPD" in der Mail steht und die Nummer direkt nach „Paketnummer", „Sendungsnummer" o. Ä. folgt, oder die Mail direkt von DPD kommt). Solche Pakete tragen keinen Namen aus dem Absender, sondern heißen „<Carrier> <Nummer>" – umbenennen geht auf der Karte. Mails, die älter als 14 Tage sind, markiert der Import nur als gelesen.

### Ohne Postfach: Mail per HTTP übergeben (für Fortgeschrittene)

Wer Paketmails schon in einem eigenen Werkzeug hat (n8n, Node-RED, ein Skript), kann sie einzeln an Home Assistant übergeben und braucht dafür kein Paket-Postfach. Der Import liest die Mail genau wie eine aus dem Postfach: Sie zählt nur einmal (Message-ID) und wird nicht gelesen, wenn sie älter als 14 Tage ist.

1. In Home Assistant unter **Profil → Sicherheit** ein **langlebiges Zugriffstoken** anlegen.
2. Die komplette Mail als Quelltext (RFC 822, `.eml`) per `POST` an `/api/parcel_tracker/import_mail` schicken, unverändert als Inhalt der Anfrage und mit dem Token in der Kopfzeile `Authorization`.

```sh
curl -H "Authorization: Bearer <Token>" --data-binary @mail.eml \
  http://homeassistant.local:8123/api/parcel_tracker/import_mail
```

In n8n ist das ein HTTP-Request-Node mit der Methode POST und der Mail als Binärdaten im Body.

Die Antwort ist JSON, z. B. `{"result": "recognized", "parcels": ["00340999999999999911"]}`. `parcels` nennt die Pakete, die die Mail angelegt oder geändert hat (bei einem Paket, das in einer Bestellung aufging, die Bestellung), `result` sagt, was aus der Mail wurde:

- `recognized`: gelesen und angewendet
- `unrecognized`: keine Sendung erkannt
- `ignored`: Werbung oder Konto-Mail
- `stale`: älter als 14 Tage
- `duplicate`: diese Mail wurde schon gelesen

Ohne gültiges Token antwortet Home Assistant mit 401, auf eine leere Anfrage mit 400, auf einen Formular-Upload (`curl -F`) mit 415, auf eine Mail über 16 MB mit 413 und mit 503, solange Paket Tracker nicht geladen ist.

Einen Dienst gibt es dafür bewusst nicht: Home Assistant gibt jeden Dienstaufruf samt Daten als Ereignis weiter, die Mail stünde dann in der Recorder-Datenbank. Der Inhalt einer HTTP-Anfrage geht dagegen nur an den Import und wird nicht gespeichert.

### Was mit den Mails passiert

- Erkannte Mails landen im Ordner `Paket-Tracker-Verarbeitet`, nicht erkannte im Ordner `Paket-Tracker-Nicht-erkannt`. Beide Ordner legt der Import bei Bedarf an. Mit ausgeschalteter Option bleiben die Mails im Posteingang und werden nur als gelesen markiert.
- Werbung und Konto-Mails von Amazon (`promotion…@amazon.de`, `no-reply@amazon.de`, `account-update@amazon.de`, `rueckgabe@amazon.de`, `no-reply@primevideo.com`) markiert der Import nur als gelesen, ebenso die Angebote von AliExpress (`…@deals.aliexpress.com`).
- Jede Mail zählt nur einmal (erkannt an ihrer Message-ID).
- Erkennt der Import fünf Amazon-Mails in Folge nicht, erscheint ein Reparatur-Hinweis – meist hat Amazon dann das Mail-Format geändert.

### Amazon-Pakete

- Pro Bestellung entsteht ein Paket mit der Nummer `AMZ` + Bestellnummer (z. B. `sensor.paket_amz99991565342587125`), benannt nach dem Artikel. Kommt eine Bestellung in mehreren Sendungen, heißt das nächste Paket „… (2)".
- Der Status geht nur vorwärts: Eine ältere Mail setzt ein Paket nie zurück.
- Eine Ausnahme ist die Mail „Versuchte Zustellung“ (niemand wurde angetroffen): Sie nimmt eine Bestellung von „In Zustellung“ zurück auf „Versendet“, mit dem Text „Zustellung versucht“ und ohne Liefertag. Die Bestellung zählt dann nicht mehr als heute. Was schon zugestellt oder abholbereit ist, bleibt, wie es ist.
- Kündigt DHL eine „Amazon Sendung" an und passt genau ein offenes Amazon-Paket dazu (gleicher Liefertag), übernimmt das Amazon-Paket die DHL-Nummer und fragt ab dann DHL ab. Ist die Zuordnung nicht eindeutig, entsteht ein eigenes Paket „Amazon-Sendung (DHL)".
- Verschickt ein Marketplace-Händler selbst, kommt von Amazon oft keine „Zugestellt“-Mail. Damit so eine Bestellung nicht für immer als „Versendet“ mit überschrittenem Termin stehen bleibt, schließt die Integration sie von selbst: Liegt der letzte Liefertag mehr als 3 volle Tage zurück und hat seitdem keine Mail die Bestellung verändert, bekommt sie den Status „Zugestellt“ mit dem Text „Abgeschlossen ohne Zustellbestätigung“ und dem Attribut `assumed_delivered` (dann `true`, sonst `false`); ohne jeden Liefertag gilt das 14 Tage nach der letzten Änderung. Die Karte zeigt „Abgeschlossen (ohne Zustellbestätigung)“, und wie jedes zugestellte Paket verschwindet die Bestellung nach der eingestellten Zahl von Tagen. Dafür gibt es keine Benachrichtigung, und die Bestellung zählt nicht bei `sensor.pakete_zugestellt_heute` und `delivered_today` mit – wann sie wirklich ankam, weiß niemand; `delivered_at` bleibt leer. Das gilt nur für Bestellungen ohne Sendungsnummer: Kennt die Bestellung die Sendungsnummer des Carriers, sagt der Carrier, was los ist. Kommt später doch eine Mail, gilt die Mail: Eine „Zugestellt“-Mail trägt den echten Zeitpunkt nach (ohne nachträgliche Benachrichtigung), eine Mail mit einem anderen Status – etwa einem neuen Liefertag – öffnet die Bestellung wieder.

### eBay-Pakete

- Pro eBay-Bestellung entsteht ein Paket mit der Nummer `EBAY` + Bestellnummer (z. B. `sensor.paket_ebay990000000001`), benannt nach dem Artikel. eBay-Mails enthalten keine Sendungsnummer; die 12-stelligen Artikelnummern werden nie als Sendungsnummer gelesen.
- „Ihre Sendung ist jetzt beim Versanddienstleister!“ setzt „Versendet“ samt Lieferzeitraum („Lieferung ca.: Mi, 28. Jan - Do, 29. Jan“), „BESTELLUNG ZUGESTELLT“ setzt „Zugestellt“. Andere eBay-Mails landen in „Nicht erkannt“.
- Nennt die Mail den Versanddienstleister, zeigt die Karte ihn an („eBay · Versendet · via Hermes“, Attribut `shipping_carrier_hint`).

- Bestellungen ohne Sendungsnummer, für die keine „Zugestellt“-Mail kommt, schließt die Integration wie bei Amazon von selbst („Abgeschlossen ohne Zustellbestätigung“, siehe [Amazon-Pakete](#amazon-pakete)).

### AliExpress-Pakete

- Pro AliExpress-Bestellung entsteht ein Paket mit der Nummer `ALI` + Bestellnummer (z. B. `sensor.paket_ali9999999999990001`), benannt nach dem Artikel; den Namen des Händlers übernimmt die Integration nie. Eine Bestellung bleibt ein Paket, auch wenn AliExpress sie in mehreren Sendungen verschickt. Eine Mail über mehrere Bestellungen („2 Bestellungen wurden bestätigt“) legt jede Bestellung an.
- Den Schritt liest der Import aus dem Betreff. „Bestellauftrag bestätigt“, „Bestellbestätigung“ und „versandfertig“ setzen „Bestellt“; „Bestellung versandt“, „teilweise versandt“, „Paket im Transit“, „In Ihrem Land / Ihrer Region angekommen“, „Neuer Lieferstatus“ und „Wird zugestellt“ setzen „Versendet“. Im Verlauf steht dazu der Schritt, den AliExpress nennt, z. B. „Im Zielland angekommen“. „Wird zugestellt“ heißt bei AliExpress nur, dass das Paket dem Versandunternehmen übergeben wurde – es zählt deshalb nicht als heute. Nennt die Mail eine „Voraussichtliche Zustellzeit“, wird sie der Liefertag.
- Die Mails „Packstück … hat die Abflugregion verlassen“, „Packstück …: Vom Kurier abgeholt“, „Packstück …: In Ihrem Land / Ihrer Region“ und „Zollabfertigung für … wurde beendet“ nennen die Sendungsnummer des Carriers. Ist es eine DHL- oder Hermes-Nummer, übernimmt die Bestellung sie und wird ab dann live beim Carrier abgefragt (DHL mit API-Key); es entsteht kein zweites Paket. Liegen mehrere Bestellungen im selben Paket, bekommt jede die Nummer. Eine Nummer in einem anderen Format (z. B. `AP…`) lässt sich bei keinem Carrier abfragen: Dann zählt nur der Schritt aus der Mail.
- Zu welcher Bestellung ein Packstück gehört, steht nur in den Links der Mail (sie werden gelesen, nie aufgerufen). Fehlen sie – etwa in einer von Hand weitergeleiteten Mail –, gilt dasselbe wie bei einer Carrier-Mail: Passt genau eine offene AliExpress-Bestellung, übernimmt sie die Nummer, sonst entsteht ein eigenes Paket „AliExpress-Sendung“ (siehe [Zusammenführen](#zusammenführen)).
- „wie ist es gelaufen?“ mit dem Satz „Wir haben die Lieferung Ihrer Bestellung … bestätigt“ setzt „Zugestellt“ mit dem Text „Lieferung bestätigt“. Die Mail kommt oft erst Tage nach der Zustellung: Hat der Carrier die Zustellung schon gemeldet, bleibt dessen Zeitpunkt stehen.
- Nur als gelesen markiert werden die Aufforderung zur Bewertung („Wie war Ihr Einkaufserlebnis?“), die Erinnerung „auf Bestätigung wird gewartet“ und „Your order … is closed“ (die Mail sagt nicht, ob die Bestellung abgeschlossen oder storniert wurde). Andere AliExpress-Mails landen in „Nicht erkannt“.
- Bestellungen ohne Sendungsnummer, für die keine Bestätigung kommt, schließt die Integration wie bei Amazon von selbst – 3 Tage nach dem letzten Liefertag, ohne Liefertag nach 14 Tagen („Abgeschlossen ohne Zustellbestätigung“, siehe [Amazon-Pakete](#amazon-pakete)).
- Auf der Karte öffnet „Bestellung“ die Bestellseite bei AliExpress.

### Hermes-Pakete

- „Information zur Zustellung an den gebuchten WunschAblageort“ (die Sendung wurde gerade angekündigt) setzt „Angekündigt“, „Ihre Hermes Sendung ist auf dem Weg“ setzt „Unterwegs“ samt Liefertag und Zeitfenster, „… wurde an deinen WunschAblageort zugestellt“ setzt „Zugestellt“. Mails über einen gescheiterten Zustellversuch („… konnte nicht zugestellt werden“, „nicht zugestellt“, „Zustellversuch“) setzen keinen Status; den liefert dann die Hermes-Abfrage. Der Shop aus der Mail wird nur dann zum Namen, wenn es ein bekannter Shop ist (z. B. Amazon, eBay, Otto, Zalando) und das Paket noch keinen Namen hat – Namen privater Absender übernimmt die Integration nie.
- Den Text des Wunsch-Ablageorts übernimmt die Integration nie – weder in Attribute noch ins Log.
- Alte Amazon-Versandmails mit Hermes-Nummer hängen die Nummer an das Amazon-Paket; ab dann fragt es Hermes ab.

### GLS-Pakete

- „Dein Paket wird in wenigen Tagen zugestellt“ setzt „Unterwegs“ samt Liefertag und Zeitfenster, „Dein GLS Paket kommt heute!“ setzt „In Zustellung“ für den Tag der Mail, „Dein Paket wurde … zugestellt“ setzt „Zugestellt“ – liegt das Paket im PaketShop zur Abholung bereit, „Abholbereit“. „Dein Paket wird an dem gewünschten Ort abgestellt“ legt das Paket nur an („Angekündigt“) und setzt nie einen Status zurück.
- Die Paketnummer liest der Import nur direkt nach „Paketnummer“ bzw. „Sendungsnummer“ (11 Ziffern). In Mails, die GLS selbst geschickt hat, darf eine Prüfziffer als zwölfte Ziffer folgen; gespeichert wird die Nummer ohne sie. Nennt eine solche Mail keine Nummer, zählt die aus dem Link `gls-group.eu/track/…`.
- Der Versender wird nur dann zum Namen, wenn es ein bekannter Shop ist oder der Name eine Rechtsform trägt (z. B. GmbH, AG, KG, e.K.) – Namen privater Absender übernimmt die Integration nie. Der Name endet an der Rechtsform: Aus „Beispiel Handels OHG (AT-B2C) Erika Musterfrau“ wird „Beispiel Handels OHG“.
- Abstellort, Zustelladresse, Empfängername, Telefonnummer und Referenzen übernimmt die Integration nie – weder in Attribute noch ins Log.
- Versandmails von Shops ohne Paketnummer (z. B. „Versand Ihrer Bestellung“) landen in „Nicht erkannt“.

### Zusammenführen

Eine Carrier-Mail (DHL „Amazon Sendung“, GLS, Hermes, UPS) gehört zu **genau einem** offenen Amazon-, eBay- oder AliExpress-Paket ohne Sendungsnummer, wenn die Mail den Shop nennt (Amazon, eBay, AliExpress) oder die Shop-Mail diesen Versanddienstleister genannt hat, und der Liefertag passt (gleicher Tag oder innerhalb des Lieferzeitraums; ohne Tag: genau ein Paket unterwegs). Das Shop-Paket übernimmt dann die Sendungsnummer und fragt ab da den Carrier ab (Attribute `tracking_ref` und `tracking_carrier`). Passt es nicht eindeutig, entsteht ein eigenes Paket.

Nennt die Carrier-Mail statt des Shops die Marke („Ihre Beispielmarke GmbH Sendung kommt heute“), gehört sie nur zu einem offenen **Amazon-Paket** ohne Sendungsnummer – nie zu einem eBay-Paket –, und nur, wenn der Titel genau eines offenen Amazon-Pakets mit allen Wörtern der Marke beginnt, dieses Paket keinen anderen Versanddienstleister nennt und der Tag der Mail im Liefertag oder Lieferzeitraum des Pakets liegt (fehlt ein Tag, muss das Paket schon „Versendet“ sein). Die Marke ist der Firmenname ohne Rechtsform: ein Wort ab 5 Buchstaben oder mehrere Wörter, ganze Wörter, Groß- und Kleinschreibung egal; Allerweltswörter allein („Neu GmbH“, „Smart Home GmbH“) und bekannte Shops (IKEA, Otto, Zalando …) zählen nicht. Für „In Zustellung“ und „Zugestellt“ gilt der Tag, an dem die Mail kam; eine Zustellmail macht aus einem nur bestellten Paket nie ein zugestelltes. Passt etwas davon nicht, entsteht ein eigenes Paket.

Besteht das Carrier-Paket schon als eigenes Paket – etwa weil die Shop-Mail erst später kam –, bleiben es zunächst zwei Einträge. Wird ein Carrier-Paket zugestellt, das aus einer Mail entstanden ist, prüft die Integration noch einmal nach denselben Regeln, ob es zu genau einem offenen Amazon- oder eBay-Paket ohne Sendungsnummer gehört – so, als käme seine „Zugestellt“-Mail jetzt: mit dem Carrier, dem Firmennamen aus der Carrier-Mail und dem Tag der Zustellung. Passt es eindeutig, übernimmt das Shop-Paket Sendungsnummer, Verlauf und Zustellzeitpunkt, gilt als zugestellt, und das eigene Carrier-Paket samt Sensor verschwindet. Gemeldet wird die Zustellung nur einmal (mit dem Carrier-Paket; stand dessen Meldung noch aus, mit dem Shop-Paket). Bei mehreren passenden Bestellungen passiert nichts, und Pakete, die von Hand eingetragen wurden, fasst die Integration nie zusammen. Geprüft wird genau einmal, mit dem Stand zum Zeitpunkt der Zustellung: Eine Bestellung, die eine Mail erst nach der Zustellung verändert hat (später bestellt oder versendet), kommt nicht infrage, und was beim ersten Mal nicht eindeutig war, wird später nicht doch noch zusammengeführt. Das gilt auch für Pakete, die beim Update schon zugestellt in der Liste stehen.

### Zustell-Code (Einmalpasswort)

Manche Amazon-Lieferungen gibt der Fahrer nur gegen einen Code heraus. Mit eingeschalteter Option liest der Import den Code aus der Mail. Die Karte zeigt ihn verdeckt: erst „Code anzeigen", dann die Rückfrage „Zustell-Code anzeigen?". Beim Zuklappen verschwindet er wieder. Der Code steht im Attribut `delivery_code`, wird nie gespeichert, landet nie im Verlauf (Recorder) und verfällt nach dem Liefertag. Verdeckt ist er nur auf der Karte: Wer Zugriff auf die Entitäts-Attribute oder die API von Home Assistant hat (Entwicklerwerkzeuge, Automationen, andere Dashboards, Apps), kann ihn im Klartext lesen.

## Karte hinzufügen

Dashboard bearbeiten → Karte hinzufügen → "Paket Tracker" auswählen. Alternativ per YAML:

```yaml
type: custom:parcel-tracker-card
add_form: button
```

Der Plus-Knopf oben rechts („Sendung hinzufügen“) klappt die Eingabe auf: Sendungsnummer, Carrier, Name, „Hinzufügen“. Nach dem Hinzufügen klappt die Eingabe wieder zu; bei einem Fehler bleibt sie offen und zeigt die Meldung. Ein weiterer Klick auf den Knopf (dann ein ×) oder Esc schließt sie. Die Option `add_form` legt fest, wie die Eingabe erscheint:

| Wert | Wirkung |
|---|---|
| `button` (Standard) | Eingabe eingeklappt hinter dem Plus-Knopf |
| `always` | Eingabe immer sichtbar, kein Plus-Knopf (das Aussehen bis v0.3.8) |
| `never` | Keine Eingabe und kein Plus-Knopf, z. B. für ein Wand-Tablet; Pakete kommen dann über den Dienst `parcel_tracker.add_parcel` oder den E-Mail-Import |

Fehlt die Option oder steht dort ein anderer Wert, gilt `button`.

Die Option `show` legt fest, wann die Karte überhaupt auf dem Dashboard steht – z. B. auf der Startseite nur, solange ein Paket unterwegs ist:

```yaml
type: custom:parcel-tracker-card
show: active
```

| Wert | Karte ist sichtbar |
|---|---|
| `always` (Standard) | immer |
| `active` | solange ein Paket noch nicht zugestellt ist (`sensor.pakete_unterwegs` größer 0) |
| `today` | wenn heute sicher etwas kommt oder heute schon etwas zugestellt wurde |
| `today_possible` | wie `today`, zusätzlich wenn ein Paket heute möglich ist (Lieferspanne schließt heute ein) |

Fehlt die Option oder steht dort ein anderer Wert (Groß- und Kleinschreibung ist egal), gilt `always`. Eine ausgeblendete Karte hinterlässt keine Lücke, weder in der Mauerwerk- noch in der Abschnitte-Ansicht. Im Bearbeitungsmodus des Dashboards und in der Vorschau des Karten-Editors bleibt sie sichtbar und zeigt die Zeile „Ausgeblendet, solange nichts ansteht (show: …)“. Solange die Eingabe über den Plus-Knopf offen ist, verschwindet die Karte nicht. Fehlt ein Sensor, den die Option braucht (Integration älter als v0.3.11), bleibt die Karte sichtbar.

Wer lieber die Sichtbarkeits-Bedingung von Home Assistant nutzt (Karte bearbeiten → Reiter „Sichtbarkeit“), nimmt denselben Sensor; das geht auch für jede andere Karte:

```yaml
type: custom:parcel-tracker-card
visibility:
  - condition: numeric_state
    entity: sensor.pakete_unterwegs
    above: 0
```

Oben rechts stehen bis zu drei Schilder, gelesen aus `sensor.pakete_heute`:

| Schild | Bedeutung | Sichtbar |
|---|---|---|
| „1 heute“ | Kommt heute sicher: in Zustellung oder fester Liefertag heute | steht immer da, auch als „0 heute“ |
| „1 möglich“ | Die Lieferspanne schließt heute ein; in der Liste bleibt die Spanne stehen (z. B. „Bis 5. Okt.“) | nur, wenn es solche Pakete gibt |
| „1 zugestellt“ | Heute zugestellt | nur, wenn heute etwas zugestellt wurde |

Wird ein Paket zugestellt, wechselt es von „heute“ zu „zugestellt“ – die Karte zeigt dann z. B. „0 heute“ und „1 zugestellt“. Eine Bestellung, die ohne Zustellmail abgeschlossen wurde, zählt dabei nicht mit; in der Liste steht bei ihr „Abgeschlossen (ohne Zustellbestätigung)“ statt „Zugestellt …“ (siehe [Amazon-Pakete](#amazon-pakete)). Die Erklärung steht auch als Tooltip auf jedem Schild. Auf schmalen Karten rutschen die Schilder gemeinsam unter den Titel, der Plus-Knopf bleibt rechts.

**Hinweis nach dem Hinzufügen:** Lässt sich der Carrier des neuen Pakets nicht abfragen, steht direkt unter der Eingabe eine Zeile in gedämpfter Schrift – für DHL ohne API-Key: „Hinzugefügt. Ohne DHL-API-Key gibt es dafür keinen Live-Status: Key unter „Konfigurieren“ eintragen – oder der Status kommt aus den DHL-Mails über den Mail-Import.“ Für UPS ohne Zugangsdaten: „Hinzugefügt. Ohne UPS-Zugangsdaten gibt es dafür keinen Live-Status: Zugangsdaten unter „Konfigurieren“ eintragen – oder der Status kommt aus den UPS-Mails über den Mail-Import.“ Die Eingabe klappt dabei wie gewohnt zu, die Zeile bleibt unter dem Kartentitel stehen (mit `add_form: always` unter der Eingabe), bis das × am Zeilenende sie schließt, das nächste Paket hinzugefügt oder die Eingabe wieder geschlossen wird. Sie verschwindet auch, sobald das Paket einen Status bekommt. Für Pakete aus Mails und für Pakete, die schon in der Liste standen, erscheint sie nie.

**Paket aufklappen:** Ein Tipp auf ein Paket klappt es auf, der kleine Pfeil rechts in der Zeile zeigt das an. Aufgeklappt stehen dort der Verlauf der Sendung und die Knöpfe „Umbenennen“ und „Löschen“ (mit Rückfrage „Wirklich löschen?“), je nach Paket auch „Details über 17track holen“ und „Code anzeigen“. Bei einer Amazon-, eBay- oder AliExpress-Bestellung öffnet „Bestellung“ die Bestellseite des Shops in einem neuen Tab. Ein weiterer Tipp klappt das Paket wieder zu. „Noch kein Termin“ heißt: Das Paket hat einen Status, aber noch keinen Zustelltag. „Kein Live-Status“ heißt: Der Carrier lässt sich nicht abfragen, weil der DHL-API-Key oder die UPS-Zugangsdaten fehlen.

Die Karte ist deutsch, unabhängig von der Sprache, die in Home Assistant eingestellt ist: Auch die Statusangaben („Unterwegs“, „Zugestellt“ …) kommen aus der Karte selbst.

Die Integration kopiert die Karte beim Start nach `www/parcel_tracker/` und trägt sie automatisch als Dashboard-Ressource ein (`/local/parcel_tracker/parcel-tracker-card.js`). Home Assistant liefert `/local` nur aus, wenn der Ordner `www` beim Start schon existierte. Sonst liefert die Integration die Karte zunächst selbst aus (`/parcel_tracker/parcel-tracker-card.js`); ein weiterer Neustart von Home Assistant aktiviert dann den `/local`-Pfad. Nach dem Einrichten die Seite einmal neu laden, erst dann kennt ein schon geöffnetes Home Assistant die neue Ressource.

Nach einem Update der Integration behält der Browser die alte Karte, bis die Seite neu geladen wird. Die Karte merkt das selbst (sie vergleicht ihre Version mit dem Attribut `integration_version` von `sensor.pakete_heute`) und zeigt dann oben die Zeile „Neue Version installiert – Seite neu laden, um die Karte zu aktualisieren.“ mit dem Knopf „Neu laden“. Den Hinweis gibt es ab v0.3.9: Eine ältere Karte kennt ihn nicht und kann ihn deshalb auch nicht zeigen – wer von einer älteren Version kommt, lädt die Seite nach dem Update einmal von Hand neu.

Die Reihenfolge nach jedem Update:

1. Das Update in HACS installieren.
2. Home Assistant neu starten.
3. Die Seite im Browser neu laden oder die Home-Assistant-App schließen und wieder öffnen.

Die Integration zu entfernen und neu hinzuzufügen ist dafür nie nötig; dabei gingen nur die Pakete und Einstellungen verloren.

### Karte wird nicht gefunden?

Meldet das Dashboard „Custom element doesn't exist: parcel-tracker-card" oder fehlt „Paket Tracker" in der Kartenauswahl, lag das bis v0.3.5 meist an der Integration selbst: Sie lud die Karte zusätzlich als Frontend-Modul, gleichzeitig mit der Oberfläche von Home Assistant, und war die Karte schneller, ging ihre Anmeldung verloren. Behoben in v0.3.6, die Karte kommt seitdem nur noch als Dashboard-Ressource.

1. Integration auf v0.3.6 oder neuer aktualisieren, Home Assistant neu starten und die Seite einmal neu laden.
2. Bis v0.3.5: normal neu laden (F5; in der Home-Assistant-App: App schließen und neu öffnen). Kein hartes Neuladen (Strg+F5 bzw. Cmd+Shift+R) und nicht den Cache leeren, beides löst den Fehler dort erst aus.
3. Unter Einstellungen → Dashboards → ⋮ → Ressourcen prüfen, ob `/local/parcel_tracker/parcel-tracker-card.js?v=…` (oder `/parcel_tracker/parcel-tracker-card.js?v=…`) eingetragen ist.
4. Werden die Dashboard-Ressourcen per YAML verwaltet (`resource_mode: yaml` oder `mode: yaml` unter `lovelace:`), kann die Integration die Karte nicht selbst eintragen. Ab v0.3.6 erscheint dann unter **Einstellungen → Reparaturen** ein Hinweis mit der genauen URL. Diese von Hand unter `lovelace:` → `resources:` ergänzen (`url: /local/parcel_tracker/parcel-tracker-card.js?v=…`, `type: module`) und Home Assistant neu starten.

Die Kartendatei selbst zu ändern ist nicht nötig; Änderungen daran überschreibt die Integration beim nächsten Start.

## Namen ausblenden

Für Geschenke auf einem gemeinsamen Dashboard: Unter **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren** gibt es den Schalter **Namen ausblenden** (Standard: aus). Eingeschaltet heißt jedes Paket nur noch nach dem Paketdienst und den letzten vier Stellen seiner Nummer: `DHL-Paket …2557`, `GLS-Paket …9977`, `Amazon-Bestellung …4321`, `eBay-Bestellung …0001`, `AliExpress-Bestellung …0001`. Ist kein Paketdienst bekannt, steht dort `Paket …2557`. Was im Paket ist und von wem es kommt, nennt die Integration dann nirgends mehr.

Das gilt überall, wo die Integration einen Namen nennt:

- **Karte**: Sie zeigt das Attribut `name` der Sensoren und braucht dafür keine eigene Einstellung.
- **Sensoren**: der Name der Entität und das Attribut `name` von `sensor.paket_<nummer>`, die Listen `parcels`, `possible`, `delivered_today` und `awaiting_pickup` von `sensor.pakete_heute` und die Liste `parcels` der vier Zählsensoren.
- **Kalender**: die Termine in `calendar.pakete`.
- **Event**: das Feld `name` von `parcel_tracker_status_changed` – und damit auch der Blueprint und eigene Automationen, die es nutzen.
- **Benachrichtigungen**: z. B. `✅ DHL-Paket …2557 wurde zugestellt`.

**Was sichtbar bleibt:** der Paketdienst (auch der, den eine Shop-Mail nennt, z. B. „via Hermes“), die Nummer, Status, Liefertag, Ort und der Verlauf des Paketdienstes – darin steht kein Artikel. Der Knopf „Bestellung“ auf der Karte öffnet weiterhin die Bestellseite beim Shop; die zeigt den Artikel nur dem, der dort angemeldet ist.

**Selbst eingetippte Namen bleiben sichtbar:** Ein Name, den du über „Umbenennen“ auf der Karte, über den Dienst `parcel_tracker.rename_parcel` oder beim Hinzufügen eines Pakets vergibst, ist deine eigene Wahl (z. B. „Überraschung“) und wird auch mit eingeschaltetem Schalter gezeigt. Ausgeblendet werden nur die Namen, die aus Mails stammen (Artikeltitel, Shop, Versender). Bei Namen, die vor v0.3.24 vergeben wurden, weiß die Integration nicht, wer sie vergeben hat: Sie gelten als Namen aus Mails und werden ausgeblendet, bis du das Paket mit einem anderen Text neu benennst. „Umbenennen“ unverändert zu speichern ändert nichts.

**Die gespeicherten Daten bleiben, wie sie sind:** Namen, Artikeltitel und alles, was das [Zusammenführen](#zusammenführen) braucht, stehen unverändert im Speicher der Integration; Mails werden weiter genauso zugeordnet. Schaltest du den Schalter wieder aus, sind die echten Namen sofort zurück. Beim Speichern lädt die Integration neu, ein Neustart von Home Assistant ist nicht nötig. Die Entitäts-IDs (`sensor.paket_<nummer>`) entstehen aus der Nummer und ändern sich durch den Schalter nicht. Der Diagnose-Download enthielt noch nie Namen; er nennt nur, ob der Schalter eingeschaltet ist.

**Grenzen:** Der Verlauf von Home Assistant (Logbuch, Historie) behält, was er vor dem Einschalten aufgezeichnet hat – also auch die früheren Namen der Pakete, bis diese Einträge ablaufen oder du sie löschst. Wer die Dateien von Home Assistant lesen kann, sieht dort auch die gespeicherten Namen. Der Schalter ist für den Blick aufs Dashboard gedacht, kein Schutz vor jemandem mit Admin-Zugang.

## Benachrichtigungen

Die Integration schickt bei einem Statuswechsel selbst eine Benachrichtigung – über die Benachrichtigungswege von Home Assistant. Eine Automation ist dafür nicht nötig.

Home Assistant kennt zwei Arten von Zielen. Beide stehen in derselben Auswahl und lassen sich mischen:

- **Benachrichtigungs-Entitäten** (`notify.…`): der neuere Weg. In der Auswahl stehen sie mit ihrem Namen, z. B. „Tablet Wohnzimmer“.
- **Klassische Dienste**: der ältere Weg, den viele Integrationen weiterhin nutzen – zum Beispiel Pushover. In der Auswahl stehen sie als „Dienst notify.…“, z. B. „Dienst notify.pushover“. Der Sammeldienst `notify.notify` steht am Ende der Liste.

### Einrichten

1. **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren** öffnen und den Bereich „Benachrichtigungen“ aufklappen.
2. **Ziele**: ein oder mehrere Ziele aus der Liste wählen – Entitäten zuerst, darunter die klassischen Dienste. Ohne Ziel wird nichts gesendet.
3. **Ereignisse**: ankreuzen, wobei benachrichtigt wird – in Zustellung, zugestellt, abholbereit, Problem. Voreingestellt sind „in Zustellung“ und „zugestellt“.

Der Schalter „Benachrichtigungen aktiv“ schaltet sich mit dem ersten Ziel von selbst ein; wer ihn einschaltet, ohne ein Ziel zu wählen, bekommt einen Hinweis im Formular. Ausschalten (oder alle Ziele entfernen) beendet die Benachrichtigungen.

**Pushover:** Pushover zuerst in Home Assistant als Integration einrichten (**Einstellungen → Geräte & Dienste → Integration hinzufügen → Pushover**). Erst danach gibt es den Dienst, und er erscheint in der Auswahl als „Dienst notify.<name>“ – mit dem Namen, den du der Pushover-Integration gegeben hast. Dasselbe gilt für andere Integrationen, die nur einen klassischen Dienst mitbringen.

**Home-Assistant-App:** Das Handy steht als „Dienst notify.mobile_app_<gerät>“ in der Auswahl, je nach Home-Assistant-Version zusätzlich als Entität. Gibt es für dasselbe Gerät beides, wähl nur eines von beiden – sonst kommt jede Meldung doppelt. Über den klassischen Dienst ersetzt eine neue Meldung die frühere zum selben Paket (siehe unten).

**Ziel verschwunden:** Ein gewähltes Ziel, das es in Home Assistant nicht mehr gibt (Gerät entfernt, Integration gelöscht oder gerade nicht geladen), bleibt gewählt und steht mit dem Zusatz „nicht mehr vorhanden“ in der Auswahl, bis du es abwählst. Beim Senden wird es übersprungen, ebenso ein Ziel, das gerade nicht verfügbar ist.

### Wann und was

Gesendet wird genau dann, wenn auch das Event `parcel_tracker_status_changed` feuert – egal, ob der neue Status vom Carrier oder aus einer Mail kommt. Also nicht doppelt für denselben Status und nicht, wenn ein Carrier nach 17track mit einem älteren Stand antwortet.

Wechselt ein Paket den Status, während Home Assistant neu startet oder die Integration neu lädt (etwa nach dem Speichern der Optionen), geht nichts verloren: Event und Benachrichtigung folgen genau einmal, sobald Home Assistant fertig gestartet ist, spätestens zwei Minuten nachdem die Integration geladen wurde – nach einem Neuladen im laufenden Betrieb sofort. Eine noch ausstehende Meldung wird mit dem Paket gespeichert: Sie übersteht auch ein erneutes Neuladen und einen weiteren Neustart, bevor sie gesendet wurde. Mehrere Wechsel in dieser Zeit werden zu einer Meldung vom alten zum neuesten Status. Der allererste Status eines neuen Pakets wird nie gemeldet.

Eine Ausnahme: Schließt die Integration eine Amazon-, eBay- oder AliExpress-Bestellung, für die keine „Zugestellt“-Mail kam („Abgeschlossen ohne Zustellbestätigung“, siehe [Amazon-Pakete](#amazon-pakete)), feuert das Event mit dem Feld `assumed` auf `true`, aber es geht keine Benachrichtigung raus – weder über die Optionen noch über den Blueprint.

Der Titel ist „Paket Tracker“, der Text eine Zeile:

- `📦 Kopfhörer (DHL) ist in Zustellung – heute 14:00–16:00 Uhr` (das Zeitfenster nur, wenn eines für heute bekannt ist)
- `✅ Kopfhörer (DHL) wurde zugestellt`
- `📍 Kopfhörer (DHL) liegt zur Abholung bereit – Bonn bis 06.10.` (Ort der Filiale und letzter Abholtag nur, wenn der Carrier sie nennt)
- `⚠️ Kopfhörer (DHL): Problem bei der Zustellung`

Genannt wird der Name des Pakets (bei Paketen aus Mails der Artikeltitel, höchstens 40 Zeichen). Hat ein Paket keinen Namen, steht dort `Paket …2557` mit den letzten vier Stellen der Nummer. Mit [Namen ausblenden](#namen-ausblenden) steht dort statt eines Namens aus einer Mail `DHL-Paket …2557`, ohne den Carrier dahinter.

**Nie im Text:** der Zustell-Code, die vollständige Sendungsnummer, eine Adresse, ein Ablageort und die Ereignistexte des Carriers. Eine Benachrichtigung verlässt Home Assistant (bei der App über den Push-Dienst von Apple oder Google), deshalb bleibt sie so knapp.

Schlägt das Senden fehl, steht eine Warnung ohne Paketdaten im Log; die Paketabfrage läuft unverändert weiter.

**Frühere Meldung ersetzen:** Über den klassischen Dienst der Home-Assistant-App („Dienst notify.mobile_app_<gerät>“) ersetzt eine neue Meldung die frühere zum selben Paket. Auf dem Handy steht dann nur der neueste Stand statt „in Zustellung“ und „zugestellt“ untereinander. Dafür schickt die Integration ein Kennzeichen mit (`data.tag`, ein Hash der Sendungsnummer, nie die Nummer selbst). Alle anderen Ziele bekommen nur Titel und Text.

Was dieser Weg nicht kann: Der Dienst `notify.send_message` für Benachrichtigungs-Entitäten kennt nur Titel und Text, ersetzen geht darüber nicht. Und dass sich beim Antippen ein Dashboard öffnet, geht nur über den Blueprint.

### Blueprint

Für eigene Texte, eigene Bedingungen und die Extras der Home-Assistant-App gibt es einen Blueprint:

[![Blueprint in Home Assistant importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FSoerenKaiser99%2Fparcel_tracker%2Fmain%2Fblueprints%2Fautomation%2Fparcel_tracker%2Fpaket_benachrichtigung.yaml)

Der Knopf importiert [`blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml`](blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml) aus diesem Repository (HACS installiert Blueprints nicht mit). Danach unter **Einstellungen → Automationen & Szenen → Blueprints** eine Automation daraus anlegen:

- **Status**: bei welchen neuen Status benachrichtigt wird (alle Status wählbar, voreingestellt „in Zustellung“ und „zugestellt“).
- **Benachrichtigungsdienst**: ein klassischer Dienst als Text, z. B. `notify.mobile_app_mein_handy`; Standard `notify.notify`.
- **Titel** und **Text**: Der Text ist eine Vorlage mit den Variablen `name`, `carrier`, `new_status`, `old_status` und `text` (der fertige Standardsatz), z. B. `{{ name }} kommt mit {{ carrier }}`.
- **Dashboard-Pfad** (nur Home-Assistant-App): z. B. `/lovelace/pakete`. Beim Antippen öffnet sich dieses Dashboard (`data.url` für iOS, `data.clickAction` für Android).
- **Frühere Meldung ersetzen** (nur Home-Assistant-App): Eine neue Meldung ersetzt die frühere zum selben Paket (`data.tag`, ein Hash der Sendungsnummer, nie die Nummer selbst).
- **Zusätzliche Bedingungen**: z. B. nur tagsüber oder nur, wenn jemand zu Hause ist.

Sind Dashboard-Pfad und Ersetzen nicht gesetzt, schickt der Blueprint nur Titel und Text und passt damit zu jedem Benachrichtigungsdienst. Wer Benachrichtigungen in den Optionen und zusätzlich über den Blueprint einschaltet, bekommt jede Meldung zweimal.

## Beispiel-Automation

Wer lieber ganz von Hand baut – das Event `parcel_tracker_status_changed` trägt `number`, `name`, `carrier` (Kürzel, z. B. `dhl`), `carrier_name` (Anzeigename wie am Sensor, z. B. `DHL`), `old_status`, `new_status`, `eta_date`, `eta_from`, `eta_to`, `location` und `assumed` (wahr, wenn eine Bestellung ohne Zustellmail abgeschlossen wurde – der neue Status ist dann `delivered`, zugestellt ist aber nur angenommen; eigene Automationen prüfen das mit `{{ not trigger.event.data.assumed }}`). Benachrichtigung, sobald ein Paket in Zustellung geht:

```yaml
triggers:
  - trigger: event
    event_type: parcel_tracker_status_changed
    event_data:
      new_status: out_for_delivery
actions:
  - action: notify.notify
    data:
      title: "Paket kommt heute"
      message: "{{ trigger.event.data.name or trigger.event.data.number }} ({{ trigger.event.data.carrier_name }}) ist in Zustellung."
```

## Datenschutz

Sendungsnummern gehen nur an den jeweiligen Carrier (DHL, DPD, GLS, Hermes bzw. – mit eigenen Zugangsdaten – UPS). Eine Ausnahme: Eine 12-stellige Nummer, die du mit „Automatisch“ einträgst, kann zu DHL oder zu GLS gehören. Sie geht mit DHL-Key zuerst an DHL und, wenn DHL sie nicht kennt oder kein DHL-Key hinterlegt ist, einmal an GLS (alle 12 Ziffern, ohne PLZ) – auch wenn sie am Ende zu keinem GLS-Paket gehört. Nummern aus Mails und Shop-Bestellungen gehen auf diesem Weg nie an GLS. Die PLZ geht nur an DHL und GLS (an GLS zusammen mit der Paketnummer, damit GLS den Verlauf liefert); ohne hinterlegte PLZ geht an GLS nur die Paketnummer. An 17track geht nur auf ausdrücklichen Wunsch die Sendungsnummer samt Carrier-Code, keine PLZ und kein Name; Adressen aus der 17track-Antwort verwirft die Integration, ohne sie zu speichern oder zu loggen.

Aus Mails übernimmt der Import nur Bestell- bzw. Sendungsnummer, einen auf 60 Zeichen gekürzten Artikeltitel, den Namen eines Shops oder einer Firma (nur bis zur Rechtsform, nie den einer Privatperson und nie den Anzeigenamen eines Carriers; das gilt auch für die Absenderzeile „Von:“ einer UPS-Mail und den Versender in der Ankündigung von DPD, und statt eines Händlernamens bei Amazon oder eBay steht nur „Amazon“ bzw. „eBay“), Status, Liefertag und Zeitfenster, den Versanddienstleister sowie – nur mit eingeschalteter Option und nur im Arbeitsspeicher – den Zustell-Code. Adresse, Name, Telefonnummer, eBay-Käufer- und Verkäufernamen, Wunsch-Ablageort bzw. Abstellort, Referenzen, Preise und Mail-Inhalte landen weder in Attributen noch im Log. Das IMAP-Passwort, die UPS-Zugangsdaten und der 17track-Key liegen wie der DHL-Key in der Konfiguration von Home Assistant.

Benachrichtigungen gehen an die gewählten Benachrichtigungs-Ziele und damit an deren Dienst. Sie enthalten nur den Namen bzw. Artikeltitel des Pakets (ohne Namen die letzten vier Stellen der Nummer), den Carrier, den Status und – wenn bekannt – das heutige Zeitfenster oder Ort und letzten Abholtag der Filiale; nie den Zustell-Code, die vollständige Sendungsnummer, eine Adresse oder einen Ablageort. Der Diagnose-Download nennt nur die Anzahl der Ziele (getrennt nach Entitäten und klassischen Diensten, nie ihre Namen) und die gewählten Ereignisse.

## Markenhinweis

DHL, DPD, Hermes, UPS, GLS, 17track, Amazon, eBay und AliExpress sind Marken ihrer Inhaber. Die Logos (Simple Icons, CC0) dienen nur zur Kennzeichnung des Carriers; DHL als gelbes Schild mit rotem Schriftzug, UPS in der Textfarbe des Themes, Hermes erscheint als blauer Punkt mit „H“, GLS als blauer Punkt mit „G“ (Simple Icons hat kein GLS-Logo), AliExpress als roter Punkt mit „A“, „Andere (über 17track)“ als grauer Punkt mit „17“. Dieses Projekt ist nicht mit den Unternehmen verbunden.

## Fehler melden

1. In Home Assistant die Diagnose herunterladen: **Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen**.
2. Die Datei kurz ansehen (JSON, jeder Texteditor zeigt sie an).
3. Auf GitHub ein Issue mit der Vorlage [„Fehler melden“](https://github.com/SoerenKaiser99/parcel_tracker/issues/new?template=fehler.yml) öffnen: Version der Integration, Home-Assistant-Version, Carrier, was passiert ist und was du erwartet hast. Die Diagnose-Datei ins Feld „Diagnose-Datei“ ziehen; ein Log-Auszug ist freiwillig.

**Die Diagnose enthält:** die Version der Integration, das eingestellte Land, ob „Namen ausblenden“ eingeschaltet ist (und je Paket, ob sein Name von Hand vergeben wurde – nie den Namen selbst), die Einstellungen ohne Geheimnisse, je Paket Carrier, Modus, Status (auch, ob eine Bestellung ohne Zustellmail abgeschlossen wurde), Fehler und Zähler sowie den Zustand des Mail-Imports (Zeitpunkt des letzten Laufs, Wartezeit nach Fehlern, Zähler für erkannte und nicht erkannte Mails). Zu den letzten zehn nicht erkannten Mails steht nur die Absender-Domain (bei unbekannten Absendern nur `other`; bei einer Weiterleitung die Domain des ursprünglichen Absenders, wenn der Import ihn kennt) und ob die Mail weitergeleitet war. Der IMAP-Server wird nur genannt, wenn er zu einem öffentlichen Mailanbieter gehört (z. B. mailbox.org, GMX, Gmail); ein eigener Server steht nur als `custom` drin. Home Assistant ergänzt die Datei selbst um Systeminformationen (Version, Installationsart, Betriebssystem) und die Liste der installierten benutzerdefinierten Integrationen.

**Die Diagnose enthält nie:** API-Keys, Passwörter, das UPS-Secret, den 17track-Key, den IMAP-Benutzer, die PLZ, Paketnamen und Artikeltitel, Zustell-Codes, Orte, Ereignistexte, Betreffzeilen und Mail-Inhalte. Sendungs- und Bestellnummern stehen nur maskiert drin: Ziffern werden zu `9`, Buchstaben zu `A`, Länge und Präfix bleiben (z. B. `JJD999999999999999999`), damit sich Erkennungsfehler trotzdem nachvollziehen lassen.

Geht es um eine Mail, die der Import nicht erkennt, hilft zusätzlich eine anonymisierte Beispielmail: siehe [Beispielmails einreichen](#beispielmails-einreichen).

## Beispielmails einreichen

Landet eine Paketmail im Ordner `Paket-Tracker-Nicht-erkannt` oder fehlt ein Shop oder Carrier, lässt sich das nur mit einer Beispielmail beheben. Eingereicht werden ausschließlich anonymisierte Mails als ZIP an einem GitHub-Issue.

**Nie rohe Mails hochladen.** **Nie Mails privat an den Autor schicken.**

1. Die Original-Mail als `.eml` speichern – nicht weiterleiten, denn eine Weiterleitung verändert Absender und Aufbau. Weitergeleitete Mails helfen deutlich weniger als Originale und müssen besonders genau gelesen werden: Steht in der Weiterleitung der Kopfzeilen-Block der Original-Mail („Von: … / Gesendet: … / An: … / Betreff: …“), übernimmt das Skript nur diesen Block und die Mail darunter – alles darüber (eigene Zeilen, die eigene Signatur) lässt es weg, den ursprünglichen Absender im Block lässt es stehen, die Empfänger ersetzt es. Ohne diesen Block und für eigene Zeilen unter dem Block kann das Skript eine Signatur nicht als solche erkennen. Thunderbird: Rechtsklick auf die Mail → „Speichern als“. Gmail im Browser: ⋮ an der Mail → „Nachricht herunterladen“. Apple Mail: die Mail aus der Liste in einen Ordner ziehen. Alle Mails in einen eigenen Ordner legen.
2. Das Skript [`anonymize_mail.py`](https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main/scripts/anonymize_mail.py) herunterladen (im Browser „Speichern unter“) und neben den Ordner legen. Es ist eine einzelne Datei, braucht nur Python 3 und läuft lokal, ohne Netzwerkzugriff und ohne Installation der Integration.
3. Im Terminal starten (unter Windows `py` statt `python3`):

   ```
   python3 anonymize_mail.py <Ordner> --zip
   ```

   Das Skript fragt nach Name, Straße und Hausnummer, Postleitzahl, Ort, Telefonnummer und Mail-Adresse (leer lassen überspringt eine Angabe) und ersetzt diese Angaben überall. Die Angaben lassen sich auch als Optionen übergeben: `--name "Vorname Nachname" --street "Straße 1" --postcode 12345 --city Ort --phone … --email …`. Mindestens eine Angabe ist nötig. Ganz ohne Angaben arbeitet das Skript nur mit `--ohne-angaben`: Es fragt dann nicht und bereinigt nur allgemein – Namen und Orte können dann stehen bleiben.

   Unabhängig von den Angaben ersetzt es alle Mail-Adressen außer dem Absender des Shops oder Carriers, Telefonnummern, Links (nur der Servername bleibt), Sendungs- und Bestellnummern (gleiche Form, erfundene Ziffern), Ablageorte, Anreden, Adressblöcke, Zeilen mit Postleitzahl und Ort sowie Namen von Nachbarn, Empfängern und privaten Absendern; technische Kopfzeilen und Anhänge entfallen. Bei weitergeleiteten oder beantworteten Mails (Betreff mit „WG:“, „Fwd:“, „AW:“, „Re:“) ersetzt es auch den Absender. Sieht eine Mail weitergeleitet aus (Betreff mit „WG:“, „Fwd:“ oder „Fw:“ oder ein zitierter Kopfzeilenblock „Von: … Gesendet: …“), nennt das Skript die Datei am Ende in einer „ACHTUNG“-Zeile – eine Signatur kann darin stehen geblieben sein. Steht eine Sendungsnummer nur in einem Link oder im Text eines Bildes, bleibt sie als erfundene Nummer in einer eigenen Zeile „[Nummer nur im Link oder Bildtext: …]“ erhalten. Nummern ab 10 Ziffern, die in Gruppen geschrieben sind (getrennt durch Leerzeichen, Tabulator, Punkt oder Bindestrich), und internationale Nummern in Gruppen („CQ 123 456 785 DE“) behalten ihre Gruppen und bekommen erfundene Ziffern – gezählt werden nur Ziffern, die mit demselben Trennzeichen zu einer Nummer gehören; Datum, Uhrzeit („2026-09-28 11:51“), Preise sowie Reihen von Jahreszahlen oder zweistelligen Zahlen ohne Bezeichnung davor bleiben, Telefonnummern werden wie bisher ersetzt. Frühere Ergebnisse des Skripts im Ordner `anonymisiert/` löscht es vor dem Schreiben.
4. Die Ergebnisse lesen: Sie liegen in `<Ordner>/anonymisiert/`. Jede Datei im Texteditor öffnen und durchlesen – das Skript erkennt nicht alles. Steht noch etwas Privates drin, die Stelle von Hand ersetzen oder die Mail weglassen und das ZIP neu packen.
5. Ein Issue mit der Vorlage [„Mail wird nicht erkannt“](https://github.com/SoerenKaiser99/parcel_tracker/issues/new?template=mail-nicht-erkannt.yml) öffnen und `paket-tracker-beispiele.zip` aus dem Ordner `anonymisiert/` anhängen.

## Roadmap & Status

- DHL (offizielle API): umgesetzt
- DPD (öffentliche Sendungsverfolgung): umgesetzt
- E-Mail-Import Amazon, DHL, UPS: umgesetzt
- Hermes Live-Abfrage: umgesetzt; von einem Tester mit einer aktuellen Sendung bestätigt
- Hermes-Mails: umgesetzt
- eBay-Mails: umgesetzt
- AliExpress-Mails (Bestellungen, Sendungsnummer des Carriers aus den „Packstück“-Mails) und Mails über Apples „E-Mail-Adresse verbergen“: umgesetzt nach Beispielmails ([Issue #15](https://github.com/SoerenKaiser99/parcel_tracker/issues/15)); im Alltag noch nicht bestätigt
- UPS Live-Status (offizielle API): umgesetzt, noch nicht mit echten Zugangsdaten getestet (UPS-Freischaltung ausstehend)
- 17track: umgesetzt; Abfrage von einem Tester bestätigt (das Kontingent wird einmal belastet, die Karte füllt sich); Anreicherung bei DPD/GLS noch ohne Live-Fall (bei einem DHL-Paket live gesehen)
- GLS-Live-Abfrage: umgesetzt; von einem Tester mit einem echten Paket bestätigt
- GLS-Mails: umgesetzt
- Von Hand weitergeleitete Mails: umgesetzt; von einem Tester bestätigt
- DPD-Ankündigung „Bald ist Ihr DPD Paket da“ (Versender als Name, Lieferschätzung in Werktagen): umgesetzt nach anonymisierten Beispielmails eines Testers
- Mails von GLS Österreich und DPD Österreich, internationale DHL-Nummern (`CQ…DE`): umgesetzt nach anonymisierten Beispielmails von Testern; DPD-Live-Abfrage für Österreich offen
- Benachrichtigungen (Optionen und Blueprint): umgesetzt, an Benachrichtigungs-Entitäten und klassische Dienste (z. B. Pushover); die frühere Meldung ersetzen über den klassischen Dienst der Home-Assistant-App oder den Blueprint, Antippen öffnet ein Dashboard nur über den Blueprint
- Land (Deutschland, Österreich, Schweiz): umgesetzt für PLZ-Länge und GLS-Abfrage; GLS Österreich mit echten Paketen noch nicht getestet
- Bestellungen ohne Zustellmail (Amazon, eBay, AliExpress): umgesetzt – ein zugestelltes Carrier-Paket schließt die passende Bestellung, überfällige Bestellungen ohne Sendungsnummer werden „Abgeschlossen ohne Zustellbestätigung“
- Amazon per Konto-Anmeldung: verworfen zugunsten des Mail-Imports
- Push-Schnittstelle von DHL (DHL meldet Statusänderungen von sich aus): geprüft, wartet auf Klärung des Zugangs für Privatnutzer
- **Barcode-Scan** (Wunsch aus [Issue #2](https://github.com/SoerenKaiser99/parcel_tracker/issues/2)): Sendungsnummer mit der Handykamera vom Label erfassen – geplant über den Scanner der Home-Assistant-App bzw. die Barcode-Erkennung des Browsers, ohne Fremdbibliothek; braucht Beispiel-Scans je Carrier, weil auf den Labels oft mehr als die Sendungsnummer steht
- **International**: Karte auch auf Englisch, weitere Amazon-Länder im Mail-Import, nationale Carrier (Beispiele: Österreichische Post, Royal Mail, PostNL, USPS) – erst sinnvoll mit anonymisierten Beispielmails von Testern aus den jeweiligen Ländern

---

## English summary

Paket Tracker is a Home Assistant custom integration, built for Germany, that tracks parcels from DHL, DPD, GLS, Hermes and, optionally, UPS. Why: one place in Home Assistant that answers "is a parcel coming today, and when?" across all carriers instead of five apps and a pile of mails – parcels appear by themselves from shipping mails, can be used in automations, and everything runs locally with no cloud account and no third-party tracking service. DHL uses the official "Shipment Tracking – Unified" API (an API key is optional; without one, DHL parcels show a "key missing" status), while DPD uses DPD's public tracking page with only the tracking number, which yields status and the five milestone dates but no location or delivery window. The integration creates one sensor per parcel (`sensor.paket_<number>`), a summary sensor counting the parcels that are certain to arrive today (parcels whose multi-day delivery window merely includes today are listed as `possible` / `possible_count` instead, parcels already delivered today as `delivered_today` / `delivered_today_count`, parcels ready for pickup as `awaiting_pickup` / `awaiting_pickup_count`; the card shows these as up to three badges, "heute", "möglich" and "zugestellt"), four count sensors for dashboard conditions (`sensor.pakete_unterwegs` = not delivered yet, `sensor.pakete_moeglich`, `sensor.pakete_zugestellt_heute`, `sensor.pakete_abholbereit` = ready for pickup at a Packstation, branch or parcel shop; the card option `show` with `always`, `active`, `today` or `today_possible` hides the card by itself while nothing is due), a delivery calendar, and fires a `parcel_tracker_status_changed` event on every status change. Optional push notifications (options section "Benachrichtigungen": pick notify entities or classic notify services such as Pushover, and the events out for delivery, delivered, ready for pickup, problem) need no automation; their one-line text never contains the delivery code, the full tracking number or an address, and a blueprint (`blueprints/automation/parcel_tracker/paket_benachrichtigung.yaml`) covers custom texts, extra conditions and, for the Home Assistant app, opening a dashboard on tap and replacing the earlier notification. It ships its own Lovelace card (`custom:parcel-tracker-card`, listed as "Paket Tracker" in the card picker) for adding, renaming, and removing parcels. Install it through HACS as a custom repository, then set up an optional DHL API key, a postcode, and how long delivered parcels stay visible. An optional mail import reads a dedicated parcel mailbox via IMAP (never enter your main mailbox: the IMAP password grants full access) and creates parcels from Amazon, DHL and UPS mails, including Amazon's own deliveries; a DHL "Amazon Sendung" mail is merged into the matching Amazon order when unambiguous. Delivery one-time codes are read only when enabled, shown on the card after a tap and a confirmation (hidden only on the card: anyone with access to the entity attributes or the Home Assistant API can read it), never stored and never recorded. Hermes uses the keyless public tracking endpoint (number only). UPS status comes from UPS mails and, with your own Client ID and Secret from developer.ups.com (product "Tracking"), from the official UPS Track API, capped by a monthly request budget (default 100) so it never costs money. The mail import also reads Hermes and eBay mails (one parcel per eBay order, never using eBay item numbers as tracking numbers) and merges a carrier mail into exactly one matching open Amazon or eBay order. AliExpress mails (`transaction@notice.aliexpress.com`, German mails) become one parcel per order (`ALI` + order number): the subject tells the step ("Bestellt" for confirmed and ready to ship, "Versendet" for shipped, in transit and arrived in the country, with AliExpress's own wording in the history), the body the item name and the estimated delivery day; the "Packstück …" and "Zollabfertigung …" mails carry the carrier's tracking number, which the order takes over when it is a DHL or Hermes number, so the order is then tracked live at the carrier and no second parcel appears (a number in any other format is dropped and only the step is taken); "wie ist es gelaufen?" with a confirmed delivery closes the order, rating requests, reminders, offers and "Your order … is closed" are ignored, and an AliExpress order without a carrier number is closed automatically like an Amazon order. Mails passed on by Apple's "Hide My Email" relay (`<sender>_at_<domain>_…@privaterelay.appleid.com`) are recognised as mails of the original sender, for every shop and carrier the import knows. Orders that never get a "delivered" mail (typical when a marketplace seller ships with a carrier himself) are settled in two ways: when a carrier parcel that a mail created on its own is delivered, it is checked once more by the same merge rules and, if it belongs to exactly one open order, folded into that order (the order becomes delivered and takes over tracking number, history and delivery time, the separate carrier parcel disappears, and the delivery is announced only once; parcels added by hand are never folded); and an Amazon or eBay order without a carrier tracking number is closed automatically when its last delivery day lies more than 3 full days back and no mail has changed it since (without any delivery day: 14 days after its last change) – status `delivered` with the text "Abgeschlossen ohne Zustellbestätigung", attribute `assumed_delivered` set to `true`, no `delivered_at`, no push notification, not counted as delivered today, and the `parcel_tracker_status_changed` event carries the field `assumed` set to `true` (the blueprint ignores such events); a later mail still wins (a real delivery mail fills in the time without a late notification, a mail with another status reopens the order). Roadmap & Status: the UPS API is implemented but not yet tested with real credentials (UPS approval pending), the Hermes live lookup is implemented and confirmed by a tester with a current parcel, the 17track lookup was confirmed by a tester (the quota is debited once and the card fills in) while its enrichment has not yet seen a live case for DPD or GLS, mails forwarded by hand were confirmed by a tester, the GLS live lookup is implemented and confirmed by a tester with a real parcel, and an Amazon account login was dropped in favour of the mail import; an International roadmap item (English card, more Amazon countries, national carriers such as Royal Mail, PostNL and USPS) waits for anonymised sample mails from testers abroad. With an optional free 17track API key, a parcel can be sent to 17track on request (each new number uses one of the account's 200 one-time numbers; polls are free, every 6 hours, at most 40 numbers per call) to fill in place, time window and history without overriding the carrier, and carriers without their own connection (e.g. FedEx) can be added as "other"; a quota sensor and repairs warn when numbers run low. Tracking numbers are sent only to the matching carrier (or, on request, to 17track with the carrier code), and the postcode is sent only to DHL and GLS. One exception: a 12-digit number entered with "Automatisch" may belong to DHL or to GLS, so it goes to DHL first (with a DHL key) and, if DHL does not know it or no DHL key is set, it is sent once to GLS with all 12 digits and without the postcode, even if it turns out to be no GLS parcel; GLS answers a parcel only for the correct check digit, a hit makes it a GLS parcel, and numbers from mails or shop orders are never sent to GLS this way. GLS uses the open tracking lookup of gls-group.com (11-digit parcel number; with a stored postcode GLS also returns the history) and GLS notification mails; the lookup is no official API and may be closed at any time, in which case GLS mails and 17track remain. A country setting (Germany, Austria, Switzerland) sets the postcode length (5 or 4 digits) and, for Austria, the Austrian variant of the GLS lookup, which is not yet tested with real parcels. The mail import also reads GLS and DPD mails seen from Austria (`noreply@gls-group.eu`, `noreply@gls-rtt.com`, `no_reply@dpd.at`) and international DHL numbers (`CQ…DE`); a DPD live lookup for Austria is still open. The announcement mail of DPD Germany ("Bald ist Ihr DPD Paket da") adds the shipper as the parcel's name (companies only, never a person) and a delivery estimate ("in 1-2 Werktagen", counted in working days Monday to Saturday from the day of the mail). An option "Namen ausblenden" (hide names, off by default, meant for gifts on a shared family dashboard) names every parcel by its carrier and the last four characters of its number only (`DHL-Paket …2557`, `Amazon-Bestellung …4321`, `Paket …2557` without a known carrier) – on the card, in the sensors (entity name, `name` attribute and the parcel lists of the summary sensors), in the calendar, in the `name` field of the `parcel_tracker_status_changed` event (and so in the blueprint) and in push notifications. A name typed in by hand (rename on the card, `rename_parcel`, or the name given when adding a parcel, from v0.3.24 on) stays visible; names taken from mails are hidden. Stored names, mail titles and the merge rules are untouched, so switching the option off brings the real names back at once; entity IDs are derived from the number and do not change, and the diagnostics download never contained names (it only states whether the option is on). Home Assistant's own history keeps what it recorded before the option was switched on.

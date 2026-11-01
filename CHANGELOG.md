# Änderungen am Paket Tracker

Die Doku-Seite steht unter <https://soerenkaiser99.github.io/parcel_tracker/>, die Release-Seiten mit den Downloads unter <https://github.com/SoerenKaiser99/parcel_tracker/releases>.

## Was die Integration kann

- **DHL:** Live-Status über die offizielle API mit eigenem, kostenlosem Key. Ohne Key kommen DHL-Pakete aus den DHL-Mails.
- **DPD, GLS, Hermes:** Live-Status über die öffentlichen Sendungsverfolgungen, ohne Zugangsdaten.
- **UPS:** Status aus UPS-Mails, live über die offizielle UPS-Track-API mit eigenem Entwicklerzugang (braucht ein UPS-Konto mit Abrechnung; mit Monatsbudget).
- **17track (optional):** ergänzt Ort, Zeitfenster und Verlauf und verfolgt Paketdienste ohne eigene Anbindung, nur auf ausdrücklichen Wunsch.
- **Länder:** Deutschland, Österreich und Schweiz (Postleitzahl und GLS-Abfrage passend zum Land).
- **E-Mail-Import (optional):** liest ein eigenes Paket-Postfach per IMAP (eigener Ordner, Port und Verbindungsart wählbar, Abfrage-Intervall einstellbar) und legt Pakete aus den Mails an. Auf Wunsch löscht er erkannte Mails nach einer einstellbaren Zahl von Tagen.
- **Absender im Mail-Import:** Amazon, DHL, DHL Express, DHL eCommerce, DPD (Deutschland, Österreich), GLS (Deutschland, Österreich), Hermes, UPS, eBay, AliExpress und Eventim (nur Postversand).
- **Weitergeleitete Mails:** von Hand weitergeleitete Mails, Apples „E-Mail-Adresse verbergen“ und Mails per HTTP-Aufruf (z. B. aus n8n oder Node-RED).
- **Zusammenführen:** Bestellung (Amazon, eBay, AliExpress) und das Paket des Paketdienstes werden zu einem Eintrag. Bestellungen ohne Zustellmail schließen sich von selbst.
- **Karte** `custom:parcel-tracker-card`: Pakete hinzufügen, umbenennen, als erhalten markieren und löschen, Verlauf, Sendungs- und Bestellnummer, Symbole „Sendung verfolgen“ und „Bestellung“.
- **Schilder auf der Karte:** „heute“, „möglich“ und „zugestellt“, jeweils nur, wenn es etwas zu zählen gibt. Die Karte blendet sich auf Wunsch selbst aus (`show`), die Eingabe ist einklappbar (`add_form`), die Kopfzeile abschaltbar (`header`), Geschenke lassen sich ausblenden (`gifts`).
- **Geschenkmodus:** neue Pakete heißen „Geschenk · …“ und verbergen Name, Links und Mail-Titel. Nur festgelegte Personen sehen auf der Karte, was drin ist. Mit `gift_for` bleibt ein Geschenk vor den Personen verborgen, für die es ist.
- **Personen zuordnen (optional):** die Integration erkennt an den Kopfzeilen der Mail, wem ein Paket gehört (Plus-Adresse, Alias oder eigene Adresse). Die Karte filtert mit `person` und lässt den Besitzer wählen, Meldungen gehen nur an dessen Ziele.
- **Namen ausblenden:** alle Pakete heißen nur nach dem Paketdienst und den letzten Stellen der Nummer.
- **Benachrichtigungen (optional):** bei „in Zustellung“, „zugestellt“, „abholbereit“ und Problem, an Benachrichtigungs-Entitäten und klassische Dienste. Dazu ein Blueprint für eigene Texte.
- **Sensoren:** `sensor.paket_<nummer>` pro Paket, `sensor.pakete_heute` und vier Zählsensoren (unterwegs, möglich, zugestellt heute, abholbereit).
- **Kalender:** `calendar.pakete` mit den erwarteten Zustellterminen.
- **Schalter:** `switch.paket_tracker_geschenkmodus` für den Geschenkmodus.
- **Dienste:** `add_parcel`, `remove_parcel`, `rename_parcel`, `mark_delivered`, `refresh`, `track_17track`, `set_gift` und `set_owner`.
- **Event und Auslöser:** das Event `parcel_tracker_status_changed`, das Event `parcel_tracker_parcel_added` für neue Pakete und fünf Auslöser im Automations-Editor ohne YAML.
- **Einfuhrabgaben (Zoll):** Betrag und Barzahlung aus der DHL-Mail am Zustelltag auf der Karte und in der Benachrichtigung.
- **Abholbereit:** Packstation, Filiale und PaketShop mit Abholort und letztem Abholtag.
- **Zustell-Codes (optional):** Einmalpasswörter aus Amazon-Mails, verdeckt auf der Karte, nie gespeichert und in keinem Attribut (der Sensor zeigt nur `has_delivery_code`).
- **Datensparsam:** kein Cloud-Konto, Zugangsdaten bleiben in Home Assistant, nur ein eigenes Paket-Postfach wird gelesen.
- **Diagnose:** Download ohne Zugangsdaten, Namen und Mail-Inhalte; Sendungsnummern maskiert.
- **Beispielmails einreichen:** ein Anonymisier-Skript ersetzt Namen, Adressen und Nummern, bevor eine Mail geteilt wird.
- **Doku und Demo:** eine Doku-Seite mit Rezepten und eine Demo-Karte mit erfundenen Paketen.

## Versionen

### v0.3.47 (2026-11-01)

Wunsch/Meldung aus dem simon42-Forum (In Zustellung ohne Termin); `person: auto` zu [Issue #39](https://github.com/SoerenKaiser99/parcel_tracker/issues/39).

- **„In Zustellung“ ohne Termin zeigt „Heute“:** Ein Paket in Zustellung, für das der Paketdienst keinen Tag nennt (Hermes, manchmal auch DPD und GLS), steht auf der Karte als „Heute“ und ganz oben, wenn sich sein Status heute geändert hat. Das Attribut `days_until` ist dann 0, dieselbe Regel wie beim Zähler „heute“. Ein Paket, das schon gestern in Zustellung ging, bleibt bei „Noch kein Termin“.
- **Kartenoption `person: auto`:** Die Karte zeigt die Pakete der Person des angemeldeten Benutzers, plus die Pakete von allen (`include_unassigned`, Standard `true`). Sie wählt bei einem Benutzerwechsel neu. Hat der Benutzer keine Person, bleiben nur die Pakete von allen. Das ist nur eine Anzeige, kein Schutz.

### v0.3.46 (2026-10-29)

Wunsch aus dem simon42-Forum.

- **Kein „0 heute“ mehr:** Kommt heute nichts sicher, zeigt die Karte das Schild „heute“ nicht. „möglich“ und „zugestellt“ stehen wie bisher nur da, wenn es welche gibt. Ohne Schild bleibt die Kopfzeile ohne Lücke.
- **Kopfzeile abschaltbar:** Mit der Kartenoption `header: false` entfallen Titel, Schilder, Geschenk-Schalter und Plus-Knopf. Pakete fügst du dann über den Knopf „Paket hinzufügen“ über der Liste hinzu (außer mit `add_form: never`), den Geschenkmodus schaltest du über `switch.paket_tracker_geschenkmodus`.
- **Erkannte Mails löschen:** Neue Option „Erkannte Mails löschen nach (Tagen)“ im E-Mail-Import, Standard aus. Sie löscht Mails endgültig, nur im Ordner `Paket-Tracker-Verarbeitet` (auch mit Präfix wie `INBOX.`), nur solche, die älter sind als die eingestellten Tage, höchstens einmal am Tag. Die Diagnose zeigt nur, ob es eingeschaltet ist, und wie viele Mails zuletzt gelöscht wurden.

### v0.3.45 (2026-10-27)

- **Geschenk für bestimmte Personen:** Der Dienst `set_gift` nimmt ein optionales `gift_for` (Liste von Personen). Wer dort steht, sieht das Geschenk auf der Karte wie jemand, der Geschenke nicht sehen darf, auch wenn er sonst Geschenk-Seher ist: kein echter Name, mit `gifts: hide_for_others` gar keine Zeile. Meldungen zum Paket gehen nicht an die Ziele dieser Personen. Ändern oder aufheben kann das Geschenk nur, wer nicht in `gift_for` steht, und eine Automation. Für wen ein Geschenk ist, steht in keinem Attribut, keinem Event, nicht in der Diagnose und nicht im Log der Integration. Ohne `gift_for` bleibt alles wie bisher ([#64](https://github.com/SoerenKaiser99/parcel_tracker/issues/64)).
- **`gift` im Status-Event:** `parcel_tracker_status_changed` sagt mit `gift`, ob das Paket ein Geschenk ist ([#64](https://github.com/SoerenKaiser99/parcel_tracker/issues/64)).
- **Roadmap:** Paket-Postfach per OAuth/Microsoft Graph steht als Wunsch auf der Stand-Seite ([#65](https://github.com/SoerenKaiser99/parcel_tracker/issues/65)).

### v0.3.44 (2026-10-23)

- **Event beim Anlegen:** `parcel_tracker_parcel_added` feuert einmal, sobald ein Paket neu angelegt ist (Mail, weiterer Karton einer Bestellung, Dienst `add_parcel`, Karte), mit `entry_id`, `number`, `name`, `carrier`, `owner` und `gift`. Bei einem Geschenk steht dort nur der Geschenk-Name. Nicht beim Neustart und nicht beim Zusammenführen, auch nicht für eine Bestellung, die ein schon gemeldetes Paket übernimmt (ein Event pro Karton). Damit lässt sich per Push nachfragen, ob ein neues Paket ein Geschenk ist ([#64](https://github.com/SoerenKaiser99/parcel_tracker/issues/64)).
- **Geschenke ausblenden:** Kartenoption `gifts`. Mit `hide_for_others` sieht nur, wer Geschenke sehen darf, die Geschenk-Zeilen; für alle anderen zählen sie auch nicht in den Schildern. `hide` zeigt nie Geschenke, z. B. auf einem gemeinsamen Wandtablet. Ohne Option bleibt die Karte wie bisher ([#64](https://github.com/SoerenKaiser99/parcel_tracker/issues/64)).
- **`gift` in den Listen:** Jeder Eintrag in `parcels`, `possible`, `delivered_today` und `awaiting_pickup` sagt mit `gift`, ob er ein Geschenk ist ([#64](https://github.com/SoerenKaiser99/parcel_tracker/issues/64)).
- **Doku UPS:** Eine App auf developer.ups.com braucht immer ein UPS-Konto mit Abrechnung (Versenderkonto). Ohne geht UPS über die Mails oder 17track ([#63](https://github.com/SoerenKaiser99/parcel_tracker/issues/63)).

### v0.3.43 (2026-10-22)

- **Einfuhrabgaben (Zoll) bei DHL:** Nennt die DHL-Mail am Zustelltag Einfuhrabgaben, zeigt die Karte den Betrag als Schild und als Zeile im Paket, auch ob bar zu zahlen ist. Die Benachrichtigung „in Zustellung“ nennt ihn ebenfalls. Neue Attribute `customs_amount`, `customs_currency` und `customs_cash`, nicht im Verlauf gespeichert und nach der Zustellung gelöscht. Bei Geschenken bleibt der Betrag sichtbar, weil er an der Tür bezahlt werden muss (Beitrag von Sven242, [#53](https://github.com/SoerenKaiser99/parcel_tracker/pull/53), [#36](https://github.com/SoerenKaiser99/parcel_tracker/issues/36)).

### v0.3.42 (2026-10-22)

- **Karte nicht mehr in `www`:** Die Integration kopiert die Karte nicht mehr nach `www/parcel_tracker/`, sondern liefert sie selbst unter `/parcel_tracker/parcel-tracker-card.js` aus. Eine alte Dashboard-Ressource mit `/local/…` stellt sie beim Start selbst um (Speicher-Modus). Erst danach löscht sie die alte Kopie. Verwaltest du die Ressourcen per YAML, nennt der Reparatur-Hinweis die neue Adresse. Du ersetzt den alten Eintrag, danach verschwindet die Kopie.
- **Zustell-Code nur noch auf der Karte (Breaking Change):** Das Attribut `delivery_code` gibt es nicht mehr, der Sensor hat dafür `has_delivery_code` (`true` oder `false`). Die Karte holt den Code erst, wenn du ihn aufdeckst. Automationen und Templates, die `state_attr(…, 'delivery_code')` lesen, bekommen den Code nicht mehr. In Benachrichtigungen stand der Code nie und steht er weiterhin nicht.
- **IMAP-Server ohne Vorgabe:** Bei aktivem Mail-Import musst du den IMAP-Server selbst eintragen, sonst meldet das Formular „Trag den IMAP-Server deines Mailanbieters ein.“ Bestehende Einrichtungen laufen weiter: Ein eingerichteter Import ohne gespeicherten Server bekommt einmalig `imap.mailbox.org` eingetragen. Umgekehrt wird ein gespeichertes `imap.mailbox.org` ohne eingerichteten Mail-Import (der frühere stille Standardwert) beim Update entfernt.
- **DHL eCommerce (Niederlande):** Neuer Absender `noreply@dhlecommerce.nl`. Die 20-stelligen Nummern, die mit `00` beginnen (SSCC), liest der Import hinter „Sendungsnummer“, „Trackingnummer“, „DHL Trackingnummer“ oder „Shipment number“, wenn die Prüfziffer stimmt, nicht hinter „Rück-“ oder „Retoure“. Jede so gefundene Nummer gilt als DHL-Nummer. Die Sendungsnummer aus der Shop-Mail wird damit vermutlich erkannt ([#62](https://github.com/SoerenKaiser99/parcel_tracker/issues/62)).
- **Anonymisier-Skript:** Namen im Fuß der Mail hinter „Geschäftsführer“, „Inhaber“ oder „Vorstand“ werden ersetzt (Beitrag von benep, [#60](https://github.com/SoerenKaiser99/parcel_tracker/pull/60)). Eine SSCC behält ihre „00“ und bekommt eine gültige Prüfziffer.

### v0.3.41 (2026-10-20)

- **Personen zuordnen:** Im Menü „Konfigurieren“ gibt es jetzt den Eintrag „Personen“. Für jede Home-Assistant-Person trägst du Mailadressen und Benachrichtigungs-Ziele ein. Die Integration liest `Delivered-To`, `X-Original-To`, `To`, `Cc`, `X-Forwarded-To`, `X-Forwarded-For`, `Resent-From` und `Resent-To` und ordnet das Paket der Person zu, deren Adresse darin steht. Nennt die Mail keine, mehrere oder eine gemeinsame Adresse, gehört das Paket der Person bei „Unklare Pakete gehören“ (Standard: allen) ([#39](https://github.com/SoerenKaiser99/parcel_tracker/issues/39)).
- Neue Attribute `owner` und `owner_detected` am Paket-Sensor, neues Feld `owner` im Event `parcel_tracker_status_changed`.
- Neuer Dienst `parcel_tracker.set_owner`; `parcel_tracker.add_parcel` nimmt ein optionales `owner`. Ein von Hand gesetzter Besitzer wird nie von einer Mail überschrieben.
- Benachrichtigungen zu einem Paket gehen nur an die Ziele des Besitzers, wenn für die Person Ziele eingetragen sind; sonst wie bisher an die allgemeinen Ziele.
- Neue Attribute `persons` und `default_owner` am Sensor „Pakete heute“ (nur Entitäten, keine Adressen).
- Karte: Auswahl „Gehört“ im aufgeklappten Paket und in der Eingabe, nur wenn Personen eingerichtet sind und nur mit diesen Personen; ohne eingerichtete Personen verhält sich die Karte wie bisher. Neue Optionen `person` und `include_unassigned`.
- Anonymisier-Skript: behält die Empfänger-Kopfzeilen mit erfundenen Adressen (`adresse1@example.org`, Plus-Teil als `+person1`), damit sich die Erkennung an eingereichten Mails prüfen lässt.
- Doku: DHL-Key-Antrag korrigiert (Freemail-Adressen sind laut DHL nicht gesperrt, Wegwerf-Adressen werden abgelehnt).

### v0.3.40 (2026-10-20)

- **Geschenkmodus:** ein Schalter neben „Pakete“ auf der Karte. Pakete, die im Modus entstehen, heißen „Geschenk · …“ und zeigen keinen Namen, keinen Mail-Titel und keine Links, auch nicht im Kalender, in Sensoren und in Benachrichtigungen. Wer Geschenke sehen darf, legst du unter Konfigurieren fest; nur diese Personen schalten den Modus aus und sehen den echten Namen. Wähle sie zuerst, sonst lässt sich der Modus nur per Automation ausschalten. Wandtablets und Kinder-Handys brauchen einen eigenen Benutzer.
- Neuer Dienst `parcel_tracker.set_gift`, um Pakete (auch alle offenen) als Geschenk zu kennzeichnen oder wieder sichtbar zu machen.
- Der Recorder zeichnet die Attribute `name`, `tracking_url` und `amazon_shipment` und die Listen der Zusammenfassungen nicht mehr auf. Der Anzeigename der Entität und der Kalendereintrag bleiben im Verlauf: Ein später gekennzeichnetes Geschenk behält dort seinen früheren Namen. Schalte den Modus am besten vor dem Bestellen ein.
- **Storniert:** Stornierte Bestellungen bei Amazon, eBay und AliExpress schließen sich als „Storniert“ ([#23](https://github.com/SoerenKaiser99/parcel_tracker/pull/23)).
- **Amazon:** Sendungen einer Bestellung werden nach Sendungs-ID getrennt ([#49](https://github.com/SoerenKaiser99/parcel_tracker/pull/49)).
- Die Postfach-Abfrage lässt sich auf bis zu 1440 Minuten einstellen (vorher 60).
- Anonymisier-Skript: erkennt mehr Namen und Adressen, darunter eBay-Kaufbestätigungen ([#58](https://github.com/SoerenKaiser99/parcel_tracker/pull/58), [#59](https://github.com/SoerenKaiser99/parcel_tracker/pull/59)).

### v0.3.39 (2026-10-19)

- Neue Option „Absendernamen aus DHL-Mails ohne Firmenprüfung übernehmen“, standardmäßig aus, weil dann auch Namen von Privatpersonen auf der Karte landen können ([#52](https://github.com/SoerenKaiser99/parcel_tracker/pull/52), [#35](https://github.com/SoerenKaiser99/parcel_tracker/issues/35)).
- eBay: „Bestellung bestätigt“ legt die Bestellung schon als „Bestellt“ an ([#47](https://github.com/SoerenKaiser99/parcel_tracker/pull/47)).
- DHL: Filiale oder Packstation mit Straße als Abholort aus der Abholmail. Neuer Absender `abholung@dhl.de` für die Filterregel ([#48](https://github.com/SoerenKaiser99/parcel_tracker/pull/48)).
- Amazon, Versand durch Verkäufer: Eine DHL- oder Hermes-Mail landet nicht mehr bei einer fremden Bestellung ([#50](https://github.com/SoerenKaiser99/parcel_tracker/pull/50)).
- Anonymisier-Skript erkennt Namen und Straßen, an die das nächste Wort geklebt ist ([#45](https://github.com/SoerenKaiser99/parcel_tracker/pull/45)).

### v0.3.38 (2026-10-17)

- Auf der Karte stehen „Sendung verfolgen“ und „Bestellung“ als kleine Symbole hinter den Nummern ([#43](https://github.com/SoerenKaiser99/parcel_tracker/pull/43)).
- Amazon: Ohne Nummer eines Paketdienstes führt „Sendung verfolgen“ zu Amazons eigener Sendungsverfolgung ([#40](https://github.com/SoerenKaiser99/parcel_tracker/pull/40)).
- Neu gelesen: DHL Express („DHL On Demand Delivery“, [#38](https://github.com/SoerenKaiser99/parcel_tracker/pull/38)) und die Mails der letzten Meile bei AliExpress ([#42](https://github.com/SoerenKaiser99/parcel_tracker/pull/42)).
- Spät gelesene Mails stufen ein Paket nicht mehr zurück, und eine spätere Shop-Mail verschiebt die Zustellzeit nicht mehr ([#44](https://github.com/SoerenKaiser99/parcel_tracker/pull/44), [#42](https://github.com/SoerenKaiser99/parcel_tracker/pull/42)).
- Fast alles in dieser Version sind Beiträge von @benep.

### v0.3.37 (2026-10-16)

- DHL-Importsendungen mit ausländischer Sendungsnummer (z. B. `LE…BE`, `LW…NL`) werden aus DHL-Mails gelesen. Mit DHL-Key gibt es den Live-Status ([#34](https://github.com/SoerenKaiser99/parcel_tracker/issues/34)).

### v0.3.36 (2026-10-16)

- Amazon-Abholmail („Paket zur Abholung bereit“ von `pickup-point@amazon.de`): Die Bestellung wird „Abholbereit“, mit Abholort und letztem Abholtag auf der Karte und in der Benachrichtigung ([#33](https://github.com/SoerenKaiser99/parcel_tracker/issues/33)).
- Der Absender `pickup-point@amazon.de` gehört in die Filterregel.
- Meldet ein Paketdienst erneut „abholbereit“, bleibt der bekannte Abholort stehen.

### v0.3.35 (2026-10-15)

- eBay „📦PAKET ZUGESTELLT“ setzt die Bestellung auf „Zugestellt“ ([#32](https://github.com/SoerenKaiser99/parcel_tracker/issues/32)).
- DPD Österreich: „Ihr DPD Paket kommt zwischen … und … Uhr“ setzt „In Zustellung“ mit Zeitfenster ([#31](https://github.com/SoerenKaiser99/parcel_tracker/issues/31)).
- Das Anonymisier-Skript erkennt Adressblöcke mit vierstelliger Postleitzahl (Österreich, Schweiz) und mehr Straßenwörter.

### v0.3.34 (2026-10-14)

- Aufgeklappt zeigt die Karte die Sendungsnummer (bei Bestellungen auch die Bestellnummer), zum Kopieren markierbar.
- Weitere Mails werden gelesen (Beitrag von @benep, [#24](https://github.com/SoerenKaiser99/parcel_tracker/pull/24)): DPD nach der Ankündigung, eBay „Update zur Bestellung“, Hermes „kommt heute“ und weitere DHL- und Amazon-Mails.
- Nicht erkannte Mails werden erneut gelesen, wenn sie wieder ungelesen im Postfach liegen ([#27](https://github.com/SoerenKaiser99/parcel_tracker/pull/27), [#21](https://github.com/SoerenKaiser99/parcel_tracker/issues/21)).
- Der DHL-Verlauf zeigt keinen rohen HTML-Link mehr ([#18](https://github.com/SoerenKaiser99/parcel_tracker/issues/18)).
- Neues Rezept „Unterwegs ohne Abholbereite“.

### v0.3.33 (2026-10-14)

- Der Mail-Import legt seine Ordner auch bei Servern an, die neue Ordner nur unterhalb des Posteingangs erlauben ([#25](https://github.com/SoerenKaiser99/parcel_tracker/issues/25)). Scheitert das Verschieben, steht je Ordner einmal eine Warnung im Protokoll.
- Neu in der Anleitung: ein eigenes Paket-Postfach im Container (Beitrag aus der Community, [#26](https://github.com/SoerenKaiser99/parcel_tracker/issues/26)).

### v0.3.32 (2026-10-12)

- Mail-Import mit eigenem Port und wählbarer Verbindung (verschlüsselt, ohne Zertifikatsprüfung, unverschlüsselt) für eigene Mailserver im Heimnetz. Wer nichts ändert, merkt nichts.
- Schutz vor Versehen: ein Hinweis unter „Reparaturen“ bei unsicherer Verbindung zu einem Server außerhalb des Heimnetzes.
- Keine doppelte Meldung „zugestellt“ mehr, auch nicht nach einem Neustart.
- Bestellungen ohne Zustellbestätigung öffnen sich nur noch bei wirklich Neuem vom Paketdienst.

### v0.3.31 (2026-10-12)

- Korrekturen nach einem unabhängigen Code-Review: Ein zugestelltes Paket schließt nur noch die passende Bestellung (Zustelltag innerhalb von drei Tagen), „Erhalten“ schließt keine Bestellung mit, und eine alte Mail öffnet keine abgeschlossene Bestellung mehr.
- AliExpress: mehrere Bestellungen in einem Karton zählen einmal, die Bewertungsanfrage gilt nicht als Zustellung, das zweite Paket einer Bestellung bekommt einen eigenen Eintrag.
- Eventim: digitale Zustellarten legen keinen Eintrag mehr an.
- Das Anonymisier-Skript ersetzt bei Eventim-Mails auch Veranstaltung, Datum, Ort, Sitzplatz und Preis.
- Den Benachrichtigungs-Blueprint vor v0.3.30 einmal neu importieren.

### v0.3.30 (2026-10-11)

- Neuer Knopf „Erhalten“ (mit Rückfrage) und Dienst `parcel_tracker.mark_delivered`: Ein Paket lässt sich von Hand als angekommen markieren. Das Event hat dafür das Feld `manual`.
- Eventim-Tickets mit Postversand werden aus den Bestell- und Versandmails von `bestellstatus@eventim.de` angelegt.

### v0.3.29 (2026-10-11)

- Hermes: Ein Paket im PaketShop ist „Abholbereit“ und löst die Benachrichtigung aus. Zugestellt ist es erst nach dem Abholen.
- Neues Feld „Ordner“ im Mail-Import, um einen anderen Ordner als den Posteingang zu lesen.
- Von @benep: DHL „wird gleich zugestellt“ und zwei weitere AliExpress-Betreffs ([#20](https://github.com/SoerenKaiser99/parcel_tracker/issues/20), [#19](https://github.com/SoerenKaiser99/parcel_tracker/issues/19)).

### v0.3.28 (2026-10-11)

- Textkorrekturen: Der DHL-Key ist optional, AliExpress wird überall genannt.
- Neue Screenshots und eine Demo-Karte mit „Sendung verfolgen“.
- Neue Doku-Seite mit Kapiteln, Rezepten und der Seite „Wie ihr helfen könnt“. Am Verhalten ändert sich nichts.

### v0.3.27 (2026-10-10)

- Neuer Link „Sendung verfolgen“ auf der Karte und das Sensor-Attribut `tracking_url`.
- Automationen ohne YAML: Die Integration hat einen Geräte-Eintrag „Paket Tracker“ mit fünf Auslösern im Automations-Editor.

### v0.3.26 (2026-10-10)

- Die Benachrichtigung „abholbereit“ ist bei neu eingerichteten Benachrichtigungen von Haus aus an ([Issue #18](https://github.com/SoerenKaiser99/parcel_tracker/issues/18)). Wer sie schon eingerichtet hat, behält seine Auswahl.

### v0.3.25 (2026-10-10)

- AliExpress-Bestellungen aus Mails von `transaction@notice.aliexpress.com`, mit Artikelname, Status und Zustelltag ([Issue #15](https://github.com/SoerenKaiser99/parcel_tracker/issues/15)).
- Mails über Apples „E-Mail-Adresse verbergen“ werden bei allen bekannten Absendern erkannt.
- Von @benep: eine Mail per HTTP übergeben (`POST /api/parcel_tracker/import_mail`, [#12](https://github.com/SoerenKaiser99/parcel_tracker/issues/12)), Amazon „Versuchte Zustellung“ ([#17](https://github.com/SoerenKaiser99/parcel_tracker/issues/17)) und ein besser umbrechender Verlauf auf der Karte ([#16](https://github.com/SoerenKaiser99/parcel_tracker/issues/16)).

### v0.3.24 (2026-10-10)

- Neuer Schalter „Namen ausblenden“ für Geschenke auf dem Familien-Dashboard: Pakete heißen nur noch nach dem Paketdienst, z. B. „DHL-Paket …0012“. Ein selbst vergebener Name bleibt sichtbar.

### v0.3.23 (2026-10-08)

- Von @benep: Knopf „Bestellung“ für Amazon und eBay ([#13](https://github.com/SoerenKaiser99/parcel_tracker/issues/13)), Amazon-Mails mit mehreren Bestellungen bekommen je Bestellung Artikel und Liefertag ([#14](https://github.com/SoerenKaiser99/parcel_tracker/issues/14)).
- DHL „Sendungs-Update“ setzt den neuen Zustelltag, auch bei einem Paket in Zustellung ([Issue #11](https://github.com/SoerenKaiser99/parcel_tracker/issues/11)).

### v0.3.22 (2026-10-08)

- DHL „liegt am gewünschten Ablageort“ gilt als zugestellt ([Issue #9](https://github.com/SoerenKaiser99/parcel_tracker/issues/9)).
- `sendungsupdate@dhl.de` steht bei den DHL-Absendern ([Issue #11](https://github.com/SoerenKaiser99/parcel_tracker/issues/11)).

### v0.3.21 (2026-10-07)

- GLS: Eine 12-stellige Nummer mit „Automatisch“ wird einmal bei GLS angefragt (mit DHL-Key zuerst bei DHL). Nur eine echte GLS-Nummer liefert einen Treffer.
- Datenschutz-Hinweis: Wer das nicht möchte, wählt den Paketdienst beim Eintragen aus.

### v0.3.20 (2026-10-07)

- Bestellungen ohne Zustellmail bleiben nicht mehr ewig auf „Versendet“: Doppel werden nach der Zustellung zusammengeführt, überfällige Bestellungen werden „Abgeschlossen (ohne Zustellbestätigung)“, ohne Push-Meldung.
- Das Event hat das neue Feld `assumed`, und es gibt das Attribut `assumed_delivered`.

### v0.3.19 (2026-10-07)

- GLS: Echte Pakete wurden als „nicht gefunden“ behandelt, wenn nur mit der Paketnummer gefragt wurde ([Issue #8](https://github.com/SoerenKaiser99/parcel_tracker/issues/8)).
- Die 12-stellige GLS-Nummer funktioniert, wenn „GLS“ gewählt ist, und beim Import von GLS-Mails.

### v0.3.18 (2026-10-06)

- Neuer Sensor `sensor.pakete_abholbereit` und die Attribute `awaiting_pickup` und `awaiting_pickup_count` ([Issue #7](https://github.com/SoerenKaiser99/parcel_tracker/issues/7)).
- DPD „Bald ist Ihr DPD Paket da“ liefert den Versender als Namen und die Schätzung in Werktagen ([Issue #6](https://github.com/SoerenKaiser99/parcel_tracker/issues/6)).

### v0.3.17 (2026-10-05)

- Das Zeitfenster von DHL („heute 14–16 Uhr“) wird gelesen, und der Liefertag auch, wenn DHL nur ein Datum nennt.
- „Automatisch“ fragt eine unbekannte Nummer mit hinterlegtem DHL-Key einmal bei DHL nach.

### v0.3.16 (2026-10-05)

- Von Hand weitergeleitete Mails werden so ausgewertet, als kämen sie direkt vom Paketdienst oder Shop (Outlook, Apple Mail, Gmail, Thunderbird, „Als Anhang weiterleiten“). Der eigene Text darüber wird nie gelesen.

### v0.3.15 (2026-10-05)

- Entstanden aus den ersten anonymisierten Beispielmails von Testern.
- DHL: alle Absender der Domain `dhl.de`, der Name aus dem Betreff „Ihre … Sendung“, 12-stellige und internationale Nummern, „kommt heute“ als „In Zustellung“.
- GLS-Mails von `noreply@gls-group.eu` und `noreply@gls-rtt.com` sowie DPD-Austria-Mails werden gelesen.
- Aus Absenderangaben wird nur noch der Firmenname übernommen, nie ein Personenname.

### v0.3.14 (2026-10-04)

- Beim Hinzufügen eines DHL-Pakets ohne Key oder eines UPS-Pakets ohne Zugangsdaten steht sofort ein Hinweis unter der Eingabe, was hilft.
- Neue Übersichtstabelle „Was brauche ich für welchen Dienst?“.

### v0.3.13 (2026-10-04)

- Neue Einstellung „Land“ (Deutschland, Österreich, Schweiz) mit passender Postleitzahl. GLS fragt bei Österreich die österreichische Variante ab.

### v0.3.12 (2026-10-03)

- Ein fehlender DHL-Key ist keine Dauerwarnung mehr. Die Karte sagt „Kein Live-Status“, wenn ein Paket gar nicht abgefragt werden kann.
- Ein kleiner Pfeil zeigt, dass sich eine Paketzeile aufklappen lässt.

### v0.3.11 (2026-10-03)

- Neue Sensoren `sensor.pakete_unterwegs`, `sensor.pakete_moeglich` und `sensor.pakete_zugestellt_heute`.
- Neue Kartenoption `show` (`always`, `active`, `today`, `today_possible`), mit der sich die Karte selbst ausblendet.

### v0.3.10 (2026-10-02)

- Drei Schilder auf der Karte: „N heute“, „N möglich“, „N zugestellt“.
- Die Statusangaben auf der Karte sind immer deutsch.

### v0.3.9 (2026-10-02)

- Die Eingabe steckt hinter einem Plus-Knopf. Neue Kartenoption `add_form` (`button`, `always`, `never`).
- Nach einem Update zeigt eine alte Karte „Neue Version installiert – Seite neu laden“.

### v0.3.8 (2026-10-02)

- Eine wartende Benachrichtigung geht nach einem Neuladen oder Neustart nicht mehr verloren.

### v0.3.7 (2026-10-02)

- „Pakete heute“ zählt nur noch, was sicher heute kommt. Pakete mit einer Lieferspanne, die heute einschließt, stehen als „möglich“ in `possible`.
- Benachrichtigungen gehen auch an klassische Dienste wie Pushover.

### v0.3.6 (2026-10-01)

- Behoben: „Custom element doesn't exist: parcel-tracker-card“ nach der Installation. Die Karte wird nur noch als Dashboard-Ressource geladen.
- Dashboards im YAML-Modus bekommen einen Hinweis unter „Reparaturen“.

### v0.3.5 (2026-10-01)

- Neu: Benachrichtigungen bei „in Zustellung“, „zugestellt“, „abholbereit“ und Problem, mit Blueprint für eigene Texte.
- Statuswechsel während eines Neustarts gehen nicht mehr verloren, und das Event enthält `carrier_name`.

### v0.3.4 (2026-10-01)

- Wichtiger Fehler behoben: Wer unter „Konfigurieren“ speicherte, verlor dabei den E-Mail-Import und teils die UPS-Zugangsdaten. Ein unberührtes Formular löscht nichts mehr.
- Wer seit v0.3.0 gespeichert hat, trägt Postfach-Benutzer und Passwort einmal neu ein.

### v0.3.3 (2026-10-01)

- Diagnose-Download ohne Zugangsdaten, Namen und Mail-Inhalte.
- Das Skript `anonymize_mail.py` zum sicheren Einreichen von Beispielmails und Issue-Vorlagen.
- README mit Bildern, Abschnitt „Warum?“ und Demo-Seite.

### v0.3.2 (2026-10-01)

- Neu: GLS mit Live-Status (höchstens alle 30 Minuten) und GLS-Mails von `no-reply@gls-pakete.de`.
- Neuer Absender für die Filterregel: `no-reply@gls-pakete.de`.

### v0.3.1 (2026-10-01)

- 17track als optionale Ergänzung: „Details über 17track holen“ auf der Karte, die Auswahl „Andere (über 17track)“, der Sensor `sensor.paket_tracker_17track_kontingent` und der Dienst `parcel_tracker.track_17track`.
- Angemeldet wird nur auf ausdrücklichen Wunsch, jede Anmeldung verbraucht eine Nummer des Kontingents.

### v0.3.0 (2026-09-30)

- Neu: Hermes (Live-Status ohne Zugangsdaten), UPS (Mails und optional die offizielle API) und eBay-Bestellungen aus Mails.
- Amazon- und eBay-Bestellungen werden mit Hermes-, DHL- und UPS-Ankündigungen zusammengeführt, wenn das eindeutig ist.

### v0.2.2 (2026-09-30)

- Das Abruf-Intervall für das Postfach ist einstellbar (1–60 Minuten, Standard 5), und „Aktualisieren“ fragt das Postfach sofort ab.

### v0.2.1 (2026-09-30)

- Amazon-Liefertermine als Zeitraum und als einzelne Tage werden erkannt. Das DHL-Logo ist besser sichtbar.

### v0.2.0 (2026-09-30)

- Neu: E-Mail-Import. Ein eigenes Paket-Postfach wird per IMAP gelesen, Amazon, DHL und UPS legen Pakete von selbst an.
- Amazon-Paket und DHL-Mail werden zusammengeführt, danach gibt es den Live-Status über die DHL-API.
- Optional: der Zustell-Code auf der Karte, verdeckt und nie gespeichert.

### v0.1.5 (2026-09-30)

- Die Karte wird nach `www/parcel_tracker` kopiert und über `/local` ausgeliefert. Kein „Konfigurationsfehler“ mehr, wenn Geräte während eines Neustarts laden.

### v0.1.4 (2026-09-30)

- Die Karten-Ressource wird sofort beim Laden der Integration angemeldet.

### v0.1.3 (2026-09-30)

- Die Karten-Ressource wird zuverlässig nach dem Start von Home Assistant angemeldet.

### v0.1.2 (2026-09-30)

- Die Karte meldet sich zusätzlich als Dashboard-Ressource an. Das behebt den gelegentlichen „Konfigurationsfehler“ nach Updates.
- DHL: Status über die offiziellen Kurzcodes, Orte ohne „, Deutschland“.

### v0.1.1 (2026-09-29)

- Karte: Fehlermeldungen nur einmal und auf Deutsch, Umbenennen und Löschen direkt in der Zeile statt in Browser-Dialogen.

### v0.1.0 (2026-09-29)

- Erste Version: DHL und DPD, Dashboard-Karte, ein Sensor pro Paket, `sensor.pakete_heute`, `calendar.pakete` und das Event `parcel_tracker_status_changed`.

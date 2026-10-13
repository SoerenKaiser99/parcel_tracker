# E-Mail-Import

Mit dem E-Mail-Import tauchen Pakete von selbst auf. Die Integration liest die Versandmails aus einem Postfach und legt die Pakete an: Bestellt, Versendet, In Zustellung, Zugestellt – samt Liefertag und Zeitfenster.

Für Amazon ist das der einzige Weg: Amazon liefert viele Pakete selbst aus und bietet dafür keine öffentliche Sendungsverfolgung.

!!! danger "Nur ein eigenes Paket-Postfach eintragen, nie das Hauptpostfach"
    Das IMAP-Passwort gibt Vollzugriff auf das Postfach. Leg bei deinem Mailanbieter ein zusätzliches Postfach an (z. B. `pakete@…`), das ausschließlich Paketmails bekommt, und trag nur dieses ein.

## So hängt es zusammen

1. Paketmails kommen wie immer in deinem Hauptpostfach an.
2. Eine Filterregel im Hauptpostfach schickt eine Kopie an das Paket-Postfach.
3. Die Integration liest nur das Paket-Postfach, und darin nur einen Ordner: den Posteingang oder den [Ordner, den du einträgst](#eigener-ordner).

Dein Hauptpostfach sieht die Integration so nie.

## Einrichten

1. Paket-Postfach anlegen (z. B. bei mailbox.org).
2. Im Hauptpostfach eine [Filterregel anlegen](#filterregel-anlegen), die Paketmails an das Paket-Postfach weiterleitet.
3. In Home Assistant **Einstellungen → Geräte & Dienste → Paket Tracker → Konfigurieren → E-Mail-Import** öffnen und ausfüllen:

    | Feld | Bedeutung |
    |---|---|
    | **E-Mail-Import aktiv** | Schaltet den Import ein. |
    | **IMAP-Server** | Standard `imap.mailbox.org`. |
    | **Port** | Standard `993`. Üblich sind 993 (verschlüsselt) und 143 (unverschlüsselt). Bei einem Mailanbieter bleibt 993 stehen. |
    | **Verbindung** | Standard „Verschlüsselt (TLS, Standard)“ – das passt für jeden Mailanbieter. Die beiden anderen sind für einen eigenen Server im Heimnetz, siehe [Port und Verbindung](#port-und-verbindung). |
    | **Benutzername** und **Passwort** | Die des Paket-Postfachs. Leere Felder behalten die gespeicherten Werte. |
    | **Ordner** | Standard `INBOX` (der Posteingang). Der eine Ordner, den der Import liest. Für das eigene Paket-Postfach bleibt `INBOX` stehen. Ein leeres Feld behält den gespeicherten Ordner. Siehe [Eigener Ordner](#eigener-ordner). |
    | **Verarbeitete Mails in Ordner verschieben** | Standard: an. |
    | **Zustell-Codes (Einmalpasswörter) mitlesen** | Standard: aus. Siehe [Zustell-Code](datenschutz.md#zustell-codes). |
    | **Postfach abfragen alle (Minuten)** | 1–60, Standard: 5. |

4. Speichern. Die Anmeldung wird sofort geprüft, ein geänderter Ordner dabei einmal geöffnet. Auch ein geänderter Port oder eine andere Verbindung wird erst gespeichert, wenn die Anmeldung damit klappt.

Ausschalten geht nur über den Schalter **E-Mail-Import aktiv**: Ausgeschaltet gespeichert, entfernt er Benutzername und Passwort.

### Port und Verbindung

Bei einem Mailanbieter im Internet musst du hier nichts ändern: Port 993 und „Verschlüsselt (TLS, Standard)“. Die beiden Felder gibt es für einen Mailserver, den du selbst im Heimnetz betreibst.

| Verbindung | Was passiert | Üblicher Port |
|---|---|---|
| **Verschlüsselt (TLS, Standard)** | Verschlüsselt, und das Zertifikat des Servers wird geprüft. | 993 |
| **Verschlüsselt, Zertifikat nicht prüfen** | Verschlüsselt, aber ohne Prüfung des Zertifikats. Für einen eigenen Server mit selbstsigniertem Zertifikat. | 993 |
| **Unverschlüsselt** | Ohne Verschlüsselung. Nur, wenn der Server gar kein TLS anbietet. | 143 |

- Der Port ändert sich nicht von selbst, wenn du eine andere Verbindung wählst. Steht nach dem Wechsel auf „Unverschlüsselt“ noch 993 im Feld, trag den Port deines Servers ein (meist 143).
- STARTTLS (erst unverschlüsselt verbinden, dann auf TLS umschalten) wird nicht versucht. Die Verbindung ist entweder von Anfang an verschlüsselt oder gar nicht.
- Meldet das Formular „Der Mailserver nimmt ohne Verschlüsselung keine Anmeldung an.“, lehnt der Server Anmeldungen über eine unverschlüsselte Verbindung ab (dovecot macht das von Haus aus). Das Passwort wurde dann gar nicht erst gesendet. Wähl „Verschlüsselt, Zertifikat nicht prüfen“ (meist Port 993) oder erlaub die Klartext-Anmeldung am Server.
- Meldet das Formular „Das Zertifikat des Mailservers wurde nicht akzeptiert.“, ist das Zertifikat selbstsigniert, abgelaufen oder auf einen anderen Namen ausgestellt. Bei einem eigenen Server im Heimnetz wählst du „Verschlüsselt, Zertifikat nicht prüfen“. Bei einem Mailanbieter stimmt meist der Servername nicht.

!!! warning "Nur im eigenen Netz"
    „Verschlüsselt, Zertifikat nicht prüfen“ und „Unverschlüsselt“ sind nur für einen Mailserver im eigenen Netz gedacht. Bei einem Anbieter im Internet könnte jemand unterwegs das Passwort mitlesen oder sich als der Server ausgeben. Sieht der eingetragene Server nicht nach einem im eigenen Netz aus (keine private Adresse, kein Name wie `nas`, `mail.fritz.box`, `mail.lan` oder ein Tailscale-Name auf `.ts.net`), erscheint unter **Einstellungen → Reparaturen** ein Hinweis. Steht der Server doch bei dir zu Hause, kannst du ihn ignorieren.

### Eigener Ordner

Gelesen wird genau ein Ordner des Postfachs, von Haus aus der Posteingang (`INBOX`). Mit dem Feld **Ordner** liest der Import stattdessen einen anderen.

- Schreib den Ordner so, wie der Mailserver ihn führt: `Pakete`, `Bestellungen & Pakete`, einen Unterordner als `Pakete/DHL`, bei manchen Anbietern als `INBOX.Pakete`. Umlaute und Leerzeichen sind erlaubt.
- Alle anderen Ordner fasst der Import nicht an.
- Gibt es den Ordner nicht, meldet das Formular „Diesen Ordner gibt es im Postfach nicht.“ und speichert nichts. Angelegt wird der Ordner nie.
- Die beiden Ablage-Ordner `Paket-Tracker-Verarbeitet` und `Paket-Tracker-Nicht-erkannt` lassen sich nicht als Ordner zum Lesen eintragen.

!!! warning "Ordner im Hauptpostfach"
    Es geht auch mit einem Ordner deines Hauptpostfachs, in den eine Filterregel die Paketmails verschiebt. Dann kennt Home Assistant aber das Passwort des ganzen Postfachs. Sicherer bleibt das eigene Paket-Postfach.

### App-Passwörter

Lehnt der Mailserver die Anmeldung ab? Viele Anbieter verlangen für IMAP nicht das normale Passwort, sondern ein eigenes **App-Passwort** (auch „Anwendungspasswort“ genannt). Du erzeugst es in den Einstellungen des Mail-Kontos und trägst es hier als Passwort ein.

- **mailbox.org:** je nach Kontoeinstellung (z. B. mit Zwei-Faktor-Anmeldung) ein Anwendungspasswort für IMAP anlegen.
- **Gmail** und **iCloud:** immer ein App-Passwort. Das normale Passwort funktioniert für IMAP nicht.
- **GMX** und **web.de:** den Zugriff per IMAP in den Einstellungen des Postfachs erst erlauben.

### Wie oft wird das Postfach gelesen?

- Im eingestellten Intervall (1–60 Minuten, Standard 5) schaut der Import nach ungelesenen Mails im eingestellten Ordner (Standard: Posteingang).
- Der Dienst `parcel_tracker.refresh` (auf der Karte „Aktualisieren“) fragt zusätzlich das Postfach sofort ab.
- Ist das Postfach nicht erreichbar, wartet der Import unabhängig vom Intervall länger (5 → 10 → 20 → 40 → 60 Minuten).
- Lehnt der Server die Anmeldung ab, erscheint unter **Einstellungen → Reparaturen** ein Hinweis.
- Wird das Zertifikat des Servers später nicht mehr akzeptiert (abgelaufen, ausgetauscht), pausiert der Import genauso und schreibt einmal eine Warnung ins Protokoll von Home Assistant.
- Gibt es den eingestellten Ordner später nicht mehr (umbenannt oder gelöscht), pausiert der Import genauso und schreibt einmal eine Warnung ins Protokoll von Home Assistant, ohne den Namen des Ordners. Trag dann unter **Konfigurieren** den richtigen Ordner ein.

## Filterregel anlegen

Nimm diese Absender in die Filterregel auf:

| Absender | Dienst |
|---|---|
| `bestellbestaetigung@amazon.de` | Amazon |
| `versandbestaetigung@amazon.de` | Amazon |
| `shipment-tracking@amazon.de` | Amazon |
| `order-update@amazon.de` | Amazon |
| `noreply@dhl.de` | DHL |
| `paketankuendigung@dhl.de` | DHL |
| `zustellung@dhl.de` | DHL |
| `sendungsupdate@dhl.de` | DHL (meldet einen verschobenen Zustelltag; der neue Tag wird übernommen) |
| `noreply@service.dpd.de` | DPD |
| `no_reply@dpd.at` | DPD Österreich |
| `pkginfo@ups.com` | UPS |
| `noreply@paketankuendigung.myhermes.de` | Hermes |
| `ebay@ebay.com` | eBay |
| `transaction@notice.aliexpress.com` | AliExpress |
| `bestellstatus@eventim.de` | Eventim (Bestellbestätigung und Versandbenachrichtigung; nur Tickets mit Postversand) |
| `no-reply@gls-pakete.de` | GLS |
| `noreply@gls-group.eu` und `noreply@gls-rtt.com` | GLS Österreich |

!!! tip "DHL: am einfachsten die ganze Domain"
    DHL schreibt von mehreren Adressen. Am einfachsten ist eine Regel auf die ganze Domain `dhl.de`, wenn dein Mail-Anbieter das kann: Der Import liest jeden Absender unter `dhl.de`.

### Beispiel als Sieve-Regel

Bei mailbox.org unter Einstellungen → Filter → Sieve. Die Regel schickt eine Kopie ins Paket-Postfach:

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
  "bestellstatus@eventim.de",
  "no-reply@gls-pakete.de"
] {
  redirect :copy "pakete@example.org";
}
```

Ersetz `pakete@example.org` durch die Adresse deines Paket-Postfachs.

In Outlook & Co. heißt das „Regel“ oder „Filter“: Bedingung „Absender ist …“, Aktion „Weiterleiten an pakete@…“.

### Beispiel für Gmail

Gmail leitet nur an Adressen weiter, die du vorher bestätigt hast. Deshalb sind es zwei Schritte.

**1. Das Paket-Postfach als Weiterleitungsadresse eintragen**

1. Gmail im Browser öffnen → Zahnrad → **Alle Einstellungen aufrufen** → Reiter **Weiterleitung und POP/IMAP**.
2. **Weiterleitungsadresse hinzufügen** und die Adresse deines Paket-Postfachs eintragen.
3. Gmail schickt einen Bestätigungslink an das Paket-Postfach. Dort öffnen und bestätigen.

**2. Den Filter anlegen**

1. In den Einstellungen den Reiter **Filter und blockierte Adressen** öffnen → **Neuen Filter erstellen**.
2. In das Feld **Von** alle Absender eintragen. Gmail trennt sie mit `OR`:

    ```text
    bestellbestaetigung@amazon.de OR versandbestaetigung@amazon.de OR shipment-tracking@amazon.de OR order-update@amazon.de OR noreply@dhl.de OR paketankuendigung@dhl.de OR zustellung@dhl.de OR sendungsupdate@dhl.de OR noreply@service.dpd.de OR pkginfo@ups.com OR noreply@paketankuendigung.myhermes.de OR ebay@ebay.com OR no_reply@dpd.at OR noreply@gls-group.eu OR noreply@gls-rtt.com OR transaction@notice.aliexpress.com OR bestellstatus@eventim.de OR no-reply@gls-pakete.de
    ```

3. **Filter erstellen** anklicken, dann den Haken bei **Weiterleiten an** setzen und dein Paket-Postfach auswählen.
4. Mit **Filter erstellen** abschließen.

Die Mails bleiben dabei in deinem Gmail-Posteingang, das Paket-Postfach bekommt eine Kopie.

!!! note "Von einem Nutzer beigesteuert"
    Diese Anleitung stammt aus [Issue #22](https://github.com/SoerenKaiser99/parcel_tracker/issues/22). Die Menünamen können sich bei Google ändern. Stimmt ein Schritt nicht mehr, gern dort melden.

### Apple „E-Mail-Adresse verbergen“

Hast du dich bei einem Shop mit einer verborgenen Adresse angemeldet, kommen dessen Mails über Apples Relay. Als Absender steht dann z. B. `transaction_at_notice_aliexpress_com_…@privaterelay.appleid.com`.

- Der Import erkennt solche Mails wie die des ursprünglichen Absenders, bei allen Shops und Paketdiensten aus der Liste oben.
- In der Filterregel brauchst du dafür die Relay-Adresse, so wie sie in der Mail steht (sie ist bei jedem anders), oder eine Regel auf den Betreff.

## Von Hand weiterleiten

Statt einer Filterregel kannst du einzelne Mails auch von Hand an das Paket-Postfach weiterleiten.

Der Import erkennt eine Weiterleitung wie die Original-Mail, wenn im weitergeleiteten Block der ursprüngliche Absender steht – also die Kopfzeilen „Von: … / Gesendet: … / An: … / Betreff: …“ über dem Mailtext.

- Alle gängigen Mailprogramme setzen diesen Block von selbst (Outlook, Apple Mail, Gmail, Thunderbird; deutsch und englisch). Lass ihn beim Weiterleiten einfach stehen.
- Auch „Als Anhang weiterleiten“ funktioniert.
- Kennt der Import den ursprünglichen Absender, liest er die Mail so, als wäre sie direkt gekommen: mit Status, Zustelltag und Namen.
- „Heute“ und „morgen“ rechnet er ab dem Datum der Original-Mail, das im Block steht. Lässt sich dieses Datum nicht sicher lesen, zählt der Zeitpunkt der Weiterleitung.
- Was du selbst über den Block schreibst (ein Gruß, deine Signatur), liest er nie mit. Dein eigener Name wird nie zum Paketnamen.

Am zuverlässigsten bleibt die automatische Filterregel: Sie leitet die Mail unverändert um.

??? note "Wenn der Block fehlt oder der Absender unbekannt ist"
    - Amazon- und GLS-Mails erkennt der Import am Betreff (mit „WG:“ oder „Fwd:“), ohne den Versender einer GLS-Mail als Namen zu übernehmen. „Heute“ und „morgen“ rechnet er ab dem Zeitpunkt der Weiterleitung.
    - Aus allen anderen Mails übernimmt er nur eindeutige Sendungsnummern: DHL `00340…` und `JJD…`, UPS `1Z…`, Hermes `H…`. DPD-Nummern nur, wenn „DPD“ in der Mail steht und die Nummer direkt nach „Paketnummer“, „Sendungsnummer“ o. Ä. folgt, oder die Mail direkt von DPD kommt.
    - Solche Pakete tragen keinen Namen aus dem Absender, sondern heißen `<Carrier> <Nummer>`. Umbenennen geht auf der Karte.

Mails, die älter als 14 Tage sind, markiert der Import nur als gelesen.

## Was mit den Mails im Postfach passiert

- Erkannte Mails landen im Ordner `Paket-Tracker-Verarbeitet`, nicht erkannte im Ordner `Paket-Tracker-Nicht-erkannt`. Beide Ordner legt der Import bei Bedarf an.
- Mit ausgeschalteter Option „Verarbeitete Mails in Ordner verschieben“ bleiben die Mails im gelesenen Ordner und werden nur als gelesen markiert.
- Die beiden Ordner liegen immer auf der obersten Ebene des Postfachs, auch wenn ein eigener Ordner gelesen wird.
- Werbung und Konto-Mails von Amazon (`promotion…@amazon.de`, `no-reply@amazon.de`, `account-update@amazon.de`, `rueckgabe@amazon.de`, `no-reply@primevideo.com`) markiert der Import nur als gelesen, ebenso die Angebote von AliExpress (`…@deals.aliexpress.com`) und alle Mails von Eventim, die keine Bestellung mit Postversand sind (Newsletter, Ticketalarm, Kundenservice, die Ticketshops der Vereine).
- Jede Mail zählt nur einmal (erkannt an ihrer Message-ID).
- Erkennt der Import fünf Amazon-Mails in Folge nicht, erscheint ein Reparatur-Hinweis. Meist hat Amazon dann das Mail-Format geändert.

## Was aus welcher Mail wird

=== "Amazon"

    - Pro Bestellung entsteht ein Paket mit der Nummer `AMZ` + Bestellnummer, benannt nach dem Artikel. Kommt eine Bestellung in mehreren Sendungen, heißt das nächste Paket „… (2)“.
    - Der Status geht nur vorwärts: Eine ältere Mail setzt ein Paket nie zurück.
    - Eine Ausnahme ist die Mail „Versuchte Zustellung“ (niemand wurde angetroffen): Sie nimmt eine Bestellung von „In Zustellung“ zurück auf „Versendet“, mit dem Text „Zustellung versucht“ und ohne Liefertag. Die Bestellung zählt dann nicht mehr als heute. Was schon zugestellt oder abholbereit ist, bleibt, wie es ist.
    - Gelesen werden auch die Mails im schlichten Layout mit „Bestellung #…“: „Ihr Paket mit … wird zugestellt“ (der Betreff nennt dort nur den Artikel) setzt „In Zustellung“, „Lieferungsaktualisierung: …“ lässt die Bestellung auf „Versendet“ und übernimmt den neuen Tag aus „Jetzt erwartet bis zum …“; nennt die Mail eine Verspätung, steht dazu der Text „Lieferung verspätet“. Die Betreffs „Unterwegs zur Zustellung: …“ und „Zur Auslieferung: …“ zählen wie „In Zustellung“, „Zustellversuch: …“ wie „Versuchte Zustellung“. Die Versandmail „Deine Amazon.de-Bestellung mit … wurde versandt!“ setzt „Versendet“ samt Liefertag; nennt sie eine DHL-, UPS- oder Hermes-Nummer, übernimmt die Bestellung sie und wird ab dann dort abgefragt.
    - Kündigt DHL eine „Amazon Sendung“ an und passt genau ein offenes Amazon-Paket dazu (gleicher Liefertag), übernimmt das Amazon-Paket die DHL-Nummer und fragt ab dann DHL ab. Ist die Zuordnung nicht eindeutig, entsteht ein eigenes Paket „Amazon-Sendung (DHL)“.

=== "eBay"

    - Pro eBay-Bestellung entsteht ein Paket mit der Nummer `EBAY` + Bestellnummer, benannt nach dem Artikel.
    - Nur die Mails „Update zur Bestellung“ und „Zustellversuch“ nennen eine Sendungsnummer. Die 12-stelligen Artikelnummern werden nie als Sendungsnummer gelesen.
    - „Ihre Sendung ist jetzt beim Versanddienstleister!“ setzt „Versendet“ samt Lieferzeitraum („Lieferung ca.: Mi, 28. Jan - Do, 29. Jan“), „BESTELLUNG ZUGESTELLT“ setzt „Zugestellt“. „Update zur Bestellung“ setzt „Versendet“ samt Lieferzeitraum und übernimmt die Sendungsnummer, wenn sie ihren Paketdienst selbst verrät (DHL `00340…` oder `JJD…`, UPS, Hermes `H…`): Die Bestellung wird dann live beim Paketdienst abgefragt. Eine Nummer aus 12 oder 14 Ziffern kann zu mehreren Paketdiensten gehören und bleibt unberührt. „Zustellversuch: …“ (niemand wurde angetroffen) nimmt die Bestellung zurück auf „Versendet“, mit dem Text „Zustellung versucht“ und ohne Liefertag (ein späterer Tag, den der Paketdienst schon genannt hat, bleibt) und übernimmt die Sendungsnummer wie „Update zur Bestellung“. Andere eBay-Mails landen in „Nicht erkannt“.
    - Nennt die Mail den Versanddienstleister, zeigt die Karte ihn an („eBay · Versendet · via Hermes“, Attribut `shipping_carrier_hint`).

=== "AliExpress"

    - Pro AliExpress-Bestellung entsteht ein Paket mit der Nummer `ALI` + Bestellnummer (z. B. `sensor.paket_ali9999999999990000`), benannt nach dem Artikel. Den Namen des Händlers übernimmt die Integration nie.
    - Eine Bestellung bleibt ein Paket, auch wenn AliExpress sie in mehreren Sendungen verschickt. Eine Mail über mehrere Bestellungen („2 Bestellungen wurden bestätigt“) legt jede Bestellung an.
    - Den Schritt liest der Import aus dem Betreff. „Bestellauftrag bestätigt“, „Bestellbestätigung“ und „versandfertig“ setzen „Bestellt“. „Bestellung versandt“, „teilweise versandt“, „Vom Kurier abgeholt“, „Paket im Transit“, „In Ihrem Land / Ihrer Region angekommen“, „Neuer Lieferstatus“ und „Wird zugestellt“ setzen „Versendet“. Im Verlauf steht dazu der Schritt, den AliExpress nennt, z. B. „Im Zielland angekommen“.
    - „Wird zugestellt“ heißt bei AliExpress nur, dass das Paket dem Versandunternehmen übergeben wurde. Es zählt deshalb nicht als heute, was auch immer im Text der Mail steht.
    - Nennt die Mail eine „Voraussichtliche Zustellzeit“, wird sie der Liefertag.
    - Die „Packstück“-Mails („Packstück … hat die Abflugregion verlassen“, „Packstück …: Vom Kurier abgeholt“, „Packstück …: In Ihrem Land / Ihrer Region“, „Packstück … hat eine Aktualisierung“) und „Zollabfertigung für … wurde beendet“ nennen die Sendungsnummer des Paketdienstes. „Hat eine Aktualisierung“ nennt keinen Schritt: Der Text im Verlauf bleibt, wie er war. Ist es eine DHL- oder Hermes-Nummer, übernimmt die Bestellung sie und wird ab dann live abgefragt (DHL mit API-Key). Es entsteht kein zweites Paket. Eine Nummer in einem anderen Format (z. B. `AP…`) lässt sich bei keinem Paketdienst abfragen: Dann zählt nur der Schritt aus der Mail.
    - Zu welcher Bestellung ein Packstück gehört, steht nur in den Links der Mail (sie werden gelesen, nie aufgerufen; es zählen nur Links zu aliexpress.com). Fehlen sie – etwa in einer von Hand weitergeleiteten Mail –, gilt dasselbe wie bei einer Carrier-Mail: Passt genau eine offene AliExpress-Bestellung, übernimmt sie die Nummer, sonst entsteht ein eigenes Paket „AliExpress-Sendung“ (siehe [Zusammenführen](#zusammenfuhren-carrier-mail-und-bestellung)).
    - Liegen mehrere Bestellungen im selben Paket, bekommt jede die Nummer. Der Paketdienst wird für dieses Paket nur einmal gefragt, es gibt eine Benachrichtigung für das Paket (sie nennt die erste Bestellung), und bei `sensor.pakete_heute`, `sensor.pakete_moeglich` und `sensor.pakete_zugestellt_heute` zählt es einmal. Das Event `parcel_tracker_status_changed` feuert für jede Bestellung.
    - Nennt eine spätere Mail zu einer Bestellung eine zweite, andere Nummer, entsteht dafür ein eigenes Paket „AliExpress-Sendung“.
    - Steht die Nummer schon als eigenes Paket in der Liste? Ist es aus einer Mail entstanden, geht es in der Bestellung auf. Hast du es von Hand eingetragen oder als erhalten markiert, bleibt es, und die Bestellung übernimmt die Nummer nicht.
    - Gelesen werden auch „Packstück …: mit lokalem Kurier“ und „Packstück …: im Zielland / in der Zielregion“ (beide „Versendet“ mit dem Schritt als Text) und „Bestellung …: zugestellt“ („Zugestellt“). Aus den Mails vom Herbst 2024 kennt der Import außerdem „verzollt“, „im Lieferzentrum“ und „Zur Auslieferung bereit“ (alle „Versendet“). Mails ohne Neuigkeit zu einem Paket (Lieferneuigkeiten ohne Nummer, Coupon nach einer Verspätung, Rücksendung und Rückerstattung) werden nur als gelesen markiert.
    - „wie ist es gelaufen?“ mit dem Satz „Wir haben die Lieferung Ihrer Bestellung … bestätigt“ (mit der Bestellnummer aus dem Betreff) schließt die Bestellung mit dem Text „Lieferung bestätigt (laut AliExpress)“ – so wie eine [Bestellung ohne Zustellmail](#bestellungen-ohne-zustellmail): `assumed_delivered` ist `true`, keine Benachrichtigung, nicht „heute zugestellt“. Die Mail kommt oft erst Tage später und beweist keine Ankunft, sie fragt selbst, ob der Artikel schon da ist. Hat der Paketdienst die Zustellung schon gemeldet, ändert die Mail nichts: Dessen Zeitpunkt bleibt stehen. Dasselbe gilt, solange die Bestellung bei ihm abgefragt wird und sich dort in den letzten 3 Tagen etwas getan hat; steht sie länger unverändert, schließt die Mail sie.
    - Nur als gelesen markiert werden die Aufforderung zur Bewertung („Wie war Ihr Einkaufserlebnis?“), die Erinnerung „auf Bestätigung wird gewartet“ und „Your order … is closed“ (die Mail sagt nicht, ob die Bestellung abgeschlossen oder storniert wurde). Andere AliExpress-Mails landen in „Nicht erkannt“.
    - Bestellungen ohne Sendungsnummer, für die keine Bestätigung kommt, schließt die Integration von selbst: 3 Tage nach dem letzten Liefertag, ohne Liefertag nach 14 Tagen (siehe [Bestellungen ohne Zustellmail](#bestellungen-ohne-zustellmail)).

    Die AliExpress-Mails sind nach Beispielmails umgesetzt und im Alltag noch nicht bestätigt, siehe [Roadmap & Status](stand.md).

=== "Eventim"

    Eventim-Tickets, die per Post kommen, tauchen wie ein Paket in der Liste auf.

    - Gelesen werden nur die beiden Mails von `bestellstatus@eventim.de`: die Bestellbestätigung („Deine EVENTIM-Bestellung: … - Bestellnummer …“) und die Versandbenachrichtigung („eventim.de - Versandbenachrichtigung - Deine Bestellung Nr. …“).
    - Pro Bestellung entsteht ein Eintrag mit der Nummer `EVT` + Bestellnummer (z. B. `sensor.paket_evt999999901`), benannt nach der Veranstaltung. Bei mehreren Veranstaltungen in einer Bestellung steht „… und 1 mehr“ dahinter. Eine Bestellung bleibt ein Eintrag, auch wenn die Tickets in zwei Briefen kommen.
    - **Nur Postversand.** Eine Bestellung entsteht nur, wenn hinter „Liefermethode:“ ein Versand per Post steht (z. B. „Standardversand (Deutschland)“, Einschreiben, Wertbrief, Express). Tickets zum Selbstausdrucken oder fürs Handy (ticketdirect, print@home, Mobile Ticket) landen nie im Briefkasten, ebenso wenig ein Versand per E-Mail, ein Download, ein PDF oder eine Abholung oder Hinterlegung an der Abendkasse: Solche Bestellmails markiert der Import nur als gelesen.
    - Die Bestellbestätigung setzt „Bestellt“, ohne Liefertag. Eventim verschickt Tickets oft erst Wochen oder Monate nach der Bestellung.
    - Die Versandbenachrichtigung setzt „Versendet“ und rechnet den Lieferzeitraum aus „innerhalb von 2 bis 4 Werktagen“ ab dem Tag der Mail. Werktage sind Montag bis Samstag; Feiertage kennt der Import nicht.
    - **Keine Sendungsverfolgung.** Eventim nennt weder Paketdienst noch Sendungsnummer. Es gibt keine Abfrage, kein „Sendung verfolgen“ und keinen Knopf „Bestellung“ (die Mails nennen keine Bestellseite, die ohne Anmeldung funktioniert).
    - **So endet die Bestellung:** Eine „Zugestellt“-Mail gibt es nie. Tipp auf der Karte auf [„Erhalten“](karte.md#erhalten), wenn die Tickets da sind. Sonst schließt die Integration die Bestellung von selbst, 3 Tage nach dem letzten Tag des Lieferzeitraums (siehe [Bestellungen ohne Zustellmail](#bestellungen-ohne-zustellmail)).
    - Solange nur „Bestellt“ dasteht, schließt die Integration die Bestellung nie von selbst. Ändert sich 30 Tage lang nichts, verschwindet sie wie jedes Paket aus der Liste; die Versandbenachrichtigung legt sie dann wieder an.
    - Käufer, Adresse, Veranstaltungsort, Plätze und Preise liest der Import nicht; Links in den Mails werden nie aufgerufen.

    Die Eventim-Mails sind nach Beispielmails umgesetzt und im Alltag noch nicht bestätigt, siehe [Roadmap & Status](stand.md). Gesehen wurde bisher nur „Standardversand (Deutschland)“.

=== "DHL"

    - Den Status liest der Import nur aus dem Betreff, siehe die Tabelle unter [Kein Key? Dann die DHL-Mails](dienste.md#kein-key-dann-die-dhl-mails).
    - Neben den langen DHL-Nummern (`00340…`, `JJD…`, `CQ…DE`) liest er aus DHL-Mails auch Nummern mit 12 Ziffern – nur direkt nach „Ihre Sendungsnummer“ bzw. „Sendungsnummer“, weil 12 Ziffern allein auch eine eBay-Artikelnummer sein können. Mit DHL-Key fragt die Integration auch diese Nummern bei DHL ab.
    - Steht im Textteil der Mail keine Nummer (er ist leer oder nennt sie nur in einem Link), liest der Import den HTML-Teil: dort auch die Nummer direkt unter „Sendungsstatus einsehen“ bzw. „Sendungsverlauf einsehen“, mit 12 Ziffern oder als Nummer aus dem Ausland (z. B. `LR…NL`, `JJATA…`).
    - DHL-Mails nennen im Betreff den Shop („Ihre Beispiel GmbH Sendung ist unterwegs“). Er wird der Name des Pakets, wenn er ein bekannter Shop ist oder eine Rechtsform trägt (GmbH, AG, OHG …) – nie der Name einer Privatperson. Der Name endet an der Rechtsform; was dahinter steht (ein Kürzel, eine Ansprechperson), wird nicht übernommen.
    - Der Anzeigename eines Paketdienstes („DHL Paketankündigung“, „DHL Zustell-Update“) wird nie zum Namen: Ohne Shop heißt das Paket `DHL <Nummer>`. Nennt der Betreff eine Firma des Paketdienstes selbst („Ihre DHL Paket (Austria) GmbH c/o … Sendung“), gibt es ebenfalls keinen Namen.
    - Trägt ein Paket aus einer älteren Version noch so einen Namen, ersetzt ihn die nächste Mail, die einen Shop nennt – aber nur, wenn der Name aus einem Paketdienst (DHL, DPD, GLS, Hermes, UPS, Deutsche Post) und Wörtern einer Benachrichtigung besteht und sonst nichts enthält („DHL Paketankündigung“, „DHL Zustell-Update“, „DPD Versandinfo“, „DHL Paket“). Jeder andere Name bleibt, auch „Hermes“, „DHL Express“ oder „Paket“: Er kann selbst vergeben sein.
    - Eine „Amazon Sendung“ landet beim passenden Amazon-Paket, siehe [Zusammenführen](#zusammenfuhren-carrier-mail-und-bestellung).
    - Abholcodes liest der Import nie.

=== "DPD"

    - DPD Deutschland (`noreply@service.dpd.de`): Die Ankündigung „Bald ist Ihr DPD Paket da“ liefert neben der Paketnummer den Versender als Namen des Pakets – nur eine Firma mit Rechtsform oder einen bekannten Shop, nie eine Privatperson – und die Lieferschätzung.
    - Aus „Ihre Sendung stellen wir in 1-2 Werktagen zu“ wird eine Lieferspanne, gerechnet ab dem Tag der Mail. Werktage sind Montag bis Samstag; Feiertage kennt der Import nicht.
    - „Ihre Sendung stellen wir am nächsten Werktag zu“ zählt als ein Werktag.
    - Das Paket steht damit auf „Angekündigt“, bis die DPD-Abfrage den Status liefert. Die Schätzung bleibt, bis die DPD-Abfrage selbst einen Tag nennt oder das Paket zugestellt bzw. abholbereit ist.
    - Die Mails danach setzen den Status aus dem Betreff: „Zwischen 14:06 und 15:06 Uhr kommt Ihr DPD Paket“ setzt „In Zustellung“ für den Tag der Mail mit diesem Zeitfenster, „Ihr Paket ist da!“ setzt „Zugestellt“, „Im Pickup Paketshop wartet Ihr DPD Paket auf Sie“ setzt „Abholbereit“.
    - Der Empfänger und der Paketshop aus der Mail werden nie gelesen.
    - Alle anderen Mails von DPD Deutschland legen nur das Paket an.
    - DPD Österreich: siehe [Österreich und Schweiz](dienste.md#osterreich-und-schweiz).

=== "GLS"

    - „Dein Paket wird in wenigen Tagen zugestellt“ setzt „Unterwegs“ samt Liefertag und Zeitfenster, „Dein Paket hat Deutschland erreicht“ setzt „Unterwegs“.
    - „Dein GLS Paket kommt heute!“ setzt „In Zustellung“ für den Tag der Mail.
    - „Dein Paket wurde … zugestellt“ setzt „Zugestellt“ – liegt das Paket im PaketShop zur Abholung bereit, „Abholbereit“.
    - „Dein Paket wird an dem gewünschten Ort abgestellt“ legt das Paket nur an („Angekündigt“) und setzt nie einen Status zurück.
    - Die Paketnummer liest der Import nur direkt nach „Paketnummer“ bzw. „Sendungsnummer“ (11 Ziffern). In Mails, die GLS selbst geschickt hat, darf eine Prüfziffer als zwölfte Ziffer folgen; gespeichert wird die Nummer ohne sie. Nennt eine solche Mail keine Nummer, zählt die aus dem Link `gls-group.eu/track/…`.
    - Der Versender wird nur dann zum Namen, wenn es ein bekannter Shop ist oder der Name eine Rechtsform trägt (z. B. GmbH, AG, KG, e.K.) – Namen privater Absender übernimmt die Integration nie. Der Name endet an der Rechtsform: Aus „Beispiel Handels OHG (AT-B2C) Erika Musterfrau“ wird „Beispiel Handels OHG“.
    - Abstellort, Zustelladresse, Empfängername, Telefonnummer und Referenzen übernimmt die Integration nie – weder in Attribute noch ins Log.
    - Versandmails von Shops ohne Paketnummer (z. B. „Versand Ihrer Bestellung“) landen in „Nicht erkannt“.

=== "Hermes"

    - „Information zur Zustellung an den gebuchten WunschAblageort“ (die Sendung wurde gerade angekündigt) setzt „Angekündigt“.
    - „Ihre Hermes Sendung ist auf dem Weg“ setzt „Unterwegs“ samt Liefertag und Zeitfenster.
    - „Deine Sendung kommt heute.“ setzt „In Zustellung“ mit dem Zeitfenster, „… Haustürzustellung“ setzt „Zugestellt“.
    - Nennt eine Mail einen neuen Tag („Neuer Zustelltermin am …“, „Neuer Zustellversuch am …“), steht das Paket wieder auf „Unterwegs“ mit diesem Tag und, wenn genannt, dem Zeitfenster.
    - „… wurde an deinen WunschAblageort zugestellt“ setzt „Zugestellt“.
    - Mails über einen gescheiterten Zustellversuch („… konnte nicht zugestellt werden“, „nicht zugestellt“, „Zustellversuch“) setzen keinen Status, solange sie keinen neuen Tag nennen (siehe oben). Den liefert dann die Hermes-Abfrage.
    - Der Shop aus der Mail wird nur dann zum Namen, wenn es ein bekannter Shop ist (z. B. Amazon, eBay, Otto, Zalando) und das Paket noch keinen Namen hat – Namen privater Absender übernimmt die Integration nie.
    - Den Text des Wunsch-Ablageorts übernimmt die Integration nie – weder in Attribute noch ins Log.
    - Alte Amazon-Versandmails mit Hermes-Nummer hängen die Nummer an das Amazon-Paket; ab dann fragt es Hermes ab.

## Bestellungen ohne Zustellmail

Verschickt ein Marketplace-Händler selbst, kommt vom Shop oft keine „Zugestellt“-Mail. Damit so eine Bestellung nicht für immer als „Versendet“ mit überschrittenem Termin stehen bleibt, schließt die Integration sie von selbst.

**Wann?**

- Der letzte Liefertag liegt mehr als 3 volle Tage zurück, und seitdem hat keine Mail die Bestellung verändert.
- Ohne jeden Liefertag: 14 Tage nach der letzten Änderung.
- Nur bei Bestellungen, zu denen niemand gefragt werden kann: ohne Sendungsnummer – oder mit einer Nummer, für die es mit den aktuellen Einstellungen gar keine Abfrage gibt (UPS ohne eingerichtete API, DHL ohne API-Key) und die auch nicht über 17track verfolgt wird.
- Lässt sich der Paketdienst fragen, bleibt die Bestellung offen – auch wenn er die Nummer noch nicht kennt oder gerade nicht erreichbar ist. Sie endet dann mit seiner Antwort, einer Mail, „Erhalten“ oder nach 30 Tagen ohne Änderung.

**Was passiert dann?**

- Die Bestellung bekommt den Status „Zugestellt“ mit dem Text „Abgeschlossen ohne Zustellbestätigung“ und dem Attribut `assumed_delivered` (dann `true`, sonst `false`).
- Die Karte zeigt „Abgeschlossen (ohne Zustellbestätigung)“.
- Wie jedes zugestellte Paket verschwindet die Bestellung nach der eingestellten Zahl von Tagen.
- Es gibt keine Benachrichtigung.
- Die Bestellung zählt nicht bei `sensor.pakete_zugestellt_heute` und `delivered_today` mit. Wann sie wirklich ankam, weiß niemand; `delivered_at` bleibt leer.

**Kommt später doch eine Mail,** gilt die Mail, wenn sie neuer ist als das Letzte, was die Bestellung beim Abschließen wusste: Eine Mail mit einem anderen Status – etwa einem neuen Liefertag – öffnet die Bestellung wieder, auch wenn sie nach einer Pause erst nach dem Abschließen gelesen wird. Eine noch ältere Mail ändert nichts.

**Hat die Bestellung eine Sendungsnummer,** wird sie weiter abgefragt, sobald das möglich ist (etwa nach dem Eintragen des DHL-Keys). Meldet der Paketdienst etwas, gilt seine Antwort statt der Annahme. Eine „Zugestellt“-Mail trägt den echten Zeitpunkt in jedem Fall nach (ohne nachträgliche Benachrichtigung).

Das gilt für Amazon, eBay, AliExpress und Eventim. Eine Eventim-Bestellung, die nur „Bestellt“ ist, schließt sich nie von selbst: Ihre Tickets werden oft erst viel später verschickt.

Weißt du selbst, dass das Paket da ist? Dann tipp auf der Karte auf [„Erhalten“](karte.md#erhalten). Eine offene Bestellung zählt dann als heute zugestellt und wartet nicht mehr. Eine schon abgeschlossene Bestellung wird nur bestätigt: Sie zählt nicht als heute zugestellt.

## Zusammenführen: Carrier-Mail und Bestellung

Oft kommen zu einem Paket zwei Mails: eine vom Shop, eine vom Paketdienst. Die Integration macht daraus ein Paket, wenn die Zuordnung eindeutig ist.

Eine Carrier-Mail (DHL „Amazon Sendung“, GLS, Hermes, UPS) gehört zu **genau einem** offenen Amazon-, eBay- oder AliExpress-Paket ohne Sendungsnummer, wenn

- die Mail den Shop nennt (Amazon, eBay, AliExpress) oder die Shop-Mail diesen Versanddienstleister genannt hat, **und**
- der Liefertag passt (gleicher Tag oder innerhalb des Lieferzeitraums; ohne Tag: genau ein Paket unterwegs).

Das Shop-Paket übernimmt dann die Sendungsnummer und fragt ab da den Paketdienst ab (Attribute `tracking_ref` und `tracking_carrier`). Passt es nicht eindeutig, entsteht ein eigenes Paket.

??? note "Carrier-Mail nennt die Marke statt des Shops"
    Nennt die Carrier-Mail statt des Shops die Marke („Ihre Beispielmarke GmbH Sendung kommt heute“), gehört sie nur zu einem offenen **Amazon-Paket** ohne Sendungsnummer – nie zu einem eBay-Paket –, und nur, wenn

    - der Titel genau eines offenen Amazon-Pakets mit allen Wörtern der Marke beginnt,
    - dieses Paket keinen anderen Versanddienstleister nennt und
    - der Tag der Mail im Liefertag oder Lieferzeitraum des Pakets liegt (fehlt ein Tag, muss das Paket schon „Versendet“ sein).

    Die Marke ist der Firmenname ohne Rechtsform: ein Wort ab 5 Buchstaben oder mehrere Wörter, ganze Wörter, Groß- und Kleinschreibung egal. Allerweltswörter allein („Neu GmbH“, „Smart Home GmbH“) und bekannte Shops (IKEA, Otto, Zalando …) zählen nicht. Für „In Zustellung“ und „Zugestellt“ gilt der Tag, an dem die Mail kam; eine Zustellmail macht aus einem nur bestellten Paket nie ein zugestelltes. Passt etwas davon nicht, entsteht ein eigenes Paket.

??? note "Das Carrier-Paket gibt es schon als eigenes Paket"
    Kam die Shop-Mail erst später, bleiben es zunächst zwei Einträge. Wird ein Carrier-Paket zugestellt, das aus einer Mail entstanden ist, prüft die Integration noch einmal nach denselben Regeln, ob es zu genau einem offenen Amazon-, eBay- oder AliExpress-Paket ohne Sendungsnummer gehört – so, als käme seine „Zugestellt“-Mail jetzt: mit dem Paketdienst, dem Firmennamen aus der Carrier-Mail und dem Tag der Zustellung.

    - Nennt die Bestellung einen Liefertag oder Lieferzeitraum, muss der Tag der Zustellung darin liegen oder höchstens 3 Tage davor oder danach – auch dann, wenn die Bestellung den Paketdienst oder die Carrier-Mail den Shop genannt hat.

    - Passt es eindeutig, übernimmt das Shop-Paket Sendungsnummer, Verlauf und Zustellzeitpunkt und gilt als zugestellt. Das eigene Carrier-Paket samt Sensor verschwindet.
    - Gemeldet wird die Zustellung nur einmal: mit dem Carrier-Paket; stand dessen Meldung noch aus oder gab es keine, weil das Carrier-Paket vorher keinen Status hatte, mit dem Shop-Paket.
    - Einen Namen, den du dem Carrier-Paket selbst gegeben hast, übernimmt das Shop-Paket.
    - Bei mehreren passenden Bestellungen passiert nichts.
    - Pakete, die von Hand eingetragen oder von Hand als [erhalten](karte.md#erhalten) markiert wurden, fasst die Integration nie zusammen.
    - Geprüft wird genau einmal, mit dem Stand zum Zeitpunkt der Zustellung: Eine Bestellung, die eine Mail erst nach der Zustellung verändert hat (später bestellt oder versendet), kommt nicht infrage, und was beim ersten Mal nicht eindeutig war, wird später nicht doch noch zusammengeführt. Das gilt auch für Pakete, die beim Update schon zugestellt in der Liste stehen.

## Ohne Postfach: Mail per HTTP übergeben

Für Fortgeschrittene. Hast du Paketmails schon in einem eigenen Werkzeug (n8n, Node-RED, ein Skript), kannst du sie einzeln an Home Assistant übergeben. Ein Paket-Postfach brauchst du dafür nicht.

Der Import liest die Mail genau wie eine aus dem Postfach: Sie zählt nur einmal (Message-ID) und wird nicht gelesen, wenn sie älter als 14 Tage ist.

1. In Home Assistant unter **Profil → Sicherheit** ein **langlebiges Zugriffstoken** anlegen.
2. Die komplette Mail als Quelltext (RFC 822, `.eml`) per `POST` an `/api/parcel_tracker/import_mail` schicken – unverändert als Inhalt der Anfrage und mit dem Token in der Kopfzeile `Authorization`.

```sh
curl -H "Authorization: Bearer <Token>" --data-binary @mail.eml \
  http://homeassistant.local:8123/api/parcel_tracker/import_mail
```

Wie das in n8n aussieht, steht im Rezept [Mail aus n8n übergeben](rezepte.md#9-mail-aus-n8n-ubergeben).

### Was zurückkommt

Die Antwort ist JSON, z. B.:

```json
{"result": "recognized", "parcels": ["00340999999999999911"]}
```

`parcels` nennt die Pakete, die die Mail angelegt oder geändert hat (bei einem Paket, das in einer Bestellung aufging, die Bestellung). `result` sagt, was aus der Mail wurde:

| `result` | Bedeutung |
|---|---|
| `recognized` | gelesen und angewendet |
| `unrecognized` | keine Sendung erkannt |
| `ignored` | Werbung oder Konto-Mail |
| `stale` | älter als 14 Tage |
| `duplicate` | diese Mail wurde schon gelesen |

Fehler erkennst du am Statuscode:

| Code | Wann |
|---|---|
| 401 | ohne gültiges Token |
| 400 | leere Anfrage |
| 415 | Formular-Upload (`curl -F`) statt der Mail als Inhalt |
| 413 | Mail über 16 MB |
| 503 | Paket Tracker ist nicht geladen |

??? question "Warum gibt es dafür keinen Dienst?"
    Home Assistant gibt jeden Dienstaufruf samt Daten als Ereignis weiter. Die Mail stünde dann in der Recorder-Datenbank. Der Inhalt einer HTTP-Anfrage geht dagegen nur an den Import und wird nicht gespeichert.

## Was aus den Mails übernommen wird

Der Import übernimmt nur:

- Bestell- bzw. Sendungsnummer,
- einen auf 60 Zeichen gekürzten Artikeltitel,
- den Namen eines Shops oder einer Firma (nur bis zur Rechtsform, nie den einer Privatperson und nie den Anzeigenamen eines Paketdienstes; das gilt auch für die Absenderzeile „Von:“ einer UPS-Mail und den Versender in der Ankündigung von DPD),
- Status, Liefertag und Zeitfenster,
- den Versanddienstleister,
- nur mit eingeschalteter Option und nur im Arbeitsspeicher: den Zustell-Code.

Adresse, Name, Telefonnummer, eBay-Käufer- und Verkäufernamen, Wunsch-Ablageort bzw. Abstellort, Referenzen, Preise und Mail-Inhalte landen weder in Attributen noch im Log.

Mehr dazu unter [Datenschutz](datenschutz.md).

## Für Fortgeschrittene: eigenes Postfach im Heimnetz

Statt eines zusätzlichen Postfachs beim Mailanbieter kannst du das Paket-Postfach auch selbst betreiben.

**Die Idee:** Bei dir zu Hause läuft ein kleiner Mailserver, z. B. dovecot in einem Container. Ein Werkzeug wie imapfilter holt nur die Paketmails aus deinen echten Postfächern und legt sie dort ab. Home Assistant kennt nur den lokalen Server.

**Was es bringt:** Home Assistant kennt kein Passwort eines echten Postfachs, und du brauchst weder ein weiteres Konto noch Weiterleitungsregeln beim Anbieter.

**Was es kostet:** Die echten Zugangsdaten liegen weiterhin in deinem Netz – auf dem Rechner mit dem Werkzeug statt in Home Assistant. Dazu kommt ein Dienst mehr, den du pflegst und aktuell hältst. Es lohnt sich, wenn dein Anbieter keine Weiterleitungsregeln kennt oder du kein weiteres Konto anlegen willst. Sonst ist das [eigene Paket-Postfach beim Anbieter](#einrichten) der einfachere Weg.

**Einstellungen in Paket Tracker:**

| Feld | Wert |
|---|---|
| **IMAP-Server** | lokaler Name oder IP-Adresse des Servers, z. B. `nas` oder `192.168.178.20` |
| **Port** | der Port deines Servers, meist 993 |
| **Verbindung** | „Verschlüsselt, Zertifikat nicht prüfen“ bei einem selbstsignierten Zertifikat. „Unverschlüsselt“ nur, wenn der Server kein TLS anbietet. |
| **Benutzername**, **Passwort**, **Ordner** | die des lokalen Postfachs |

Ein NAS mit einem Mailserver-Paket oder ein Docker-Host kann dasselbe. Eine Schritt-für-Schritt-Anleitung für bestimmte Geräte oder Programme gibt es hier nicht: Getestet ist bisher keine. Läuft so ein Aufbau bei dir, ist deine Konfiguration als [GitHub-Issue](https://github.com/SoerenKaiser99/parcel_tracker/issues) willkommen.

**Einfacher mit n8n oder Node-RED:** Läuft eines der beiden schon bei dir, brauchst du gar keinen Mailserver. Übergib die Mails per `POST /api/parcel_tracker/import_mail`, siehe [Ohne Postfach: Mail per HTTP übergeben](#ohne-postfach-mail-per-http-ubergeben).

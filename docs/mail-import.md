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
    | **IMAP-Server** | Standard `imap.mailbox.org`, Port 993 mit SSL. |
    | **Benutzername** und **Passwort** | Die des Paket-Postfachs. Leere Felder behalten die gespeicherten Werte. |
    | **Ordner** | Standard `INBOX` (der Posteingang). Der eine Ordner, den der Import liest. Für das eigene Paket-Postfach bleibt `INBOX` stehen. Ein leeres Feld behält den gespeicherten Ordner. Siehe [Eigener Ordner](#eigener-ordner). |
    | **Verarbeitete Mails in Ordner verschieben** | Standard: an. |
    | **Zustell-Codes (Einmalpasswörter) mitlesen** | Standard: aus. Siehe [Zustell-Code](datenschutz.md#zustell-codes). |
    | **Postfach abfragen alle (Minuten)** | 1–60, Standard: 5. |

4. Speichern. Die Anmeldung wird sofort geprüft, ein geänderter Ordner dabei einmal geöffnet.

Ausschalten geht nur über den Schalter **E-Mail-Import aktiv**: Ausgeschaltet gespeichert, entfernt er Benutzername und Passwort.

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
- Der Dienst `parcel_tracker.refresh` fragt zusätzlich das Postfach sofort ab.
- Ist das Postfach nicht erreichbar, wartet der Import unabhängig vom Intervall länger (5 → 10 → 20 → 40 → 60 Minuten).
- Lehnt der Server die Anmeldung ab, erscheint unter **Einstellungen → Reparaturen** ein Hinweis.
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
| `noreply.odd@dhl.com` | DHL Express („On Demand Delivery“) |
| `noreply@dhl.com` | DHL Online Frankierung (eigene Sendungen) |
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
  "sendungsupdate@dhl.de", "noreply.odd@dhl.com", "noreply@dhl.com",
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
    bestellbestaetigung@amazon.de OR versandbestaetigung@amazon.de OR shipment-tracking@amazon.de OR order-update@amazon.de OR noreply@dhl.de OR paketankuendigung@dhl.de OR zustellung@dhl.de OR sendungsupdate@dhl.de OR noreply.odd@dhl.com OR noreply@dhl.com OR noreply@service.dpd.de OR pkginfo@ups.com OR noreply@paketankuendigung.myhermes.de OR ebay@ebay.com OR no_reply@dpd.at OR noreply@gls-group.eu OR noreply@gls-rtt.com OR transaction@notice.aliexpress.com OR bestellstatus@eventim.de OR no-reply@gls-pakete.de
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
    - Kündigt DHL eine „Amazon Sendung“ an und passt genau ein offenes Amazon-Paket dazu (gleicher Liefertag), übernimmt das Amazon-Paket die DHL-Nummer und fragt ab dann DHL ab. Ist die Zuordnung nicht eindeutig, entsteht ein eigenes Paket „Amazon-Sendung (DHL)“.

=== "eBay"

    - Pro eBay-Bestellung entsteht ein Paket mit der Nummer `EBAY` + Bestellnummer, benannt nach dem Artikel.
    - Nur die Mail „Update zur Bestellung“ nennt eine Sendungsnummer. Die 12-stelligen Artikelnummern werden nie als Sendungsnummer gelesen.
    - „Ihre Sendung ist jetzt beim Versanddienstleister!“ setzt „Versendet“ samt Lieferzeitraum, „BESTELLUNG ZUGESTELLT“ setzt „Zugestellt“. „Update zur Bestellung“ setzt „Versendet“ samt Lieferzeitraum und übernimmt die Sendungsnummer, wenn sie ihren Paketdienst selbst verrät (DHL `00340…` oder `JJD…`, UPS, Hermes `H…`): Die Bestellung wird dann live beim Paketdienst abgefragt. Eine Nummer aus 12 oder 14 Ziffern kann zu mehreren Paketdiensten gehören und bleibt unberührt. Andere eBay-Mails landen in „Nicht erkannt“.
    - Nennt die Mail den Versanddienstleister, zeigt die Karte ihn an („eBay · Versendet · via Hermes“, Attribut `shipping_carrier_hint`).

=== "AliExpress"

    - Pro AliExpress-Bestellung entsteht ein Paket mit der Nummer `ALI` + Bestellnummer, benannt nach dem Artikel. Den Namen des Händlers übernimmt die Integration nie.
    - Eine Bestellung bleibt ein Paket, auch wenn AliExpress sie in mehreren Sendungen verschickt. Eine Mail über mehrere Bestellungen legt jede Bestellung an.
    - Den Schritt liest der Import aus dem Betreff. „Bestellauftrag bestätigt“, „Bestellbestätigung“ und „versandfertig“ setzen „Bestellt“. „Bestellung versandt“, „teilweise versandt“, „Paket im Transit“, „In Ihrem Land / Ihrer Region angekommen“, „Neuer Lieferstatus“ und „Wird zugestellt“ setzen „Versendet“.
    - „Wird zugestellt“ heißt bei AliExpress nur, dass das Paket dem Versandunternehmen übergeben wurde. Es zählt deshalb nicht als heute.
    - Nennt die Mail eine „Voraussichtliche Zustellzeit“, wird sie der Liefertag.
    - Die „Packstück“-Mails und „Zollabfertigung für … wurde beendet“ nennen die Sendungsnummer des Paketdienstes. Ist es eine DHL- oder Hermes-Nummer, übernimmt die Bestellung sie und wird ab dann live abgefragt (DHL mit API-Key). Es entsteht kein zweites Paket. Eine Nummer in einem anderen Format (z. B. `AP…`) lässt sich bei keinem Paketdienst abfragen: Dann zählt nur der Schritt aus der Mail.
    - „wie ist es gelaufen?“ mit dem Satz „Wir haben die Lieferung Ihrer Bestellung … bestätigt“ setzt „Zugestellt“ mit dem Text „Lieferung bestätigt“.
    - Nur als gelesen markiert werden die Aufforderung zur Bewertung, die Erinnerung „auf Bestätigung wird gewartet“ und „Your order … is closed“.

    Die AliExpress-Mails sind nach Beispielmails umgesetzt und im Alltag noch nicht bestätigt, siehe [Roadmap & Status](stand.md).

=== "Eventim"

    Eventim-Tickets, die per Post kommen, tauchen wie ein Paket in der Liste auf.

    - Gelesen werden nur die beiden Mails von `bestellstatus@eventim.de`: die Bestellbestätigung („Deine EVENTIM-Bestellung: … - Bestellnummer …“) und die Versandbenachrichtigung („eventim.de - Versandbenachrichtigung - Deine Bestellung Nr. …“).
    - Pro Bestellung entsteht ein Eintrag mit der Nummer `EVT` + Bestellnummer, benannt nach der Veranstaltung. Bei mehreren Veranstaltungen in einer Bestellung steht „… und 1 mehr“ dahinter. Eine Bestellung bleibt ein Eintrag, auch wenn die Tickets in zwei Briefen kommen.
    - **Nur Postversand.** Eine Bestellung entsteht nur, wenn hinter „Liefermethode:“ ein Versand per Post steht (z. B. „Standardversand (Deutschland)“, Einschreiben, Express). Tickets zum Selbstausdrucken oder fürs Handy (ticketdirect, print@home, Mobile Ticket) landen nie im Briefkasten: Solche Bestellmails markiert der Import nur als gelesen.
    - Die Bestellbestätigung setzt „Bestellt“, ohne Liefertag. Eventim verschickt Tickets oft erst Wochen oder Monate nach der Bestellung.
    - Die Versandbenachrichtigung setzt „Versendet“ und rechnet den Lieferzeitraum aus „innerhalb von 2 bis 4 Werktagen“ ab dem Tag der Mail. Werktage sind Montag bis Samstag; Feiertage kennt der Import nicht.
    - **Keine Sendungsverfolgung.** Eventim nennt weder Paketdienst noch Sendungsnummer. Es gibt keine Abfrage, kein „Sendung verfolgen“ und keinen Knopf „Bestellung“.
    - **So endet die Bestellung:** Eine „Zugestellt“-Mail gibt es nie. Tipp auf der Karte auf [„Erhalten“](karte.md#erhalten), wenn die Tickets da sind. Sonst schließt die Integration die Bestellung von selbst, 3 Tage nach dem letzten Tag des Lieferzeitraums (siehe [Bestellungen ohne Zustellmail](#bestellungen-ohne-zustellmail)).
    - Solange nur „Bestellt“ dasteht, schließt die Integration die Bestellung nie von selbst. Ändert sich 30 Tage lang nichts, verschwindet sie wie jedes Paket aus der Liste; die Versandbenachrichtigung legt sie dann wieder an.
    - Käufer, Adresse, Veranstaltungsort, Plätze und Preise liest der Import nicht.

    Die Eventim-Mails sind nach Beispielmails umgesetzt und im Alltag noch nicht bestätigt, siehe [Roadmap & Status](stand.md). Gesehen wurde bisher nur „Standardversand (Deutschland)“.

=== "DHL"

    - Den Status liest der Import nur aus dem Betreff, siehe die Tabelle unter [Kein Key? Dann die DHL-Mails](dienste.md#kein-key-dann-die-dhl-mails).
    - Neben den langen DHL-Nummern (`00340…`, `JJD…`, `CQ…DE`) liest er aus DHL-Mails auch Nummern mit 12 Ziffern – nur direkt nach „Ihre Sendungsnummer“ bzw. „Sendungsnummer“, weil 12 Ziffern allein auch eine eBay-Artikelnummer sein können.
    - DHL-Mails nennen im Betreff den Shop („Ihre Beispiel GmbH Sendung ist unterwegs“). Er wird der Name des Pakets, wenn er ein bekannter Shop ist oder eine Rechtsform trägt (GmbH, AG, OHG …) – nie der Name einer Privatperson.
    - Der Anzeigename eines Paketdienstes („DHL Paketankündigung“, „DHL Zustell-Update“) wird nie zum Namen: Ohne Shop heißt das Paket `DHL <Nummer>`.
    - Abholcodes liest der Import nie.

=== "DPD"

    - DPD Deutschland (`noreply@service.dpd.de`): Die Ankündigung „Bald ist Ihr DPD Paket da“ liefert neben der Paketnummer den Versender als Namen des Pakets – nur eine Firma mit Rechtsform oder einen bekannten Shop, nie eine Privatperson – und die Lieferschätzung.
    - Aus „Ihre Sendung stellen wir in 1-2 Werktagen zu“ wird eine Lieferspanne, gerechnet ab dem Tag der Mail. Werktage sind Montag bis Samstag; Feiertage kennt der Import nicht.
    - Das Paket steht damit auf „Angekündigt“, bis die DPD-Abfrage den Status liefert.
    - Die Mails danach setzen den Status aus dem Betreff: „Zwischen 14:06 und 15:06 Uhr kommt Ihr DPD Paket“ setzt „In Zustellung“ für den Tag der Mail mit diesem Zeitfenster, „Ihr Paket ist da!“ setzt „Zugestellt“, „Im Pickup Paketshop wartet Ihr DPD Paket auf Sie“ setzt „Abholbereit“.
    - Der Empfänger aus der Mail wird nie gelesen.
    - Alle anderen Mails von DPD Deutschland legen nur das Paket an.
    - DPD Österreich: siehe [Österreich und Schweiz](dienste.md#osterreich-und-schweiz).

=== "GLS"

    - „Dein Paket wird in wenigen Tagen zugestellt“ setzt „Unterwegs“ samt Liefertag und Zeitfenster.
    - „Dein GLS Paket kommt heute!“ setzt „In Zustellung“ für den Tag der Mail.
    - „Dein Paket wurde … zugestellt“ setzt „Zugestellt“ – liegt das Paket im PaketShop zur Abholung bereit, „Abholbereit“.
    - „Dein Paket wird an dem gewünschten Ort abgestellt“ legt das Paket nur an („Angekündigt“) und setzt nie einen Status zurück.
    - Die Paketnummer liest der Import nur direkt nach „Paketnummer“ bzw. „Sendungsnummer“ (11 Ziffern).
    - Der Versender wird nur dann zum Namen, wenn es ein bekannter Shop ist oder der Name eine Rechtsform trägt (z. B. GmbH, AG, KG, e.K.).
    - Abstellort, Zustelladresse, Empfängername, Telefonnummer und Referenzen übernimmt die Integration nie.
    - Versandmails von Shops ohne Paketnummer (z. B. „Versand Ihrer Bestellung“) landen in „Nicht erkannt“.

=== "Hermes"

    - „Information zur Zustellung an den gebuchten WunschAblageort“ setzt „Angekündigt“.
    - „Ihre Hermes Sendung ist auf dem Weg“ setzt „Unterwegs“ samt Liefertag und Zeitfenster.
    - „Deine Sendung kommt heute.“ setzt „In Zustellung“ mit dem Zeitfenster, „… Haustürzustellung“ setzt „Zugestellt“.
    - Nennt eine Mail einen neuen Tag („Neuer Zustelltermin am …“, „Neuer Zustellversuch am …“), steht das Paket wieder auf „Unterwegs“ mit diesem Tag und, wenn genannt, dem Zeitfenster.
    - „… wurde an deinen WunschAblageort zugestellt“ setzt „Zugestellt“.
    - Mails über einen gescheiterten Zustellversuch setzen keinen Status. Den liefert dann die Hermes-Abfrage.
    - Der Shop aus der Mail wird nur dann zum Namen, wenn es ein bekannter Shop ist (z. B. Amazon, eBay, Otto, Zalando) und das Paket noch keinen Namen hat.
    - Den Text des Wunsch-Ablageorts übernimmt die Integration nie.

## Bestellungen ohne Zustellmail

Verschickt ein Marketplace-Händler selbst, kommt vom Shop oft keine „Zugestellt“-Mail. Damit so eine Bestellung nicht für immer als „Versendet“ mit überschrittenem Termin stehen bleibt, schließt die Integration sie von selbst.

**Wann?**

- Der letzte Liefertag liegt mehr als 3 volle Tage zurück, und seitdem hat keine Mail die Bestellung verändert.
- Ohne jeden Liefertag: 14 Tage nach der letzten Änderung.
- Nur bei Bestellungen ohne Sendungsnummer. Kennt die Bestellung die Sendungsnummer des Paketdienstes, sagt der Paketdienst, was los ist.

**Was passiert dann?**

- Die Bestellung bekommt den Status „Zugestellt“ mit dem Text „Abgeschlossen ohne Zustellbestätigung“ und dem Attribut `assumed_delivered` (dann `true`, sonst `false`).
- Die Karte zeigt „Abgeschlossen (ohne Zustellbestätigung)“.
- Wie jedes zugestellte Paket verschwindet die Bestellung nach der eingestellten Zahl von Tagen.
- Es gibt keine Benachrichtigung.
- Die Bestellung zählt nicht bei `sensor.pakete_zugestellt_heute` und `delivered_today` mit. Wann sie wirklich ankam, weiß niemand; `delivered_at` bleibt leer.

**Kommt später doch eine Mail,** gilt die Mail: Eine „Zugestellt“-Mail trägt den echten Zeitpunkt nach (ohne nachträgliche Benachrichtigung). Eine Mail mit einem anderen Status – etwa einem neuen Liefertag – öffnet die Bestellung wieder.

Das gilt für Amazon, eBay, AliExpress und Eventim. Eine Eventim-Bestellung, die nur „Bestellt“ ist, schließt sich nie von selbst: Ihre Tickets werden oft erst viel später verschickt.

Weißt du selbst, dass das Paket da ist? Dann tipp auf der Karte auf [„Erhalten“](karte.md#erhalten). Das Paket zählt dann als heute zugestellt, und die Bestellung wartet nicht mehr.

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

    Die Marke ist der Firmenname ohne Rechtsform: ein Wort ab 5 Buchstaben oder mehrere Wörter. Allerweltswörter allein („Neu GmbH“, „Smart Home GmbH“) und bekannte Shops (IKEA, Otto, Zalando …) zählen nicht. Passt etwas davon nicht, entsteht ein eigenes Paket.

??? note "Das Carrier-Paket gibt es schon als eigenes Paket"
    Kam die Shop-Mail erst später, bleiben es zunächst zwei Einträge. Wird ein Carrier-Paket zugestellt, das aus einer Mail entstanden ist, prüft die Integration noch einmal nach denselben Regeln, ob es zu genau einem offenen Amazon-, eBay- oder AliExpress-Paket ohne Sendungsnummer gehört.

    - Passt es eindeutig, übernimmt das Shop-Paket Sendungsnummer, Verlauf und Zustellzeitpunkt und gilt als zugestellt. Das eigene Carrier-Paket samt Sensor verschwindet.
    - Gemeldet wird die Zustellung nur einmal.
    - Bei mehreren passenden Bestellungen passiert nichts.
    - Pakete, die von Hand eingetragen wurden, fasst die Integration nie zusammen.
    - Geprüft wird genau einmal, mit dem Stand zum Zeitpunkt der Zustellung.

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
- den Namen eines Shops oder einer Firma (nur bis zur Rechtsform, nie den einer Privatperson und nie den Anzeigenamen eines Paketdienstes),
- Status, Liefertag und Zeitfenster,
- den Versanddienstleister,
- nur mit eingeschalteter Option und nur im Arbeitsspeicher: den Zustell-Code.

Adresse, Name, Telefonnummer, eBay-Käufer- und Verkäufernamen, Wunsch-Ablageort bzw. Abstellort, Referenzen, Preise und Mail-Inhalte landen weder in Attributen noch im Log.

Mehr dazu unter [Datenschutz](datenschutz.md).

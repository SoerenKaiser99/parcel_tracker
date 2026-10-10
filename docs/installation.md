# Installation

Die Installation hat drei Teile: Integration herunterladen, Integration einrichten, Karte hinzufügen.

!!! info "Aufnahme in den HACS-Standardkatalog ist beantragt"
    Der Antrag liegt in der Warteschlange von HACS ([hacs/default#11781](https://github.com/hacs/default/pull/11781)). Bis er bearbeitet ist, trägst du das Repository in HACS als benutzerdefiniertes Repository ein. Das macht der Knopf unten für dich.

## Mit HACS (empfohlen)

Voraussetzung: [HACS](https://hacs.xyz/docs/use/) ist in Home Assistant installiert.

HACS lädt die Integration nur herunter. Eingerichtet wird sie danach in Home Assistant selbst (Schritt 5). Ohne diesen Schritt passiert nichts.

=== "Mit dem Knopf"

    Der Knopf öffnet HACS in deinem Home Assistant und trägt das Repository als Quelle ein:

    [![Repository in HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=SoerenKaiser99&repository=parcel_tracker&category=integration)

    Danach weiter bei Schritt 3.

=== "Von Hand"

    1. HACS öffnen → Menü (⋮) oben rechts → **Benutzerdefinierte Repositories**.
    2. Repository `https://github.com/SoerenKaiser99/parcel_tracker` eintragen, Typ **Integration** wählen, hinzufügen.

Dann geht es für beide Wege gleich weiter:

3. In HACS nach „Paket Tracker“ suchen, öffnen und **Herunterladen** wählen.
4. Home Assistant neu starten.
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → „Paket Tracker“ suchen und einrichten (siehe [Integration einrichten](#integration-einrichten)).
6. Seite einmal neu laden, dann im Dashboard die Karte „Paket Tracker“ hinzufügen (siehe [Karte hinzufügen](#karte-hinzufugen)).

!!! question "„Paket Tracker“ taucht in Schritt 5 nicht auf?"
    Prüf in HACS, ob die Integration unter den heruntergeladenen steht, und starte Home Assistant noch einmal neu. Dass das Repository nach dem Herunterladen nicht mehr im Dialog „Benutzerdefinierte Repositories“ erscheint, ist kein Fehler.

## Ohne HACS (ZIP von Hand)

1. Auf der [Release-Seite](https://github.com/SoerenKaiser99/parcel_tracker/releases/latest) die Datei `parcel_tracker.zip` herunterladen.
2. Im Konfigurationsordner von Home Assistant den Ordner `custom_components/parcel_tracker` anlegen und den Inhalt der ZIP-Datei dort hinein entpacken. Die Datei `manifest.json` liegt dann direkt in diesem Ordner.
3. Home Assistant neu starten.
4. Weiter wie oben ab Schritt 5.

Updates kommen auf diesem Weg nicht von selbst: Für eine neue Version lädst du die ZIP-Datei erneut herunter, ersetzt den Ordnerinhalt und startest Home Assistant neu.

## Integration einrichten

**Einstellungen → Geräte & Dienste → Integration hinzufügen** → „Paket Tracker“. Das Formular hat vier Felder:

| Feld | Bedeutung |
|---|---|
| **DHL-API-Key** (optional) | Wird beim Speichern geprüft. Das Feld darf leer bleiben: DPD, GLS und Hermes brauchen keinen Key, DHL-Pakete kommen ohne Key aus den DHL-Mails. Der Key lässt sich später ergänzen. Siehe [DHL](dienste.md#dhl). |
| **Land** | Deutschland, Österreich oder Schweiz. Vorbelegt mit dem Land aus den Home-Assistant-Einstellungen, sonst Deutschland. Bestimmt, wie viele Ziffern die PLZ hat und welche GLS-Abfrage gefragt wird. |
| **PLZ** (optional) | Deutschland 5 Ziffern (z. B. 10115), Österreich und Schweiz 4 Ziffern (z. B. 1010). Mit PLZ liefert DHL zusätzliche Details und GLS den Verlauf. |
| **Zugestellte Pakete ausblenden nach (Tagen)** | Standard 3, Bereich 1–30. Nach dieser Zeit verschwindet ein zugestelltes Paket aus der Übersicht. |

Alle vier Felder änderst du später über **Konfigurieren** an der Integration. Dort gibt es zusätzlich:

- den Schalter **Namen ausblenden** (siehe [Datenschutz](datenschutz.md#namen-ausblenden)),
- das Feld **17track-API-Key** (siehe [17track](dienste.md#17track-optional)),
- die Bereiche **E-Mail-Import**, **UPS-Live-Status** und **Benachrichtigungen**.

Gut zu wissen:

- Lässt du das Key-Feld beim Ändern leer, bleibt der vorhandene Key erhalten.
- Wechselst du das Land, trag die PLZ im selben Formular neu ein. Passt die gespeicherte PLZ nicht zur Länge des neuen Landes, meldet das Formular das, statt sie zu verwerfen.

## Karte hinzufügen

1. Seite im Browser einmal neu laden. Erst dann kennt ein schon geöffnetes Home Assistant die neue Karte.
2. Dashboard bearbeiten → **Karte hinzufügen** → „Paket Tracker“ auswählen.

Oder per YAML:

```yaml
type: custom:parcel-tracker-card
```

Was die Karte kann und welche Optionen sie hat, steht unter [Die Karte](karte.md).

### Hinweis zur Ressource

Du musst die Karte nicht als Ressource eintragen. Die Integration kopiert sie beim Start nach `www/parcel_tracker/` und trägt sie selbst als Dashboard-Ressource ein (`/local/parcel_tracker/parcel-tracker-card.js`).

Home Assistant liefert `/local` nur aus, wenn der Ordner `www` beim Start schon existierte. Sonst liefert die Integration die Karte zunächst selbst aus (`/parcel_tracker/parcel-tracker-card.js`). Ein weiterer Neustart von Home Assistant aktiviert dann den `/local`-Pfad.

Verwaltest du die Dashboard-Ressourcen per YAML, kann die Integration die Karte nicht selbst eintragen. Was dann zu tun ist, steht unter [Karte wird nicht gefunden?](hilfe.md#karte-wird-nicht-gefunden).

### Karte wird nicht gefunden?

Meldet das Dashboard „Custom element doesn't exist: parcel-tracker-card“ oder fehlt „Paket Tracker“ in der Kartenauswahl: Die Schritte dazu stehen unter [Hilfe → Karte wird nicht gefunden?](hilfe.md#karte-wird-nicht-gefunden).

## Nach jedem Update

1. Das Update in HACS installieren.
2. Home Assistant neu starten.
3. Die Seite im Browser neu laden oder die Home-Assistant-App schließen und wieder öffnen.

Die Integration zu entfernen und neu hinzuzufügen ist dafür nie nötig. Dabei gingen nur die Pakete und Einstellungen verloren.

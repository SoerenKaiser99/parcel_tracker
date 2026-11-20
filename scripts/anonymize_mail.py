"""Anonymise parcel mails: for testers (sample mails for an issue) and for the fixtures.

Runs locally with the Python standard library only (Python 3.9 or newer), as a single file,
without network access.

Tester mode, the default (messages in German, --help lists the options):

    python3 anonymize_mail.py <file.eml | folder> [--zip] [--out DIR] [--ohne-angaben] ...

Fixture mode, for the developer and only with the explicit flag (see "fixture mode" below):

    python3 anonymize_mail.py --fixtures SRC_DIR DST_DIR POSTCODE CITY FIRSTNAME LASTNAME
        [MAILDOMAIN ...]

The replaced values are never printed. Exit codes: 0 done, 1 aborted or failed, 2 wrong call.

What each rule replaces is told by the tests (tests/test_anonymize_*.py); the instructions for
testers are in docs/hilfe.md ("Beispielmails einreichen").
"""
import email
import email.utils
import glob
import hashlib
import html
import os
import re
import secrets
import sys
import unicodedata
import zipfile
from email import policy
from email.message import EmailMessage
from html.parser import HTMLParser

BLOCK = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table", "td", "th"}
SKIP = {"style", "script", "head", "title"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(self.skip - 1, 0)
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(markup):
    parser = _Text()
    parser.feed(markup)
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in "".join(parser.out).splitlines())
    return "\n".join(line for line in lines if line)

def as_html(text):
    return "<html><body>\n" + "\n".join(
        f"<p>{html.escape(line)}</p>" for line in text.splitlines() if line.strip()
    ) + "\n</body></html>\n"


def load(path):
    with open(path, "rb") as handle:
        return email.message_from_binary_file(handle, policy=policy.default)


# Apple's relay "E-Mail-Adresse verbergen": "<local>_at_<domain>_<id>_<id>@privaterelay…".
# The two ids belong to the recipient.
RELAY_HOST = "privaterelay.appleid.com"
_RELAY_FILL = "0a1b2c3d4e5f6g7h8i9j"
# Where the sender's domain ends in a relay address (its dots are underscores there).
_RELAY_TLDS = frozenset(
    "com de net org eu at ch info io co uk fr it nl es pl be dk se no fi cz us ca au jp cn "
    "shop store app online biz".split()
)


def _relay_parts(address):
    """(sender's local part, labels of its domain, what follows them) of an address of
    Apple's relay; None for any other address and for one without a sender in it.

    The domain ends with its top-level domain ("…_com", "…_co_uk"): everything behind it
    belongs to the recipient, whatever it looks like (two ids as a rule, but nobody
    promises their number or their characters). Without a top-level domain the script
    knows, the last two parts are taken for the ids and at least two labels stay.
    """
    local, _, host = address.lower().rpartition("@")
    name, at, rest = local.rpartition("_at_")
    parts = rest.split("_")
    if host != RELAY_HOST or not at or not name or len(parts) < 2:
        return None
    end = next((n for n in range(1, len(parts)) if parts[n] in _RELAY_TLDS), None)
    if end is None:
        end = max(len(parts) - 3, 1)
    else:
        while end + 1 < len(parts) and parts[end + 1] in _RELAY_TLDS:
            end += 1
    return name, parts[:end + 1], parts[end + 1:]


def relay_address(address):
    """An address of Apple's relay with invented ids of the same length; any other as it is.

    Fails closed: at the relay's host everything behind the sender's domain is replaced,
    and an address without a sender in it becomes a placeholder as a whole.
    """
    if address.rpartition("@")[2].lower() != RELAY_HOST:
        return address
    found = _relay_parts(address)
    if found is None:
        return f"absender@{RELAY_HOST}"
    name, domain, ids = found
    invented = [(_RELAY_FILL * (len(part) // len(_RELAY_FILL) + 1))[:len(part)] for part in ids]
    return f"{name}_at_{'_'.join(domain + invented)}@{RELAY_HOST}"


def relay_original(address):
    """The address a relay address stands for, "" if it has not that shape. Dots of the
    original are underscores there, so the result is only good for comparing."""
    found = _relay_parts(address)
    return f"{found[0]}@{'.'.join(found[1])}" if found else ""


# ----- Eventim (both modes) -----
# Senders: every sender at eventim.de and eventimpresents.com, also passed on by Apple's relay.
# Nothing of the buyer, the purchase or the event stays.
#
# Order sender (bestellstatus@eventim.de: order confirmation and shipping notice):
# - Only lines the script knows are written, every other line is dropped: headings, Eventim's
#   own sentences, the labels of the order ("Bestellnummer:", "Liefermethode:" with its
#   value, ...).
# - Replaced in them: the greeting, the address blocks, every date (also the Date header:
#   invented days, one after the other from Mon, 5 Jan 2026), the payment method, prices, the
#   event (name, day, venue, organiser: invented ones, the same name for the same event) and
#   its tickets.
# - Order numbers become 99…01, 99…02, … in order of appearance.
# - The text ends with the heading "HINWEISE": hints, legal texts and the imprint are cut.
#
# Every other Eventim mail (newsletter, ticket alarm, customer service, a club's ticket shop):
# - Only the sender address is kept, with the club's name in "kundenservice-<club>@" replaced.
# - The display name is "EVENTIM", subject and text are one fixed line each.
#
# Tester mode: also a mail forwarded by hand; its quoted header block stays in front, with
# its sender, subject and day replaced the same way. The general rules run afterwards.
EVT_DOMAINS = ("eventim.de", "eventimpresents.com")
EVT_ORDER_SENDER = "bestellstatus@eventim.de"


def is_eventim(address):
    """A sender at eventim.de or eventimpresents.com, also passed on by Apple's relay."""
    host = (relay_original(address) or address).rpartition("@")[2]
    return any(host == domain or host.endswith("." + domain) for domain in EVT_DOMAINS)


_EVT_EVENTS = (
    "Beispielband – Tour 2026",
    "Musterfestival 2026 – Wochenendticket",
    "Beispielorchester – Neujahrskonzert",
    "Musterensemble – Das Beispielstück",
    "Beispielkünstlerin – Live 2026",
)
_EVT_VENUE = "Ort: Musterhalle, Musterstraße 1, 12345 Musterstadt"
_EVT_ORGANISER = (
    "Veranstalter: Beispiel Konzert GmbH, Musterstraße 2, 12345 Musterstadt, Deutschland"
)
_EVT_DAY = "Datum: Sa., 05.12.2026, 20:00"
_EVT_TICKET = "Stehplatz, Normalpreis: € 1,99"
_EVT_ADDRESS = ("Max Mustermann", "Musterstraße 1", "12345 Musterstadt", "Deutschland")
_EVT_OTHER_SUBJECT = "Neuigkeiten von EVENTIM"
_EVT_OTHER_TEXT = "[Inhalt entfernt: keine Bestellung mit Postversand]\n"
_EVT_END = "HINWEISE"
_EVT_HEADINGS = {
    "BESTELLBESTÄTIGUNG", "VERSANDBENACHRICHTIGUNG", "DEINE BESTELLUNG",
    "EINZELHEITEN DEINER BESTELLUNG", "GESAMT",
}
# Eventim's own sentences, told by how they begin; dates and numbers in them are replaced.
_EVT_SENTENCES = re.compile(
    r"Vielen Dank für deine Bestellung|vielen Dank für deinen Einkauf vom"
    r"|Vielen Dank für deinen Einkauf bei EVENTIM|Klicke auf einen der folgenden Punkte"
    r"|Lieferadresse: https?://|Lieferzeiten:|Versandstatus:|Für weitere Themen"
    r"|Diese E-Mail ist deine Buchungsbestätigung|wir haben heute deine Bestellung Nr\."
    r"|Wir wünschen dir viel Spaß|Dein EVENTIM-Kundenservice"
    r"|Dies ist eine automatisch generierte|Die Lieferanschrift für diese Bestellung"
    r"|Die Zustellung erfolgt spätestens innerhalb|Der Versand der Tickets erfolgt zwischen"
    r"|Das ticketdirect kann|Voraussichtliche Ankunft:"
)
_EVT_ADDRESS_LABELS = ("Lieferadresse:", "Rechnungsadresse:")
# Labels of the order: (label, value written instead; None keeps the value, with its
# numbers and dates replaced like everywhere).
_EVT_LABELS = (
    ("Bestellnummer:", None), ("Bestelldatum:", None), ("Gesamtwert:", None),
    ("Rechnung als PDF herunterladen:", None), ("Liefermethode:", None),
    ("Zahlungsart:", "Rechnung"), ("Zwischensumme:", None), ("Versandkosten:", None),
    ("Gesamtsumme inkl. MwSt.:", None),
)
_EVT_GREETING = re.compile(r"(Hallo|Hi|Liebe[rs]?|Guten Tag)\b[^\n]*,")
_EVT_SEPARATOR = re.compile(r"[-=]{5,}")
_EVT_PRICED = re.compile(r"[^:\n]{1,80}:\s*(?:\d+ x )?€ ?\d")
_EVT_PRICE = re.compile(r"€ ?\d[\d.]*,\d\d")
_EVT_DATE = re.compile(r"(?<!\d)\d{1,2}\.\d{1,2}\.\d{4}(?!\d)")
_EVT_SHIP_WINDOW = re.compile(r"zwischen dem .{1,40}? und .{1,40}? \d{4}\.")
_EVT_NUMBER = re.compile(r"(?<!\d)\d{6,12}(?!\d)")
_EVT_URL = re.compile(r"https?://[^\s<>\]\)\"]+")
_EVT_ORDER_SUBJECT = re.compile(
    r"(?i)(Deine EVENTIM-Bestellung:\s*)(.*?)((?:\s+und\s+\d+\s+mehr)?\s+-\s+Bestellnummer\s+)(\d+)"
)
_EVT_SHIPPED_SUBJECT = re.compile(
    r"(?i)(.*Versandbenachrichtigung\s+-\s+Deine Bestellung Nr\.?\s*)(\d+)"
)
_EVT_CLUB = re.compile(r"^((?:noreply_)?kundenservice)-[^@_]+")
evt_numbers, evt_events = {}, {}


def _evt_number(match):
    real = match.group(0)
    if real in evt_numbers.values():
        return real  # an invented number met again
    if real not in evt_numbers:
        evt_numbers[real] = "9" * (len(real) - 2) + f"{len(evt_numbers) + 1:02d}"
    return evt_numbers[real]


def _evt_event(real):
    """An invented event name for a real one (the same for the same event)."""
    key = re.sub(r"\W+", "", real.lower())[:12]
    if key not in evt_events:
        evt_events[key] = _EVT_EVENTS[len(evt_events) % len(_EVT_EVENTS)]
    return evt_events[key]


def _evt_values(line):
    """Dates, prices, links and order numbers of a line that is kept."""
    line = _EVT_URL.sub(lambda m: re.match(r"https?://[^/\s]+", m.group(0)).group(0) + "/…", line)
    line = _EVT_SHIP_WINDOW.sub("zwischen dem 1. Juni und 5. Juni 2026.", line)
    line = _EVT_DATE.sub("05.01.2026", line)
    line = _EVT_PRICE.sub("€ 1,99", line)
    return _EVT_NUMBER.sub(_evt_number, line)


def evt_address(address):
    """The sender address of an Eventim mail without a club's name in it."""
    return _EVT_CLUB.sub("\\1-musterverein", relay_address(address))


def evt_date(count):
    """The invented Date header of the ``count``-th Eventim mail of a run (1, 2, …)."""
    day = email.utils.parsedate_to_datetime("Mon, 05 Jan 2026 10:00:00 +0100")
    return email.utils.format_datetime(day.replace(day=day.day + (count - 1) % 20))


def evt_quoted_day(count):
    """The day of ``evt_date`` as a mail program quotes it above a forwarded mail."""
    day = email.utils.parsedate_to_datetime(evt_date(count))
    return f"{day.day}. Januar {day.year} {day:%H:%M}"


def scrub_eventim_subject(subject):
    """The subject of a mail of Eventim's order sender; an unknown one is not kept."""
    subject = " ".join(subject.split())
    if found := _EVT_ORDER_SUBJECT.fullmatch(subject):
        head, event, tail, number = found.groups()
        return head + _evt_event(event) + tail + _EVT_NUMBER.sub(_evt_number, number)
    if found := _EVT_SHIPPED_SUBJECT.fullmatch(subject):
        return found.group(1) + _EVT_NUMBER.sub(_evt_number, found.group(2))
    return _EVT_OTHER_SUBJECT


def scrub_eventim(t):
    """A mail of Eventim's order sender, the text: only lines the script knows are kept
    (see the module docstring); runs before scrub()."""
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in t.replace("\r\n", "\n").split("\n")]
    lines = [line for line in lines if line]
    out, index = [], 0
    while index < len(lines):
        line = lines[index]
        below = lines[index + 1] if index + 1 < len(lines) else ""
        index += 1
        if line == _EVT_END:
            out.append(line)
            break
        if line in _EVT_HEADINGS or _EVT_SEPARATOR.fullmatch(line):
            out.append(line)
        elif _EVT_GREETING.fullmatch(line):
            out.append("Hallo Max,")
        elif line in _EVT_ADDRESS_LABELS:
            # name, street, postcode and place, country: up to the next line the script
            # knows (never more than six lines)
            block = 0
            while index < len(lines) and block < 6 and not _evt_known(lines[index]):
                index += 1
                block += 1
            out += [line, *_EVT_ADDRESS]
        elif _EVT_SENTENCES.match(line):
            out.append(_evt_values(line))
        elif label := next((item for item in _EVT_LABELS if line.startswith(item[0])), None):
            name, fixed = label
            value = line[len(name):].strip()
            if not value and below and not _evt_known(below):
                # (older mails: the value stands on the next line)
                index += 1
                out += [name, fixed or _evt_values(below)]
            else:
                out.append(f"{name} {fixed or _evt_values(value)}".rstrip())
        elif line.startswith("Datum:"):
            out.append(_EVT_DAY)
        elif line.startswith("Ort:"):
            out.append(_EVT_VENUE)
        elif line.startswith("Veranstalter:"):
            out.append(_EVT_ORGANISER)
        elif below.startswith("Datum:"):
            out.append(_evt_event(line))
        elif _EVT_PRICED.match(line):
            out.append(_EVT_TICKET)
        # (every other line is dropped: seats, notes, whatever a new layout brings)
    return "\n".join(out) + "\n"


def _evt_known(line):
    """A line of an Eventim mail that is none of an address block."""
    return bool(
        line == _EVT_END or line in _EVT_HEADINGS or line in _EVT_ADDRESS_LABELS
        or _EVT_SEPARATOR.fullmatch(line) or _EVT_SENTENCES.match(line)
        or any(line.startswith(name) for name, _ in _EVT_LABELS)
    )


# ----- tester mode: anonymise own mails before they are attached to a GitHub issue -----
_T_USAGE = (
    'usage: anonymize_mail.py <Datei.eml | Ordner> [--zip] [--out ORDNER] [--ohne-angaben]\n'
    '           [--name "Vorname Nachname"] [--street "Straße Hausnummer"] [--postcode PLZ]\n'
    '           [--city ORT] [--phone TELEFON] [--email MAILADRESSE] [--salt DATEI]\n'
    '       anonymize_mail.py --fixtures SRC_DIR DST_DIR POSTCODE CITY FIRSTNAME LASTNAME'
    ' [MAILDOMAIN ...]'
)
_T_HELP = """
Macht aus gespeicherten Paketmails (.eml) anonymisierte Beispielmails für ein GitHub-Issue.

  <Datei.eml | Ordner>  eine Mail oder ein Ordner mit .eml-Dateien
  --zip                 zusätzlich paket-tracker-beispiele.zip schreiben
  --out ORDNER          Zielordner (Standard: "anonymisiert" neben den Mails)
  --name, --street, --postcode, --city, --phone, --email
                        die eigenen Angaben, die überall ersetzt werden; mehrere Werte
                        mit ; trennen. Fehlt eine Angabe, fragt das Skript im Terminal
                        danach (leer lassen = überspringen).
  --ohne-angaben        ausdrücklich ohne eigene Angaben arbeiten: Das Skript fragt nicht
                        und bereinigt nur allgemein. Namen und Orte können dann stehen
                        bleiben. Ohne diese Option braucht das Skript mindestens eine Angabe.
  --salt DATEI          wiederholbare Ergebnisse: Fehlt DATEI, legt das Skript sie mit einem
                        zufälligen Salt an (ein selbst ausgedachter ließe sich erraten und
                        wird abgelehnt). Erfundene Nummern und Dateinamen hängen dann nur an
                        der Mail, nicht an ihrer Stelle im Lauf. Eine Mail ergibt so in jedem
                        Lauf dieselbe Datei, solange das Skript aus den anderen Mails nichts
                        Neues lernt (bei Eventim zählen Tag und Bestellnummer weiter die Mails
                        des Laufs). Sie heißt <Datum>_<Absender>_<Kennung>.eml und ersetzt ihr
                        Ergebnis aus einem früheren Lauf; andere frühere Ergebnisse mit Salt
                        bleiben liegen und werden am Ende genannt. Die DATEI nicht weitergeben
                        und nicht in den Zielordner legen: Mit ihr lassen sich die erfundenen
                        Nummern zurückrechnen.

Ersetzt werden außerdem alle Mail-Adressen außer dem Absender, Telefonnummern, Links (im
Text bleibt nur der Servername, im HTML-Teil Server, Pfad und Namen der Parameter mit erfundenen
Werten; dort bleiben auch Bilder und Bildtexte, erfunden, was die Mail nicht ohnehin zeigt),
Sendungs-, Bestell- und andere lange Nummern (gleiche Form, erfundene
Ziffern), Ablageorte, Anreden, Adressblöcke, Zeilen mit Postleitzahl und Ort, Namen von
Nachbarn, Empfängern und privaten Absendern sowie Nummer und Straße einer Filiale oder
Packstation. Technische Kopfzeilen und Anhänge entfallen.
Frühere Ergebnisse im Zielordner (NNN_*.eml des Skripts und das ZIP) werden vorher gelöscht.
Das Skript läuft nur lokal und baut keine Netzwerkverbindung auf.

Die letzte Zeile der Aufruf-Übersicht ist der Entwickler-Aufruf für Test-Fixtures.
"""
_T_OPTIONS = {
    "name": "Vor- und Nachname",
    "street": "Straße und Hausnummer",
    "postcode": "Postleitzahl",
    "city": "Ort",
    "phone": "Telefonnummer",
    "email": "Mail-Adresse",
}
_T_BARE = "--ohne-angaben"
# A salt file as the script writes it: 32 random bytes. One a tester thought of could be found
# by trying, from a number in a mail whose original is public (a trade licence number).
_T_SALT = re.compile(r"[0-9a-f]{64}")
_T_ZIP = "paket-tracker-beispiele.zip"
_T_MAIL = "max@example.org"
_T_PHONE = "+49 000 0000000"
# A sender at one of these providers is a person (a forwarded mail), never a shop or carrier.
_T_FREEMAIL = {
    "gmail.com", "googlemail.com", "gmx.de", "gmx.net", "gmx.at", "gmx.ch", "web.de",
    "t-online.de", "outlook.com", "outlook.de", "hotmail.com", "hotmail.de", "live.com",
    "live.de", "yahoo.com", "yahoo.de", "icloud.com", "me.com", "mac.com", "posteo.de",
    "posteo.net", "mailbox.org", "freenet.de", "aol.com", "proton.me", "protonmail.com",
    "arcor.de", "online.de", "mail.de", "email.de", "tutanota.com", "tuta.io", "vodafone.de",
}
# Where a given or learnt word may begin and end: no letter before / behind it, or the case
# changes there. Some senders write the text part beside their HTML without its line breaks
# ("Herr MeierIhre Bestellung", "Jonas MeierLindenweg 7", in capitals "MEIERIhre": the last
# capital starts the next word); inside an ordinary word the case never changes like that.
_T_LOWER, _T_UPPER = (
    "".join(char for char in map(chr, range(0x250)) if kind(char))
    for kind in (str.islower, str.isupper)
)
_T_CASE_CHANGE = (
    rf"(?-i:(?<=[{_T_LOWER}])(?=[{_T_UPPER}])|(?<=[{_T_UPPER}])(?=[{_T_UPPER}][{_T_LOWER}]))"
)
_T_B0, _T_B1 = rf"(?:(?<![^\W\d_])|{_T_CASE_CHANGE})", rf"(?:(?![^\W\d_])|{_T_CASE_CHANGE})"
_T_UMLAUT = {"ä": "a", "ö": "o", "ü": "u"}
_T_DIGRAPH = {"ae": "ä", "oe": "ö", "ue": "ü"}
# "=" and "%" belong to the local part: bounce+user=gmx.de@shop.example is one address.
# It begins where its characters begin: tried from within a long run of digits, every try
# would read to the run's end (time growing with the square of the run's length).
_T_ADDRESS = r"(?<![\w.+%=&~-])[\w.+%=&~-]+@[\w-]+(?:\.[\w-]+)+"
_T_LINKS = re.compile(rf"(?P<url>(?:https?://|(?<![\w@.])www\.)[^\s<>\"'()\[\]{{}}]+)|(?P<mail>{_T_ADDRESS})")
_T_DATE = r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}(?!\d)"
# One pass, the first alternative that fits wins: links and addresses stay as the first pass
# left them, then order numbers, labelled numbers, one-time codes, IBANs, long tokens of
# letters and digits, phone numbers, tracking numbers and every other long digit run.
# A number written in groups ("0034 0434 1610 9401 2345", "1234.5678.901"): groups of two to
# six digits with one kind of separator (space, tab, dot or dash), ten digits or more in all.
# Only digits joined by that one separator count ("2026-09-28 11:51" is a date and a time).
# It may not end inside a date, a time or a price. With 14 digits or more it is no phone
# number, so it is looked for before the phone rule (which took the first digits and left the
# rest), with fewer digits after it. Without a label in front of it, a row of years ("2026
# 2027 2028") or of two-digit numbers ("10 20 30 40 50 60") is no number in groups.
def _t_sscc_check(digits):
    """The GS1 check digit (mod 10) of the 19 digits in front of it."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return str((10 - total % 10) % 10)


def _t_sscc(run):
    """An SSCC as carriers print it: "00", 18 digits, the last a check digit that fits."""
    return bool(re.fullmatch(r"00[0-9]{18}", run)) and _t_sscc_check(run[:-1]) == run[-1]


def _t_groups(minimum, labelled=False):
    runs = []
    for gap in (" ", r"\t", r"\.", "-"):
        ahead = rf"(?=(?:{gap}?\d){{{minimum}}})"
        if not labelled:
            year, end = r"(?:19|20)\d\d", rf"(?!{gap}?\d)"
            ahead += rf"(?!(?:{year}{gap})+{year}{end})(?!(?:\d\d{gap})+\d\d{end})"
        runs.append(rf"{ahead}\d{{2,6}}(?:{gap}\d{{2,6}})+")
    return rf"(?<![\w+./=-])(?:{'|'.join(runs)})(?![.,:]?\d)"


_T_GROUPED = _t_groups(10)
_T_GROUPED_LONG = _t_groups(14)
_T_GROUPED_LABELLED = _t_groups(10, labelled=True)
_T_GROUPED_MIN = 10
# An international number (UPU S10) in groups: "CQ 123 456 785 DE".
_T_S10_GROUPED = (
    r"(?<![A-Za-z0-9])[A-Z]{2}(?=(?:[ \t.-]?\d){9}[ \t.-]?[A-Z]{2}(?![A-Za-z0-9]))"
    r"(?:[ \t.-]?\d)+[ \t.-]?[A-Z]{2}"
)
_T_IN_GROUPS = re.compile(rf"{_T_S10_GROUPED}|{_T_GROUPED_LABELLED}")
# A no-break space between two digits, also as an entity in a text part that carries HTML.
# (also next to the letters of an international number: "CQ&nbsp;123&nbsp;456&nbsp;785&nbsp;DE")
_T_DIGIT_GAP = re.compile(
    r"(?<=[0-9A-Z])(?i:&nbsp;|&#160;|&#xa0;|[\xa0\u2007\u2009\u202f])(?=[0-9A-Z])"
)
# Tracking numbers in a link or in the text of an image: the known forms, or the value of a
# parameter that names a parcel.
_T_HIDDEN = re.compile(
    r"(?<![A-Za-z0-9])(?:00340\d{15}|JJD\d{12,22}|1Z[0-9A-Z]{16}|H\d{19}|[A-Z]{2}\d{9}[A-Z]{2})"
    r"(?![A-Za-z0-9])"
    r"|(?i:(?:piececode|idc|tracknum|tracking_?(?:number|no|id|code)|parcel_?(?:number|no|id)"
    r"|sendungsnummer|paketnummer)=)(?P<value>[A-Za-z]{0,4}\d{8,30}[A-Za-z]{0,2})(?![A-Za-z0-9])"
)
_T_HIDDEN_NOTE = "[Nummer nur im Link oder Bildtext: {}]"
_T_HIDDEN_MARK = re.compile("\x00([^\x00]*)\x00")
_T_GENERIC = re.compile(
    _T_LINKS.pattern
    + r"|(?P<order>(?<![\w-])(?:\d{3}-\d{7}-\d{7}|\d{2}-\d{5}-\d{5})(?![\w-]))"
    + r"|(?P<label>(?:(?i:[\w-]*(?:nummer|nr|number|code|pin|referenz|reference|passwort"
    + r"|kennwort))|\bID|\bTAN)\b[ \t.:#*]*\n?[ \t#*]*)"
    + rf"(?P<token>{_T_S10_GROUPED}|{_T_GROUPED_LABELLED}|(?=[\w-]*\d)[A-Za-z0-9][A-Za-z0-9_-]{{2,}})"
    + r"|(?P<otp_label>(?i:passwort|kennwort|code|pin|tan)\b[^0-9\n]{0,40})(?P<otp>\d{4,8})(?!\d)"
    + rf"|(?P<s10>{_T_S10_GROUPED})"
    + r"|(?P<iban>(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?"
    + r"(?![A-Za-z0-9]))"
    + r"|(?P<blob>(?<![A-Za-z0-9])(?=[A-Za-z0-9]*?\d)(?=[A-Za-z0-9]*?[A-Za-z])[A-Za-z0-9]{16,}"
    + r"(?![A-Za-z0-9]))"
    + rf"|(?P<grouped>{_T_GROUPED_LONG})"
    # up to three separators between two digits: "0211 / 123 45 67"
    + r"|(?P<phone>\+\d[\d /()-]{6,}\d"
    + rf"|(?<![\w+./=-])(?!{_T_DATE})\(?0\d(?:[ /()-]{{0,3}}\d){{6,16}}(?!\d))"
    + rf"|(?P<grouped_short>{_T_GROUPED})"
    + r"|(?P<track>(?<![A-Za-z0-9])(?:1Z[0-9A-Z]{16}|[A-Z]{1,4}\d{6,}[A-Z]{0,2})(?![A-Za-z0-9]))"
    + r"|(?P<dashed>(?<![\w-])\d{2,}(?:-\d{2,})+(?![\w-]))"
    + r"|(?P<digits>\d{6,})"
)
_T_PLACE = (  # (from the word's start only, as _T_ADDRESS)
    r"(?<!\w)\w*(?:ablageort|abstellort|wunschort|ablageplatz|abstellplatz|abstellgenehmigung"
    r"|abstell-okay|abstellerlaubnis)\w*"
)
_T_PLACED = r"(?:erkannt|hinterlegt|abgelegt|abgestellt|zugestellt|deponiert|gespeichert)"
# "Abstellort" as a heading, the place on the next line that is no rule.
_T_PLACE_NEXT = re.compile(
    rf"(?im)(^[^\n]{{0,40}}?{_T_PLACE}[*_ \t]*:?[*_ \t]*\n(?:[-=_* \t]*\n)*)[ \t]*([^\n]+)"
)
_T_PLACE_SAME = re.compile(rf"(?i){_T_PLACE}[*_ \t]*:[*_ \t]*(\S[^\n]*)")
_T_PLACE_PHRASE = re.compile(
    rf"(?i)({_T_PLACE})[ \t]+(?!{_T_PLACED}\b)[^\n]{{1,80}}?[ \t]+({_T_PLACED})\b"
)
_T_RECIPIENT = (
    r"(?:(?:Zustell|Liefer|Versand|Rechnungs)-?(?:adresse|anschrift)|Empf(?:ä|ae)nger(?:in)?"
    r"|Geliefert an|Lieferung an|Versand an|Die Sendung geht an"
    # eBay: "Ihre Bestellung wird verschickt an:", older mails "Versandziel:"
    r"|(?:Ihre Bestellung )?wird verschickt (?:an|nach)|Versandziel"
    r"|Ship(?:ping)?[ -]?(?:To|Address)|Deliver(?:y(?: Address)?| to))"
)
_T_COUNTRY = r"(?:Deutschland|Germany|Österreich|Austria|Schweiz|DE|AT|CH)"
# The label alone on its line, then up to five lines and the line with the postcode: the
# postcode alone (a line with only the city below it goes too), "PLZ Ort", "Ort, PLZ" or
# "ORT BUNDESLAND PLZ".
_T_BARE_POSTCODE = (
    r"[ \t]*(?:D-)?\d{5}[ \t]*,?[ \t]*"
    rf"(?:\n[ \t]*(?!{_T_COUNTRY}\b)[^\W\d_][^\s\d:*_]*(?:[ \t]+[^\s\d:*_]+){{0,2}}[ \t]*(?=\n|\Z))?"
    r"(?=\n|\Z)"
)
_T_ADDRESS_BLOCK = re.compile(
    rf"(?im)^([*_ \t]*{_T_RECIPIENT}[*_ \t]*:?[*_ \t]*\n)(?:[^\n]*\n){{0,5}}?"
    rf"(?:{_T_BARE_POSTCODE}|[^\n:]{{0,60}}?\b\d{{5}}\b[^\n]*"
    r"|[ \t]*(?:(?:A|CH|D)[- ])?\d{4}[ \t]+[^\W\d_][^\n]*)"
)
_T_ADDRESS_LINE = re.compile(
    rf"(?im)^([*_ \t]*{_T_RECIPIENT}[*_ \t]*:[ \t]*)(\S[^\n]*\b\d{{5}}\b[^\n]*)$"
)
# "… an folgende Adresse zugestellt:" (DPD Austria), also at the end of a sentence: the
# lines below it up to the line with the postcode (four or five digits), at most four lines.
_T_ADDRESS_INTRO = re.compile(
    r"(?im)^([^\n]{0,80}?\b(?:(?:an[ \t]+)?(?:die[ \t]+)?folgende[nr]?[ \t]+(?:Adresse|Anschrift)"
    r"(?:[ \t]+(?:zugestellt|geliefert|gesendet|versendet|verschickt|zu))?"
    # "(bei einer Wunschzustellung ggf. abweichend)"; DPD in 2020: "Ich habe Ihr Paket
    # erfolgreich zugestellt:"
    r"(?:[ \t]*\([^()\n]{0,80}\))?|Ihr Paket erfolgreich zugestellt)[*_ \t]*:[*_ \t]*\n)"
    rf"(?:[^\n]*\n){{0,3}}?(?:{_T_BARE_POSTCODE}|[^\n:]{{0,60}}?\b\d{{5}}\b[^\n]*"
    r"|[ \t]*(?:(?:A|CH|D)[- ])?\d{4}[ \t]+[^\W\d_][^\n]*)"
)
# AliExpress: "Versand nach", then place and street without a postcode; in most layouts the
# name with the phone number "(+49) …" ends the block, in one it is a single line. The
# block has as many lines as the address needs (street, addition, town, state, postcode),
# so it is read up to the line with the phone number, never beyond the next label.
_T_ALI_SHIP_TO = re.compile(
    r"(?im)^((?:Versand nach|Ship to|Lieferanschrift)[ \t]*\n)"
    r"(?:(?P<lines>(?:(?![^\n]*\(\+\d+\)|Zahlungsmethode\b|Payment method\b)[^\n]*\n){0,12})"
    r"(?P<name>(?!Zahlungsmethode\b|Payment method\b)[^\n(]*)\(\+\d+\)[^\n]*"
    r"|(?P<single>[^\n]+))"
)
# Amazon until 2025: "Die Sendung geht an:", the first name and the place on the lines below.
_T_AMAZON_SHIP_TO = re.compile(
    r"(?im)^([*_ \t]*Die Sendung geht an:[*_ \t]*\n[ \t]*)([^\n]{2,40}?)([ \t]*\n[ \t]*)"
    r"([^\n\d]{2,40}?)([ \t]*\n[ \t]*(?:Gesamtbetrag|Bestellnummer))"
)
# The recipient's name behind "Empfänger:" or on the line below it, without an address (DPD).
_T_RECIPIENT_NAME = re.compile(
    r"((?i:Empf(?:ä|ae)nger(?:in)?)[*_ \t]*:[*_ \t]*(?:\n[*_ \t]*)?)"
    r"((?:[A-ZÄÖÜ][^\W\d_]+(?:-[A-ZÄÖÜ][^\W\d_]+)*|[A-ZÄÖÜ]\.)"
    r"(?:[ \t]+(?:von|van|de|der|zu))?[ \t]+[A-ZÄÖÜ][^\W\d_]+(?:-[A-ZÄÖÜ][^\W\d_]+)*)"
    r"(?![^\W\d_])"
)
# GLS delivery mail: "*an NAME*" and the address lines up to the next rule or empty line.
_T_DELIVERED_TO = re.compile(
    r"(?m)^(\*an )([^*\n]{2,60})(\*[ \t]*\n)((?:[ \t]*[^\s-][^\n]*\n){0,4})"
)
# A sender is kept only if it is a company or a known shop or carrier, never a person:
# a legal form or a shop word anywhere, or a shop that is also a first name as the whole name.
_T_COMPANY = re.compile(
    r"(?i)(?<![\w.])(?:GmbH|AG|KG|UG|SE|OHG|GbR|Ltd|Inc|mbH|SARL|e\.\s?K|e\.\s?V|B\.\s?V|Co"
    r"|shop|store|versand|online|amazon|ebay|zalando|about you|media ?markt|saturn|ikea|lidl"
    r"|tchibo|bonprix|thomann|notebooksbilliger|cyberport|galaxus|decathlon|kaufland|shein"
    r"|temu|aliexpress|dhl|dpd|gls|hermes|ups|fedex|deutsche post)(?![^\W_])"
)
_T_SHOP = re.compile(r"(?i)(?:otto|conrad|alternate)(?:\.(?:de|com))?")
# Words of a service, never of a person: "Kundenservice", "Paket Team", "Mein Laden".
_T_SERVICE = re.compile(
    r"(?i)service|team|kunde|support|info|versand|paket|päckchen|post|shop|store|news|bestell"
    r"|liefer|zustell|sendung|tracking|logisti|express|reply|mail|konto|portal|zentrale|markt"
    r"|handel|laden|center|centrum|zentrum|deutschland|germany|quantum|prime|payment|filiale"
    r"|station|kiosk|apotheke|verlag|bank|versicher|studio|technik|elektr|möbel|digital|media"
    r"|group|gruppe|international|rechnung|einkauf|artikel|retoure|status|update|abholung"
)
_T_NAME_TOKEN = re.compile(
    r"[A-ZÄÖÜ][a-zäöüßéèáàç]+(?:-[A-ZÄÖÜ][a-zäöüßéèáàç]+)*|[A-ZÄÖÜ]{2,}(?:-[A-ZÄÖÜ]{2,})*"
    r"|[A-ZÄÖÜ]\."
)
_T_PARTICLE = re.compile(r"von|van|de|der|den|zu|zur|vom|und|&")
_T_TITLE = re.compile(r"(?i)(?:herrn?|frau|familie|fam\.?|dr\.?|prof\.?|mr\.?|mrs\.?|ms\.?)")
# Capitalised words that are never (part of) a person's name.
_T_NOT_NAME = re.compile(
    r"(?i)(?:ihr\w*|ihnen|dein\w*|dir|sie|du|uns|unser\w*|eure?\w*|die|der|das|den|dem|des"
    r"|ein\w*|mein\w*|kein\w*|alle\w*|diese\w*|jede\w*|heute|morgen|gestern|montag|dienstag"
    r"|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag|januar|februar|märz|april|mai"
    r"|juni|juli|august|september|oktober|november|dezember|zusammen|leute|freunde|welt"
    r"|nachbar\w*|empf(?:ä|ae)nger\w*|hausbewohner\w*|mitbewohner\w*|briefkasten|packstation"
    r"|ablageort|wunschort|abstellort|zusteller\w*|bote\w*|fahrer\w*|besteller\w*"
    r"|k(?:ä|ae)ufer\w*|verk(?:ä|ae)ufer\w*|nutzer\w*|user|gast|mitglied|interessent\w*"
    r"|damen|herren|person|dritte\w*|angeh(?:ö|oe)rige\w*|ehepartner\w*|max|mustermann"
    r"|beispielversender|beispielnachbar|beispiel|erforderlich|unbekannt|vorhanden|neu\w*|wichtig\w*"
    # officers of a company in front of their names ("Geschäftsführer Vorname Nachname")
    r"|gesch(?:ä|ae)ftsf(?:ü|ue)hr\w*|vorstand\w*|vorsitz\w*|inhaber\w*|direktor\w*"
    r"|gesellschafter\w*"
    # status words a mail may put above an address ("Abholbereit\nHauptstraße 1\n…")
    r"|abholbereit|zugestellt|hinterlegt|abholort|abholung|abholstation|bereit|abgestellt"
    r"|abgegeben|trafik|zustellung|zustellort|lieferung|lieferort|sendung|paket|status"
    r"|adresse|anschrift|filiale|paketshop|hinweis)"
)
_T_NO_STREET = re.compile(r"(?i)packstation|postfiliale|filiale|paketshop|postfach|paketbox")
# The name line below "Versender" / "Absender", with the address lines up to the postcode.
_T_SENDER_BLOCK = re.compile(
    r"(?im)^([*_ \t]*(?:Versender|Absender)(?:in)?[*_ \t]*:?[*_ \t]*\n)([^\n]+)"
    rf"((?:\n(?![ \t]*\n)[^\n]*){{0,2}}?\n(?:{_T_BARE_POSTCODE}|[^\n]*\b\d{{5}}\b[^\n]*))?"
)
_T_SENDER_NEXT = re.compile(r"(?i)(Paket von(?: dem Absender)?[ \t]*\n\s*)([^\n]+)")
# "Sendung von NAME wurde ...", "Paket von NAME mit der Sendungsnummer", "Sendung von NAME, ...",
# "Paket von NAME." and UPS' "auf Antrag von NAME , um ...": up to four capitalised words in
# front of a verb, a comma or the end.
_T_SENDER_INLINE = re.compile(
    # Hermes glues the words together in its text part: "deine Sendungvon NAME findet …"
    r"(?m)((?:(?:Sendung|Paket|Päckchen|Lieferung|Antrag|Auftrag) ?von|(?:request|behalf) of) )"
    r"(?!(?:Ihnen|Ihre[mnrs]?|Dir|Deine[mnrs]?|Uns|Unsere[mnrs]?|Montag|Dienstag|Mittwoch"
    r"|Donnerstag|Freitag|Samstag|Sonnabend|Sonntag|Heute|Gestern|Morgen)\b)"
    r"((?:[A-ZÄÖÜ][^\s,:]* ){0,3}?[A-ZÄÖÜ](?:[^\s,:]*[^\s,:.])?)"
    r"(?= (?:wurde|wird|kommt|ist|befindet|findet|mit der|hat|liegt|konnte|kann|möchten|to)\b"
    r"|[ \t]?[,.]?[ \t]*$|[ \t]?[,.][ \t])"
)
# "Absender: NAME" / "Versender: NAME" / "Von: NAME" on one line.
_T_SENDER_SAME = re.compile(
    r"(?im)^([*_> \t]*(?:Versender(?:in)?|Absender(?:in)?|Von|From)[*_ \t]*:[*_ \t]*)"
    r"([^\W\d_][^\n\d,;|(<@]*?)[ \t]*(?=$|[,;|(<])"
)
# Neighbours and the person that took the parcel.
_T_NEIGHBOUR = re.compile(
    r"(?P<label>(?i:\bNachbar\w*|\babgegeben bei|\bEmpfangen von|\bUnterschrift"
    r"|\bentgegengenommen von|\b(?:ü|ue)bergeben an))"
    r"(?P<gap>[ \t]*[:(]?[ \t]*(?:(?:Herrn?|Frau|Familie|Fam\.)[ \t]+)?)"
    r"(?P<name>(?:[A-ZÄÖÜ]\.[ \t]?)?[A-ZÄÖÜ][^\W\d_]+(?:[-'’][^\W\d_]+)*"
    r"(?:[ \t]+[A-ZÄÖÜ][^\W\d_]+(?:[-'’][^\W\d_]+)*){0,2})"
)
# Amazon: "Vorname – Ort" on the line above the order number.
_T_AMAZON_LINE = re.compile(
    r"(?m)^([ \t]*)([^\W\d_][^\n–—-]{1,30}?)([ \t]+[–—-][ \t]+)([^\W\d_][^\n]{1,40}?)"
    r"([ \t]*\n(?:[ \t]*\n)*[ \t]*Bestell(?:nr\b|nummer))"
)
# The officers of a company in its legal footer ("Geschäftsführer: …", "Vorstand: …",
# "Vorsitzender des Aufsichtsrates: …"): public, but the names of persons all the same. The
# list ends at the register court or another part of the footer.
_T_OFFICER_WORDS = (
    r"gesch(?:ä|ae)ftsf(?:ü|ue)hr(?:er(?:in|innen)?|ung"
    r"|ende[rn]?[ \t]+(?:Direktor(?:en|in)?|Gesellschafter(?:in)?))"
    r"|vorstand|aufsichtsrat|vertreten[ \t]+durch|managing[ \t]+directors?|directors?"
)
# one person only: a separator after the name ends the list
_T_OFFICER_ONE = (
    r"vorsitzende[rs]?[ \t]+des[ \t]+aufsichtsrat(?:e?s)|aufsichtsratsvorsitzende[rs]?"
    r"|inhaber(?:in)?"
)
_T_OFFICERS = re.compile(
    rf"(?i:\b(?:{_T_OFFICER_WORDS}|(?P<one>{_T_OFFICER_ONE}))\b)"
    r"(?P<list>(?:(?!\b(?:Sitz|Amtsgericht|Registergericht|Handelsregister\w*|HR[AB]|USt|Umsatz"
    r"\w*|Steuer\w*|WEEE|Telefon|Tel|E-Mail|Auf diese)\b)[^\n]){1,300})"
)
# Where such a list may end early: at a separator of a one-line footer ("|", "·", " – ", " / ")
# or at the end of a sentence. A title, an initial or "Co." ends nothing.
_T_OFFICERS_END = re.compile(
    r"(?P<sep>[ \t]*[|·]|[ \t]+[–—/-][ \t])"
    r"|(?<![^\W\d_])(?!(?:Dr|Prof|Dipl|Ing|Co|[^\W\d_])\.)[^\W\d_]+(?=\.(?:[ \t]|$))"
)
# One name in such a list, with its titles: "Dr. Vorname Nachname", "Vorname de Nachname".
_T_OFFICER_WORD = r"[A-ZÄÖÜ][^\W\d_]+(?:-[A-ZÄÖÜ][^\W\d_]+)*"
_T_OFFICER_MIDDLE = r"[dD]e|[vV]an|[vV]on|der|zu|Di|Da|Le|La|[A-ZÄÖÜ]\."
_T_OFFICER = re.compile(
    r"(?<![^\W\d_])(?P<title>(?:(?:Dr|Prof)\.[ \t]*)*)"
    rf"(?P<name>{_T_OFFICER_WORD}(?:[ \t]+(?:{_T_OFFICER_MIDDLE}))*"
    rf"[ \t]+{_T_OFFICER_WORD})(?![^\W\d_])"
)
# In a line of names only a name may have a second given name: "Vorname Vorname Nachname".
_T_OFFICER_LONG = re.compile(
    r"(?<![^\W\d_])(?P<title>(?:(?:Dr|Prof)\.[ \t]*)*)"
    rf"(?P<name>{_T_OFFICER_WORD}(?:[ \t]+(?:{_T_OFFICER_MIDDLE}|{_T_OFFICER_WORD}))*"
    rf"[ \t]+{_T_OFFICER_WORD})(?![^\W\d_])"
)
# The role behind a name: "(CEO)", "(Vorsitzender)".
_T_OFFICER_ROLE = r"(?:[ \t]*\([^\W\d_][^()\n/:]{0,29}\))?"
# A part of a one-line footer that holds one name only: "| Dr. Vorname Nachname (CEO) |".
_T_OFFICER_PART = re.compile(
    r"[ \t]*" + _T_OFFICER.pattern + _T_OFFICER_ROLE + r"[ \t]*(?:[|·/–—-]|$)"
)
# The officers in the lines below their heading: "Vertreten durch die Geschäftsführung der
# Paket GmbH\nVorname Nachname, Dr. Vorname Nachname" or "Geschäftsführung:\nVorname
# Nachname\nVorname Nachname". The heading ends at the word, a colon or the company.
_T_OFFICER_ANY = (
    rf"(?:(?:Dr|Prof)\.[ \t]*)*{_T_OFFICER_WORD}"
    rf"(?:[ \t]+(?:{_T_OFFICER_MIDDLE}|{_T_OFFICER_WORD}))*"
    rf"[ \t]+{_T_OFFICER_WORD}(?![^\W\d_]){_T_OFFICER_ROLE}"
)
_T_OFFICER_LINES = re.compile(
    rf"(?m)(?P<head>^[ \t]*(?:<p>)?[^\n.:;<]{{0,30}}?"
    rf"(?i:\b(?:{_T_OFFICER_WORDS}|(?P<one>{_T_OFFICER_ONE}))\b)"
    r"(?:[ \t]*:|[ \t]+(?:der|des|von|of|the)[ \t]+[^\n.:;<]{1,60}?"
    r"\b(?:GmbH|mbH|AG|SE|KG|KGaA|UG|Ltd|Inc)\.?)?"
    r"[ \t]*(?:</p>|<br[ \t]*/?>)?[ \t]*\n)"
    rf"(?P<lines>(?:[ \t]*(?:<p>)?[ \t]*{_T_OFFICER_ANY}"
    rf"(?:[ \t]*(?:[,;|·&]|und)[ \t]*{_T_OFFICER_ANY})*"
    r"[ \t,]*(?:</p>|<br[ \t]*/?>)?[ \t]*(?:\n|\Z))+)"
)
# An address without a label: [name line,] street with house number, postcode and city.
_T_STREET = (
    r"[^\W\d_][^\n\d:@,;|]{2,40}?[ \t.]\d{1,4}(?:[ \t]?[a-zA-Z]\b)?"
    r"(?:[ \t]?[-/+][ \t]?\d{1,4}(?:[ \t]?[a-zA-Z]\b)?)?"
    # Austria: staircase and door ("12/3/7", "3/Top 5", "1/Stiege 2/Tür 4")
    r"(?:[ \t]?/[ \t]?(?:(?:Top|Stiege|Stg\.?|Tür|Haus)[ \t]?)?\d{1,4}(?:[ \t]?[a-zA-Z]\b)?){0,3}"
)
_T_PLZ = r"(?:DE?[- ])?(?!12345[ \t]+Musterstadt|00000[ \t]+Beispielstadt)\d{5}"
# Austria and Switzerland: four digits ("A-6789", "CH-8999"); only below a street line that
# names a street (four digits alone are too often a year or an amount).
_T_PLZ4 = r"(?:(?:A|CH)[- ])?\d{4}(?!\d)"
# What names a street: "-straße", "-strasse", "-str.", "-gasse", "-weg", "-platz", … as the end
# of a word or a word of its own ("Am Mühlendamm", "Hauptplatz", "Rheinufer").
_T_STREET_WORD = re.compile(
    r"(?i)(?:stra(?:ß|ss)e|str\.?|gasse|gässchen|gässli|weg|platz|allee|ring|damm|ufer"
    r"|chaussee|steig|stieg|pfad|zeile|gürtel|kai|lände|promenade|markt|graben|hof)(?![^\W\d_])"
)
_T_CITY = (
    r"[A-ZÄÖÜ][^\W\d_]+\.?(?:[ \t-]+(?:[A-ZÄÖÜ][^\W\d_]*\.?|am|an|der|im|in|bei|ob|vor"
    r"|a\.|d\.|\([^)\n]{1,20}\))){0,3}"
)
_T_PLAIN_BLOCK = re.compile(
    r"(?m)^(?P<lead>[*_> \t]*)"
    r"(?:(?P<name>[^\W\d_][^\n\d:@,;|]{3,50}?)[ \t]*,?[ \t]*\n(?P<lead2>[*_> \t]*))?"
    rf"(?P<street>{_T_STREET})[ \t]*,?[ \t]*\n(?P<lead3>[*_> \t]*)"
    rf"(?P<plz>{_T_PLZ}|{_T_PLZ4})[ \t]+(?P<city>{_T_CITY})"
)
_T_INLINE_ADDRESS = re.compile(
    rf"(?m)(?P<lead>^[*_> \t]*|[,:|·•][ \t]*)(?P<street>{_T_STREET})[ \t]*,[ \t]*"
    rf"(?P<plz>{_T_PLZ}|{_T_PLZ4})[ \t]+(?P<city>{_T_CITY})"
)
_T_PLZ_CITY = re.compile(
    rf"(?m)(?P<lead>^[*_> \t]*|[,|·•][*_ \t]*)(?P<plz>{_T_PLZ})"
    # also glued to the place ("12345Musterstadt")
    rf"(?:[ \t]+|(?=[A-ZÄÖÜ][a-zäöüß]))(?P<city>{_T_CITY})"
)
# Fields of a form, the value behind the label or on the line below it.
_T_FORM = re.compile(
    r"(?im)^(?P<label>[*_ \t]*(?P<kind>(?:Vor|Nach|Familien|Kunden|Empf(?:ä|ae)nger)name"
    r"|Name[ \t]*/[ \t]*(?:Unternehmen|Firma)"
    r"|Stra(?:ß|ss)e(?:nname)?(?:[ \t]*(?:&|und|/|\|)[ \t]*(?:Hausnummer|Haus-?Nr\.?|Nr\.?))?"
    r"|PLZ(?:[ \t]*(?:&|und|/|,|\|)[ \t]*Ort)?|Postleitzahl|Wohnort|Ort|Stadt)"
    r"[*_ \t]*:[*_ \t]*(?:\n[*_ \t]*)?)(?P<value>[^\n]*?)[ \t]*$"
)
# A place to pick a parcel up at, with its number ("Postfiliale 999", "Packstation 123"): the
# number tells where the recipient lives, so it is invented like a tracking number (the same
# place gets the same number in every mail of a run).
_T_PICKUP = r"(?:post)?filiale|packstation|poststation|paketshop|paketbox"
_T_PICKUP_NUMBER = re.compile(
    rf"(?i)(?<![^\W\d_])((?:{_T_PICKUP})[ \t]*(?:nr\.?[ \t]*)?)(\d{{2,6}})(?!\d)"
)
# Its street, learnt and then replaced wherever it stands: on the line below the place, up
# to the line with the postcode (maybe with an addition: "Hauptstr. 3, Supermarkt"), also in
# a text part that carries HTML ("Postfiliale 999</a><br />"), or in brackets behind it
# ("Filiale 999 (Hauptstraße 1, 12345 Ort)").
_T_MARKUP = r"(?:<[^<>\n]{0,300}>|[ \t*_>])*"
_T_PICKUP_STREET = re.compile(
    rf"(?im)^{_T_MARKUP}(?:pickup[ \t]+)?(?:{_T_PICKUP})\b[^\n]{{0,80}}\n"
    # DPD names the shop on a line of its own above its street
    rf"(?:{_T_MARKUP}[^\n\d]{{2,60}}\n)?{_T_MARKUP}(?P<street>{_T_STREET})"
    rf"(?![^\W_])[^\n]{{0,80}}\n{_T_MARKUP}(?:DE?-)?\d{{5}}(?:[ \t]|(?=[^\W\d_]))"
    rf"|(?:{_T_PICKUP})[ \t]*\d{{1,6}}[ \t]*\((?P<inline>{_T_STREET})[ \t]*,[ \t]*(?:D-)?\d{{5}}[ \t]"
)
# Quoted header lines of a forwarded mail: the recipients.
_T_QUOTED_TO = re.compile(r"(?im)^([> \t]*(?:An|To|Cc|Kopie):)[ \t]*\S[^\n]*$")
# A forwarded or answered mail: its outer sender is a person, whatever the address.
_T_FORWARD = re.compile(r"(?i)\s*(?:WG|Fwd?|FW|AW|Re)\s*:")
# Passed on by hand: the forwarder's own lines (a signature) may stand above the mail.
_T_PASSED_ON = re.compile(r"(?i)\s*(?:(?:AW|Re)\s*:\s*)*(?:WG|Fwd?|FW)\s*:")
_T_QUOTED_FROM = re.compile(
    r"(?im)^[>*_ \t]*(?:Von|From):[^\n]*\n(?:[^\n]*\n){0,3}?"
    r"[>*_ \t]*(?:Gesendet|Sent|Datum|Date|An|To|Betreff|Subject):"
)
# The attribution line some mail programs write above a quoted mail instead of a header block:
# "Am 14.11.26, 15:50 schrieb Name <addr>:", "On <date> at <time>, Name <addr> wrote:".
_T_ATTRIBUTION_DE = re.compile(
    r"^(?P<head>[> \t]*Am[ \t]+.{1,120}?\d{1,2}:\d{2}.{0,40}?[ \t]schrieb[ \t]+)"
    r"(?P<who>[^\n]{1,200}?)(?P<tail>[ \t]*:[ \t]*)$"
)
_T_ATTRIBUTION_EN = re.compile(
    r"^(?P<head>[> \t]*On[ \t]+.{1,120}?\d{1,2}:\d{2}(?::\d{2})?"
    r"(?:[ \t]*[AaPp]\.?[Mm]\b\.?)?(?:[ \t]*(?:GMT|UTC)?[ \t]*[+-]\d{2}:?\d{2})?[ \t,]*)"
    r"(?P<who>[^\n]{1,200}?)(?P<tail>[ \t]+wrote[ \t]*:[ \t]*)$"
)
_T_ATTRIBUTION_START = re.compile(r"^[> \t]*(?:Am|On)[ \t]")
# The domains of every sender the import knows (KNOWN_MAIL_DOMAINS of the integration, a test
# keeps both the same): only such a sender stays in an attribution line.
_T_KNOWN_DOMAINS = frozenset({
    "aliexpress.com", "amazon.de", "dhl.com", "dhl.de", "dhlecommerce.nl", "dpd.at", "dpd.de",
    "ebay.com", "eventim.de", "gls-group.eu", "gls-pakete.de", "gls-rtt.com",
    "paketankuendigung.myhermes.de", "service.dpd.de", "ups.com",
})
# One line of the header block a mail program quotes above a forwarded mail: the label
# (maybe bold or behind quote marks) and its value.
_T_QUOTED_LINE = re.compile(
    r"(?i)^(?P<head>[>*_ \t]*(?P<label>Von|From|Gesendet|Sent|Datum|Date|An|To|Cc|Bcc|Kopie"
    r"|Betreff|Subject|Antwort an|Reply-To)[*_ \t]*:[*_ \t]*)(?P<value>.*)$"
)
_T_QUOTED_KIND = {
    "von": "from", "from": "from", "betreff": "subject", "subject": "subject",
    "gesendet": "date", "sent": "date", "datum": "date", "date": "date",
}
_T_INVISIBLE = re.compile("[\u00ad\u034f\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
# eBay: the buyer's name and user name in the footer ("… von eBay an NAME (NUTZER) gesendet",
# "… von eBay gesendet an NAME (NUTZER)"), the user name (or the name) in the subject of a
# purchase confirmation and in "Willkommen zurück, NUTZER!".
_T_EBAY_FOOTER = re.compile(
    r"(?i)(\bvon eBay (?:an|gesendet an)[ \t]+)([^()\n]{3,60}?)([ \t]*\()([^()\s]{3,64})(\))"
)
_T_EBAY_HANDLE = re.compile(
    r"(?im)^(?P<head>)(?P<who>[^,\n]{3,64})(?=, Ihre Bestellung wurde bestätigt)"
    r"|(?P<hi>\bWillkommen zurück, )(?P<user>[^\s!,]{3,64})(?=!)"
)
_T_SELLER = re.compile(r"(?i)(Verk(?:ä|ae)ufer(?:in)?:[ \t]*\n?[ \t]*)([^\n]+)")
_T_GREETING = (
    r"(?i:Hallo|Hi|Hey|Moin|Servus|Guten (?:Tag|Morgen|Abend)|Liebe[rs]?"
    r"|Sehr geehrte[rs]?|Dear|Hello)(?:[ \t]+(?i:Herrn?|Frau|Familie|Mr\.?|Mrs\.?|Ms\.?))?"
)
_T_HELLO = re.compile(
    rf"(?m)^(?P<hello>[*_> \t]*{_T_GREETING})[ \t]+"
    r"(?P<name>[^\s,!:*]+(?:[ \t]+[^\s,!:*]+){0,3}?)(?P<end>[ \t]*[,!:*])"
)
# Without punctuation only capitalised words count: "Guten Tag Vorname Nachname".
_T_HELLO_BARE = re.compile(
    rf"(?m)^(?P<hello>[*_> \t]*{_T_GREETING})[ \t]+"
    r"(?P<name>[A-ZÄÖÜ][^\s,!:*]*(?:[ \t]+[A-ZÄÖÜ][^\s,!:*]*){0,2})(?P<end>[ \t]*)$"
)
_T_NAME2 = (
    rf"(?:{_T_NAME_TOKEN.pattern})(?:[ \t]+(?:von|van|de|der|zu))?[ \t]+(?:{_T_NAME_TOKEN.pattern})"
)
# Names in a subject: (pattern, a recipient?).
_T_SUBJECT_NAMES = (
    (re.compile(rf"\b(?:von|vom) ({_T_NAME2})(?![^\W\d_])"), False),
    (re.compile(rf"\b(?:für|an) ({_T_NAME2})(?![^\W\d_])"), True),
    (re.compile(rf"^(?:(?:WG|Fwd?|FW|AW|Re):\s*)*({_T_NAME2}) (?:hat|sendet|schickt|möchte)\b"),
     False),
)


def _t_hidden(text):
    """The tracking numbers a link or an image text carries."""
    return [match.group("value") or match.group(0) for match in _T_HIDDEN.finditer(text)]


class _TText(_Text):
    """Tester mode: a tracking number that stands only in a link or in the text of an image
    is kept as a marked number (nothing else of such an attribute is ever taken)."""

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if self.skip:
            return
        for name, value in attrs:
            if value and name in ("href", "alt", "title", "aria-label"):
                self.out.extend(f"\x00{number}\x00" for number in _t_hidden(value))


def _t_html_to_text(markup):
    """html_to_text, plus one note line for each number that is not in the visible text."""
    parser = _TText()
    parser.feed(markup.replace("\x00", ""))
    text = "".join(parser.out)
    visible, noted = _T_HIDDEN_MARK.sub("", text), set()

    def note(match):
        number = match.group(1)
        if number in visible or number in noted:
            return ""
        noted.add(number)
        return "\n" + _T_HIDDEN_NOTE.format(number) + "\n"

    text = _T_HIDDEN_MARK.sub(note, text)
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


class _TUsage(Exception):
    """A wrong call; the message never contains a value of an option."""


def _t_parse(args):
    """(paths, out dir or None, zip?, help?, without values?, salt file or None,
    {option: [values]})."""
    paths, out, pack, usage, values = [], None, False, False, {key: [] for key in _T_OPTIONS}
    bare, salt, i = False, None, 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            paths.extend(args[i:])
            break
        if not arg.startswith("-") or arg == "-":
            paths.append(arg)
            continue
        name, equals, value = arg.partition("=")
        key = name[2:]
        if name in ("-h", "--help") and not equals:
            usage = True
        elif name == "--zip" and not equals:
            pack = True
        elif name == _T_BARE and not equals:
            bare = True
        elif name.startswith("--") and (key in ("out", "salt") or key in _T_OPTIONS):
            if not equals:
                if i >= len(args) or args[i].startswith("--"):
                    raise _TUsage(f"Option {name} braucht einen Wert.")
                value = args[i]
                i += 1
            if key == "out":
                out = value
            elif key == "salt":
                salt = value
            else:
                values[key].extend(value.split(";"))
        else:
            raise _TUsage(f"Unbekannte Option {name}")
    return paths, out, pack, usage, bare, salt, values


def _t_variants(value, gap=r"[\s._-]*"):
    """Regex source of a value: umlauts also as ae/oe/ue (and back), ß as ss, any spacing."""
    low, out, i = value.lower(), [], 0
    while i < len(low):
        char, two = low[i], low[i:i + 2]
        if char in _T_UMLAUT:
            out.append(f"(?:{char}|{_T_UMLAUT[char]}e|{_T_UMLAUT[char]})")
        elif two in _T_DIGRAPH:
            out.append(f"(?:{two}|{_T_DIGRAPH[two]})")
            i += 1
        elif char == "ß" or two == "ss":
            out.append("(?:ß|ss)")
            i += two == "ss"
        elif char.isspace() or char == "-":
            if not out or out[-1] != gap:
                out.append(gap)
        else:
            out.append(re.escape(char))
        i += 1
    return "".join(out)


def _t_street(street):
    """(regex, replacement) for a street in every spelling, with any or no house number."""
    name = re.sub(r"[\s,.]*\d+\s*[A-Za-z]?(?:\s*[-/+]\s*\d+\s*[A-Za-z]?)?\s*$", "", street)
    name = name.strip() or street
    ending = re.match(r"(?i)(.+?)[\s.-]*str(?:a(?:ß|ss)e|\.)?$", name)
    source = _t_variants(name)
    if ending:  # Hauptstraße = Hauptstrasse = Hauptstr. = Haupt-Str
        source = _t_variants(ending.group(1)) + r"[\s.-]*str(?:a(?:ß|ss)e|\.)?"
    # with any house number behind it, or the street name alone
    number = r"(?P<number>[\s,.]*\d{1,4}(?:\s?[a-z](?![^\W_]))?(?![^\W_]))?"
    return (
        re.compile(_T_B0 + source + _T_B1 + number, re.I),
        lambda m: "Musterstraße 1" if m.group("number") else "Musterstraße",
    )


def _t_given(values):
    """([(regex, replacement)], [too short option], [digits no invented number may contain])."""
    rules, short, avoid = [], [], []

    def add(source, replacement, flags=re.I):
        rules.append((re.compile(source, flags), replacement))

    def usable(key, value, length):
        if len(re.sub(r"\W", "", value)) >= length:
            return True
        short.append(key)
        return False

    for mail in values["email"]:
        if usable("email", mail, 3):
            add(re.escape(mail), _T_MAIL)
            add(re.escape(mail.replace("@", "%40")), _T_MAIL)
    for name in values["name"]:
        tokens = [t for t in name.split() if re.search(r"\w", t)]
        if not usable("name", name, 3):
            continue
        parts = [_t_variants(t) for t in tokens]
        gap = r"[\s.,_+-]*"
        if len(tokens) > 1:
            add(_T_B0 + gap.join(parts) + _T_B1, "Max Mustermann")
            add(_T_B0 + parts[-1] + gap + gap.join(parts[:-1]) + _T_B1, "Max Mustermann")
            if len(tokens[-1]) >= 4:  # jprobst, j.probst
                add(_T_B0 + _t_variants(tokens[0][0]) + "[._-]?" + parts[-1] + _T_B1,
                    "Max Mustermann")
            if len(tokens[0]) >= 5:  # joergp
                add(_T_B0 + parts[0] + "[._-]?" + _t_variants(tokens[-1][0]) + _T_B1, "Max")
        for i, token in enumerate(tokens):
            replacement = "Mustermann" if i == len(tokens) - 1 else "Max"
            if len(token) >= 3:
                add(_T_B0 + parts[i] + "(?:'?s)?" + _T_B1, replacement)
            elif len(token) == 2:  # too short for any spelling: exactly as typed
                add(_T_B0 + re.escape(token) + _T_B1, replacement, 0)
    for street in values["street"]:
        if usable("street", street, 4):
            rules.append(_t_street(street))
    for postcode in values["postcode"]:
        if usable("postcode", postcode, 4):
            add(r"(?<!\d)" + r"\s*".join(map(re.escape, postcode.split())) + r"(?!\d)", "12345")
            avoid.append(re.sub(r"\D", "", postcode))
    for city in values["city"]:
        if usable("city", city, 2):
            add(_T_B0 + _t_variants(city, r"[\s-]*") + _T_B1, "Musterstadt")
    for phone in values["phone"]:
        digits = re.sub(r"\D", "", phone)
        if not usable("phone", digits, 6):
            continue
        if phone.strip().startswith("+"):
            digits = "00" + digits
        gap = r"[\s/().-]*"
        if digits.startswith("0049"):
            national = digits[4:].lstrip("0")
        elif digits.startswith("00"):
            national = None
        else:
            national = digits[1:] if digits.startswith("0") else digits
        if national:  # 0151 ..., +49 151 ..., 0049 (0) 151 ...
            prefix = rf"(?:(?:\+|00){gap}49{gap}(?:0{gap})?|0{gap})?"
            add(r"(?<![\d+])\(?" + prefix + gap.join(national) + r"(?!\d)", _T_PHONE)
        else:
            add(r"(?<![\d+])(?:\+|00)?" + gap + gap.join(digits[2:]) + r"(?!\d)", _T_PHONE)
        avoid.append(national or digits[2:])
    return rules, sorted(set(short)), [a for a in avoid if a]


def _t_address_parts(block):
    """(name, street, postcode, city) of the lines of an address; "" for what is not found."""
    lines = [" ".join(line.split()).strip("*_, ") for line in block.split("\n")]
    lines = [line for line in lines if line]
    # eBay puts the country above the name
    while len(lines) > 1 and re.fullmatch(rf"(?i){_T_COUNTRY}", lines[0]):
        lines.pop(0)
    # five digits anywhere, four (Austria, Switzerland) only in front of the place
    code = re.compile(r"(?<!\d)\d{5}(?!\d)|^(?:(?:A|CH|D)[- ])?(?P<four>\d{4})(?=[ \t]+[^\W\d_])")
    at = next((i for i, line in enumerate(lines) if code.search(line)), None)
    name = re.split(r"[+\d]", lines[0])[0].strip("*_, ") if lines else ""
    if not at:  # no postcode, or nothing in front of it
        return ("" if at == 0 else name), "", "", ""
    found = code.search(lines[at])
    postcode = found.group("four") or found.group(0)
    lines[at] = re.sub(r"^(?:A|CH|D)[- ](?=\d{4}\b)", "", lines[at])
    region = re.compile(r"[A-Z]{2}|NRW")
    country = re.compile(rf"(?i){_T_COUNTRY}")
    rest = re.sub(r"\bD-|[,;]", " ", lines[at].replace(postcode, " ")).split()
    city = " ".join(word for word in rest if not region.fullmatch(word))
    before = lines[1:at]
    if not city:
        below = lines[at + 1] if at + 1 < len(lines) else ""
        if below and not re.search(r"\d", below) and not country.fullmatch(below):
            city = below
        elif len(before) >= 2:
            for line in reversed(before):
                if not re.search(r"\d", line) and not region.fullmatch(line):
                    city = line
                    before.remove(line)
                    break
    before = [line for line in before if not region.fullmatch(line)]
    # the street: a line with letters, with its house number or above it ("Lindenweg" / "7,")
    before = [line for line in before if re.search(r"[^\W\d_]{3}", line)]
    streets = [line for line in before if re.search(r"\d", line)] or before[-1:]
    return name, (streets[0] if streets else ""), postcode, city


def _t_name_line(name):
    """True for the line above a street that can only be a name: one to four capitalised
    words (a title may stand in front), no company, no service, no common word."""
    tokens = name.split()
    return bool(
        1 <= len(tokens) <= 4
        and not name.rstrip("*_ \t").endswith(":")
        and all(
            _T_NAME_TOKEN.fullmatch(t) or _T_PARTICLE.fullmatch(t) or _T_TITLE.fullmatch(t)
            for t in tokens
        )
        and not any(_T_NOT_NAME.fullmatch(t) for t in tokens)
        and not _t_company(name) and not _T_SERVICE.search(name)
        and not _T_STREET_WORD.search(name)
    )


def _t_person(name):
    """True for a name that looks like a person's: two to four capitalised words, no company."""
    tokens = name.split()
    return bool(
        2 <= len(tokens) <= 4
        and all(_T_NAME_TOKEN.fullmatch(t) or _T_PARTICLE.fullmatch(t) for t in tokens)
        and _T_NAME_TOKEN.fullmatch(tokens[0]) and _T_NAME_TOKEN.fullmatch(tokens[-1])
        and not any(_T_NOT_NAME.fullmatch(t) for t in tokens)
        and not _t_company(name) and not _T_SERVICE.search(name)
    )


class _TScrubber:
    """Scrubs texts of one run; the same number becomes the same invented number in every mail.

    Every mail is scrubbed twice: the first pass (``learn``) only collects what the rules
    find (recipients, their streets, postcodes and places, private senders, neighbours,
    drop-off places), the second pass replaces these in every mail of the run.
    """

    def __init__(self, values, salt=None):
        self.rules, self.short, self.avoid = _t_given(values)
        self.learned = {}  # text found in one mail -> its replacement in every mail
        self.words = {}  # single word of a recipient's name (lower case) -> replacement
        self.streets, self.postcodes, self.cities = set(), set(), set()
        self._learning = False
        self._learnt = None  # compiled rules of what was learnt
        # The tester's own salt invents the same numbers in every run; without a secret an
        # invented number could be traced back by trying.
        self.fixed = salt is not None
        self._salt = secrets.token_hex(16) if salt is None else salt
        self._runs = {}
        self._mailboxes, self._tags = {}, {}  # real address / plus part (lower case) -> number
        self.items = {}  # Amazon item's ASIN -> its invented name (_THtml)
        self.titles = {}  # Amazon item's name in any mail of the run -> its ASIN (_t_learn_amazon)
        self.sellers = {}  # marketplace seller's brand (lower case) -> invented one (seller)
        self._sellers = None  # (compiled from ``sellers``)
        self.html_parts = {}  # part of a link or an attribute -> scrubbed (_THtml._scrub)
        # what must not be readable in a result: every value and every part of a name
        self._check = {v.casefold() for key in values for v in values[key] if len(v) >= 3}
        self._check.update(t.casefold() for v in values["name"] for t in v.split() if len(t) >= 3)
        # what marks a sender address as the tester's own: the mail address, the surname
        surnames = [v.split()[-1].casefold() for v in values["name"] if len(v.split()[-1]) >= 4]
        self.own = {v.casefold() for v in values["email"] if len(v) >= 3} | set(surnames)
        for old, new in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
            self.own.update(name.replace(old, new) for name in surnames)

    # ----- first pass -----
    def learn(self, text, subject="", display="", domain="", recipients=()):
        """Remember what the rules find in one mail; nothing is returned."""
        self._learning, self._learnt = True, None
        try:
            for name in recipients:
                if "," in name:  # "Nachname, Vorname"
                    name = " ".join(reversed([part.strip() for part in name.split(",", 1)]))
                if _t_person(name):
                    self._person(name)
            name = re.sub(r"(?i)\s+(?:via|über|bei)\s+.*$", "", display).strip()
            if _t_person(name) and not any(
                t.casefold() in domain for t in name.split() if len(t) >= 4
            ):
                self._note(name, "Beispielversender")
            for pattern, recipient in _T_SUBJECT_NAMES:
                for match in pattern.finditer(subject):
                    if _t_person(match.group(1)):
                        if recipient:
                            self._person(match.group(1))
                        else:
                            self._note(match.group(1), "Beispielversender")
            self.scrub(subject)
            self.scrub(text)
        finally:
            self._learning = False

    def _note(self, found, replacement, single=r"(?!)"):
        # Only what cannot be a common word: two words or more, or a user name.
        found = found.strip("*_ \t,")
        if self._learning and len(found) >= 5 and re.search(r"[^\W\d_]", found) and (
            len(found.split()) >= 2 or re.search(single, found)
        ):
            self.learned.setdefault(found, replacement)

    def _person(self, name, single="Max"):
        """A recipient: the whole name and each of its words are replaced in every mail."""
        if not self._learning:
            return
        tokens = [t.strip(".,;:()*_") for t in name.split()]
        tokens = [t for t in tokens if t and not _T_TITLE.fullmatch(t)]
        if not tokens or len(tokens) > 4 or _t_company(name) or any(
            not re.fullmatch(r"[^\W\d_](?:[^\W\d_]|['’.-])*", t) or _T_NOT_NAME.fullmatch(t)
            or not (t[0].isupper() or _T_PARTICLE.fullmatch(t)) for t in tokens
        ):
            return
        if len(tokens) > 1:
            self._note(" ".join(tokens), "Max Mustermann")
        for i, token in enumerate(tokens):
            if len(token.strip(".")) >= 3 and not _T_PARTICLE.fullmatch(token):
                last = len(tokens) > 1 and i == len(tokens) - 1
                self.words.setdefault(token.casefold(), "Mustermann" if last else single)

    def _recipient(self, name, street, postcode, city):
        """The parts of a recipient's address: replaced wherever they stand."""
        if not self._learning:
            return
        if len(name.split()) <= 4:
            self._note(name, "Max Mustermann")
            if len(name.split()) >= 2:
                self._person(name)
        bare = re.sub(r"[\s,.]*\d.*$", "", street).strip()
        if len(bare) >= 5 and re.search(r"[^\W\d_]{3}", bare) and not _T_NO_STREET.search(bare):
            self.streets.add(street)
        if postcode and postcode not in ("12345", "00000"):
            self.postcodes.add(postcode)
        if len(city) >= 3 and not re.search(r"\d", city) and not re.fullmatch(
            rf"(?i){_T_COUNTRY}|Musterstadt|Beispielstadt", city
        ):
            self.cities.add(city)

    def _pickup_street(self, street):
        """The street of a pickup place (``_T_PICKUP_STREET``): replaced wherever it stands."""
        bare = re.sub(r"[\s,.]*\d.*$", "", street).strip()
        if len(bare) >= 4 and re.search(r"[^\W\d_]{3}", bare):
            self.streets.add(street.strip())

    def _pickup_number(self, match):
        """An invented number for a pickup place; never with a 0 in front, which together with
        the postcode behind it ("Packstation 081 12345") would read as a phone number."""
        real, invented = match.group(2), self._run(match.group(2))
        if invented[0] == "0":
            invented = next(d for d in "123456789" if d != real[0]) + invented[1:]
        return match.group(1) + invented

    def _rules(self):
        """The compiled rules of everything learnt, the longest first."""
        if self._learnt is None:
            rules = [_t_street(street) for street in sorted(self.streets, key=len, reverse=True)]
            for postcode in sorted(self.postcodes):
                # four digits only in front of a place: they may as well be a year or an amount
                if len(postcode) >= 5:
                    rules.append((re.compile(rf"(?<!\d){postcode}(?!\d)"), "12345"))
                else:
                    rules.append((re.compile(
                        rf"(?<![\d.,:/]){postcode}(?=[ \t]+[^\W\d_])"), "12345"))
                if postcode not in self.avoid:
                    self.avoid.append(postcode)
            for city in sorted(self.cities, key=len, reverse=True):
                source = _T_B0 + _t_variants(city, r"[\s-]*") + _T_B1
                rules.append((re.compile(source, re.I), "Musterstadt"))
            for word in sorted(self.words, key=len, reverse=True):
                source = _T_B0 + _t_variants(word) + "(?:'?s)?" + _T_B1
                rules.append((re.compile(source, re.I), self.words[word]))
            self._learnt = rules
        return self._learnt

    # ----- the rules that also learn -----
    def _block(self, match):
        self._recipient(*_t_address_parts(match.group(0).split("\n", 1)[1]))
        return match.group(1) + "Max Mustermann\nMusterstraße 1\n12345 Musterstadt"

    def _line(self, match):
        self._recipient(*_t_address_parts(match.group(2).replace(",", "\n")))
        return match.group(1) + "Max Mustermann, Musterstraße 1, 12345 Musterstadt"

    def _ali_ship_to(self, match):
        # "Lieferanschrift" is a label of other mails too: a block an earlier rule replaced stays
        if re.match(r"[ \t]*(?:Max Mustermann|Musterstraße 1)\b", match.group(0).split("\n", 1)[1]):
            return match.group(0)
        if match.group("single") is not None:
            self._note(match.group("single"), "Musterstraße 1, Musterstadt")
            return match.group(1) + "Musterstraße 1, Musterstadt"
        self._person(match.group("name").strip())
        for line in match.group("lines").splitlines():
            self._note(line, "Musterstraße 1, Musterstadt")
        return match.group(1) + f"Musterstraße 1, Musterstadt\nMax Mustermann {_T_PHONE}"

    def _delivered(self, match):
        self._recipient(*_t_address_parts(match.group(2) + "\n" + match.group(4)))
        return match.group(1) + "Max Mustermann" + match.group(3) + (
            "Musterstraße 1\n12345 Musterstadt\n" if match.group(4) else "")

    def _recipient_name(self, match):
        """A person's name behind "Empfänger:", without an address."""
        name = match.group(2)
        if not _t_person(name):
            return match.group(0)
        self._person(name)
        return match.group(1) + "Max Mustermann"

    def _amazon_ship_to(self, match):
        self._person(match.group(2).strip())
        self._recipient("", "", "", match.group(4).strip())
        return f"{match.group(1)}Max{match.group(3)}Musterstadt{match.group(5)}"

    def _form(self, match):
        """A field of a form: name, street, or postcode and place."""
        kind, value = match.group("kind").casefold(), match.group("value")
        if kind.startswith(("plz", "postleitzahl", "ort", "wohnort", "stadt")):
            found = re.fullmatch(rf"({_T_PLZ}|{_T_PLZ4})[ \t]+({_T_CITY})", value)
            if found:
                self._recipient("", "", re.sub(r"\D", "", found.group(1)), found.group(2))
                return match.group("label") + "12345 Musterstadt"
            if kind.startswith(("plz", "postleitzahl")) and re.fullmatch(_T_PLZ, value):
                self._recipient("", "", re.sub(r"\D", "", value), "")
                return match.group("label") + "12345"
            if kind.startswith("plz") or kind.startswith("postleitzahl") or not (
                re.fullmatch(_T_CITY, value) and not _T_SERVICE.search(value)
                and not any(_T_NOT_NAME.fullmatch(word) for word in value.split())
            ):
                return match.group(0)
            self._recipient("", "", "", value)
            return match.group("label") + "Musterstadt"
        if kind.startswith("stra"):
            found = re.match(_T_STREET, value)
            if not found:
                return match.group(0)
            self._recipient("", found.group(0), "", "")
            return match.group("label") + "Musterstraße 1"
        if not _t_name_line(value):
            return match.group(0)
        if kind.startswith("vor"):
            self._person(value)
            return match.group("label") + "Max"
        if kind.startswith(("nach", "familien")):
            self._person(value, "Mustermann")
            return match.group("label") + "Mustermann"
        self._person(value)
        return match.group("label") + "Max Mustermann"

    def _hello(self, match):
        words = [word for word in match.group("name").split() if not re.search(r"\d", word)]
        titled = re.search(r"(?i)(?:Herrn?|Frau|Mr|Mrs|Ms)\.?$", match.group("hello"))
        self._person(" ".join(words), "Mustermann" if titled else "Max")
        return f"{match.group('hello')} Max Mustermann{match.group('end')}"

    def _sender(self, match):
        """A person as sender becomes a placeholder, a company stays; the address never stays."""
        name = match.group(2)
        if not _t_company(name):
            if match.re is _T_SELLER:
                # eBay writes the handle twice, one line below the other: then it is one
                # even without a digit or a dash ("beispielverkaeufer")
                again = match.string.startswith(f"\n{name.strip()}\n", match.end())
                self._note(name, "beispielshop", r"." if again else r"[-_.\d]")
            else:
                self._note(name, "Beispielversender")
            placeholder = "beispielshop" if match.re is _T_SELLER else "Beispielversender"
            name = re.sub(r"[^*_\s](?:[^*\n]*[^*_\s])?", placeholder, name, count=1)
        address = match.re is _T_SENDER_BLOCK and match.group(3)
        return match.group(1) + name + ("\nBeispielweg 2\n00000 Beispielstadt" if address else "")

    def _ebay_footer(self, match):
        """eBay's footer: the buyer's name and user name, replaced in every mail."""
        name, user = match.group(2), match.group(4)
        if _t_person(name):
            self._person(name)
        self._note(user, "beispielnutzer", r".")
        return f"{match.group(1)}Max Mustermann{match.group(3)}beispielnutzer{match.group(5)}"

    def _ebay_handle(self, match):
        """The buyer's user name (or name) in a purchase confirmation."""
        if match.group("hi") is not None:
            self._note(match.group("user"), "beispielnutzer", r".")
            return match.group("hi") + "beispielnutzer"
        who = match.group("who").strip()
        if _t_person(who):
            self._person(who)
            return "Max Mustermann"
        if " " in who or _t_company(who):
            return match.group(0)
        self._note(who, "beispielnutzer", r".")
        return "beispielnutzer"

    def _amazon(self, match):
        self._person(match.group(2))
        self._recipient("", "", "", match.group(4).strip())
        return f"{match.group(1)}Max{match.group(3)}Musterstadt{match.group(5)}"

    def _plain(self, match):
        name, street = match.group("name"), match.group("street")
        postcode = re.sub(r"\D", "", match.group("plz"))
        if len(postcode) == 4 and not _T_STREET_WORD.search(street):
            return match.group(0)  # four digits below no street: no postcode
        if name is None:
            head = match.group("lead")
        else:
            if _t_person(name.strip()):
                self._recipient(name.strip(), street, postcode, match.group("city"))
                name = "Max Mustermann"
            elif _t_name_line(name.strip()):  # a single name, a name with a title
                self._recipient("", street, postcode, match.group("city"))
                name = "Max Mustermann"
            head = f"{match.group('lead')}{name}\n{match.group('lead2')}"
        return f"{head}Musterstraße 1\n{match.group('lead3')}12345 Musterstadt"

    def _inline(self, match):
        if len(re.sub(r"\D", "", match.group("plz"))) == 4 and not _T_STREET_WORD.search(
            match.group("street")
        ):
            return match.group(0)
        return f"{match.group('lead')}Musterstraße 1, 12345 Musterstadt"

    def _neighbour(self, match):
        name, label = match.group("name"), match.group("label").casefold()
        first = name.split()[0]
        if _T_NOT_NAME.fullmatch(first) or _t_company(name):
            return match.group(0)
        neighbour = label.startswith(("nachbar", "abgegeben"))
        replacement = "Beispielnachbar" if neighbour else "Max Mustermann"
        self._note(name, replacement)
        return match.group("label") + match.group("gap") + replacement

    def _place(self, match):
        found = match.group(match.re.groups)
        if "Garage" not in found:
            self._note(found, "Garage")
        return (match.group(1) if match.re is _T_PLACE_NEXT else "") + "Ablageort: Garage"

    def _officers(self, match):
        """The persons in a list of a company's officers; a company in it stays.

        Only where they stand, nothing is learnt: what follows "Inhaber" may be a brand.
        """
        names, rest, pos, out = match.group("list"), "", 0, ""
        for end in _T_OFFICERS_END.finditer(names):
            # "Geschäftsführung: Vorname Nachname | Dr. Vorname Nachname" goes on
            part = (
                end.group("sep") and not match.group("one")
                and _T_OFFICER_PART.match(names, end.end())
            )
            if not (part and _t_person(part.group("name"))):
                cut = end.start() if end.group("sep") else end.end()
                # what follows may be the next list: "| Vorsitzender des Aufsichtsrates: …"
                names, rest = names[:cut], _T_OFFICERS.sub(self._officers, names[cut:])
                break
        while True:
            found = _T_OFFICER.search(names, pos)
            if not found:
                break
            if _t_person(found.group("name")):
                out += names[pos:found.start()] + found.group("title") + "Erika Beispiel"
                pos = found.end()
            else:
                # "DHL Paket GmbH Vorname Nachname": try again from the next word
                step = found.start("name") + len(found.group("name").split()[0])
                out += names[pos:step]
                pos = step
        return match.group(0)[:match.start("list") - match.start()] + out + names[pos:] + rest

    def _officer_lines(self, match):
        """The names below a heading such as "Geschäftsführung:".

        Line by line up to the first line that holds anything else ("Paket GmbH"); after
        "Inhaber" one name only.
        """
        lines = match.group("lines").splitlines(keepends=True)
        for i, line in enumerate(lines):
            found = list(_T_OFFICER_LONG.finditer(line))
            if not all(_t_person(f.group("name")) for f in found) or (
                match.group("one") and (i or len(found) > 1)
            ):
                break
            lines[i] = _T_OFFICER_LONG.sub(lambda f: f.group("title") + "Erika Beispiel", line)
        return match.group("head") + "".join(lines)

    # ----- numbers, links -----
    def label(self, msg, number):
        """What stands for a mail in its file name, Message-ID and MIME boundary: its number in
        the run, or with the tester's salt a hash of the mail (of its Message-ID if it has
        one) that every run gives again."""
        if not self.fixed:
            return f"{number:03d}"
        source = _t_header(msg, "Message-ID").encode() or bytes(msg)
        return hashlib.sha256(self._salt.encode() + b"\0" + source).hexdigest()[:12]

    def _run(self, run):
        """Invented digits for digits, letters for letters (hex stays hex); DHL's 00340 stays,
        and so does the "00" of an SSCC (DHL eCommerce), with a check digit that fits again."""
        if run not in self._runs:
            sscc = _t_sscc(run) and not run.startswith("00340")
            keep = 5 if re.fullmatch(r"00340\d{15}", run) else 2 if sscc else 0
            letters = 6 if re.fullmatch(r"[A-Fa-f]+", run) else 26
            attempt = 0
            while True:
                seed = f"{self._salt}:{attempt}:{run}".encode()
                stream = hashlib.shake_256(seed).digest(len(run))
                invented = run[:keep] + "".join(
                    str(byte % 10) if char.isdigit()
                    else chr((65 if char.isupper() else 97) + byte % letters)
                    for char, byte in zip(run[keep:], stream)
                )
                if sscc:
                    invented = invented[:-1] + _t_sscc_check(invented[:-1])
                attempt += 1
                if sscc and invented.startswith("00340"):
                    continue  # (would read as DHL's own number anywhere)
                if invented != run and not any(a in invented for a in self.avoid):
                    break
            self._runs[run] = invented
        return self._runs[run]

    def fake(self, token):
        """Same length and structure: a prefix such as JJD, 1Z, H or HW- and separators stay."""
        head = re.match(r"1Z|[A-Za-z]{1,4}(?=[-_]?\d)", token)
        head = head.group(0) if head else ""
        rest, tail = token[len(head):], ""
        country = re.fullmatch(r"(\d{8,})([A-Z]{2})", rest) if head else None
        if country:  # RR123456789DE
            rest, tail = country.groups()
        return head + re.sub(r"\d+|[A-Za-z]+", lambda m: self._run(m.group(0)), rest) + tail

    def _grouped(self, text):
        """A number written in groups: invented as one number, written in the same groups
        (so it is the same number as without groups). Groups joined by dashes are invented
        group by group, like every other dashed number."""
        if text[0].isdigit() and sum(char.isdigit() for char in text) < _T_GROUPED_MIN:
            # only the digits behind it made it look long: no number in groups
            return re.sub(r"\d{6,}", lambda m: self.fake(m.group(0)), text)
        if "-" in text:
            return self.fake(text)
        invented = iter(self.fake(re.sub(r"[ \t.]", "", text)))
        return re.sub(r"[0-9A-Za-z]", lambda m: next(invented), text)

    def _link(self, match, keep, visible=None, noted=None):
        """A mail address or a link cut to its host. In the first pass over a text
        (``visible`` given) a tracking number that only the link carries is noted behind it."""
        text = match.group(0)
        if match.lastgroup == "mail":
            return text if text.lower() in keep else _T_MAIL
        host = re.match(r"(?i)(https?://)?(?:[^/?#@]*@)?([^/?#]*)", text)
        server = host.group(2).rstrip(".,;:!?")
        rest = text[host.end() - (len(host.group(2)) - len(server)):]
        if not rest.strip("/.,;:!?…"):
            return text
        notes = ""
        if visible is not None:
            for number in _t_hidden(rest):
                if number not in visible and number not in noted:
                    noted.add(number)
                    notes += " " + _T_HIDDEN_NOTE.format(number)
        return (host.group(1) or "") + server + "/…" + notes

    def _generic(self, match, keep):
        kind, text = match.lastgroup, match.group(0)
        if kind in ("url", "mail"):
            return self._link(match, keep)
        if kind == "token":
            token = match.group("token")
            return match.group("label") + (
                self._grouped(token) if _T_IN_GROUPS.fullmatch(token) else self.fake(token))
        if kind in ("grouped", "grouped_short", "s10"):
            return self._grouped(text)
        if kind == "otp":
            return match.group("otp_label") + self._run(match.group("otp"))
        if kind == "phone":
            return self.fake(text) if text.isdigit() else _T_PHONE
        if kind == "dashed" and (
            sum(char.isdigit() for char in text) < 8
            or re.fullmatch(r"(?:19|20)\d\d-\d\d-\d\d|\d\d-\d\d-(?:19|20)\d\d", text)
        ):
            return text  # a date or a time range
        return self.fake(text)

    def scrub(self, text, keep=()):
        """Scrubbed text; ``keep`` are the mail addresses that stay (the shop or carrier)."""
        text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
        text = _T_DIGIT_GAP.sub(" ", _T_INVISIBLE.sub("", text))
        # Links and addresses first: a replaced name would tear a link apart.
        visible, noted = _T_LINKS.sub(" ", text), set()
        text = _T_LINKS.sub(lambda m: self._link(m, keep, visible, noted), text)
        if self._learning:
            for match in _T_PICKUP_STREET.finditer(text):
                self._pickup_street(match.group("street") or match.group("inline"))
        text = _T_PICKUP_NUMBER.sub(self._pickup_number, text)
        text = _T_AMAZON_SHIP_TO.sub(self._amazon_ship_to, text)
        text = _T_ADDRESS_BLOCK.sub(self._block, text)
        text = _T_ADDRESS_INTRO.sub(self._block, text)
        text = _T_ALI_SHIP_TO.sub(self._ali_ship_to, text)
        text = _T_ADDRESS_LINE.sub(self._line, text)
        text = _T_DELIVERED_TO.sub(self._delivered, text)
        text = _T_RECIPIENT_NAME.sub(self._recipient_name, text)
        text = _T_HELLO.sub(self._hello, text)
        text = _T_HELLO_BARE.sub(self._hello, text)
        text = _T_QUOTED_TO.sub(f"\\1 {_T_MAIL}", text)
        for pattern in (_T_SENDER_BLOCK, _T_SENDER_NEXT, _T_SENDER_INLINE, _T_SENDER_SAME,
                        _T_SELLER):
            text = pattern.sub(self._sender, text)
        text = _T_EBAY_FOOTER.sub(self._ebay_footer, text)
        text = _T_EBAY_HANDLE.sub(self._ebay_handle, text)
        text = _T_AMAZON_LINE.sub(self._amazon, text)
        text = _T_FORM.sub(self._form, text)
        text = _T_PLAIN_BLOCK.sub(self._plain, text)
        text = _T_INLINE_ADDRESS.sub(self._inline, text)
        text = _T_PLZ_CITY.sub("\\g<lead>12345 Musterstadt", text)
        text = _T_OFFICERS.sub(self._officers, text)
        text = _T_OFFICER_LINES.sub(self._officer_lines, text)
        text = _T_NEIGHBOUR.sub(self._neighbour, text)
        for pattern, replacement in self.rules:
            text = pattern.sub(replacement, text)
        if not self._learning:
            for found in sorted(self.learned, key=len, reverse=True):
                source = re.escape(found)
                if self.learned[found] in ("beispielshop", "beispielnutzer"):
                    # a user name only as a whole word ("versand" never in
                    # "Versanddienstleister"; "shop.24" never in "myshop.24" or "shop.245")
                    source = rf"(?<![\w.-]){source}(?![\w-]|\.\w)"
                text = re.sub(source, self.learned[found], text, flags=re.I)
            for pattern, replacement in self._rules():
                text = pattern.sub(replacement, text)
        text = _T_PLACE_NEXT.sub(self._place, text)
        text = _T_PLACE_SAME.sub(self._place, text)
        text = _T_PLACE_PHRASE.sub("\\1 Garage \\2", text)
        return _T_GENERIC.sub(lambda m: self._generic(m, keep), text)

    def mailbox(self, real):
        """The invented address of a real one: ``adresse1@example.org`` for the first address
        of the run; a plus part stays as ``+person1`` (the same plus part, the same number)."""
        local, _, host = real.strip().lower().rpartition("@")
        base, plus, tag = local.partition("+")
        number = self._mailboxes.setdefault(f"{base}@{host}", len(self._mailboxes) + 1)
        if not plus:
            return f"adresse{number}@example.org"
        tag_number = self._tags.setdefault(tag, len(self._tags) + 1)
        return f"adresse{number}+person{tag_number}@example.org"

    def seller(self, name):
        """An Amazon marketplace seller (first pass): its brand gets an invented one, the same
        in every mail of the run, also where a carrier's mail names the seller as the sender
        ("Ihre Echthandel Sendung"): the integration takes the box for that seller's then."""
        brand = _t_brand(name)
        key = brand.lower()
        if len(brand) < 4 or key in self.sellers or key in _T_NOT_SELLERS:
            return
        taken, count = set(self.sellers.values()), len(_T_AMZ_SELLERS)
        first = int(hashlib.sha256(key.encode()).hexdigest(), 16) % count
        free = [_T_AMZ_SELLERS[(first + step) % count] for step in range(count)]
        self.sellers[key] = next((n for n in free if n not in taken),
                                 f"Beispielhandel {len(taken) + 1}")
        self._sellers = None

    def sellers_in(self, text):
        """``text`` with the brand of each seller ``seller`` learnt as its invented one."""
        if not self.sellers:
            return text
        if self._sellers is None:
            brands = sorted(self.sellers, key=len, reverse=True)
            self._sellers = re.compile(
                r"(?i)(?<!\w)(?:" + "|".join(re.escape(b).replace(r"\ ", r"\s+") for b in brands)
                + r")(?!\w)"
            )

        def invented(m):
            name = self.sellers[" ".join(m.group(0).split()).lower()]
            return name.upper() if m.group(0).isupper() else name

        return self._sellers.sub(invented, text)

    def left(self, text):
        """True if a given value can still be read in ``text``."""
        text = text.casefold()
        return any(value in text for value in self._check)


def _t_company(name):
    name = name.strip("*_ \t")
    return bool(_T_COMPANY.search(name) or _T_SHOP.fullmatch(name))


def _t_content(part):
    try:
        content = part.get_content()
    except Exception:
        content = part.get_payload(decode=True) or b""
    return content if isinstance(content, str) else content.decode("utf-8", "replace")


def _t_texts(msg):
    """(text of all text/plain parts, text of all text/html parts); other parts are dropped."""
    plain, markup = [], []
    for part in msg.walk():
        kind = part.get_content_type()
        if kind == "text/plain":
            plain.append(_t_content(part))
        elif kind == "text/html":
            markup.append(_t_html_to_text(_t_content(part)))
    return "\n".join(plain), "\n".join(markup), bool(plain), bool(markup)


def _t_header(msg, name):
    try:
        return " ".join(str(msg.get(name, "") or "").split())
    except Exception:
        return ""


def _t_sender(msg):
    """(display name, address in lower case) of the From header."""
    raw = _t_header(msg, "From")
    found = re.findall(_T_ADDRESS, raw)
    address = found[-1].lower() if found else ""
    name = raw[:raw.rfind("<")] if "<" in raw else ""
    return name.strip(" \t\"'"), address


def _t_recipients(msg):
    """The display names of the To and Cc headers."""
    names = []
    for header in ("To", "Cc"):
        for part in re.split(r",(?=[^<>]*(?:<|$))", _t_header(msg, header)):
            if "<" in part:
                names.append(part[:part.rfind("<")].strip(" \t\"'"))
    return [name for name in names if name]


def _t_private(msg, address, scrubber, subject, text):
    """A sender that is a person: a freemail address, the recipient itself, the tester, or
    the sender of a forwarded or answered mail (subject prefix, quoted header block)."""
    if not address:
        return True
    recipients = ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To")
    others = " ".join(_t_header(msg, name) for name in recipients).lower()
    return bool(
        address.rsplit("@", 1)[-1] in _T_FREEMAIL
        or address in re.findall(_T_ADDRESS, others)
        or any(value in address for value in scrubber.own)
        or _T_FORWARD.match(subject)
        or _T_QUOTED_FROM.search(text.replace("\r\n", "\n"))
    )


def _t_quoted_blocks(lines):
    """(start, end, kinds) of the quoted header blocks in the lines of a text: runs of header
    lines that name a sender and a subject or a date. A value may stand on the line below its
    label, and a long recipient list may go on for two lines when another header follows."""
    blocks, index = [], 0
    while index < len(lines):
        if not _T_QUOTED_LINE.match(lines[index]):
            index += 1
            continue
        start, kinds, kind = index, set(), ""
        while index < len(lines):
            match = _T_QUOTED_LINE.match(lines[index])
            if match:
                found = _T_QUOTED_KIND.get(match.group("label").lower(), "to")
                if found != "to" and found in kinds:
                    break  # a second sender, subject or date: a line of the mail itself
                kind = found
                kinds.add(kind)
                index += 1
                if (not match.group("value").strip() and index < len(lines)
                        and lines[index].strip("> \t")
                        and not _T_QUOTED_LINE.match(lines[index])):
                    index += 1
                continue
            ahead = lines[index:index + 3]
            more = next((n for n, line in enumerate(ahead) if _T_QUOTED_LINE.match(line)), 0)
            if kind == "to" and more and all(line.strip("> \t") for line in ahead[:more]):
                index += more
                continue
            break
        if "from" in kinds and kinds & {"subject", "date"}:
            blocks.append((start, index))
    return blocks


def _t_attribution(line):
    """The match of an attribution line that names an address, else None."""
    for pattern in (_T_ATTRIBUTION_DE, _T_ATTRIBUTION_EN):
        match = pattern.match(line)
        if match and re.search(_T_ADDRESS, match.group("who")):
            return match
    return None


def _t_known_domain(address):
    """True for an address at a domain the import knows (or below it), also behind the relay."""
    host = (relay_original(address) or address).rpartition("@")[2].lower()
    while host:
        if host in _T_KNOWN_DOMAINS:
            return True
        host = host.partition(".")[2]
    return False


def _t_attribution_address(match):
    return re.findall(_T_ADDRESS, match.group("who"))[-1]


def _t_attribution_sender(match, private):
    """(address to keep or None, the attribution line with its sender cleaned).

    Only a sender at a domain the import knows stays, everyone else becomes the placeholder
    address; a name that looks like a person's becomes "Beispielversender"."""
    head, who, tail = match.group("head"), match.group("who"), match.group("tail").rstrip()
    quoted = _t_attribution_address(match)
    if not (_t_known_domain(quoted) or is_eventim(quoted)):
        return None, head + _T_MAIL + tail
    name = re.split(r"[<\[]", who, maxsplit=1)[0].strip(" \t\"',")
    if name and "@" not in name and _t_person(name):
        who = who.replace(name, "Beispielversender", 1)
    address, line = _t_quoted_sender(head, who, private)
    return address, line + tail


def _t_attributions(lines):
    """(start, end, match) of the attribution lines in the lines of a text; a line may be
    wrapped once (Gmail and Apple Mail break a long one in their text part)."""
    found, index = [], 0
    while index < len(lines):
        line = lines[index].strip()
        if _T_ATTRIBUTION_START.match(line):
            match = _t_attribution(line)
            if match:
                found.append((index, index + 1, match))
                index += 1
                continue
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            match = following and _t_attribution(f"{line} {following}")
            if match:
                found.append((index, index + 2, match))
                index += 2
                continue
        index += 1
    return found


def _t_original(text, private, forward=False):
    """(the text from the innermost quoted header block on, the quoted sender's address).

    What stands above that block (the note and signature of the person that forwarded the
    mail, the blocks of earlier forwards) is dropped. In the block the recipients are replaced;
    the sender stays (the importer tells the original mail by it) only at a domain the
    import knows and unless ``private`` says it is a person. Without such a block, in a ``forward`` (WG:, Fwd:, FW:), the innermost
    attribution line ("Am … schrieb DHL <…>:") is taken the same way, as the importer does.
    Without either the text comes back as it is, with no address.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = _t_quoted_blocks(lines)
    if not blocks:
        found = _t_attributions(lines) if forward else []
        if not found:
            return text, None
        # The innermost line of a sender the import knows, as the import takes it.
        known = [item for item in found if _t_known_domain(_t_attribution_address(item[2]))]
        start = (known or found)[-1][0]
        below = {first: (end, match) for first, end, match in found if first >= start}
        kept, address, index = [], None, start
        while index < len(lines):
            if index in below:
                end, match = below[index]
                quoted, line = _t_attribution_sender(match, private)
                address = quoted if index == start else address
                kept.append(line)
                index = end
            else:
                kept.append(lines[index])
                index += 1
        return "\n".join(kept), address
    start, end = blocks[-1]

    def unknown(quoted):  # only a sender the import knows stays in the block
        return private(quoted) or not (_t_known_domain(quoted) or is_eventim(quoted))

    kept, kind, pending, address = [], None, False, None
    for line in lines[start:end]:
        match = _T_QUOTED_LINE.match(line)
        if match:
            kind = _T_QUOTED_KIND.get(match.group("label").lower(), "to")
            value = match.group("value").strip()
            pending = not value
            if not value:
                kept.append(line)
            elif kind == "to":
                kept.append(match.group("head") + _T_MAIL)
            elif kind == "from":
                address, line = _t_quoted_sender(match.group("head"), value, unknown)
                kept.append(line)
            else:
                kept.append(line)
        elif kind == "to":
            if pending:  # the value on the line below its label
                kept.append(_T_MAIL)
            pending = False  # (a wrapped recipient list is dropped)
        elif kind == "from" and pending:
            address, line = _t_quoted_sender("", line, unknown)
            kept.append(line)
            pending = False
        else:
            kept.append(line)
    return "\n".join(kept + lines[end:]), address


def _t_quoted_sender(head, value, private):
    """(address to keep or None, the quoted sender line)."""
    found = re.findall(_T_ADDRESS, value)
    address = found[-1].lower() if found else ""
    if not address or re.search(r"[=%]", address.rpartition("@")[0]) or private(address):
        return None, head + _T_MAIL
    if address.rpartition("@")[2] == RELAY_HOST:
        # Apple's relay: the ids in the local part are the recipient's, here as well.
        invented = relay_address(address)
        return invented, head + value.replace(found[-1], invented)
    return address, head + value


def _t_passed_on(msg, texts=None):
    """A mail that looks forwarded: subject prefix (WG:, Fwd:, Fw:), a quoted header block or
    an attribution line ("Am … schrieb DHL <…>:"). ``texts``: ``_t_texts(msg)``, if known."""
    plain, markup = (texts or _t_texts(msg))[:2]
    text = (plain + "\n" + markup).replace("\r\n", "\n")
    return bool(
        _T_PASSED_ON.match(_t_header(msg, "Subject"))
        or _T_QUOTED_FROM.search(text)
        or _t_attributions(text.split("\n"))
    )


_T_KEPT_ADDRESSES = (
    "To", "Cc", "Delivered-To", "X-Original-To", "X-Forwarded-To", "X-Forwarded-For",
    "Resent-From", "Resent-To",
)


def _t_address_headers(msg, out, scrubber):
    """Copy the headers that tell for whom a mail was meant, in their order, with every
    address invented (no display names). The detection of the owner reads exactly these."""
    wanted = {name.lower(): name for name in _T_KEPT_ADDRESSES}
    for key, value in msg.items():
        name = wanted.get(str(key).lower())
        found = re.findall(_T_ADDRESS, " ".join(str(value).split())) if name else []
        if found:
            out.add_header(name, ", ".join(scrubber.mailbox(a) for a in found))
    if "To" not in out:
        out["To"] = _T_MAIL


def _t_set(out, name, value):
    try:
        out[name] = value
    except Exception:  # a header the mail library refuses is left out
        del out[name]


def _t_body(out, text, subtype, alternative=False):
    # 8bit keeps the text readable in an editor; too long lines need an encoding.
    short = all(len(line.encode("utf-8")) <= 900 for line in text.splitlines())
    options = {"cte": "8bit"} if short and not text.isascii() else {}
    (out.add_alternative if alternative else out.set_content)(text, subtype=subtype, **options)


def _t_eventim_subject(subject, order_mail):
    """The subject of an Eventim mail; "WG:" and the like in front of it stay."""
    prefix = re.match(r"(?i)(?:\s*(?:WG|Fwd?|FW|AW|Re)\s*:\s*)*", subject).group(0)
    if not order_mail:
        return prefix + _EVT_OTHER_SUBJECT
    return prefix + scrub_eventim_subject(subject[len(prefix):])


def _t_eventim(text, order_mail, count):
    """The text of an Eventim mail by the rules of the fixture mode (``scrub_eventim``).

    A tester's own values say nothing about the event: its name, day, venue, organiser,
    seats and prices, the payment method and the day of the order are replaced by what
    Eventim's layout tells. The quoted header block of a mail forwarded by hand stays in
    front (the importer tells the original mail by it), with its sender, subject and day
    replaced the same way.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    head, blocks = [], _t_quoted_blocks(lines)
    if blocks:
        kind = None
        for line in lines[blocks[0][0]:blocks[0][1]]:
            match = _T_QUOTED_LINE.match(line)
            if match:
                kind = _T_QUOTED_KIND.get(match.group("label").lower(), "to")
            lead = match.group("head") if match else ""
            value = (match.group("value") if match else line).strip()
            if not value:
                head.append(line)
            elif kind == "subject":
                head.append(lead + _t_eventim_subject(value, order_mail))
            elif kind == "date":
                head.append(lead + evt_quoted_day(count))
            elif kind == "from" and (found := re.findall(_T_ADDRESS, value)):
                head.append(f"{lead}EVENTIM <{evt_address(found[-1].lower())}>")
            else:
                head.append(lead + value)
        head.append("")
        lines = lines[blocks[0][1]:]
    body = scrub_eventim("\n".join(lines)) if order_mail else _EVT_OTHER_TEXT
    return "\n".join(head + [body])


# ----- tester mode: the HTML part -----
# A mail with an HTML part keeps it with what carries text or meaning where it stands, every
# value replaced; only what is known to be layout or technique goes, so whatever a carrier or
# shop brings later (an attribute nobody knows yet) shows up in the result:
# - Gone: <head>, <style>, <script>, drawn icons (<svg>), comments (Outlook's [if mso] layout),
#   <meta>, pictures of one pixel (counters with the reader's ids) and the layout attributes
#   (_T_LAYOUT_ATTRS). Tables, rows and cells only break the lines.
# - Kept: every text (one line per block), every link with its text, every picture, hidden
#   text (it keeps style="display:none") and every other attribute. Texts and the attributes
#   that hold text (_T_TEXT_ATTRS) are scrubbed like the text part; any other attribute is
#   invented in its form, and its name is told at the end.
# - A link keeps its server, its path and the names of its parameters: plain words and
#   numbers of up to three digits stay, every other value is scrubbed like the text (a number
#   reads the same in both parts) or invented in its form, a link in a link the same way.
#   Amazon's shipment keeps its first letter ("D": sent by the seller). A picture keeps its
#   server only.
# - Amazon: an item's number (ASIN) becomes "ZZ" and invented digits (the same for the same
#   item; "ZZ" begins no real ASIN), its name an invented one (_T_AMZ_ITEMS, _T_AMZ_KINDS:
#   the same for the same item) in the subject, the text, the alt text, the title and the
#   link's text, cut where the real one was cut (see _THtml.shop); the
#   marketplace seller Beispielhandel e.K. (a company) or Beispielhändler (none).
# A mail that looks forwarded (subject, quoted header block, "Am … schrieb …:"), one from a
# private address and an Eventim mail keep the simple HTML part (one <p> per line of the
# scrubbed text): what stands above the quoted header is cut from the text only, and
# Eventim's rules work on the text.
_T_HTML_SKIP = frozenset({"head", "style", "script", "title", "noscript", "xml", "svg"})
_T_HTML_VOID = frozenset({"br", "img", "hr", "input", "wbr", "area", "col"})
_T_HTML_INLINE = frozenset({"a", "span", "b", "strong", "i", "em", "u", "font", "small", "img"})
_T_LAYOUT_ATTRS = frozenset({
    "style", "class", "id", "align", "valign", "width", "height", "border", "cellpadding",
    "cellspacing", "bgcolor", "background", "color", "role", "dir", "lang", "colspan",
    "rowspan", "target", "face", "size", "padding", "nowrap", "xml:lang", "hspace", "vspace",
    "frame", "rules", "scope", "summary", "aria-hidden", "border-collapse", "bordercolor",
    "leftmargin", "topmargin", "marginwidth", "marginheight", "type", "rel", "alink", "vlink",
    "link", "text", "tabindex", "translate", "spellcheck", "start", "headers", "for", "yahoo",
})
_T_TEXT_ATTRS = frozenset({"alt", "title", "aria-label", "aria-describedby", "aria-description",
                           "aria-roledescription", "data-sonar-role"})
# Marks of the tools a template was made with: invented like any attribute, but never told.
_T_TEMPLATE_ATTRS = frozenset({"data-bee-code", "data-bee-name", "data-bee-type", "elaine-attr",
                               "link-id", "name"})
_T_KNOWN_ATTRS = _T_LAYOUT_ATTRS | _T_TEXT_ATTRS | _T_TEMPLATE_ATTRS | {"href", "src"}
# Words of the templates in such attributes that stay although the mail does not show them.
_T_ATTR_WORDS = frozenset({
    "Abgeschlossen", "Ausstehend", "Amazon", "Logo", "Visit", "Bild", "Status", "Paket",
    "Pakete", "Sendung", "Sendungen", "Bestellung", "Lieferung", "Zustellung", "Abholung",
    "Artikel", "Ihr", "Ihre", "Dein", "Deine", "Der", "Die", "Das",
})
# A name an attribute can have; anything else is broken HTML (a piece of a link in the tag).
_T_ATTR_NAME = re.compile(r"[A-Za-z][A-Za-z_:-]{0,40}")
_T_HIDDEN_STYLE = re.compile(r"(?i)display\s*:\s*none|max-height\s*:\s*0|mso-hide\s*:\s*all")
# One character of the private use area per element that stays: open, close, picture.
_T_MARK_BASE = {"o": 0xF0000, "c": 0xF4000, "v": 0xF8000}
_T_MARK_RANGE = r"\U000F0000-\U000FBFFF"
_T_HTML_MARK = re.compile(f"[{_T_MARK_RANGE}]")
_T_LINE_END = re.compile(rf"[\n{_T_MARK_RANGE}]")  # (a line's end, also between elements)
# An id of letters and digits (an item's ASIN as the title of its link, in older Amazon mails).
_T_IDENT = re.compile(r"(?<![\w-])(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[A-Za-z0-9_-]{6,}(?![\w-])")
_T_PICTURE = re.compile(r"(?i)(https?://[^/?#\s]+)[^?#\s]*?(\.(?:png|jpe?g|gif|webp))?(?:[?#]\S*)?$")
_T_URL = re.compile(r"(?i)(https?://)([^/?#\s]+)([^?#\s]*)(\?[^#\s]*)?(#\S*)?")
_T_URL_WORD = re.compile(r"[a-z]+(?:[-_.][a-z]+)*|[a-z]{2}[-_][A-Z]{2}|\d{0,3}")
_T_URL_NAME = re.compile(r"(?!(?:\D*\d){4})[A-Za-z_][\w.\[\]-]{0,40}")
_T_AMZ_PRODUCT = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
# Amazon's marketplace seller ("Verkauf durch Echthandel GmbH, Händler & Versand aus …").
_T_AMZ_SELLER = re.compile(
    rf"(Verkauf durch[ \t]+)(?!Amazon\b|einen Drittanbieter\b)([^,\n<>{_T_MARK_RANGE}]+)"
)
# A seller's legal form, as the integration's ``base.LEGAL_FORM`` cuts it from its name.
_T_LEGAL_FORM = re.compile(
    r"(?<![\w.])(?:GmbH|GMBH|AG|KG|UG|SE|OHG|GbR|Ltd\.?|e\.\s?K\.?|B\.\s?V\.|SARL"
    r"|S\.\s?[aà]\.?\s?r\.\s?[lL]\.)(?!\w)"
)
# Invented brands of the sellers of a run (_TScrubber.seller), each with its legal form.
_T_AMZ_SELLERS = tuple(
    f"{name} {part}".strip()
    for name in ("Beispielhandel", "Musterladen")
    for part in ("", "Nord", "Süd", "West", "Ost", "Mitte", "Plus", "Direkt")
)
# Brands no seller's name may change in every mail: the words the mails of shops and
# carriers live by.
_T_NOT_SELLERS = frozenset({"amazon", "dhl", "dpd", "gls", "hermes", "ups", "ebay", "post",
                            "deutsche post", "fedex", "versand", "shop", "store", "online"})
# Each begins with a letter of its own: Amazon cuts a name in a subject to a few characters
# ("WAGO…"), and two items of one order must not look the same there.
_T_AMZ_ITEMS = (
    "Akkuschrauber Beispielmarke 18 V mit zwei Akkus und Ladegerät",
    "Batterien Musterfirma AA 12 Stück Alkaline langlebig",
    "Campingbecher Beispielmarke 4er Set Edelstahl mit Deckel",
    "Duschkopf Musterfirma mit fünf Strahlarten und Kalkschutz",
    "Eierkocher Beispielmarke für 1 bis 7 Eier mit Messbecher",
    "Fahrradlicht-Set Beispielmarke LED mit USB-Akku und Halterung",
    "Gartenschlauch Beispielmarke 20 m mit Brause und Kupplung grün",
    "Handtücher Musterfirma 4er Set Baumwolle 50 x 100 cm grau",
    "Isolierband Musterfirma 10 Rollen farbig sortiert 19 mm",
    "Kopfhörer Beispielmarke kabellos mit Ladeetui und Mikrofon",
    "LED-Schreibtischlampe Beispielmarke dimmbar mit USB-Anschluss",
    "Notizbücher Musterfirma A5 liniert 4 Stück Hardcover",
    "Rucksack Beispielmarke 25 l wasserabweisend mit Laptopfach",
    "Thermoskanne Musterfirma 1 l Edelstahl doppelwandig grau",
    "Wasserkocher Beispielmarke 1,7 l Edelstahl mit Kalkfilter",
    "Zollstock Musterfirma 2 m Holz mit Winkelanzeige",
)
# A word behind the name: 16 × 16 names, enough for each item of a run its own (_THtml._item).
_T_AMZ_KINDS = (
    "", "kompakt", "robust", "leicht", "faltbar", "wetterfest", "rutschfest", "platzsparend",
    "nachfüllbar", "ergonomisch", "matt", "glänzend", "extra stark", "für unterwegs",
    "vielseitig", "pflegeleicht",
)
_t_html_notes = {"attributes": set()}


def _t_brand(name):
    """A company's name in front of its legal form (all of it without one)."""
    form = _T_LEGAL_FORM.search(name)
    return " ".join((name[: form.start()] if form else name).strip(" ,;:&+-*_").split())


def _t_words(text, pattern=r"[^\W_]{3,}"):
    """The words of ``text`` (by default of three letters or digits or more), in lower case."""
    return {word.casefold() for word in re.findall(pattern, text)}


def _t_unquote(text):
    """%XX read as UTF-8 (no urllib: see the module's docstring); a byte that is none goes back
    as it came (``_t_quote``)."""
    return re.sub(
        r"(?:%[0-9A-Fa-f]{2})+",
        lambda m: bytes.fromhex(m.group(0).replace("%", "")).decode("utf-8", "surrogateescape"),
        text,
    )


def _t_quote(text):
    return "".join(
        c if c.isascii() and (c.isalnum() or c in "-._~+")
        else "".join(f"%{b:02X}" for b in c.encode("utf-8", "surrogateescape"))
        for c in text
    )


def _t_amz_asin(url):
    """The ASIN a link to an item's page at amazon.de names, also behind Amazon's redirect."""
    url = html.unescape(url or "")
    if "/gp/r.html" in url and (inner := re.search(r"[?&]U=([^&]+)", url)):
        url = _t_unquote(inner.group(1))
    found = _T_AMZ_PRODUCT.search(url.split("?")[0]) if "amazon.de" in url else None
    return found.group(1) if found else None


class _TMarkup(HTMLParser):
    """The text of an HTML part, with a mark for each element that stays (see above)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.elements, self.stack, self.skip = [], [], [], 0

    def _mark(self, kind, index, block):
        if index >= _T_MARK_BASE["c"] - _T_MARK_BASE["o"]:
            raise ValueError("too many elements")  # (the simple HTML part instead)
        nl = "\n" if block else ""
        self.parts.append(f"{nl}{chr(_T_MARK_BASE[kind] + index)}{nl}")

    def handle_starttag(self, tag, attrs):
        if tag in _T_HTML_SKIP:
            self.skip += 1
            return
        if self.skip or tag in ("meta", "link"):
            return
        values = dict(attrs)
        hidden = _T_HIDDEN_STYLE.search(values.get("style") or "")
        kept = [(k, v) for k, v in attrs if v is not None and _T_ATTR_NAME.fullmatch(k)
                and k not in _T_LAYOUT_ATTRS and not k.startswith("xmlns")]
        _t_html_notes["attributes"].update(k for k, _ in kept if k not in _T_KNOWN_ATTRS)
        if tag == "br":
            self.parts.append("\n")
        elif tag == "img":
            if "0" not in (values.get("width"), values.get("height")) and not (
                values.get("width") == values.get("height") == "1"
            ):  # (not a counter)
                self._mark("v", len(self.elements), False)
                self.elements.append(("img", kept))
        elif tag in _T_HTML_VOID:
            pass
        elif kept or tag == "a" or hidden:
            name = tag if tag in _T_HTML_INLINE else "div"
            if hidden:
                kept.append(("style", "display:none"))
            index = len(self.elements)
            self.elements.append((name, kept))
            self._mark("o", index, name == "div")
            self.stack.append((tag, index, name))
        else:
            if tag not in _T_HTML_INLINE:
                self.parts.append("\n")
            self.stack.append((tag, None, None))

    def handle_endtag(self, tag):
        if tag in _T_HTML_SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        for pos in range(len(self.stack) - 1, -1, -1):
            if self.stack[pos][0] == tag:
                while len(self.stack) > pos:
                    self._close(*self.stack.pop())
                return

    def _close(self, tag, index, name):
        if index is not None:
            self._mark("c", index, name == "div")
        elif tag not in _T_HTML_INLINE:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            # (a character of the private use area, as icon fonts use them, is no mark)
            self.parts.append(_T_HTML_MARK.sub("", data))

    def close(self):
        super().close()
        while self.stack:
            self._close(*self.stack.pop())


class _TAmazonTitles(HTMLParser):
    """The name of each item an Amazon mail links: the alt text of its picture, else the
    link's title, else the link's text (older mails: the picture beside the link, the ASIN as
    its title, the name in a second link)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.asin, self.names, self.asins, self.text = None, {}, set(), []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "a":
            self.asin, self.text = _t_amz_asin(values.get("href")), []
            if self.asin:
                self.asins.add(self.asin)
            if self.asin and values.get("title") and values["title"].strip() != self.asin:
                self.names.setdefault(self.asin, " ".join(values["title"].split()))
        elif tag == "img" and self.asin and values.get("alt"):
            self.names[self.asin] = " ".join(values["alt"].split())

    def handle_data(self, data):
        if self.asin:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            if self.asin and (text := " ".join("".join(self.text).split())):
                self.names.setdefault(self.asin, text)
            self.asin = None


class _THtml:
    """The HTML part of one mail as described above."""

    def __init__(self, scrubber, keep, markup, amazon):
        self.scrubber, self.keep, self.markup, self.amazon = scrubber, keep, markup, amazon
        self.titles, self.asins, self.gone, self.inside = [], set(), frozenset(), ()
        self.named, self.inserted = {}, set()  # ASIN -> real name; invented names put in
        self.context = ""  # the whole mail as it came (``shop``)
        if amazon:
            learner = _TAmazonTitles()
            learner.feed(markup)
            self.asins = learner.asins
            self.named = {asin: real for asin, real in learner.names.items() if len(real) >= 12}
            products = set()  # (the items of one mail never share the product)
            for asin, real in self.named.items():
                invented = self._item(asin, products)
                products.add(invented.split(",")[0])
                self.titles.append((real, invented))
            self.titles.sort(key=lambda rule: -len(rule[0]))

    def _item(self, asin, products=frozenset()):
        """An item's invented name, the same in every mail of the run: from its invented
        number, the next free one if another item has that already (all taken: shared), and
        none of ``products``, the products of the other items of the mail, if one is free."""
        names = self.scrubber.items
        if asin not in names:
            count, taken = len(_T_AMZ_ITEMS) * len(_T_AMZ_KINDS), set(names.values())
            first = int(self._asin(asin)[2:]) % count
            free = []
            for step in range(count):
                # (the next step is another product first: their names differ at once)
                kind, product = divmod((first + step) % count, len(_T_AMZ_ITEMS))
                name = ", ".join(filter(None, (_T_AMZ_ITEMS[product], _T_AMZ_KINDS[kind])))
                if name not in taken:
                    free.append(name)
            names[asin] = next((n for n in free if n.split(",")[0] not in products),
                               free[0] if free else _T_AMZ_ITEMS[first % len(_T_AMZ_ITEMS)])
        return names[asin]

    def shop(self, text):
        """An Amazon mail's item names and sellers, invented; in any other mail the sellers
        (``_TScrubber.sellers_in``).

        The items are those the mail links and those of the run's other mails it names
        (a cancellation names its item without a link). A name cut short counts where the
        cut shows ("Echtmarke Maßband 5 m mi…", also just "WAGO..." of an item the mail
        links). A text that begins like the name for 12 characters and then goes on
        otherwise (older mails list an item longer than its picture names it) is the same
        item, unless another item begins the same ("Amazon Basics HDMI-Kabel" beside
        "Amazon Basics USB-C-Kabel"): alone in its line it becomes the invented name as a
        whole, within a sentence only its start."""
        if not self.amazon:
            return self.scrubber.sellers_in(text)
        # (the mail's own items first: another item of the run that begins the same never
        # takes the place of one the mail links; of the others first those the mail names
        # in full somewhere, so that a name cut short is cut from the right one)
        own = {real for real, _ in self.titles}
        titles = self.titles + sorted(
            ((real, self._item(asin)) for real, asin in self.scrubber.titles.items()
             if real not in own and real[:8] in text),
            key=lambda rule: (rule[0] not in self.context, -len(rule[0])),
        )
        for real, invented in titles:
            others = [other for other, _ in titles if other != real]
            start, out = 0, []
            for m in re.finditer(r"(?<!\w)" + re.escape(real[:3]), text):
                pos = m.start()
                if pos < start:
                    continue
                k = 3
                while k < len(real) and pos + k < len(text) and text[pos + k] == real[k]:
                    k += 1
                end, name = pos + k, None
                if k == len(real):
                    name = invented
                elif text[end:end + 4].lstrip(" ").startswith(("…", "...")):
                    name = invented[:k].rstrip()
                elif k >= 12 and not any(other.startswith(real[:k]) for other in others):
                    line = text[text.rfind("\n", 0, pos) + 1:pos]
                    if _T_HTML_MARK.sub("", line).strip():
                        name = invented[:k].rstrip()
                    else:
                        stop = _T_LINE_END.search(text, end)
                        end, name = stop.start() if stop else len(text), invented
                if name is None:
                    continue
                self.inserted.add(name)
                out += [text[start:pos], name]
                start = end
            text = "".join(out) + text[start:]

        # (a seller too short to learn: invented here only)
        text, invented = self.scrubber.sellers_in(text), set(self.scrubber.sellers.values())
        return _T_AMZ_SELLER.sub(lambda m: m.group(0) if _t_brand(m.group(2)) in invented
                                 else m.group(1) + ("Beispielhandel e.K." if _t_company(m.group(2))
                                                    else "Beispielhändler"), text)

    def _scrub(self, text):
        """``scrubber.scrub`` for a part of a link or an attribute: they repeat (Amazon's
        redirect has the same parameters in every mail), and writing learns nothing new."""
        done, key = self.scrubber.html_parts, (self.keep, text)
        if key not in done:
            done[key] = self.scrubber.scrub(text, self.keep)
        return self._safe(done[key])

    def _safe(self, text):
        """No word the scrubbing of the HTML part as plain text took out (``gone``) stays: the
        marks of the elements may hide what a rule looks for ("Hallo <span>Name</span>").
        An invented name ``shop`` put in stays as it is ("mit" may be such a word)."""
        kept = sorted(self.inserted | set(self.scrubber.sellers.values()), key=len, reverse=True)
        parts = re.split(r"((?<!\w)(?:" + "|".join(map(re.escape, kept)) + r")(?!\w))",
                         text) if kept else [text]
        return "".join(
            part if n % 2 else self._fake_words(part, lambda word: word.casefold() in self.gone)
            for n, part in enumerate(parts)
        )

    def _fake_words(self, text, when=None):
        """``text`` with its words (of letters and digits) invented in their form; with
        ``when`` only those it says."""
        return re.sub(r"[^\W_]+", lambda m: self.scrubber.fake(m.group(0))
                      if when is None or when(m.group(0)) else m.group(0), text)

    def _asin(self, asin):
        digits = f"{int(hashlib.sha256(asin.encode()).hexdigest(), 16) % 10**8:08d}"
        return "ZZ" + self.scrubber.fake(digits)

    def _value(self, raw, depth, name=""):
        """A part of a link (a segment of its path, a parameter, its fragment)."""
        once = _t_unquote(raw)
        for times, text in enumerate((raw, once, _t_unquote(once))):
            if depth < 3 and re.match(r"(?i)https?://", text):
                inner = self.link(text, depth + 1)
                for _ in range(times):
                    inner = _t_quote(inner)
                return inner
        if _T_URL_WORD.fullmatch(once):
            # (``gone`` also within a word of the link: "wquandtberg" for "W. Quandtberg")
            safe = self._fake_words(once, lambda word: word.casefold() in self.gone
                                    or any(w in word.casefold() for w in self.inside))
            return raw if safe == once else _t_quote(safe)
        if name == "shipmentId" and len(once) > 1:
            return _t_quote(once[0] + self.scrubber.fake(once[1:]))
        value = self._scrub(once)
        return _t_quote(self._fake_words(once) if value == once else value)

    def link(self, url, depth=0):
        """A link with its server, path and the names of its parameters; values invented."""
        url = html.unescape(url.strip())
        low = url.lower()
        if low.startswith("mailto:"):
            return f"mailto:{_T_MAIL}"
        if low.startswith("tel:"):
            return "tel:+490000000000"
        match = _T_URL.fullmatch(url)
        if match is None:
            return "#"
        scheme, host, path, query, fragment = match.groups()
        asin = _t_amz_asin(scheme + host + path)
        link = scheme + host.lower() + "/".join(
            self._asin(s) if s == asin else self._value(s, depth) if s else s
            for s in path.split("/")
        )
        if query:
            params = []
            for param in query[1:].split("&"):
                name, eq, value = param.partition("=")
                if not _T_URL_NAME.fullmatch(_t_unquote(name)):
                    name = self._value(name, depth)
                params.append(name + eq + (self._value(value, depth, name) if eq else ""))
            link += "?" + "&".join(params)
        if fragment:
            link += "#" + self._value(fragment[1:], depth)
        return link

    def attribute(self, name, value):
        if name == "href":
            return self.link(value)
        if name == "src":
            found = _T_PICTURE.match(html.unescape(value.strip()))
            if not found:
                return "cid:bild"
            return f"{found.group(1).lower()}/bild{(found.group(2) or '.png').lower()}"
        if name == "style":
            return value
        if name not in _T_TEXT_ATTRS:
            return self._fake_words(value)
        named = self.shop(value)
        text = self._scrub(named)
        if named != value:
            return text  # (an Amazon item's name: invented as a whole)
        # An id the scrubbing left as it was: an ASIN of the mail becomes its number of the
        # links, any other is invented in its form.
        left = set(_T_IDENT.findall(named))
        text = _T_IDENT.sub(
            lambda m: m.group(0) if m.group(0) not in left
            else self._asin(m.group(0)) if m.group(0) in self.asins
            else self.scrubber.fake(m.group(0)),
            text,
        )

        # A word the mail shows anyway, a word in lower case ("amount", "footer"), a short
        # code ("EUR", "DHL") or one of Amazon's stages stays; any other (a name nobody
        # recognised in a picture's text) is invented in its form.
        def word(m):
            found = m.group(0)
            if (found.casefold() in self.shown or found.islower() or found in _T_ATTR_WORDS
                    or (found.isupper() and len(found) <= 4)):
                return found
            return self.scrubber.fake(found)

        return re.sub(r"[^\W\d_]{2,}", word, text)

    def render(self, gone=frozenset()):
        """The HTML part; ``gone`` are the words the scrubbing of it as plain text took out
        (see ``_safe``)."""
        self.gone = gone
        self.inside = tuple(w for w in gone if len(w) >= 4 and not w.isdigit())
        parser = _TMarkup()
        parser.feed(self.markup)
        parser.close()
        lines = (_T_INVISIBLE.sub("", re.sub(r"[ \t\xa0]+", " ", line)).strip()
                 for line in "".join(parser.parts).splitlines())
        text = self._safe(
            self.scrubber.scrub(self.shop("\n".join(line for line in lines if line)), self.keep)
        )
        self.shown = _t_words(_T_HTML_MARK.sub(" ", text), r"[^\W\d_]{2,}")
        tags = [(f"<{tag}" + "".join(
            f' {name}="{html.escape(self.attribute(name, value), quote=True)}"'
            for name, value in attrs
        ) + ">", f"</{tag}>") for tag, attrs in parser.elements]
        # A rule may have taken a mark with what it replaced: an element whose end went is
        # closed at the end, an end whose element went is left out.
        out, opened = [], set()
        for line in text.splitlines():
            shown = []
            for part in re.split(f"({_T_HTML_MARK.pattern})", line):
                if not part or not _T_HTML_MARK.fullmatch(part):
                    shown.append(html.escape(part, quote=False))
                    continue
                code = ord(part)
                kind = max((base, kind) for kind, base in _T_MARK_BASE.items() if code >= base)[1]
                index = code - _T_MARK_BASE[kind]
                if kind == "o":
                    opened.add(index)
                    shown.append(tags[index][0])
                elif kind == "c" and index in opened:
                    opened.discard(index)
                    shown.append(tags[index][1])
                elif kind == "v":
                    shown.append(tags[index][0])
            bare = not _T_HTML_MARK.sub("", line).strip()
            out.append("".join(shown) if bare else f"<p>{''.join(shown)}</p>")
        out.extend(tags[index][1] for index in sorted(opened, reverse=True))
        return "<!DOCTYPE html>\n<html><body>\n" + "\n".join(out) + "\n</body></html>\n"


def _t_learn_amazon(scrubber, texts, markup):
    """First pass, a mail of Amazon: the names of the items it links and its marketplace
    sellers, so that every mail of the run gets the same invented ones (``_THtml.shop``).
    The names are given here already: the items of a mail get products of their own."""
    if markup:
        for asin, real in _THtml(scrubber, (), markup, True).named.items():
            scrubber.titles.setdefault(real, asin)
    for text in texts:
        for match in _T_AMZ_SELLER.finditer(text):
            scrubber.seller(match.group(2))


def _t_html_part(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return _t_content(part)
    return None


def _t_build(msg, number, scrubber, texts=None):
    """(anonymised mail, file name, private sender?, value left?, looks forwarded?);
    ``texts``: ``_t_texts(msg)``, if known."""
    display, address = _t_sender(msg)
    texts = texts or _t_texts(msg)
    looks_passed_on = _t_passed_on(msg, texts)
    plain, markup, has_plain, has_html = texts
    raw_subject = _t_header(msg, "Subject")
    private = _t_private(msg, address, scrubber, raw_subject, plain + "\n" + markup)
    keep = () if private else (address,)

    def person(quoted):
        return bool(
            quoted == address
            or quoted.rsplit("@", 1)[-1] in _T_FREEMAIL
            or any(value in quoted for value in scrubber.own)
        )

    # A forwarded mail: only the quoted header block and the mail below it are taken.
    forward = bool(_T_PASSED_ON.match(raw_subject))
    plain, quoted_plain = _t_original(plain, person, forward)
    markup, quoted_markup = _t_original(markup, person, forward)
    keep += tuple(quoted for quoted in (quoted_plain, quoted_markup) if quoted)
    # Eventim, also forwarded by hand or passed on by the relay: its own rules first.
    evt = next((sender for sender in keep if is_eventim(sender)), None)
    if evt:
        order_mail = (relay_original(evt) or evt) == EVT_ORDER_SENDER
        plain = _t_eventim(plain, order_mail, number) if has_plain or not has_html else plain
        markup = _t_eventim(markup, order_mail, number) if has_html else markup
        raw_subject = _t_eventim_subject(raw_subject, order_mail)
        if not private:
            display, address = "EVENTIM", evt_address(address)
        keep = tuple(evt_address(sender) for sender in keep)
    local, _, host = address.rpartition("@")
    if not private and re.search(r"[=%]", local):
        # The local part carries another address (bounce+user=gmx.de@shop.example).
        address, keep = f"absender@{host}", ()
    elif not private and host == RELAY_HOST:
        # Apple's relay: the ids in the local part are the recipient's.
        address, keep = relay_address(address), ()
    out = EmailMessage()
    if private:
        _t_set(out, "From", f"Max Mustermann <{_T_MAIL}>")
    else:
        display = scrubber.scrub(scrubber.sellers_in(display), keep).replace('"', "").strip()
        _t_set(out, "From", f'"{display}" <{address}>' if display else address)
        if "From" not in out:
            _t_set(out, "From", address)
    _t_address_headers(msg, out, scrubber)
    # The HTML part with its links, pictures and attributes, see above (not for a mail that
    # looks forwarded, one from a private address or Eventim: see there).
    passed_on = forward or quoted_markup or private or looks_passed_on
    raw_markup = _t_html_part(msg) if has_html and not passed_on and not evt else None
    amazon = address.endswith("@amazon.de")
    rich = _THtml(scrubber, keep, raw_markup, amazon) if raw_markup else None
    # The run's item names and sellers also in a mail without a rich HTML part (a
    # cancellation, a carrier's mail that names the seller).
    names = rich or _THtml(scrubber, keep, "", amazon)
    names.context = "\n".join((raw_subject, plain, markup))
    raw_subject, plain = names.shop(raw_subject), names.shop(plain)
    subject = " ".join(scrubber.scrub(raw_subject, keep).split())
    _t_set(out, "Subject", subject)
    if evt:
        out["Date"] = evt_date(number)  # (the real one tells the day of the order)
    elif _t_header(msg, "Date"):
        _t_set(out, "Date", _t_header(msg, "Date"))
    label = scrubber.label(msg, number)
    out["Message-ID"] = f"<beispiel-{label}@example.org>"
    # (names and sellers first: their words are no words the scrubbing took out, see ``gone``)
    unscrubbed = markup = names.shop(markup)
    plain, markup = scrubber.scrub(plain, keep), scrubber.scrub(markup, keep)
    # (what the scrubbing of the HTML part as plain text took out never stays in the rich one)
    gone = _t_words(unscrubbed) - _t_words(markup)
    if has_plain or not has_html:
        _t_body(out, plain if plain.endswith("\n") or not plain else plain + "\n", "plain")
    if has_html:
        try:
            page = rich.render(gone) if rich else as_html(markup)
        except ValueError:  # (more elements than marks)
            page = as_html(markup)
        _t_body(out, page, "html", alternative=has_plain)
    if scrubber.fixed and out.is_multipart():
        out.set_boundary(f"===============beispiel-{label}==")  # else a random one
    domain = re.sub(r"[^a-z0-9.-]", "", address.rsplit("@", 1)[-1])
    domain = "privat" if private else domain or "unbekannt"
    name = f"{_t_day(out)}_{domain}_{label}" if scrubber.fixed else f"{label}_{domain}"
    left = scrubber.left(f"{out['From']}\n{subject}\n{plain}\n{page if has_html else markup}")
    return out, f"{name}.eml", private, left, looks_passed_on


def _t_day(out):
    """The day of the Date header of a result, for its file name."""
    try:
        return email.utils.parsedate_to_datetime(str(out["Date"])).strftime("%Y-%m-%d")
    except (TypeError, ValueError, IndexError):
        return "ohne-datum"


def _t_terminal():
    """True if somebody can answer on stdin. In some development environments the null
    device (subprocess.DEVNULL, "< NUL") says it is a terminal too; there Python reads a
    real console only through its console reader."""
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
        if os.name != "nt":
            return True
        return type(sys.stdin.buffer.raw).__name__ == "_WindowsConsoleIO"
    except Exception:  # a replaced stdin without these parts: nobody is asked
        return False


def _t_ask(values):
    """Ask on the terminal for every value that no option gave; an empty answer skips it."""
    missing = [key for key in _T_OPTIONS if not values[key]]
    if not missing:
        return
    print("Eigene Angaben, die in den Mails ersetzt werden. Leer lassen und Enter drücken")
    print("überspringt eine Angabe; mehrere Werte mit ; trennen.")
    for key in missing:
        try:
            answer = input(f"{_T_OPTIONS[key]}: ")
        except EOFError:
            break
        values[key].extend(answer.split(";"))


def _t_files(paths):
    files = []
    for path in paths:
        if os.path.isdir(path):
            files.extend(
                os.path.join(path, name) for name in sorted(os.listdir(path))
                if name.lower().endswith(".eml") and os.path.isfile(os.path.join(path, name))
            )
        elif os.path.isfile(path):
            files.append(path)
        else:
            raise _TUsage("Datei oder Ordner nicht gefunden." + (
                " Der Entwickler-Aufruf für Test-Fixtures braucht --fixtures."
                if len(paths) >= 6 else ""))
    if not files:
        raise _TUsage("Keine .eml-Dateien gefunden. Mails zuerst als .eml speichern.")
    return files


def _t_clear(out_dir):
    """Remove the results of an earlier run: the ZIP and the NNN_*.eml this script wrote."""
    for name in os.listdir(out_dir):
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path):
            continue
        if name == _T_ZIP:
            os.remove(path)
        elif re.fullmatch(r"\d{3}_[a-z0-9.-]+\.eml", name) and _t_own(path):
            os.remove(path)  # (a mail of someone else with such a name stays)


def _t_own(path):
    """A result of this script: its Message-ID is one the script invents."""
    with open(path, "rb") as handle:
        return b"\nMessage-ID: <beispiel-" in handle.read(8192)


def _t_salt(path, out_dir):
    """The salt in the file of --salt; a missing file is written with a random one."""
    folder = os.path.normcase(os.path.dirname(os.path.abspath(path)))
    if folder == os.path.normcase(os.path.abspath(out_dir)):
        raise _TUsage("Die Datei zu --salt darf nicht im Zielordner liegen (sie würde mit"
                      " hochgeladen).")
    if not os.path.exists(path):
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(secrets.token_hex(32) + "\n")
        except OSError:
            raise _TUsage("Die Datei zu --salt lässt sich nicht anlegen.") from None
        print(f"Neuer Salt in {os.path.abspath(path)}: behalten und nie weitergeben.")
    try:
        with open(path, encoding="utf-8") as handle:
            salt = handle.read().strip()
    except (OSError, UnicodeDecodeError):
        raise _TUsage("Die Datei zu --salt lässt sich nicht lesen.") from None
    if not _T_SALT.fullmatch(salt):
        raise _TUsage(
            "Die Datei zu --salt stammt nicht von diesem Skript. Einen Salt nicht selbst\n"
            "ausdenken (er ließe sich erraten): Fehlt die Datei, legt das Skript sie selbst an."
        )
    return salt


def _t_run(args):
    paths, out_dir, pack, usage, bare, salt, values = _t_parse(args)
    if usage:
        print(_T_USAGE + "\n" + _T_HELP)
        return 0
    if not paths:
        raise _TUsage("Datei oder Ordner fehlt.")
    files = _t_files(paths)
    first = os.path.abspath(paths[0])
    if out_dir is None:
        out_dir = os.path.join(first if os.path.isdir(first) else os.path.dirname(first),
                               "anonymisiert")
    if any(os.path.abspath(out_dir) == os.path.dirname(os.path.abspath(f)) for f in files):
        raise _TUsage("Der Zielordner darf nicht der Ordner mit den Original-Mails sein.")
    if not bare and _t_terminal():
        _t_ask(values)
    values = {
        key: [unicodedata.normalize("NFC", v.strip()) for v in found if v.strip()]
        for key, found in values.items()
    }
    if not any(values.values()) and not bare:
        raise _TUsage(
            "Ohne eigene Angaben erkennt das Skript Namen und Orte nur an typischen Stellen.\n"
            'Mindestens eine Angabe übergeben (z. B. --name "Vorname Nachname" --street ...'
            " --postcode ... --city ...)\n"
            f"oder mit {_T_BARE} ausdrücklich darauf verzichten."
        )
    if salt is not None:
        salt = _t_salt(salt, out_dir)
    scrubber = _TScrubber(values, salt)
    if not any(values.values()):
        print("ACHTUNG: Ohne eigene Angaben werden die Mails nur allgemein bereinigt")
        print("(Mail-Adressen, Telefonnummern, Links, Nummern, Ablageorte, Anreden, Adressblöcke")
        print("und Namen an typischen Stellen). Namen und Orte können stehen bleiben, wo das")
        print("Skript sie nicht als solche erkennt. Jede Datei Zeile für Zeile lesen. Sicherer")
        print("ist der Aufruf mit --name, --street, --postcode und --city.")
        print()
    for key in scrubber.short:
        print(f"Hinweis: Eine Angabe zu --{key} ist zu kurz und wird nicht verwendet.")
    mails, unreadable = [], []
    for path in files:
        try:
            mail = load(path)
            texts = _t_texts(mail)
            scrubber.learn(
                "\n".join(texts[:2]), _t_header(mail, "Subject"),
                *_t_sender(mail), _t_recipients(mail),
            )
            if _t_sender(mail)[1].endswith("@amazon.de"):
                _t_learn_amazon(scrubber, texts[:2], _t_html_part(mail))
            mails.append((os.path.basename(path), mail, texts))
        except Exception:
            unreadable.append(os.path.basename(path))
    try:
        os.makedirs(out_dir, exist_ok=True)
        _t_clear(out_dir)  # (a result with a salt is written over its own earlier one)
    except OSError:
        raise _TUsage("Der Zielordner lässt sich nicht anlegen oder leeren.") from None
    written, forwarded, doubtful, passed_on = [], 0, [], []
    for source, mail, texts in mails:
        number = len(written) + 1
        try:
            out, name, private, left, looks_passed_on = _t_build(mail, number, scrubber, texts)
            data = bytes(out)
        except Exception:  # no traceback: it could show a part of a mail
            unreadable.append(source)
            continue
        with open(os.path.join(out_dir, name), "wb") as handle:
            handle.write(data)
        written.append((name, data))
        forwarded += private
        if left:
            doubtful.append(name)
        if looks_passed_on:
            passed_on.append(name)
    print(f"{len(written)} Mail(s) anonymisiert, Ordner: {os.path.abspath(out_dir)}")
    for name, _ in written:
        print(f"  {name}")
    if pack and written:
        with zipfile.ZipFile(os.path.join(out_dir, _T_ZIP), "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in written:
                archive.writestr(name, data)
        print(f"ZIP: {os.path.join(os.path.abspath(out_dir), _T_ZIP)}")
    for name in unreadable:
        print(f"Nicht lesbar und ausgelassen: {name}")
    if forwarded:
        print(f"Hinweis: {forwarded} Mail(s) kommen von einer privaten Adresse (weitergeleitet?);"
              " der Absender wurde ersetzt. Besser die Original-Mail als .eml speichern.")
    if passed_on:
        print("ACHTUNG: Diese Mails sehen weitergeleitet aus: " + ", ".join(passed_on))
        print("Eine Signatur oder eigene Zeilen der Person, die weitergeleitet hat, kann das")
        print("Skript nicht erkennen. Diese Dateien besonders genau lesen. Hilfreicher ist die")
        print("Original-Mail, als .eml gespeichert.")
    if doubtful:
        print("ACHTUNG: In diesen Dateien steht noch eine der eigenen Angaben, vielleicht als")
        print("Teil eines anderen Wortes. Besonders genau lesen: " + ", ".join(doubtful))
    # Results of an earlier run that _t_clear leaves (those with a salt): named, not removed.
    done = {name for name, _ in written}
    stale = sorted(
        name for name in os.listdir(out_dir)
        if name.lower().endswith(".eml") and name not in done
        and os.path.isfile(os.path.join(out_dir, name)) and _t_own(os.path.join(out_dir, name))
    )
    if stale:
        print("ACHTUNG: Diese Dateien im Zielordner stammen aus einem früheren Lauf, nicht aus")
        print("diesem. Nicht mit hochladen: " + ", ".join(stale))
    if _t_html_notes["attributes"]:
        # (names only: a value may be private) For the developers: a rule of its own needed?
        print("Hinweis: Attribute ohne eigene Regel (mit erfundenem Wert geschrieben): "
              + ", ".join(sorted(_t_html_notes["attributes"])))
    print()
    print("WICHTIG: Jede Datei vor dem Hochladen selbst öffnen und durchlesen (ein Texteditor")
    print("genügt). Das Skript erkennt nicht alles: Steht noch etwas Privates drin, die Stelle")
    print("von Hand ersetzen oder die Mail weglassen" + (", danach das ZIP neu packen." if pack
                                                          else "."))
    print("Hochgeladen werden nur die Dateien " + ("dieses Laufs (oben aufgelistet)" if stale
                                                    else "aus diesem Ordner")
          + ", nie die Original-Mails.")
    return 0


def tester_main(args):
    """Exit code of the tester mode: 0 done, 2 wrong call, 1 aborted."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    try:
        return _t_run(args)
    except _TUsage as error:
        print(f"{_T_USAGE}\n{error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 1
    except Exception as error:  # only the kind of error: its text could show a value
        print(f"Unerwarteter Fehler ({type(error).__name__}), nichts hochladen.", file=sys.stderr)
        return 1


# Fixture mode only with the explicit flag; every other call is a tester's.
_ARGS = sys.argv[1:]
if "--fixtures" not in _ARGS:
    sys.exit(tester_main(_ARGS))
_ARGS.remove("--fixtures")

# ----- fixture mode -----
# - Personal values come only from the command line, there are no other options: an argument
#   starting with "-" is an error, so a mistyped call never runs with half the values.
# - Mails with a text/plain part are written as text/plain. HTML-only mails (eBay, older
#   Hermes) are converted to text, scrubbed and written back as simple text/html (one <p> per
#   line), so the parser's HTML fallback is exercised by the fixtures.
# - Numbering continues after the highest fixture in DST_DIR; mails with an already written
#   Message-ID are skipped.
# - Mails of other senders (shops) are never taken: a shop mail needed as a fixture is written
#   by hand with invented content and marked with an "X-Fixture: synthetic" header.
_USAGE = (
    "usage: anonymize_mail.py --fixtures SRC_DIR DST_DIR POSTCODE CITY FIRSTNAME LASTNAME"
    " [MAILDOMAIN ...]"
)
# Only the name of an unknown option is shown: its value may be private.
_ERRORS = [f"unknown option {arg.split('=', 1)[0]}" for arg in _ARGS if arg.startswith("-")]
if _ERRORS or len(_ARGS) < 6:
    print("\n".join([_USAGE, *_ERRORS]), file=sys.stderr)
    sys.exit(2)
SRC, DST, POSTCODE, CITY, FIRST, LAST = _ARGS[:6]
DOMAINS = _ARGS[6:] or ["gmail", "googlemail"]
GLS_SENDER = "no-reply@gls-pakete.de"
KEEP = {
    GLS_SENDER,
    "bestellbestaetigung@amazon.de", "versandbestaetigung@amazon.de",
    "shipment-tracking@amazon.de", "order-update@amazon.de", "pickup-point@amazon.de",
    "noreply@dhl.de", "pkginfo@ups.com", "noreply@paketankuendigung.myhermes.de", "ebay@ebay.com",
}
ALI_DOMAIN = "aliexpress.com"


def body(msg):
    """(text, was_html): text/plain if present, else text extracted from text/html."""
    for kind in ("plain", "html"):
        for part in msg.walk():
            if part.get_content_type() == f"text/{kind}":
                try:
                    content = part.get_content()
                except Exception:
                    content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
                return (content, False) if kind == "plain" else (html_to_text(content), True)
    return "", False


def sender(msg):
    return (re.findall(r"<([^>]+)>", str(msg["From"])) or [str(msg["From"])])[0].lower()


def is_aliexpress(address):
    """A sender at aliexpress.com, also passed on by Apple's relay."""
    host = (relay_original(address) or address).rpartition("@")[2]
    return host == ALI_DOMAIN or host.endswith("." + ALI_DOMAIN)


FIRST_RE = re.escape(FIRST).replace("ö", "(?:ö|oe)").replace("ä", "(?:ä|ae)").replace(
    "ü", "(?:ü|ue)"
)
_ABLAGE_NEXT = re.compile(r"(Ablageort:)[ \t]*\n+[ \t]*([^\n]+)")
_ABLAGE_SAME = re.compile(r"(Ablageort:)[ \t]*([^\n]+)")
_ABLAGE_PHRASE = re.compile(r"(Ablageort )(.+?)( erkannt)")
_SELLER = re.compile(r"(Verkäufer:)[ \t]*\n+[ \t]*([^\n]+)")
# A German state on its own line (address block of old Amazon mails).
_REGION = re.compile(
    r"(?im)^[ \t]*(?:NRW|BW|BY|BE|BB|HB|HH|HE|MV|NI|NW|RP|SL|SN|ST|SH|TH|Bayern|Berlin|Brandenburg"
    r"|Bremen|Hamburg|Hessen|Niedersachsen|Nordrhein-Westfalen|Rheinland-Pfalz|Saarland"
    r"|Sachsen|Sachsen-Anhalt|Schleswig-Holstein|Th(?:ü|ue)ringen|Baden-W(?:ü|ue)rttemberg"
    r"|Mecklenburg-Vorpommern)[ \t]*\n"
)
_SHIP_TO = re.compile(r"(Geliefert an:)[ \t]*\n(?:[^\n]*\n){1,6}?(Deutschland)")


# ----- GLS -----
# Sender: no-reply@gls-pakete.de.
# - Replaced as a whole, whatever they contain: the recipient blocks ("*Zustelladresse*",
#   "*Empfänger*", "*an NAME*" of the delivery mail) and the sender block ("*Versender*").
# - Replaced in the text and in the subject (and so in the file name): phone numbers, parcel
#   numbers (99999999901, 99999999902, ... in order of appearance), references and the
#   drop-off place ("Ablageort: Garage").
# - The legal footer is cut.
# - Recipient and company names learnt from these blocks are replaced in every mail.

# GLS:"*Zustelladresse*" / "*Empfänger*" + name line (+ address lines) up to the next
# empty line; "*Versender*" + company line (+ address lines) likewise.
_GLS_RECIPIENT_BLOCK = re.compile(
    r"(\*(?:Zustelladresse|Empfänger)\*[ \t]*\n)((?:[ \t]*[^\s][^\n]*\n)+)"
)
# GLS delivery mail: "*an NAME*" + address lines up to the next rule or empty line.
_GLS_DELIVERED_TO = re.compile(r"(?m)^(\*an )[^*\n]+(\*[ \t]*\n)((?:[ \t]*[^\s-][^\n]*\n)*)")
_GLS_COMPANY_BLOCK = re.compile(r"(\*Versender\*[ \t]*\n)((?:[ \t]*[^\s][^\n]*\n)+)")
_GLS_FROM = re.compile(r"(?i)(Paket von(?: dem Absender)?[ \t]*\n\s*)([^\n]+)")
_GLS_PLACE = re.compile(r"(\*Gewünschter Abstellort\*[ \t]*\n(?:[-\s]*\n)*)([^\n]+)")
_GLS_FOOTER = re.compile(r"\n[* \t]*General Logistics Systems Germany.*", re.DOTALL)
_GLS_REFERENCE = re.compile(r"\(Referenz:[^)]*\)")
_GLS_NUMBER = re.compile(r"(?<!\d)\d{11}(?!\d)")
# International (+49 ...) or national (0..., 8 or more digits, blanks/slashes/dashes between
# them). 11 bare digits are a parcel number, a date or a postcode is too short.
_PHONE = re.compile(
    r"\+\d[\d /-]{6,}\d|(?<![\w+./=-])(?!\d{11}(?!\d))0\d(?:[ /-]?\d){6,}"
)
_PHONE_PLACEHOLDER = "+49 000 0000000"
_LEGAL_FORM = re.compile(r"\s+(?:GmbH|AG|KG|UG|SE|OHG|GbR|Ltd|mbH|e\.\s?K\.|B\.\s?V\.|&)(?!\w).*$")

# Pass 1: learn street lines, drop-off texts, seller, company and recipient names from every
# mail.
street, ablage, sellers, companies, recipients = set(), set(), set(), set(), set()
for path in glob.glob(SRC + "/*.eml"):
    mail = load(path)
    text, _ = body(mail)
    if sender(mail) == GLS_SENDER:
        companies.update(m.group(2).splitlines()[0].strip("* \t") for m in
                         _GLS_COMPANY_BLOCK.finditer(text))
        companies.update(m.group(2).strip("* \t") for m in _GLS_FROM.finditer(text))
        ablage.update(m.group(2).strip() for m in _GLS_PLACE.finditer(text))
        # the name line of a recipient block, without the phone number behind the name
        recipients.update(re.split(r"[+\d]", m.group(2).splitlines()[0])[0].strip("* \t")
                          for m in _GLS_RECIPIENT_BLOCK.finditer(text))
        recipients.update(m.group(0).splitlines()[0][4:].strip("* \t")
                          for m in _GLS_DELIVERED_TO.finditer(text))
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if POSTCODE in line:
            for j in range(max(0, i - 3), i):
                s = lines[j].strip()
                if s and re.search(r"\d", s) and len(s) < 60:
                    street.add(s)
            if len(line.strip()) < 60:
                street.add(line.strip())
    for pattern in (_ABLAGE_NEXT, _ABLAGE_SAME, _ABLAGE_PHRASE):
        ablage.update(m.group(2).strip() for m in pattern.finditer(text))
    sellers.update(m.group(2).strip() for m in _SELLER.finditer(text))
ablage = {a for a in ablage if a and a != "Garage"}
companies = {c for c in companies if c}
recipients = {r for r in recipients if len(r) >= 3}
# Bare shop names: a company without its legal form.
shop_names = {n for n in (_LEGAL_FORM.sub("", c) for c in companies) if len(n) >= 4}
gls_numbers = {}


def _gls_number(match):
    real = match.group(0)
    if real not in gls_numbers:
        gls_numbers[real] = f"{99999999901 + len(gls_numbers)}"
    return gls_numbers[real]


def _gls_company(match):
    lines = match.group(2).splitlines()
    address = "Beispielweg 2 ,\n00000 Beispielstadt\n" if len(lines) > 1 else ""
    return f"{match.group(1)}Beispiel GmbH\n{address}"


def _gls_recipient(match):
    lines = match.group(2).splitlines()
    # A digit in the name line is the phone number GLS prints behind the name.
    phone = f" {_PHONE_PLACEHOLDER}" if re.search(r"\d", lines[0]) else ""
    address = "Musterstraße 1 ,\n12345 Musterstadt\n" if len(lines) > 1 else ""
    return f"{match.group(1)}Max Mustermann{phone}\n{address}"


def _gls_delivered_to(match):
    address = "Musterstraße 1 ,\n12345 Musterstadt\n" if match.group(3) else ""
    return f"{match.group(1)}Max Mustermann{match.group(2)}{address}"


def scrub_gls_values(t):
    """GLS mails only, text and subject: references, phone and parcel numbers."""
    t = _GLS_REFERENCE.sub("(Referenz: REF-0001)", t)
    t = _PHONE.sub(_PHONE_PLACEHOLDER, t)
    return _GLS_NUMBER.sub(_gls_number, t)


def scrub_gls(t):
    """GLS mails only, the text: runs before scrub()."""
    t = _GLS_FOOTER.sub("\n", t)
    if not t.endswith("\n"):
        t += "\n"
    t = _GLS_RECIPIENT_BLOCK.sub(_gls_recipient, t)
    t = _GLS_DELIVERED_TO.sub(_gls_delivered_to, t)
    t = _GLS_COMPANY_BLOCK.sub(_gls_company, t)
    t = _GLS_PLACE.sub("\\1Ablageort: Garage", t)
    return scrub_gls_values(t)


# ----- AliExpress -----
# Senders: transaction@notice.aliexpress.com and every other sender at aliexpress.com, also
# passed on by Apple's relay. Nothing of the buyer or the purchase stays:
# - The text ends in front of the offers and the footer.
# - Replaced: the greeting, the block below "Versand nach", the day of the order, the shop's
#   name, item names (invented ones, cut where the real one was cut), variants, quantities
#   and prices.
# - Order numbers and the carrier's number become 99…0001, 99…0002, … in order of appearance.
#   A prefix of letters and DHL's 00340 stay, so the carrier is still told.
# - The links of a mail about a parcel name its orders: each is kept as one invented link
#   with the replaced number. All other links are cut to the host.
# - The ids in a relay address are replaced by invented ones of the same length.
_ALI_ITEMS = (
    "Beispiel-Kabel USB-C auf USB-A geflochten 2 m schwarz",
    "Beispiel-Sensor für Temperatur und Luftfeuchte weiß",
    "Beispiel-Schalter kabellos mit Batterie zum Kleben",
    "Beispiel-Lampe LED flach mit Bewegungsmelder warmweiß",
    "Beispiel-Handtuch aus Baumwolle 70 x 140 cm grau",
    "Beispiel-Spielzeug Kreisel aus Metall für Kinder bunt",
    "Beispiel-Ersatzteil Getriebe Set für Modellauto 1:14",
    "Beispiel-Netzteil 12 V 2 A mit Hohlstecker schwarz",
    "Beispiel-Halterung für die Wand aus Aluminium silber",
    "Beispiel-Trikot Größe L mit Rückennummer blau",
)
_ALI_URL = re.compile(r"https?://[^\s<>\]\)\"]+")
_ALI_LINK_ORDERS = re.compile(r"(?i)[?&](?:tradeOrderId|o_ids|orderId)=(\d+(?:(?:,|%2C)\d+)*)")
_ALI_PARCEL_SUBJECT = re.compile(r"(?:Packstück|Zollabfertigung für) ")
# A carrier's number or an order number: letters in front stay, the digits are counted.
_ALI_NUMBER = re.compile(r"(?<![0-9A-Za-z])([A-Z]{0,4})(\d{12,22})(?![0-9A-Za-z])")
_ALI_GREETING = re.compile(r"(?m)^(Hallo|Hi)\b[^\n,]*(?:\n[^\n,]*)?,")
# The name of an account nobody named: "ae<digits>" and a word of the buyer behind it.
_ALI_ALIAS = re.compile(r"\bae\d{5,}(?:[ .][^\W\d_]+)?")
_ALI_SHIP_TO = "versand nach"
_ALI_PHONE = re.compile(r"\(\+\d+\)")
_ALI_PAYMENT = "zahlungsmethode"
_ALI_BLANK = re.compile(r"[\s.\u00ad\u034f\u200b-\u200f\u2060\ufeff]*")
_ALI_NO_LINK = re.compile(r"<\s*>|\[\s*\]|\(\s*\)")
# The text ends here: offers and the footer with the buyer's address.
_ALI_END = re.compile(
    r"(?i)(?:Das|Dies) könnte Ihnen auch gefallen|Weitere Artikel anzeigen"
    r"|Jetzt herunterladen|Die in dieser E-Mail angezeigten Preise|Diese E-Mail wurde gesendet"
    r"|This email was sent|Beliebte Kategorien|Gesendet mit Liebe|Sent with"
)
_ALI_PLACED = re.compile(r"Aufgegeben am\b.*")
_ALI_QUANTITY = re.compile(r"(€ ?)?(?:[\d.,]+)?( ?)x\d+")
_ALI_VARIANT_QUANTITY = re.compile(r"\S.* x\d+")
_ALI_PRICE = re.compile(r"€ ?\d[\d.]*,\d\d|\d[\d.]*,\d\d ?€")
_ALI_ORDER_LINE = re.compile(r"Bestellung \d{13,22}")
_ALI_ABOVE_ITEMS = {
    "paketinfos", "bestellung verfolgen", "sendungsverfolgung", "lieferung verfolgen",
    "empfang bestätigen", "bewertung schreiben", "bestellung prüfen", "bestelldetails",
    "bestelldetails anzeigen", "details anzeigen", "aktualisierung anzeigen", "bestätigt",
    "verpackt", "versandt", "im transit", "zugestellt",
}
ali_numbers, ali_items = {}, {}


def _ali_number(match):
    letters, digits = match.groups()
    real = letters + digits
    if real in ali_numbers.values():
        return real  # an invented number met again
    if real not in ali_numbers:
        keep = "00340" if digits.startswith("00340") and len(digits) == 20 else ""
        count = f"{len(ali_numbers) + 1:04d}"
        ali_numbers[real] = letters + keep + "9" * (len(digits) - len(keep) - 4) + count
    return ali_numbers[real]


def _ali_item(real):
    """An invented item name for a real one, cut where AliExpress cut the real one."""
    core = real.rstrip(" .…")
    if not core:
        return real  # only dots: the mail shows no name
    key = re.sub(r"\W+", "", core.lower())[:12]
    if key not in ali_items:
        ali_items[key] = _ALI_ITEMS[len(ali_items) % len(_ALI_ITEMS)]
    invented = ali_items[key]
    if core == real.strip():
        return invented[:len(core)].rstrip()
    return invented[:len(core)].rstrip() + real.strip()[len(core):]


def _ali_above_items(lines, index):
    line = lines[index]
    return bool(
        _ALI_QUANTITY.fullmatch(line) or _ALI_VARIANT_QUANTITY.fullmatch(line)
        or line.lower() in _ALI_ABOVE_ITEMS or _ALI_ORDER_LINE.fullmatch(line)
        or (index > 0 and lines[index - 1].startswith("Aufgegeben am"))
    )


def ali_link_orders(msg):
    """The order numbers the links of a mail name (they stand nowhere in its text)."""
    orders = []
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                content = part.get_content()
            except Exception:
                content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
            for listed in _ALI_LINK_ORDERS.findall(html.unescape(content)):
                for order in re.findall(r"(?<!\d)\d{12,20}(?!\d)", listed):
                    if order not in orders:
                        orders.append(order)
    return orders


def scrub_aliexpress(t, order_digits=0):
    """AliExpress mails only, the text: runs before scrub(). ``order_digits``: the length
    of the order number in the subject (a list of orders counts them in front of it)."""
    lines = []
    for line in t.replace("\r\n", "\n").split("\n"):
        line = _ALI_NO_LINK.sub("", _ALI_URL.sub("", line))
        line = re.sub(r"[ \t\xa0]+", " ", line).strip(" [<>]")
        if _ALI_END.match(line):
            break
        if not _ALI_BLANK.fullmatch(line):
            lines.append(line)
    out, skip = [], 0
    for index, line in enumerate(lines):
        if skip:
            skip -= 1
            continue
        if line.lower() == _ALI_SHIP_TO:
            # The block ends with the name and phone line; without one it is one line.
            rest = lines[index + 1:index + 5]
            phone = next((i for i, row in enumerate(rest) if _ALI_PHONE.search(row)), None)
            skip = 1 if phone is None else phone + 1
            out.append(line)
            out.append("Musterstraße 1, Musterstadt")
            if phone is not None:
                out.append("Max Mustermann (+49) 0000000000")
            continue
        if _ALI_PLACED.fullmatch(line):
            out += ["Aufgegeben am Jan 01,2026, 12:00", "Beispiel Store"]
            skip = 1  # the shop's name
            continue
        if line.lower() == _ALI_PAYMENT:
            skip = 1  # how the order was paid
            continue
        out.append(line)
    # Items: name, mostly a variant, then the quantity; found from the quantity upwards.
    for index, line in enumerate(out):
        variant = None
        if found := _ALI_QUANTITY.fullmatch(line):
            out[index] = f"{'€ 1,99' if found.group(1) else ''}{found.group(2)}x1"
            rows = (index - 2, index - 1)
        elif _ALI_VARIANT_QUANTITY.fullmatch(line):
            out[index], rows = "Variante A x1", (index - 1,)
        else:
            continue
        if rows[0] < 0 or _ali_above_items(out, rows[-1]):
            continue
        if len(rows) == 2 and not _ali_above_items(out, rows[0]):
            variant = rows[1]
        name = rows[0] if variant is not None or len(rows) == 1 else rows[-1]
        out[name] = _ali_item(out[name])
        if variant is not None:
            out[variant] = "Variante A"
    for index, line in enumerate(out):
        if order_digits and _ALI_ORDER_LINE.fullmatch(line):
            # "Bestellung " + running number + order number
            digits = line.split()[-1]
            count, order = digits[:-order_digits], digits[-order_digits:]
            out[index] = f"Bestellung {count}\x00{_ALI_NUMBER.sub(_ali_number, order)}"
    t = "\n".join(out) + "\n"
    t = _ALI_GREETING.sub("\\1 Max Mustermann,", t)
    t = _ALI_ALIAS.sub("Max Mustermann", t)
    t = _ALI_PRICE.sub(lambda m: "€ 1,99" if m.group(0).startswith("€") else "1,99€", t)
    return _ALI_NUMBER.sub(_ali_number, t).replace("\x00", "")


def fake(kind, real):
    h = int(hashlib.sha256(real.encode()).hexdigest(), 16)
    digits = str(h)
    if kind == "order":
        return f"999-{h % 10**7:07d}-{(h // 10**7) % 10**7:07d}"
    if kind == "ebay_order":
        return f"99-{h % 10**5:05d}-{(h // 10**5) % 10**5:05d}"
    if kind == "item":
        return "9999" + digits[:8]
    if kind == "hermes_h":
        return "H9999" + digits[:15]
    if kind == "digits14":
        return "9999" + digits[:10]
    if kind == "jjd":
        return "JJD0000" + digits[:14]
    if kind == "1z":
        return "1Z999AA1" + digits[:10]
    if kind == "tba":
        return "TBA" + digits[:12]
    if kind == "shipment":
        rest = "".join(_AMZ_ALPHABET[(h >> 6 * i) % 62] for i in range(len(real) - 1))
        return real[0] + rest
    return real


# ----- Amazon: the link to the tracking page -----
# The mails from "Versendet" on link the box's tracking page with the order and the box's id
# (shipmentId); the mail import tells the boxes of an order apart by it. Each such link is
# kept where it stands, as one invented link: the replaced order number and an invented id,
# the same for the same box in every mail, its first letter kept ("D": sent by the seller).
# Through Amazon's redirect as well. Any other link is cut to the host as before.
_AMZ_LINK = re.compile(r"(?i)https://(?:www\.)?amazon\.de(/[^?#\s]*)\?([^#\s]*)")
_AMZ_TRACKER = "/progress-tracker/package"
_AMZ_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _unquote(text):
    return re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), text)


def _amz_tracker(link, redirect=True):
    """(order, id) a link to Amazon's tracking page names, else None (no urllib: the script
    stays clear of every module that could reach the network)."""
    match = _AMZ_LINK.fullmatch(html.unescape(link))
    if match is None:
        return None
    path = match.group(1)
    params = dict(part.partition("=")[::2] for part in match.group(2).split("&"))
    if redirect and path == "/gp/r.html" and params.get("U"):
        return _amz_tracker(_unquote(params["U"]), redirect=False)
    order, shipment = _unquote(params.get("orderId", "")), _unquote(params.get("shipmentId", ""))
    if path == _AMZ_TRACKER and re.fullmatch(r"\d{3}-\d{7}-\d{7}", order) and re.fullmatch(
        r"[A-Za-z0-9]{5,20}", shipment
    ):
        return order, shipment
    return None


def mark_amazon_trackers(t):
    """(text, links): each link to the tracking page replaced by a mark that ``scrub`` leaves
    alone, and the invented links in the order of their marks."""
    links = []

    def mark(match):
        if (found := _amz_tracker(match.group(0))) is None:
            return match.group(0)
        order, shipment = found
        links.append(
            f"https://www.amazon.de{_AMZ_TRACKER}?orderId={fake('order', order)}"
            f"&packageIndex=0&shipmentId={fake('shipment', shipment)}"
        )
        return f"\x00{len(links) - 1}\x00"

    return re.sub(r"https?://[^\s<>\]\)\"]+", mark, t), links


def scrub(t):
    t = _SHIP_TO.sub(
        "\\1\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\n\\2", t
    )
    for s in sorted(street, key=len, reverse=True):
        t = t.replace(s, "Musterstraße 1")
    for a in sorted(ablage, key=len, reverse=True):
        t = t.replace(a, "Garage")
    t = _ABLAGE_NEXT.sub("\\1\nGarage", t)
    t = _ABLAGE_PHRASE.sub("\\1Garage\\3", t)
    for s in sorted(sellers, key=len, reverse=True):
        t = t.replace(s, "beispielshop")
    for c in sorted(companies, key=len, reverse=True):
        t = t.replace(c, "Beispiel GmbH")
    for n in sorted(shop_names, key=len, reverse=True):
        t = re.sub(rf"(?i)(?<!\w){re.escape(n)}(?!\w)", "Beispielshop", t)
    for r in sorted(recipients, key=len, reverse=True):
        t = t.replace(r, "Max Mustermann")
    t = re.sub(rf"(?i){FIRST_RE}\s*{re.escape(LAST)}", "Max Mustermann", t)
    t = re.sub(rf"(?i)\b{FIRST_RE}\w*", "Max", t)
    t = re.sub(rf"(?i)\b{re.escape(LAST)}\b", "Mustermann", t)
    t = re.sub(r"(?m)^(Hallo )(?!Max\b)([^\s,]+),", "\\1max,", t)
    t = re.sub(r"[\w.+-]+@(" + "|".join(map(re.escape, DOMAINS)) + r")\.[\w.]+",
               "max@example.org", t)
    t = _REGION.sub("", t)
    t = t.replace(POSTCODE, "12345")
    t = re.sub(rf"\b{re.escape(CITY)}\b", "Musterstadt", t)
    t = re.sub(r"\b\d{3}-\d{7}-\d{7}\b", lambda m: fake("order", m.group(0)), t)
    t = re.sub(r"\b\d{2}-\d{5}-\d{5}\b", lambda m: fake("ebay_order", m.group(0)), t)
    t = re.sub(r"\bH\d{19}\b", lambda m: fake("hermes_h", m.group(0)), t)
    t = re.sub(r"(?<![\d-])\d{14}(?![\d-])", lambda m: fake("digits14", m.group(0)), t)
    t = re.sub(r"(?<![\d-])\d{12}(?![\d-])", lambda m: fake("item", m.group(0)), t)
    t = re.sub(r"\bJJD\d{10,}\b", lambda m: fake("jjd", m.group(0)), t)
    t = re.sub(r"\b1Z[0-9A-Z]{16}\b", lambda m: fake("1z", m.group(0)), t)
    t = re.sub(r"\bTBA\d{9,}\b", lambda m: fake("tba", m.group(0)), t)
    t = re.sub(r"(?i)(einmalpasswort[^0-9\n]{0,40})\d{4,8}", r"\g<1>123456", t)
    t = re.sub(r"\[#[0-9a-f]{16,}\]", "[#00000000000000000000000000000000]", t)
    t = re.sub(r"https?://[^\s<>\]\)\"]+",
               lambda m: re.match(r"https?://[^/\s]+", m.group(0)).group(0) + "/…", t)
    return t


os.makedirs(DST, exist_ok=True)
numbers = [int(m.group(1)) for f in os.listdir(DST) if (m := re.match(r"(\d{3})_", f))]
n = max(numbers, default=0)
seen = set()
for f in os.listdir(DST):
    if f.endswith(".eml"):
        seen.add(str(load(os.path.join(DST, f))["Message-ID"]))
written = evt_count = 0
for path in sorted(glob.glob(SRC + "/*.eml")):
    m = load(path)
    a = sender(m)
    ali = is_aliexpress(a)
    evt = is_eventim(a)
    if a not in KEEP and not ali and not evt:
        continue
    mid = "<" + hashlib.sha256(str(m["Message-ID"]).encode()).hexdigest()[:24] + "@example.org>"
    if mid in seen:
        continue
    seen.add(mid)
    text, was_html = body(m)
    subject = str(m["Subject"])
    if a == GLS_SENDER:
        # The text first: parcel numbers are counted in the order of the mail texts.
        text = scrub_gls(text)
        subject = scrub_gls_values(subject)
    links, tracked = [], []
    if a.endswith("@amazon.de"):
        text, tracked = mark_amazon_trackers(text)
    if ali:
        in_subject = re.search(r"(?<!\d)\d{12,20}(?!\d)", subject)
        text = scrub_aliexpress(text, len(in_subject.group(0)) if in_subject else 0)
        subject = _ALI_NUMBER.sub(_ali_number, _ALI_ALIAS.sub("Max Mustermann", subject))
        if _ALI_PARCEL_SUBJECT.match(subject):
            links = [_ALI_NUMBER.sub(_ali_number, order) for order in ali_link_orders(m)]
    if evt:
        evt_count += 1
        if (relay_original(a) or a) == EVT_ORDER_SENDER:
            text, subject = scrub_eventim(text), scrub_eventim_subject(subject)
        else:
            text, subject = _EVT_OTHER_TEXT, _EVT_OTHER_SUBJECT
        a, was_html = evt_address(a), False
    out = EmailMessage()
    # (of an AliExpress or Eventim mail only the address stays, with invented ids in a
    # relay address)
    if ali:
        out["From"] = f"AliExpress <{relay_address(a)}>"
    else:
        out["From"] = f"EVENTIM <{a}>" if evt else str(m["From"])
    out["To"] = "max@example.org"
    subject = scrub(subject)
    out["Subject"] = subject
    out["Date"] = evt_date(evt_count) if evt else str(m["Date"])
    out["Message-ID"] = mid
    text = re.sub(r"\x00(\d+)\x00", lambda m: tracked[int(m.group(1))], scrub(text))
    # The orders of an AliExpress parcel: one invented link each, as the mail has them.
    link = "https://www.aliexpress.com/p/tracking/index.html?tradeOrderId="
    if was_html:
        markup = as_html(text)
        anchors = "".join(f'<p><a href="{link}{order}">Lieferung verfolgen</a></p>\n'
                          for order in links)
        out.set_content(markup.replace("</body>", anchors + "</body>"), subtype="html")
    else:
        out.set_content(text + "".join(f"Lieferung verfolgen <{link}{order}>\n"
                                       for order in links))
    # File name from the scrubbed subject, without item titles (after ':' or a quote).
    subj = re.sub(r"[„“\":].*", "", subject)
    name = re.sub(r"[^a-z0-9]+", "_", (a.split("@")[0] + "_" + subj).lower()).strip("_")[:40]
    if ali:
        # The status instead: the local part of a relay address and the number say nothing.
        words = re.sub(r"[0-9A-Z]*\d{6,}", "", subject)
        name = re.sub(r"[^a-z0-9]+", "_", ("aliexpress_" + words).lower()).strip("_")[:40]
    if evt:
        # The kind of mail: the event's name (behind the colon) and the number say nothing.
        words = re.sub(r"\d{6,}", "", re.sub(r"(?i)eventim(?:\.de)?", "", subj))
        local = relay_original(a) or a
        words = words if local == EVT_ORDER_SENDER else local.split("@")[0]
        name = re.sub(r"[^a-z0-9]+", "_", ("eventim_" + words).lower()).strip("_")[:40]
    n += 1
    written += 1
    with open(f"{DST}/{n:03d}_{name}.eml", "wb") as handle:
        handle.write(bytes(out))
print("written", written, "street patterns", len(street), "drop-off texts", len(ablage),
      "sellers", len(sellers), "companies", len(companies), "gls numbers", len(gls_numbers))

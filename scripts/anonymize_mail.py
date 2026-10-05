"""Anonymise parcel mails: for testers (sample mails for an issue) and for the fixtures.

Runs locally with the Python standard library only (Python 3.9 or newer), as a single file,
without network access.

Tester mode (messages in German):

    python3 anonymize_mail.py <file.eml | folder> [--zip] [--out DIR] [--ohne-angaben]
        [--name "First Last"] [--street ...] [--postcode ...] [--city ...] [--phone ...]
        [--email ...]

Takes the mails of every sender and writes them to "anonymisiert/" next to the mails as
001_<sender domain>.eml, with --zip also as paket-tracker-beispiele.zip; results of an earlier
run in that folder (the ZIP and the NNN_*.eml files this script wrote) are removed first. A
value that no option gives is asked for on a terminal (an empty answer skips it). Without any
value the call is refused (exit code 2) unless --ohne-angaben says that this is intended; then
nothing is asked, only the generic scrubbing runs and a warning says that names and places may
remain. Replaced are the given values in every spelling (case, ae/oe/ue, name parts, street
with any or no house number), every mail address but the sender's (the sender of a forwarded
or answered mail is a person and is replaced too, as is a sender address that carries another
address in its local part; of a forwarded mail with a quoted header block "Von: … / Gesendet:
… / An: … / Betreff: …" only that block and the mail below it are taken, the lines above it
are dropped, the quoted sender address stays and the quoted recipients are replaced), phone
numbers, links (cut to the host), tracking, order and other
long numbers (same length and structure, invented digits, the same number becomes the same
replacement in every mail of a run, a number of ten digits or more written in groups with
spaces, tabs, dots or dashes keeps its groups, as does an international number, and a
tracking number that stands only in a link or in the text of an image is kept as a marked
line "[Nummer nur im Link oder Bildtext: ...]"), drop-off places and permissions, salutations, recipient
address blocks ("PLZ Ort", "Ort, PLZ", "ORT BUNDESLAND PLZ"), addresses without a label
(street line above a postcode and city, lines with postcode and city), Amazon's "first name –
place" line above the order number, the names of neighbours and of the person that took the
parcel, and senders or sellers that are no company (in the text, in the From display name and
in the subject). What the rules find in one mail (the recipient's name with each of its words,
street, postcode and place, private senders, drop-off places, also the display name of the To
header) is replaced in every mail of the run. Only From, Subject and Date are kept of the
headers; HTML parts are reduced to their text (one <p> per line, no attributes, no comments)
and every other attachment is dropped. The replaced values are never printed. Exit codes:
0 done, 2 wrong call.

Fixture mode (for the developer, only with the explicit flag):

usage: anonymize_mail.py --fixtures SRC_DIR DST_DIR POSTCODE CITY FIRSTNAME LASTNAME [MAILDOMAIN ...]

Personal values come only from the command line; there are no other options (an argument
starting with "-" is an error, so a mistyped call never runs with half the values). Mails with a
text/plain part are written as text/plain; HTML-only mails (eBay, older Hermes) are converted
to text, scrubbed and written back as simple text/html (one <p> per line), so the parser's
HTML fallback is exercised by the fixtures. Numbering continues after the highest fixture in
DST_DIR; mails with an already written Message-ID are skipped.

GLS mails (no-reply@gls-pakete.de): the recipient blocks ("*Zustelladresse*", "*Empfänger*",
"*an NAME*" of the delivery mail) and the sender block ("*Versender*") are replaced as a
whole, whatever they contain; phone numbers, parcel numbers (99999999901, 99999999902, ... in
order of appearance), references and the drop-off place ("Ablageort: Garage") are replaced in
the text and in the subject (and so in the file name), and the legal footer is cut. Recipient
and company names learnt from these blocks are replaced in every mail. Mails of other senders
(shops) are never taken: a shop mail needed as a fixture is written by hand with invented
content and marked with an "X-Fixture: synthetic" header.
"""
import email
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


# ----- tester mode: anonymise own mails before they are attached to a GitHub issue -----
_T_USAGE = (
    'usage: anonymize_mail.py <Datei.eml | Ordner> [--zip] [--out ORDNER] [--ohne-angaben]\n'
    '           [--name "Vorname Nachname"] [--street "Straße Hausnummer"] [--postcode PLZ]\n'
    '           [--city ORT] [--phone TELEFON] [--email MAILADRESSE]\n'
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

Ersetzt werden außerdem alle Mail-Adressen außer dem Absender, Telefonnummern, Links (nur
der Servername bleibt), Sendungs-, Bestell- und andere lange Nummern (gleiche Form, erfundene
Ziffern), Ablageorte, Anreden, Adressblöcke, Zeilen mit Postleitzahl und Ort sowie Namen von
Nachbarn, Empfängern und privaten Absendern. Technische Kopfzeilen und Anhänge entfallen.
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
_T_B0, _T_B1 = r"(?<![^\W\d_])", r"(?![^\W\d_])"  # no letter before / behind
_T_UMLAUT = {"ä": "a", "ö": "o", "ü": "u"}
_T_DIGRAPH = {"ae": "ä", "oe": "ö", "ue": "ü"}
# "=" and "%" belong to the local part: bounce+user=gmx.de@shop.example is one address.
_T_ADDRESS = r"[\w.+%=&~-]+@[\w-]+(?:\.[\w-]+)+"
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
_T_PLACE = (
    r"\w*(?:ablageort|abstellort|wunschort|ablageplatz|abstellplatz|abstellgenehmigung"
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
    rf"(?:{_T_BARE_POSTCODE}|[^\n:]{{0,60}}?\b\d{{5}}\b[^\n]*)"
)
_T_ADDRESS_LINE = re.compile(
    rf"(?im)^([*_ \t]*{_T_RECIPIENT}[*_ \t]*:[ \t]*)(\S[^\n]*\b\d{{5}}\b[^\n]*)$"
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
    r"|beispielversender|beispielnachbar|erforderlich|unbekannt|vorhanden|neu\w*|wichtig\w*)"
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
    r"(?m)((?:(?:Sendung|Paket|Päckchen|Lieferung|Antrag|Auftrag) von|(?:request|behalf) of) )"
    r"(?!(?:Ihnen|Ihre[mnrs]?|Dir|Deine[mnrs]?|Uns|Unsere[mnrs]?|Montag|Dienstag|Mittwoch"
    r"|Donnerstag|Freitag|Samstag|Sonnabend|Sonntag|Heute|Gestern|Morgen)\b)"
    r"((?:[A-ZÄÖÜ][^\s,:]* ){0,3}?[A-ZÄÖÜ](?:[^\s,:]*[^\s,:.])?)"
    r"(?= (?:wurde|wird|kommt|ist|befindet|mit der|hat|liegt|konnte|kann|möchten|to)\b"
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
# An address without a label: [name line,] street with house number, postcode and city.
_T_STREET = (
    r"[^\W\d_][^\n\d:@,;|]{2,40}?[ \t.]\d{1,4}(?:[ \t]?[a-zA-Z]\b)?"
    r"(?:[ \t]?[-/+][ \t]?\d{1,4}(?:[ \t]?[a-zA-Z]\b)?)?"
)
_T_PLZ = r"(?:D[- ])?(?!12345[ \t]+Musterstadt|00000[ \t]+Beispielstadt)\d{5}"
_T_CITY = (
    r"[A-ZÄÖÜ][^\W\d_]+\.?(?:[ \t-]+(?:[A-ZÄÖÜ][^\W\d_]*\.?|am|an|der|im|in|bei|ob|vor"
    r"|a\.|d\.|\([^)\n]{1,20}\))){0,3}"
)
_T_PLAIN_BLOCK = re.compile(
    r"(?m)^(?P<lead>[*_> \t]*)"
    r"(?:(?P<name>[^\W\d_][^\n\d:@,;|]{3,50}?)[ \t]*,?[ \t]*\n(?P<lead2>[*_> \t]*))?"
    rf"(?P<street>{_T_STREET})[ \t]*,?[ \t]*\n(?P<lead3>[*_> \t]*)"
    rf"(?P<plz>{_T_PLZ})[ \t]+(?P<city>{_T_CITY})"
)
_T_INLINE_ADDRESS = re.compile(
    rf"(?m)(?P<lead>^[*_> \t]*|[,:|·•][ \t]*)(?P<street>{_T_STREET})[ \t]*,[ \t]*"
    rf"(?P<plz>{_T_PLZ})[ \t]+(?P<city>{_T_CITY})"
)
_T_PLZ_CITY = re.compile(
    rf"(?m)(?P<lead>^[*_> \t]*|[,|·•][ \t]*)(?P<plz>{_T_PLZ})[ \t]+(?P<city>{_T_CITY})"
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
    """(paths, out dir or None, zip?, help?, without values?, {option: [values]})."""
    paths, out, pack, usage, values = [], None, False, False, {key: [] for key in _T_OPTIONS}
    bare, i = False, 0
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
        elif name.startswith("--") and (key == "out" or key in _T_OPTIONS):
            if not equals:
                if i >= len(args) or args[i].startswith("--"):
                    raise _TUsage(f"Option {name} braucht einen Wert.")
                value = args[i]
                i += 1
            if key == "out":
                out = value
            else:
                values[key].extend(value.split(";"))
        else:
            raise _TUsage(f"Unbekannte Option {name}")
    return paths, out, pack, usage, bare, values


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
    code = re.compile(r"(?<!\d)\d{5}(?!\d)")
    at = next((i for i, line in enumerate(lines) if code.search(line)), None)
    name = re.split(r"[+\d]", lines[0])[0].strip("*_, ") if lines else ""
    if not at:  # no postcode, or nothing in front of it
        return ("" if at == 0 else name), "", "", ""
    postcode = code.search(lines[at]).group(0)
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

    def __init__(self, values):
        self.rules, self.short, self.avoid = _t_given(values)
        self.learned = {}  # text found in one mail -> its replacement in every mail
        self.words = {}  # single word of a recipient's name (lower case) -> replacement
        self.streets, self.postcodes, self.cities = set(), set(), set()
        self._learning = False
        self._learnt = None  # compiled rules of what was learnt
        self._salt = secrets.token_hex(16)
        self._runs = {}
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

    def _rules(self):
        """The compiled rules of everything learnt, the longest first."""
        if self._learnt is None:
            rules = [_t_street(street) for street in sorted(self.streets, key=len, reverse=True)]
            for postcode in sorted(self.postcodes):
                rules.append((re.compile(rf"(?<!\d){postcode}(?!\d)"), "12345"))
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

    def _delivered(self, match):
        self._recipient(*_t_address_parts(match.group(2) + "\n" + match.group(4)))
        return match.group(1) + "Max Mustermann" + match.group(3) + (
            "Musterstraße 1\n12345 Musterstadt\n" if match.group(4) else "")

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
                self._note(name, "beispielshop", r"[-_.\d]")
            else:
                self._note(name, "Beispielversender")
            placeholder = "beispielshop" if match.re is _T_SELLER else "Beispielversender"
            name = re.sub(r"[^*_\s](?:[^*\n]*[^*_\s])?", placeholder, name, count=1)
        address = match.re is _T_SENDER_BLOCK and match.group(3)
        return match.group(1) + name + ("\nBeispielweg 2\n00000 Beispielstadt" if address else "")

    def _amazon(self, match):
        self._person(match.group(2))
        self._recipient("", "", "", match.group(4).strip())
        return f"{match.group(1)}Max{match.group(3)}Musterstadt{match.group(5)}"

    def _plain(self, match):
        name = match.group("name")
        if name is None:
            head = match.group("lead")
        else:
            if _t_person(name.strip()):
                self._recipient(name.strip(), match.group("street"),
                                match.group("plz")[-5:], match.group("city"))
                name = "Max Mustermann"
            head = f"{match.group('lead')}{name}\n{match.group('lead2')}"
        return f"{head}Musterstraße 1\n{match.group('lead3')}12345 Musterstadt"

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

    # ----- numbers, links -----
    def _run(self, run):
        """Invented digits for digits, letters for letters (hex stays hex); DHL's 00340 stays."""
        if run not in self._runs:
            keep = 5 if re.fullmatch(r"00340\d{15}", run) else 0
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
                attempt += 1
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
        text = _T_ADDRESS_BLOCK.sub(self._block, text)
        text = _T_ADDRESS_LINE.sub(self._line, text)
        text = _T_DELIVERED_TO.sub(self._delivered, text)
        text = _T_HELLO.sub(self._hello, text)
        text = _T_HELLO_BARE.sub(self._hello, text)
        text = _T_QUOTED_TO.sub(f"\\1 {_T_MAIL}", text)
        for pattern in (_T_SENDER_BLOCK, _T_SENDER_NEXT, _T_SENDER_INLINE, _T_SENDER_SAME,
                        _T_SELLER):
            text = pattern.sub(self._sender, text)
        text = _T_AMAZON_LINE.sub(self._amazon, text)
        text = _T_PLAIN_BLOCK.sub(self._plain, text)
        text = _T_INLINE_ADDRESS.sub("\\g<lead>Musterstraße 1, 12345 Musterstadt", text)
        text = _T_PLZ_CITY.sub("\\g<lead>12345 Musterstadt", text)
        text = _T_NEIGHBOUR.sub(self._neighbour, text)
        for pattern, replacement in self.rules:
            text = pattern.sub(replacement, text)
        if not self._learning:
            for found in sorted(self.learned, key=len, reverse=True):
                text = re.sub(re.escape(found), self.learned[found], text, flags=re.I)
            for pattern, replacement in self._rules():
                text = pattern.sub(replacement, text)
        text = _T_PLACE_NEXT.sub(self._place, text)
        text = _T_PLACE_SAME.sub(self._place, text)
        text = _T_PLACE_PHRASE.sub("\\1 Garage \\2", text)
        return _T_GENERIC.sub(lambda m: self._generic(m, keep), text)

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


def _t_original(text, private):
    """(the text from the innermost quoted header block on, the quoted sender's address).

    What stands above that block (the note and signature of the person that forwarded the
    mail, the blocks of earlier forwards) is dropped. In the block the recipients are replaced;
    the sender stays (the importer tells the original mail by it) unless ``private`` says it
    is a person. Without such a block the text comes back as it is, with no address.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = _t_quoted_blocks(lines)
    if not blocks:
        return text, None
    start, end = blocks[-1]
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
                address, line = _t_quoted_sender(match.group("head"), value, private)
                kept.append(line)
            else:
                kept.append(line)
        elif kind == "to":
            if pending:  # the value on the line below its label
                kept.append(_T_MAIL)
            pending = False  # (a wrapped recipient list is dropped)
        elif kind == "from" and pending:
            address, line = _t_quoted_sender("", line, private)
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
    return address, head + value


def _t_passed_on(msg):
    """A mail that looks forwarded: subject prefix (WG:, Fwd:, Fw:) or a quoted header block."""
    plain, markup = _t_texts(msg)[:2]
    return bool(
        _T_PASSED_ON.match(_t_header(msg, "Subject"))
        or _T_QUOTED_FROM.search((plain + "\n" + markup).replace("\r\n", "\n"))
    )


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


def _t_build(msg, number, scrubber):
    """(anonymised mail, domain for the file name, private sender?, value left?)."""
    display, address = _t_sender(msg)
    plain, markup, has_plain, has_html = _t_texts(msg)
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
    plain, quoted_plain = _t_original(plain, person)
    markup, quoted_markup = _t_original(markup, person)
    keep += tuple(quoted for quoted in (quoted_plain, quoted_markup) if quoted)
    local, _, host = address.rpartition("@")
    if not private and re.search(r"[=%]", local):
        # The local part carries another address (bounce+user=gmx.de@shop.example).
        address, keep = f"absender@{host}", ()
    out = EmailMessage()
    if private:
        _t_set(out, "From", f"Max Mustermann <{_T_MAIL}>")
    else:
        display = scrubber.scrub(display, keep).replace('"', "").strip()
        _t_set(out, "From", f'"{display}" <{address}>' if display else address)
        if "From" not in out:
            _t_set(out, "From", address)
    out["To"] = _T_MAIL
    subject = " ".join(scrubber.scrub(raw_subject, keep).split())
    _t_set(out, "Subject", subject)
    if _t_header(msg, "Date"):
        _t_set(out, "Date", _t_header(msg, "Date"))
    out["Message-ID"] = f"<beispiel-{number:03d}@example.org>"
    plain, markup = scrubber.scrub(plain, keep), scrubber.scrub(markup, keep)
    if has_plain or not has_html:
        _t_body(out, plain if plain.endswith("\n") or not plain else plain + "\n", "plain")
    if has_html:
        _t_body(out, as_html(markup), "html", alternative=has_plain)
    domain = re.sub(r"[^a-z0-9.-]", "", address.rsplit("@", 1)[-1])
    left = scrubber.left(f"{out['From']}\n{subject}\n{plain}\n{markup}")
    return out, "privat" if private else domain or "unbekannt", private, left


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
        elif re.fullmatch(r"\d{3}_[a-z0-9.-]+\.eml", name):
            with open(path, "rb") as handle:
                own = b"\nMessage-ID: <beispiel-" in handle.read(8192)
            if own:  # a mail of someone else with such a name stays
                os.remove(path)


def _t_run(args):
    paths, out_dir, pack, usage, bare, values = _t_parse(args)
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
    if not bare and sys.stdin is not None and sys.stdin.isatty():
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
    scrubber = _TScrubber(values)
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
            scrubber.learn(
                "\n".join(_t_texts(mail)[:2]), _t_header(mail, "Subject"),
                *_t_sender(mail), _t_recipients(mail),
            )
            mails.append((os.path.basename(path), mail))
        except Exception:
            unreadable.append(os.path.basename(path))
    try:
        os.makedirs(out_dir, exist_ok=True)
        _t_clear(out_dir)
    except OSError:
        raise _TUsage("Der Zielordner lässt sich nicht anlegen oder leeren.") from None
    written, forwarded, doubtful, passed_on = [], 0, [], []
    for source, mail in mails:
        number = len(written) + 1
        try:
            out, domain, private, left = _t_build(mail, number, scrubber)
            data = bytes(out)
        except Exception:  # no traceback: it could show a part of a mail
            unreadable.append(source)
            continue
        name = f"{number:03d}_{domain}.eml"
        with open(os.path.join(out_dir, name), "wb") as handle:
            handle.write(data)
        written.append((name, data))
        forwarded += private
        if left:
            doubtful.append(name)
        if _t_passed_on(mail):
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
    print()
    print("WICHTIG: Jede Datei vor dem Hochladen selbst öffnen und durchlesen (ein Texteditor")
    print("genügt). Das Skript erkennt nicht alles: Steht noch etwas Privates drin, die Stelle")
    print("von Hand ersetzen oder die Mail weglassen" + (", danach das ZIP neu packen." if pack
                                                          else "."))
    print("Hochgeladen werden nur die Dateien aus diesem Ordner, nie die Original-Mails.")
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
    "shipment-tracking@amazon.de", "order-update@amazon.de", "noreply@dhl.de",
    "pkginfo@ups.com", "noreply@paketankuendigung.myhermes.de", "ebay@ebay.com",
}


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
# GLS: "*Zustelladresse*" / "*Empfänger*" + name line (+ address lines) up to the next
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
    return real


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
written = 0
for path in sorted(glob.glob(SRC + "/*.eml")):
    m = load(path)
    a = sender(m)
    if a not in KEEP:
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
    out = EmailMessage()
    out["From"] = str(m["From"])
    out["To"] = "max@example.org"
    subject = scrub(subject)
    out["Subject"] = subject
    out["Date"] = str(m["Date"])
    out["Message-ID"] = mid
    if was_html:
        out.set_content(as_html(scrub(text)), subtype="html")
    else:
        out.set_content(scrub(text))
    # File name from the scrubbed subject, without item titles (after ':' or a quote).
    subj = re.sub(r"[„“\":].*", "", subject)
    name = re.sub(r"[^a-z0-9]+", "_", (a.split("@")[0] + "_" + subj).lower()).strip("_")[:40]
    n += 1
    written += 1
    with open(f"{DST}/{n:03d}_{name}.eml", "wb") as handle:
        handle.write(bytes(out))
print("written", written, "street patterns", len(street), "drop-off texts", len(ablage),
      "sellers", len(sellers), "companies", len(companies), "gls numbers", len(gls_numbers))

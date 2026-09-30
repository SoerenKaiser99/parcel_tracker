"""Build anonymised fixtures from real parcel mails (runs locally, never on real data in CI).

usage: anonymize_mail.py SRC_DIR DST_DIR POSTCODE CITY FIRSTNAME LASTNAME [MAILDOMAIN ...]

Personal values come only from the command line. Mails with a text/plain part are written
as text/plain; HTML-only mails (eBay, older Hermes) are converted to text, scrubbed and
written back as simple text/html (one <p> per line), so the parser's HTML fallback is
exercised by the fixtures. Numbering continues after the highest fixture in DST_DIR;
mails with an already written Message-ID are skipped.
"""
import email
import glob
import hashlib
import html
import os
import re
import sys
from email import policy
from email.message import EmailMessage
from html.parser import HTMLParser

SRC, DST, POSTCODE, CITY, FIRST, LAST = sys.argv[1:7]
DOMAINS = sys.argv[7:] or ["gmail", "googlemail"]
KEEP = {
    "bestellbestaetigung@amazon.de", "versandbestaetigung@amazon.de",
    "shipment-tracking@amazon.de", "order-update@amazon.de", "noreply@dhl.de",
    "pkginfo@ups.com", "noreply@paketankuendigung.myhermes.de", "ebay@ebay.com",
}
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


def load(path):
    with open(path, "rb") as handle:
        return email.message_from_binary_file(handle, policy=policy.default)


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

# Pass 1: learn street lines, drop-off texts and seller names from every mail.
street, ablage, sellers = set(), set(), set()
for path in glob.glob(SRC + "/*.eml"):
    text, _ = body(load(path))
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


def as_html(text):
    return "<html><body>\n" + "\n".join(
        f"<p>{html.escape(line)}</p>" for line in text.splitlines() if line.strip()
    ) + "\n</body></html>\n"


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
    out = EmailMessage()
    out["From"] = str(m["From"])
    out["To"] = "max@example.org"
    subject = scrub(str(m["Subject"]))
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
      "sellers", len(sellers))

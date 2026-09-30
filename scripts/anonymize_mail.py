"""Build anonymised text-only fixtures from real Amazon/DHL/UPS mails (runs locally)."""
import email, glob, re, sys, hashlib
from email import policy
from email.message import EmailMessage

# usage: anonymize_mail.py SRC_DIR DST_DIR POSTCODE CITY FIRSTNAME LASTNAME [MAILDOMAIN ...]
SRC, DST, POSTCODE, CITY, FIRST, LAST = sys.argv[1:7]
DOMAINS = sys.argv[7:] or ["gmail", "googlemail"]
KEEP = {"bestellbestaetigung@amazon.de","versandbestaetigung@amazon.de","shipment-tracking@amazon.de",
        "order-update@amazon.de","noreply@dhl.de","pkginfo@ups.com"}

def plain(m):
    for p in m.walk():
        if p.get_content_type()=="text/plain":
            try: return p.get_content()
            except Exception: pass
    return ""

# collect street-like lines directly before the postcode line, to scrub
street=set()
for f in glob.glob(SRC+"/*.eml"):
    t=plain(email.message_from_binary_file(open(f,"rb"),policy=policy.default)).splitlines()
    for i,l in enumerate(t):
        if POSTCODE in l:
            for j in range(max(0,i-3),i):
                s=t[j].strip()
                if s and re.search(r"\d",s) and len(s)<60: street.add(s)
            if POSTCODE in l and len(l.strip())<60: street.add(l.strip())

def fake(kind, real):
    h=int(hashlib.sha256(real.encode()).hexdigest(),16)
    if kind=="order": return f"999-{h%10**7:07d}-{(h//10**7)%10**7:07d}"
    if kind=="jjd": return "JJD0000"+str(h)[:14]
    if kind=="1z": return "1Z999AA1"+str(h)[:10]
    if kind=="tba": return "TBA"+str(h)[:12]
    return real

def scrub(t):
    for s in sorted(street,key=len,reverse=True): t=t.replace(s,"Musterstraße 1")
    first = re.escape(FIRST).replace("ö", "(?:ö|oe)")
    t=re.sub(rf"(?i){first}\s*{re.escape(LAST)}","Max Mustermann",t)
    t=re.sub(rf"(?i)\b{first}\b","Max",t); t=re.sub(rf"(?i)\b{re.escape(LAST)}\b","Mustermann",t)
    t=re.sub(r"[\w.+-]+@(" + "|".join(map(re.escape, DOMAINS)) + r")\.[\w.]+","max@example.org",t)
    t=t.replace(POSTCODE,"12345"); t=re.sub(rf"\b{re.escape(CITY)}\b","Musterstadt",t)
    t=re.sub(r"\b\d{3}-\d{7}-\d{7}\b",lambda m:fake("order",m.group(0)),t)
    t=re.sub(r"\bJJD\d{10,}\b",lambda m:fake("jjd",m.group(0)),t)
    t=re.sub(r"\b1Z[0-9A-Z]{16}\b",lambda m:fake("1z",m.group(0)),t)
    t=re.sub(r"\bTBA\d{9,}\b",lambda m:fake("tba",m.group(0)),t)
    t=re.sub(r"(?i)(einmalpasswort[^0-9\n]{0,40})\d{4,8}",r"\g<1>123456",t)
    t=re.sub(r"https?://[^\s<>\]\)\"]+",lambda m:re.match(r"https?://[^/\s]+",m.group(0)).group(0)+"/…",t)
    return t

import os; os.makedirs(DST,exist_ok=True)
n=0
for f in sorted(glob.glob(SRC+"/*.eml")):
    m=email.message_from_binary_file(open(f,"rb"),policy=policy.default)
    a=(re.findall(r"<([^>]+)>",str(m["From"])) or [str(m["From"])])[0]
    if a not in KEEP: continue
    out=EmailMessage()
    out["From"]=str(m["From"]); out["To"]="max@example.org"
    out["Subject"]=scrub(str(m["Subject"])); out["Date"]=str(m["Date"])
    out["Message-ID"]="<"+hashlib.sha256(str(m["Message-ID"]).encode()).hexdigest()[:24]+"@example.org>"
    out.set_content(scrub(plain(m)))
    name=re.sub(r"[^a-z0-9]+","_",(a.split("@")[0]+"_"+re.sub(r"[„“\"].*","",str(m["Subject"]))).lower()).strip("_")[:40]
    n+=1; open(f"{DST}/{n:03d}_{name}.eml","wb").write(bytes(out))
print("written",n,"street patterns",len(street))

"""Mail import: parsers and IMAP access (no Home Assistant imports)."""

from __future__ import annotations

from email.message import EmailMessage

from .amazon import (
    AMAZON_SENDERS,
    LEGACY_PREFIXES,
    parse_amazon,
    parse_amazon_legacy,
    subject_status,
)
from .base import DPD_DOMAINS, MailResult, body_text, domain_of, is_forwarded, sender, subject
from .ebay import EBAY_SENDER, parse_ebay
from .gls import GLS_SENDER, parse_gls_mail
from .hermes import HERMES_SENDER, parse_hermes_mail
from .shipping import (
    DHL_SENDER,
    KNOWN_SENDER_DOMAINS,
    UPS_SENDER,
    parse_dhl_mail,
    parse_generic,
    parse_ups_mail,
)

IGNORED_SENDERS = frozenset(
    {
        "no-reply@primevideo.com",
        "rueckgabe@amazon.de",
        "account-update@amazon.de",
        "no-reply@amazon.de",
    }
)


# Domains of the shops and carriers whose mails the parsers know. Only these may be
# named in the diagnostics; every other sender (a private person, an unknown shop)
# is just "other".
KNOWN_MAIL_DOMAINS = frozenset(
    {
        *KNOWN_SENDER_DOMAINS,
        *DPD_DOMAINS,
        *(
            domain_of(address)
            for address in (
                *AMAZON_SENDERS,
                EBAY_SENDER,
                GLS_SENDER,
                HERMES_SENDER,
                DHL_SENDER,
                UPS_SENDER,
            )
        ),
    }
)
OTHER_DOMAIN = "other"


def known_sender_domain(address: str) -> str:
    """The known shop/carrier domain an address belongs to, else "other".

    A sub-domain counts as its known parent ("x@mail.dhl.de" -> "dhl.de"), so
    nothing but an entry of KNOWN_MAIL_DOMAINS is ever returned.
    """
    domain = domain_of(address.strip().lower())
    while domain:
        if domain in KNOWN_MAIL_DOMAINS:
            return domain
        domain = domain.partition(".")[2]
    return OTHER_DOMAIN


def is_ignored(address: str) -> bool:
    """Senders whose mails are skipped without counting as unrecognised."""
    return address in IGNORED_SENDERS or (
        address.startswith("promotion") and address.endswith("@amazon.de")
    )


def parse_mail(msg: EmailMessage, read_otp: bool = False) -> MailResult:
    """Route a mail to its parser. Parser exceptions propagate to the caller."""
    address, _ = sender(msg)
    if is_ignored(address):
        return MailResult(ignored=True)
    if address == EBAY_SENDER:
        # eBay mails never go to the generic parser: their item numbers look like
        # tracking numbers. Unknown subjects are simply unrecognised.
        return MailResult(updates=parse_ebay(msg))
    subj = subject(msg)
    # Only mails Amazon sent itself count towards the "Amazon unrecognised" issue;
    # a hand-forwarded mail that doesn't parse is just an ordinary unknown mail.
    real_amazon = address.endswith("@amazon.de")
    forwarded_amazon = subject_status(subj) is not None and "Bestellnr." in body_text(msg)
    if address in AMAZON_SENDERS or forwarded_amazon:
        if subj.startswith(LEGACY_PREFIXES):
            updates = parse_amazon_legacy(msg)
        else:
            updates = parse_amazon(msg, read_otp)
        if updates or real_amazon:
            return MailResult(updates=updates, amazon=real_amazon)
        return MailResult(updates=parse_generic(msg))
    if address == DHL_SENDER and (updates := parse_dhl_mail(msg)):
        return MailResult(updates=updates)
    if address == UPS_SENDER and (updates := parse_ups_mail(msg)):
        return MailResult(updates=updates)
    if address == HERMES_SENDER and (updates := parse_hermes_mail(msg)):
        return MailResult(updates=updates)
    # GLS numbers (11 digits) are never read by the generic parser: a GLS mail someone
    # forwarded by hand is recognised by its subject instead.
    if (address == GLS_SENDER or is_forwarded(msg)) and (updates := parse_gls_mail(msg)):
        return MailResult(updates=updates)
    return MailResult(updates=parse_generic(msg))

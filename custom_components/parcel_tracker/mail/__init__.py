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
from .dpd import DPD_AT_DOMAIN, DPD_AT_SENDER, parse_dpd_mail
from .ebay import EBAY_SENDER, parse_ebay
from .forward import original_message
from .gls import GLS_GROUP_SENDERS, GLS_SENDER, parse_gls_group_mail, parse_gls_mail
from .hermes import HERMES_SENDER, parse_hermes_mail
from .shipping import (
    DHL_DOMAIN,
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
                *GLS_GROUP_SENDERS,
                DPD_AT_SENDER,
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


def _known(address: str) -> bool:
    return known_sender_domain(address) != OTHER_DOMAIN


def forwarded_original(msg: EmailMessage) -> EmailMessage | None:
    """The original of a mail forwarded by hand, if a sender we know wrote it (else None).

    Looked for only in a mail whose own sender is none we know: what a shop's or carrier's
    own mail quotes is its text. A quoted header can therefore do no more than a mail from
    that sender could, and what stands above it (the forwarder's lines) is never read.
    """
    address = sender(msg)[0]
    if _known(address) or is_ignored(address):
        return None
    return original_message(msg, _known)


def parse_mail(msg: EmailMessage, read_otp: bool = False) -> MailResult:
    """Route a mail to its parser. Parser exceptions propagate to the caller.

    A forward whose original sender we know is parsed as that original (see
    ``forwarded_original``); it never counts as a mail Amazon sent itself.
    """
    original = forwarded_original(msg)
    if original is None:
        return _route(msg, read_otp)
    result = _route(original, read_otp)
    result.amazon = False
    return result


def _route(msg: EmailMessage, read_otp: bool) -> MailResult:
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
    domain = domain_of(address)
    if (domain == DHL_DOMAIN or domain.endswith(f".{DHL_DOMAIN}")) and (
        updates := parse_dhl_mail(msg)
    ):
        return MailResult(updates=updates)
    if address == UPS_SENDER and (updates := parse_ups_mail(msg)):
        return MailResult(updates=updates)
    if address == HERMES_SENDER and (updates := parse_hermes_mail(msg)):
        return MailResult(updates=updates)
    if address in GLS_GROUP_SENDERS and (updates := parse_gls_group_mail(msg)):
        return MailResult(updates=updates)
    # DPD Austria tells the status in its mails; DPD Germany only names the number.
    if domain == DPD_AT_DOMAIN and (updates := parse_dpd_mail(msg)):
        return MailResult(updates=updates)
    # GLS numbers (11 digits) are never read by the generic parser: a GLS mail someone
    # forwarded by hand is recognised by its subject instead.
    if (address == GLS_SENDER or is_forwarded(msg)) and (updates := parse_gls_mail(msg)):
        return MailResult(updates=updates)
    return MailResult(updates=parse_generic(msg))

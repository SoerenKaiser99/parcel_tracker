"""Mail import: parsers and IMAP access (no Home Assistant imports)."""

from __future__ import annotations

from email.message import EmailMessage

from .amazon import AMAZON_SENDERS, LEGACY_PREFIX, parse_amazon, parse_amazon_legacy, subject_status
from .base import MailResult, body_text, sender, subject
from .shipping import DHL_SENDER, UPS_SENDER, parse_dhl_mail, parse_generic, parse_ups_mail

IGNORED_SENDERS = frozenset(
    {
        "no-reply@primevideo.com",
        "rueckgabe@amazon.de",
        "account-update@amazon.de",
        "no-reply@amazon.de",
    }
)


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
    subj = subject(msg)
    # Only mails Amazon sent itself count towards the "Amazon unrecognised" issue;
    # a hand-forwarded mail that doesn't parse is just an ordinary unknown mail.
    real_amazon = address.endswith("@amazon.de")
    forwarded_amazon = subject_status(subj) is not None and "Bestellnr." in body_text(msg)
    if address in AMAZON_SENDERS or forwarded_amazon:
        if subj.startswith(LEGACY_PREFIX):
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
    return MailResult(updates=parse_generic(msg))

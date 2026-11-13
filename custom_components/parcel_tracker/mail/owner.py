"""The person a mail belongs to, read from its headers (no Home Assistant imports).

Addresses are only compared here, never logged: they are personal data.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Sequence
from email.message import EmailMessage
from email.utils import getaddresses

from ..models import PersonConfig
from . import OTHER_DOMAIN, forwarded_original, is_ignored, known_sender_domain
from .base import _raw_subject, sender

# Every station a mail went through may leave one of these (a forwarded mail carries
# several Delivered-To, the newest on top): every occurrence of each counts.
OWNER_HEADERS = (
    "Delivered-To",
    "X-Original-To",
    "To",
    "Cc",
    "X-Forwarded-To",
    "X-Forwarded-For",
    "Resent-From",
    "Resent-To",
)
_SEPARATORS = re.compile(r"[\s,;]+")
# A forward (WG:/Fwd:/FW:), not a reply (AW:/Re:): who answers a parcel mail is not
# whom the parcel belongs to.
_HAND_FORWARD = re.compile(r"^(?:wg|fwd?)\s*:", re.IGNORECASE)


def _addresses(value: str) -> set[str]:
    """The lower-case addresses of one header value.

    Gmail writes ``X-Forwarded-For`` as addresses separated by a blank, which is no
    address list: such a value is read word by word. A display name never counts.
    """
    found = {address.strip().lower() for _, address in getaddresses([value])}
    found = {address for address in found if "@" in address}
    if not found:
        for word in _SEPARATORS.split(value):
            found |= {
                address.strip().lower()
                for _, address in getaddresses([word])
                if "@" in address
            }
    return found


def _values(msg: EmailMessage, names: Iterable[str]) -> list[str]:
    values = []
    for name in names:
        for value in msg.get_all(name) or ():
            try:
                values.append(str(value))
            except Exception:  # noqa: BLE001 - an unreadable header names nobody
                continue
    return values


def _hand_forwarder(msg: EmailMessage) -> str:
    """The address of whoever forwarded this mail by hand ('' for any other mail).

    A mail forwarded by hand has a sender no parser knows (the person) and a forward
    subject (WG:/Fwd:/FW:, not AW:/Re:) or a forwarded original of a known sender (see
    ``forwarded_original``).
    """
    address = sender(msg)[0]
    if not address or known_sender_domain(address) != OTHER_DOMAIN or is_ignored(address):
        return ""
    if _HAND_FORWARD.match(_raw_subject(msg)) or forwarded_original(msg) is not None:
        return address
    return ""


def owner_from_message(
    msg: EmailMessage, persons: Sequence[PersonConfig], shared: Collection[str] = ()
) -> str | None:
    """The person (entity id) the mail belongs to; None if none or several match.

    A person matches if one of her addresses occurs in any of ``OWNER_HEADERS`` or, for
    a mail forwarded by hand, is its sender. Compared without case but otherwise exactly:
    ``pakete+anna@`` is not ``pakete@``. A person without addresses never matches. A
    mail that names one of the ``shared`` addresses (lower case, "familie@…") belongs to
    everybody: None, whoever else it names.
    """
    if not any(person.addresses for person in persons):
        return None
    found: set[str] = set()
    for value in _values(msg, OWNER_HEADERS):
        found |= _addresses(value)
    if forwarder := _hand_forwarder(msg):
        found.add(forwarder)
    if any(address in found for address in shared):
        return None
    matches = {
        person.person
        for person in persons
        if any(address in found for address in person.addresses)
    }
    return matches.pop() if len(matches) == 1 else None

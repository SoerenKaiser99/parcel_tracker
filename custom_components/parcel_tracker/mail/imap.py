"""Blocking IMAP access for the parcel mailbox (no Home Assistant imports).

All methods block; the coordinator runs them in the executor.

One folder is read: INBOX unless another one is set. Its name goes over the wire in
modified UTF-7 (RFC 3501, 5.1.3) as a quoted string; imaplib does neither by itself.
The two folders mails are filed into stay top-level and are never the folder read.

The connection is TLS from the first byte with a checked certificate unless the options
say otherwise: TLS without checking the certificate (an own server at home with a
self-signed one), or no TLS at all. STARTTLS is never tried.
"""

from __future__ import annotations

import base64
import imaplib
import ipaddress
import logging
import re
import ssl
from collections.abc import Callable
from typing import Any

from ..const import (
    DEFAULT_IMAP_FOLDER,
    DEFAULT_IMAP_PORT,
    DEFAULT_IMAP_SECURITY,
    FOLDER_PROCESSED,
    FOLDER_UNRECOGNIZED,
    IMAP_SECURITIES,
    IMAP_SECURITY_NOVERIFY,
    IMAP_SECURITY_PLAIN,
    MAX_IMAP_PORT,
    MIN_IMAP_PORT,
)

_LOGGER = logging.getLogger(__name__)

IMAP_PORT = DEFAULT_IMAP_PORT
IMAP_TIMEOUT = 30
FETCH_LIMIT = 50

# Server texts that really mean "wrong user or password" (RFC 5530 code, Dovecot, Gmail).
_AUTH_MARKERS = ("authenticationfailed", "authentication failed", "invalid credentials")


class ImapError(Exception):
    """Base error."""


class ImapAuthError(ImapError):
    """Login rejected."""


class ImapUnavailable(ImapError):
    """Server unreachable, timeout or protocol error."""


class ImapCertificateError(ImapUnavailable):
    """The server's TLS certificate was not accepted (self-signed, expired, other name).

    A kind of "unavailable", so callers that do not care keep backing off as before.
    Its text never carries what the certificate or the server said.
    """


class ImapLoginDisabled(ImapUnavailable):
    """The server takes no login over an unencrypted connection (LOGINDISABLED).

    Raised before user and password are sent. A kind of "unavailable", so callers that
    do not care keep backing off as before.
    """


class ImapFolderNotFound(ImapUnavailable):
    """The folder to read cannot be selected (missing, renamed, or no valid name).

    A kind of "unavailable", so callers that do not care keep backing off as before.
    Its text never carries the folder name.
    """


_RESERVED = frozenset({FOLDER_PROCESSED.casefold(), FOLDER_UNRECOGNIZED.casefold()})
# What servers use between the levels of a folder path.
_DELIMITER = re.compile(r"[/.]")


# Names that only resolve inside an own network (RFC 6762, RFC 8375, the usual router
# domains, Tailscale's own); the suffix itself counts as well ("fritz.box").
_LOCAL_SUFFIXES = (
    "local",
    "lan",
    "home",
    "home.arpa",
    "fritz.box",
    "internal",
    "intranet",
    "localdomain",
    "ts.net",
)
# Shared address space of carrier-grade NAT (RFC 6598); Tailscale hands these out too.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
# What a resolver reads as one number, and so as an IPv4 address: "0x08080808" (and
# plain digits, which hold no letter at all) is 8.8.8.8, not a host called that.
_HEX_NUMBER = re.compile(r"0x[0-9a-f]*")


def clean_port(value: Any) -> int:
    """The port as stored or typed in; 993 for anything that is no port."""
    if isinstance(value, bool):
        return DEFAULT_IMAP_PORT
    if isinstance(value, str) and value.strip().isdecimal():
        value = int(value.strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and MIN_IMAP_PORT <= value <= MAX_IMAP_PORT:
        return value
    return DEFAULT_IMAP_PORT


def clean_security(value: Any) -> str:
    """The kind of connection as stored or chosen; the verifying default for any other."""
    return value if isinstance(value, str) and value in IMAP_SECURITIES else DEFAULT_IMAP_SECURITY


def looks_local(host: Any) -> bool:
    """True if a mail server's host lies in an own network, as far as its name tells.

    An address counts if it is private, loopback, link-local or from the shared range
    of carrier-grade NAT (IPv4, IPv6 also in brackets or with a zone, an IPv4 address
    mapped into IPv6 as that address). A name counts if it has a single label with a
    letter in it ("nas"; never a number in decimal, octal or hex form, which is an
    address written differently) or ends in a domain that only resolves at home
    (``_LOCAL_SUFFIXES``). Nothing is looked up: a public name that points to a private
    address is not local here.
    """
    if not isinstance(host, str):
        return False
    name = host.strip().lower().rstrip(".")
    if not name:
        return False
    literal = name[1:-1] if name.startswith("[") and name.endswith("]") else name
    try:
        address = ipaddress.ip_address(literal.partition("%")[0])
    except ValueError:
        pass
    else:
        mapped = getattr(address, "ipv4_mapped", None)
        address = mapped or address
        return (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or (address.version == 4 and address in _CGNAT)
        )
    if "." not in name:
        return (
            ":" not in name
            and any(char.isalpha() for char in name)
            and not _HEX_NUMBER.fullmatch(name)
        )
    return any(name == suffix or name.endswith(f".{suffix}") for suffix in _LOCAL_SUFFIXES)


def clean_folder(value: Any) -> str:
    """The folder to read as stored or typed in: stripped, INBOX if there is none.

    INBOX is case-insensitive in IMAP and is always spelled the one way, so that an
    entry without a folder and one with "inbox" behave the same.
    """
    name = value.strip() if isinstance(value, str) else ""
    if not name or name.upper() == DEFAULT_IMAP_FOLDER:
        return DEFAULT_IMAP_FOLDER
    return name


def is_reserved_folder(name: str) -> bool:
    """True for the two folders mails are filed into (also below a prefix like INBOX.)."""
    return _DELIMITER.split(name.strip().casefold())[-1] in _RESERVED


def encode_mailbox(name: str) -> str:
    """A folder name in modified UTF-7 (RFC 3501, 5.1.3): pure ASCII for the wire.

    Printable ASCII stays as it is, "&" becomes "&-"; every other run of characters
    is UTF-16BE in base64 with "," for "/" and without padding, between "&" and "-".
    """
    parts: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            packed = base64.b64encode("".join(run).encode("utf-16-be")).decode("ascii")
            parts.append("&" + packed.rstrip("=").replace("/", ",") + "-")
            run.clear()

    for char in name:
        if " " <= char <= "~":
            flush()
            parts.append("&-" if char == "&" else char)
        else:
            run.append(char)
    flush()
    return "".join(parts)


def quote_mailbox(name: str) -> str:
    """The name as an IMAP quoted string in modified UTF-7.

    ValueError for an empty name and for control characters: a quoted string cannot
    carry them, and a line break would start a command of its own.
    """
    if not name or any(char < " " or char == "\x7f" for char in name):
        raise ValueError("not a folder name")
    escaped = encode_mailbox(name).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _is_auth_error(err: Exception) -> bool:
    text = str(err).lower()
    return any(marker in text for marker in _AUTH_MARKERS)


class MailboxClient:
    """Reads unseen mails from one folder (INBOX by default) and files them away."""

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        factory: Callable[..., Any] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        folder: str | None = None,
        port: Any = DEFAULT_IMAP_PORT,
        security: Any = DEFAULT_IMAP_SECURITY,
    ) -> None:
        self.host = host
        self.user = user
        self.folder = clean_folder(folder)
        self.port = clean_port(port)
        self.security = clean_security(security)
        self._password = password
        # Without TLS it is imaplib.IMAP4, which takes no context; a factory handed in
        # (tests) is called with the arguments of the class it stands for.
        self._factory = factory or (imaplib.IMAP4_SSL if self.tls else imaplib.IMAP4)
        # Home Assistant hands in its shared context that fits the kind of connection
        # (verifying or not); without one it is built on first connect (in the
        # executor, it loads certs).
        self._ssl_context = ssl_context
        self._told_no_expunge = False

    @property
    def tls(self) -> bool:
        """True unless the connection is unencrypted by choice."""
        return self.security != IMAP_SECURITY_PLAIN

    @property
    def custom_port(self) -> bool:
        """True when another port than 993 is used."""
        return self.port != DEFAULT_IMAP_PORT

    def _context(self) -> ssl.SSLContext:
        if self._ssl_context is None:
            context = ssl.create_default_context()
            if self.security == IMAP_SECURITY_NOVERIFY:
                # (the name check goes first: a context that checks names must verify)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            self._ssl_context = context
        return self._ssl_context

    @property
    def custom_folder(self) -> bool:
        """True when another folder than INBOX is read."""
        return self.folder != DEFAULT_IMAP_FOLDER

    def _mailbox(self) -> str:
        """The folder as SELECT takes it; INBOX exactly as it always went out."""
        if not self.custom_folder:
            return DEFAULT_IMAP_FOLDER
        if is_reserved_folder(self.folder):
            raise ImapFolderNotFound("reserved folder")
        try:
            return quote_mailbox(self.folder)
        except ValueError as err:
            raise ImapFolderNotFound("invalid folder name") from err

    def _connect(self) -> Any:
        mailbox = self._mailbox()  # before any connection: a refused folder costs none
        try:
            if self.tls:
                conn = self._factory(
                    self.host, self.port, ssl_context=self._context(), timeout=IMAP_TIMEOUT
                )
            else:
                conn = self._factory(self.host, self.port, timeout=IMAP_TIMEOUT)
        except ssl.SSLCertVerificationError as err:
            # (only the kind of error: the certificate's own words name the server)
            raise ImapCertificateError("certificate rejected") from err
        except (OSError, imaplib.IMAP4.error) as err:
            raise ImapUnavailable(type(err).__name__) from err
        try:
            self._login(conn)
            try:
                status, _ = conn.select(mailbox)
            except (OSError, imaplib.IMAP4.error) as err:
                raise ImapUnavailable(type(err).__name__) from err
            if status != "OK":
                if self.custom_folder:
                    # The server said NO to this folder; it is never created here.
                    raise ImapFolderNotFound("select rejected")
                raise ImapUnavailable("select failed")
        except BaseException:
            self._logout(conn)
            raise
        return conn

    def _login(self, conn: Any) -> None:
        if not self.tls:
            # Without TLS the password would go out readable. A server that says it takes
            # no such login (Dovecot does by default) is not sent one at all.
            announced = {str(c).upper() for c in getattr(conn, "capabilities", None) or ()}
            if "LOGINDISABLED" in announced:
                raise ImapLoginDisabled("login disabled")
        try:
            conn.login(self.user, self._password)
        except imaplib.IMAP4.abort as err:
            raise ImapUnavailable("abort") from err
        except imaplib.IMAP4.error as err:
            if _is_auth_error(err):
                raise ImapAuthError("login rejected") from err
            raise ImapUnavailable("login failed") from err
        except OSError as err:
            raise ImapUnavailable(type(err).__name__) from err

    @staticmethod
    def _logout(conn: Any) -> None:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 - closing must never mask the real error
            try:
                conn.shutdown()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _capabilities(conn: Any) -> set[str]:
        """Capabilities after login (servers often announce MOVE/UIDPLUS only then)."""
        caps = {str(c).upper() for c in getattr(conn, "capabilities", ())}
        status, data = conn.capability()
        if status == "OK":
            for item in data or []:
                if isinstance(item, bytes):
                    item = item.decode("ascii", "replace")
                if isinstance(item, str):
                    caps.update(item.upper().split())
        return caps

    @staticmethod
    def _ensure_folder(conn: Any, folder: str) -> bool:
        """True when ``folder`` exists or could be created (and subscribed)."""
        status, data = conn.list('""', folder)
        if status == "OK" and any(data or []):
            return True
        status, _ = conn.create(folder)
        if status != "OK":
            _LOGGER.debug("Could not create a mail folder (%s); mails stay in INBOX", status)
            return False
        conn.subscribe(folder)
        return True

    def check_login(self) -> None:
        """Log in and select the folder to read.

        Raises ImapAuthError, ImapFolderNotFound or (any other) ImapUnavailable.
        """
        self._logout(self._connect())

    def fetch_unseen(self) -> list[tuple[str, bytes]]:
        """(uid, raw message) of the folder's unseen mails, oldest first, not marked."""
        conn = self._connect()
        try:
            status, data = conn.uid("SEARCH", None, "UNSEEN")
            if status != "OK":
                raise ImapUnavailable("search failed")
            uids = [u.decode() for u in (data[0] or b"").split()][:FETCH_LIMIT]
            mails: list[tuple[str, bytes]] = []
            for uid in uids:
                status, parts = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
                if status == "OK" and raw:
                    mails.append((uid, raw))
            return mails
        except (OSError, imaplib.IMAP4.error) as err:
            raise ImapUnavailable(type(err).__name__) from err
        finally:
            self._logout(conn)

    def finish(self, dispositions: list[tuple[str, str | None]], move: bool) -> None:
        """Mark mails seen and, if ``move``, file them into their target folder.

        ``dispositions`` holds (uid, folder); folder None means "only mark seen".
        A failed CREATE/COPY/MOVE leaves the mail where it is (marked seen).
        """
        conn = self._connect()
        try:
            caps = self._capabilities(conn) if move else set()
            can_move = "MOVE" in caps
            uidplus = "UIDPLUS" in caps
            ready: dict[str, bool] = {}
            deleted: list[str] = []
            for uid, folder in dispositions:
                conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
                if not move or folder is None:
                    continue
                if folder not in ready:
                    ready[folder] = self._ensure_folder(conn, folder)
                if not ready[folder]:
                    continue
                if can_move:
                    status, _ = conn.uid("MOVE", uid, folder)
                    if status != "OK":
                        _LOGGER.debug("Could not move a mail (%s); it stays in INBOX", status)
                    continue
                status, _ = conn.uid("COPY", uid, folder)
                if status != "OK":
                    _LOGGER.debug("Could not copy a mail (%s); it stays in INBOX", status)
                    continue
                status, _ = conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                if status == "OK":
                    deleted.append(uid)
            if deleted:
                if uidplus:
                    # Only our mails: a plain EXPUNGE would also purge what others marked.
                    conn.uid("EXPUNGE", ",".join(deleted))
                elif not self._told_no_expunge:
                    self._told_no_expunge = True
                    _LOGGER.debug(
                        "Server has neither MOVE nor UIDPLUS; filed mails stay marked "
                        "as deleted in INBOX until the mail client expunges them"
                    )
        except (OSError, imaplib.IMAP4.error) as err:
            raise ImapUnavailable(type(err).__name__) from err
        finally:
            self._logout(conn)

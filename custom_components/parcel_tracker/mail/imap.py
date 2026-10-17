"""Blocking IMAP access for the parcel mailbox (no Home Assistant imports).

All methods block; the coordinator runs them in the executor.

One folder is read: INBOX unless another one is set. Its name goes over the wire in
modified UTF-7 (RFC 3501, 5.1.3) as a quoted string; imaplib does neither by itself.
The two folders mails are filed into are never the folder read. They go where the
server keeps its own folders: top-level, or below INBOX on servers that say so with
NAMESPACE (Courier, Dovecot with a prefix); see ``_Filing``.

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

# An IMAP atom: printable ASCII without the atom-specials (RFC 3501, 9).
_ATOM = re.compile(r"[!#$&'+,\-./0-9:;<=>?@A-Z\[^_`a-z|}~]+")
_QUOTED = r'"(?:[^"\\]|\\.)*"'
# NAMESPACE answer: (("<prefix>" "<delimiter>") ...) <others> <shared>; the first one.
_NAMESPACE_PERSONAL = re.compile(rf"\s*\(\(\s*({_QUOTED})\s+({_QUOTED}|NIL)\s*\)", re.IGNORECASE)
# LIST answer: (<flags>) "<delimiter>" <name>.
_LIST_DELIMITER = re.compile(rf"\s*\([^)]*\)\s+({_QUOTED}|NIL)", re.IGNORECASE)

# For the diagnostics: prefixes and delimiters servers use; any other is "other" (it
# could hold a name). Filing folder keys there, never the folder read.
_SAFE_PREFIX = re.compile(r"(?:INBOX)?[./]?", re.IGNORECASE)
_SAFE_DELIMITERS = frozenset("./\\:")
_FOLDER_KEYS = {FOLDER_PROCESSED: "processed", FOLDER_UNRECOGNIZED: "unrecognized"}

# Filing problems, one warning per outage (codes for the diagnostics).
_FILING_WARNINGS = {
    "folder_unavailable": (
        "Could not find or create the mail folder %s on the mail server; mails stay "
        "in the folder read, marked as read. Create the folder in the mail client or "
        "turn off moving mails in the options"
    ),
    "move_refused": (
        "The mail server refused to move mails into %s; they stay in the folder read, "
        "marked as read"
    ),
    "copy_refused": (
        "The mail server refused to copy mails into %s; they stay in the folder read, "
        "marked as read"
    ),
    "delete_refused": (
        "The mail server copied mails into %s but refused to mark them as deleted; "
        "they stay in the folder read as well"
    ),
}


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


def _quote(wire: str) -> str:
    """A name already in modified UTF-7 as an IMAP quoted string."""
    escaped = wire.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def quote_mailbox(name: str) -> str:
    """The name as an IMAP quoted string in modified UTF-7.

    ValueError for an empty name and for control characters: a quoted string cannot
    carry them, and a line break would start a command of its own.
    """
    if not name or any(char < " " or char == "\x7f" for char in name):
        raise ValueError("not a folder name")
    return _quote(encode_mailbox(name))


def _astring(wire: str) -> str:
    """A name already in modified UTF-7 as a command takes it.

    Bare where IMAP allows an atom, so the filing folders go out exactly as they always
    did; quoted otherwise (a prefix with a space, say).
    """
    return wire if _ATOM.fullmatch(wire) else _quote(wire)


def _unquote(token: str) -> str:
    """The text of an IMAP quoted string ("..." with backslash escapes)."""
    return re.sub(r"\\(.)", r"\1", token[1:-1])


def _text(data: Any) -> str | None:
    """The first line of an untagged answer as text; None for none or a literal."""
    line = (data or [None])[0]
    if isinstance(line, bytes):
        return line.decode("ascii", "replace")
    return line if isinstance(line, str) else None


def _printable(text: str) -> bool:
    return all(" " <= char <= "~" for char in text)


class _Filing:
    """Where the two filing folders are on this server, worked out once per run.

    A server that announces NAMESPACE (RFC 2342) says where an own folder belongs: at
    the top (prefix "") or below INBOX ("INBOX." on Courier, Dovecot with a prefix).
    A folder is looked up there first, then at the top (where it always was looked for);
    only then is it created where the server says. Without NAMESPACE it is the top, as
    up to v0.3.32. Whenever the prefix is "" (no NAMESPACE, or one that says "top") and
    the server refuses to create the folder there, LIST "" "" tells the delimiter and the
    folder is looked up and created below INBOX. Made only when the first mail of a run
    needs a folder, after that mail is marked seen. Nothing is kept beyond the run: a
    folder renamed or deleted in the mail client is found or created anew next time.
    """

    def __init__(self, conn: Any, caps: set[str]) -> None:
        self.conn = conn
        self.namespace = self._namespace(caps)
        self.prefix, self.delimiter = self.namespace or ("", None)
        self._listed_delimiter = False
        # name -> (wire name or None, how it was found, where it is)
        self.folders: dict[str, tuple[str | None, str, str | None]] = {}

    def _namespace(self, caps: set[str]) -> tuple[str, str | None] | None:
        """Prefix and delimiter of the first personal namespace; None if not told."""
        if "NAMESPACE" not in caps:
            return None
        try:
            status, data = self.conn.namespace()
        except imaplib.IMAP4.abort:
            raise
        except imaplib.IMAP4.error:
            return None
        text = _text(data) if status == "OK" else None
        match = _NAMESPACE_PERSONAL.match(text or "")
        if match is None:
            return None
        prefix = _unquote(match.group(1))
        delimiter = None if match.group(2).upper() == "NIL" else _unquote(match.group(2))
        if not _printable(prefix):
            return None
        if delimiter is not None and (len(delimiter) != 1 or not _printable(delimiter)):
            delimiter = None
        if prefix and not (delimiter and prefix.endswith(delimiter)):
            if delimiter is None:
                return None  # ("INBOX" NIL): no way to tell where below it; the top
            prefix += delimiter  # ("INBOX" "."): the folders go to INBOX.<name>
        return prefix, delimiter

    def _list_delimiter(self) -> str | None:
        """The hierarchy delimiter as LIST "" "" tells it (RFC 3501, 6.3.8)."""
        if not self._listed_delimiter:
            self._listed_delimiter = True
            status, data = self.conn.list('""', '""')
            match = _LIST_DELIMITER.match((_text(data) if status == "OK" else None) or "")
            if match and match.group(1).upper() != "NIL":
                delimiter = _unquote(match.group(1))
                if len(delimiter) == 1 and _printable(delimiter):
                    self.delimiter = delimiter
        return self.delimiter

    def _exists(self, wire: str) -> bool:
        status, data = self.conn.list('""', _astring(wire))
        return status == "OK" and any(data or [])

    def _create(self, wire: str) -> bool:
        status, _ = self.conn.create(_astring(wire))
        if status != "OK":
            _LOGGER.debug("Could not create a mail folder (%s); mails stay in INBOX", status)
            return False
        self.conn.subscribe(_astring(wire))
        return True

    def resolve(self, name: str) -> str | None:
        """The folder ``name`` as commands take it; None if it is neither there nor made."""
        if name not in self.folders:
            self.folders[name] = self._resolve(name)
        wire = self.folders[name][0]
        return None if wire is None else _astring(wire)

    def _resolve(self, name: str) -> tuple[str | None, str, str | None]:
        own = encode_mailbox(name)
        primary = self.prefix + own
        place = "namespace" if self.prefix else "top_level"
        if self._exists(primary):
            return primary, "found", place
        if self.prefix and self._exists(own):
            return own, "found", "top_level"
        if self._create(primary):
            return primary, "created", place
        if not self.prefix and (delimiter := self._list_delimiter()):
            below = f"{DEFAULT_IMAP_FOLDER}{delimiter}{own}"
            if self._exists(below):
                return below, "found", "below_inbox"
            if self._create(below):
                return below, "created", "below_inbox"
        return None, "missing", None


def _is_auth_error(err: Exception) -> bool:
    text = str(err).lower()
    return any(marker in text for marker in _AUTH_MARKERS)


def _shown_prefix(prefix: str) -> str:
    """The namespace prefix for the diagnostics: a fixed spelling as it is, else "other"."""
    return prefix if _SAFE_PREFIX.fullmatch(prefix) else "other"


def _shown_delimiter(delimiter: str | None) -> str | None:
    if delimiter is None:
        return None
    return delimiter if delimiter in _SAFE_DELIMITERS else "other"


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
        # Filing folders in an outage (warned once each).
        self._failing: set[str] = set()
        # How filing went (diagnostics): kept across runs, the layout asked anew each run.
        self._filing: dict[str, Any] = {
            "has_move": None,
            "has_uidplus": None,
            "has_namespace": None,
            "namespace_prefix": None,
            "delimiter": None,
            "folders": dict.fromkeys(_FOLDER_KEYS.values()),
            # True while any folder fails (see failing_folders: one warning per folder
            # outage, over once a mail is filed into that folder again).
            "failing": False,
            "failing_folders": [],
            "last_error": None,
        }

    def filing_state(self) -> dict[str, Any]:
        """How the last runs filed mails, for the diagnostics: flags and fixed words only.

        Never the host, the user or a folder name; the namespace prefix only in one of
        the spellings servers use ("", "INBOX.", "INBOX/"), any other as "other".
        """
        state = dict(self._filing)
        state["failing_folders"] = list(self._filing["failing_folders"])
        state["folders"] = {
            key: dict(value) if isinstance(value, dict) else value
            for key, value in self._filing["folders"].items()
        }
        return state

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
        A failed CREATE/COPY/MOVE leaves the mail where it is (marked seen); the first
        such failure after a working run is a warning in the log (see ``filing_state``).
        """
        conn = self._connect()
        try:
            caps = self._capabilities(conn) if move else set()
            can_move = "MOVE" in caps
            uidplus = "UIDPLUS" in caps
            # Made when the first mail needs a folder, after it is marked seen: a server
            # that drops the connection on NAMESPACE must never keep mails unseen.
            filing: _Filing | None = None
            problems: list[tuple[str, str]] = []
            filed: list[str] = []
            deleted: list[str] = []
            for uid, folder in dispositions:
                conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
                if not move or folder is None:
                    continue
                if filing is None:
                    filing = _Filing(conn, caps)
                    self._filing.update(
                        has_move=can_move,
                        has_uidplus=uidplus,
                        has_namespace=filing.namespace is not None,
                        namespace_prefix=(
                            _shown_prefix(filing.prefix) if filing.namespace is not None else None
                        ),
                        delimiter=_shown_delimiter(filing.delimiter),
                    )
                target = filing.resolve(folder)
                self._note_folder(filing, folder)
                if target is None:
                    problems.append(("folder_unavailable", folder))
                    continue
                if can_move:
                    status, _ = conn.uid("MOVE", uid, target)
                    if status != "OK":
                        _LOGGER.debug("Could not move a mail (%s); it stays in INBOX", status)
                        problems.append(("move_refused", folder))
                    else:
                        filed.append(folder)
                    continue
                status, _ = conn.uid("COPY", uid, target)
                if status != "OK":
                    _LOGGER.debug("Could not copy a mail (%s); it stays in INBOX", status)
                    problems.append(("copy_refused", folder))
                    continue
                status, _ = conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                if status == "OK":
                    deleted.append(uid)
                    filed.append(folder)
                else:
                    problems.append(("delete_refused", folder))
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
            if filing is not None:
                self._filing["delimiter"] = _shown_delimiter(filing.delimiter)
            self._filing_done(problems, filed)
        except (OSError, imaplib.IMAP4.error) as err:
            if move:
                self._filing["last_error"] = "connection"
            raise ImapUnavailable(type(err).__name__) from err
        finally:
            self._logout(conn)

    def _note_folder(self, filing: _Filing, folder: str) -> None:
        key = _FOLDER_KEYS.get(folder)
        if key is not None:
            _, state, place = filing.folders[folder]
            self._filing["folders"][key] = {"state": state, "place": place}

    def _filing_done(self, problems: list[tuple[str, str]], filed: list[str]) -> None:
        """One warning when a folder starts failing; over once a mail lands in it again.

        Per folder: a run that only files into the other one (that works) does not end
        this one's outage. A folder with a problem in this run stays failing even if
        another mail made it in.
        """
        failed = {folder for _, folder in problems}
        for code, folder in problems:
            if folder not in self._failing:
                self._failing.add(folder)
                _LOGGER.warning(_FILING_WARNINGS[code], folder)
        self._failing -= set(filed) - failed
        if problems:
            self._filing["last_error"] = problems[-1][0]
        self._filing["failing"] = bool(self._failing)
        self._filing["failing_folders"] = sorted(
            key for folder, key in _FOLDER_KEYS.items() if folder in self._failing
        )

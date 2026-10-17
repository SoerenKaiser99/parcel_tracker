import imaplib
import ssl

import pytest

from custom_components.parcel_tracker.const import FOLDER_PROCESSED, FOLDER_UNRECOGNIZED
from custom_components.parcel_tracker.mail.imap import (
    ImapAuthError,
    ImapCertificateError,
    ImapFolderNotFound,
    ImapLoginDisabled,
    ImapUnavailable,
    MailboxClient,
    clean_folder,
    encode_mailbox,
    is_reserved_folder,
    looks_local,
    quote_mailbox,
)

from .conftest import FIXTURES

RAW = (FIXTURES / "mail" / "001_bestellbestaetigung_bestellt.eml").read_bytes()


class FakeImap:
    """Records calls; behaves like imaplib.IMAP4_SSL for the calls MailboxClient makes.

    ``caps`` is what the server announces before login, ``login_caps`` what
    CAPABILITY returns afterwards. ``results`` maps a command (CREATE, COPY,
    MOVE, SELECT, ...) to the status it answers with; ``folders`` already exist.
    """

    instances: list[FakeImap] = []

    def __init__(
        self,
        host,
        port,
        ssl_context=None,
        timeout=None,
        *,
        mails=None,
        caps=("IMAP4REV1",),
        login_caps=None,
        results=None,
        folders=(),
        namespace=None,
        delimiter=None,
        create_under="",
    ):
        self.host, self.port, self.ssl_context, self.timeout = host, port, ssl_context, timeout
        self.mails = dict(mails or {})
        self.capabilities = caps
        self.login_caps = caps if login_caps is None else login_caps
        self.results = dict(results or {})
        self.folders = set(folders)
        # NAMESPACE answer (bytes) and the delimiter LIST "" "" tells (None: no answer).
        self.namespace_reply = namespace
        self.delimiter = delimiter
        # Like Courier or Dovecot with a prefix: CREATE only below this.
        self.create_under = create_under
        self.calls: list[tuple] = []
        self.login_error: Exception | None = None
        self.logged_in = False
        FakeImap.instances.append(self)

    def _status(self, command):
        return self.results.get(command, "OK")

    def login(self, user, password):
        self.calls.append(("login", user))
        if self.login_error:
            raise self.login_error
        self.logged_in = True
        return "OK", [b"logged in"]

    def capability(self):
        self.calls.append(("capability",))
        caps = self.login_caps if self.logged_in else self.capabilities
        return "OK", [" ".join(caps).encode()]

    def select(self, mailbox):
        self.calls.append(("select", mailbox))
        return self._status("SELECT"), [b"2"]

    def namespace(self):
        self.calls.append(("namespace",))
        if self.namespace_reply is None:
            return "NO", [b"unknown command"]
        return "OK", [self.namespace_reply]

    def list(self, directory, pattern):
        self.calls.append(("list", pattern))
        if pattern == '""' and self.delimiter is not None:
            return "OK", [f'(\\Noselect) "{self.delimiter}" ""'.encode()]
        if pattern in self.folders:
            return "OK", [f'(\\HasNoChildren) "{self.delimiter or "/"}" {pattern}'.encode()]
        return "OK", [None]

    def create(self, folder):
        self.calls.append(("create", folder))
        status = self._status("CREATE")
        if not folder.strip('"').startswith(self.create_under):
            status = "NO"
        if status == "OK":
            self.folders.add(folder)
        return status, [b""]

    def subscribe(self, folder):
        self.calls.append(("subscribe", folder))
        return "OK", [b""]

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            return "OK", [" ".join(self.mails).encode()]
        if command == "FETCH":
            uid = args[0]
            return "OK", [(f"{uid} (UID {uid} BODY[] {{1}}".encode(), self.mails[uid]), b")"]
        return self._status(command), [None]

    def expunge(self):
        self.calls.append(("expunge",))
        return "OK", [None]

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", [b""]


def _client(folder=None, **fake_kwargs):
    FakeImap.instances = []

    def factory(host, port, ssl_context=None, timeout=None):
        return FakeImap(host, port, ssl_context, timeout, **fake_kwargs)

    extra = {} if folder is None else {"folder": folder}
    return MailboxClient(
        "imap.mailbox.org", "pakete@example.org", "secret", factory=factory, **extra
    )


def _failing_login(message):
    FakeImap.instances = []

    def factory(host, port, ssl_context=None, timeout=None):
        fake = FakeImap(host, port, ssl_context, timeout)
        fake.login_error = imaplib.IMAP4.error(message)
        return fake

    return MailboxClient("imap.mailbox.org", "u", "bad", factory=factory)


def test_fetch_unseen_peeks_and_logs_out():
    client = _client(mails={"7": RAW, "9": RAW})
    assert client.fetch_unseen() == [("7", RAW), ("9", RAW)]
    fake = FakeImap.instances[0]
    assert (fake.host, fake.port, fake.timeout) == ("imap.mailbox.org", 993, 30)
    assert ("login", "pakete@example.org") in fake.calls
    assert ("select", "INBOX") in fake.calls
    assert ("uid", "SEARCH", None, "UNSEEN") in fake.calls
    assert ("uid", "FETCH", "7", "(BODY.PEEK[])") in fake.calls
    assert fake.calls[-1] == ("logout",)


def test_finish_with_move_announced_after_login():
    client = _client(login_caps=("IMAP4REV1", "MOVE"))
    client.finish([("7", FOLDER_PROCESSED), ("8", FOLDER_UNRECOGNIZED), ("9", None)], move=True)
    calls = FakeImap.instances[0].calls
    assert calls.index(("capability",)) > calls.index(("login", "pakete@example.org"))
    assert ("uid", "STORE", "7", "+FLAGS", "(\\Seen)") in calls
    assert ("uid", "STORE", "9", "+FLAGS", "(\\Seen)") in calls
    assert ("create", FOLDER_PROCESSED) in calls
    assert ("create", FOLDER_UNRECOGNIZED) in calls
    assert ("subscribe", FOLDER_PROCESSED) in calls
    assert ("subscribe", FOLDER_UNRECOGNIZED) in calls
    assert ("uid", "MOVE", "7", FOLDER_PROCESSED) in calls
    assert ("uid", "MOVE", "8", FOLDER_UNRECOGNIZED) in calls
    assert not any(c[:2] == ("uid", "COPY") for c in calls)
    assert not any(c[0] == "expunge" or c[:2] == ("uid", "EXPUNGE") for c in calls)
    assert not any(c[1:3] == ("MOVE", "9") for c in calls if len(c) > 2)
    assert calls[-1] == ("logout",)


def test_finish_existing_folder_is_neither_created_nor_subscribed():
    client = _client(caps=("MOVE",), folders={FOLDER_PROCESSED})
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert not any(c[0] in ("create", "subscribe") for c in calls)
    assert ("uid", "MOVE", "7", FOLDER_PROCESSED) in calls


def test_finish_with_uidplus_expunges_only_our_uids():
    client = _client(login_caps=("IMAP4REV1", "UIDPLUS"))
    client.finish([("7", FOLDER_PROCESSED), ("8", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert calls.count(("create", FOLDER_PROCESSED)) == 1
    assert ("uid", "COPY", "7", FOLDER_PROCESSED) in calls
    assert ("uid", "STORE", "7", "+FLAGS", "(\\Deleted)") in calls
    assert ("uid", "STORE", "8", "+FLAGS", "(\\Deleted)") in calls
    assert ("uid", "EXPUNGE", "7,8") in calls
    assert ("expunge",) not in calls


def test_finish_without_move_or_uidplus_leaves_expunge_to_the_client(caplog):
    caplog.set_level("DEBUG", logger="custom_components.parcel_tracker.mail.imap")
    client = _client()
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    client.finish([("8", FOLDER_PROCESSED)], move=True)
    for fake in FakeImap.instances:
        assert any(c[:2] == ("uid", "COPY") for c in fake.calls)
        assert any(c[-1] == "(\\Deleted)" for c in fake.calls)
        assert not any(c[0] == "expunge" or c[:2] == ("uid", "EXPUNGE") for c in fake.calls)
    assert caplog.text.count("neither MOVE nor UIDPLUS") == 1


@pytest.mark.parametrize(
    ("caps", "results", "forbidden"),
    [
        (("MOVE",), {"CREATE": "NO"}, ("MOVE", "COPY")),
        (("MOVE",), {"MOVE": "NO"}, ()),
        (("UIDPLUS",), {"COPY": "NO"}, ("EXPUNGE",)),
    ],
)
def test_finish_failed_commands_keep_mail_in_inbox(caplog, caps, results, forbidden):
    caplog.set_level("DEBUG", logger="custom_components.parcel_tracker.mail.imap")
    client = _client(login_caps=caps, results=results)
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert ("uid", "STORE", "7", "+FLAGS", "(\\Seen)") in calls
    assert not any(c[0] == "uid" and c[1] in forbidden for c in calls)
    assert not any(c[-1] == "(\\Deleted)" for c in calls)
    assert "in INBOX" in caplog.text
    assert calls[-1] == ("logout",)


def test_finish_without_moving_only_marks_seen():
    client = _client(caps=("MOVE",))
    client.finish([("7", FOLDER_PROCESSED)], move=False)
    calls = FakeImap.instances[0].calls
    assert ("uid", "STORE", "7", "+FLAGS", "(\\Seen)") in calls
    assert not any(c[0] == "create" for c in calls)
    assert not any(c[:2] == ("uid", "MOVE") for c in calls)


def test_unreachable_is_unavailable():
    def factory(host, port, ssl_context=None, timeout=None):
        raise OSError("no route")

    client = MailboxClient("imap.mailbox.org", "u", "p", factory=factory)
    with pytest.raises(ImapUnavailable):
        client.fetch_unseen()


def test_check_login_selects_inbox():
    client = _client()
    client.check_login()
    calls = FakeImap.instances[0].calls
    assert calls == [("login", "pakete@example.org"), ("select", "INBOX"), ("logout",)]


def test_factory_gets_a_verifying_tls_context():
    client = _client()
    client.check_login()
    context = FakeImap.instances[0].ssl_context
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_given_tls_context_is_used():
    context = ssl.create_default_context()
    FakeImap.instances = []
    client = MailboxClient(
        "imap.mailbox.org",
        "u",
        "p",
        factory=lambda host, port, ssl_context=None, timeout=None: FakeImap(
            host, port, ssl_context, timeout
        ),
        ssl_context=context,
    )
    client.check_login()
    assert FakeImap.instances[0].ssl_context is context


@pytest.mark.parametrize(
    "message",
    [
        "[AUTHENTICATIONFAILED] Authentication failed.",
        "[AUTHENTICATIONFAILED] Invalid credentials (Failure)",
        "LOGIN failed: authentication failed",
    ],
)
def test_login_rejected_is_auth_error_and_closes(message):
    client = _failing_login(message)
    with pytest.raises(ImapAuthError):
        client.check_login()
    assert FakeImap.instances[0].calls[-1] == ("logout",)


@pytest.mark.parametrize(
    "message", ["[UNAVAILABLE] Temporary failure", "LOGIN failed: server busy", "[INUSE] try later"]
)
def test_other_login_errors_are_transient(message):
    client = _failing_login(message)
    with pytest.raises(ImapUnavailable):
        client.fetch_unseen()
    assert FakeImap.instances[0].calls[-1] == ("logout",)


def test_failed_select_closes_the_connection():
    client = _client(results={"SELECT": "NO"})
    with pytest.raises(ImapUnavailable):
        client.fetch_unseen()
    assert FakeImap.instances[0].calls[-1] == ("logout",)


def test_unexpected_error_after_connect_closes_the_connection():
    class Boom(Exception):
        pass

    class BrokenSelect(FakeImap):
        def select(self, mailbox):
            raise Boom

    FakeImap.instances = []
    client = MailboxClient(
        "imap.mailbox.org",
        "u",
        "p",
        factory=lambda host, port, ssl_context=None, timeout=None: BrokenSelect(host, port),
    )
    with pytest.raises(Boom):
        client.check_login()
    assert FakeImap.instances[0].calls[-1] == ("logout",)


# ----- v0.3.29: the folder to read can be chosen -----


@pytest.mark.parametrize(
    ("name", "encoded"),
    [
        ("INBOX", "INBOX"),
        ("Pakete/DHL", "Pakete/DHL"),
        ("INBOX.Pakete", "INBOX.Pakete"),
        ("Bestellungen & Pakete", "Bestellungen &- Pakete"),
        ("Müll", "M&APw-ll"),
        ("Entwürfe", "Entw&APw-rfe"),
        ("Pakete/Große Größen", "Pakete/Gro&AN8-e Gr&APYA3w-en"),
        ("~peter/mail/台北/日本語", "~peter/mail/&U,BTFw-/&ZeVnLIqe-"),  # RFC 3501, 5.1.3
        ("📦", "&2D3c5g-"),  # outside the BMP: a surrogate pair
        ("", ""),
    ],
)
def test_encode_mailbox_is_modified_utf7(name, encoded):
    assert encode_mailbox(name) == encoded
    assert encoded.isascii()


@pytest.mark.parametrize(
    ("name", "quoted"),
    [
        ("Pakete", '"Pakete"'),
        ("Bestellungen & Pakete", '"Bestellungen &- Pakete"'),
        ("Müll", '"M&APw-ll"'),
        ("Pakete/DHL", '"Pakete/DHL"'),
        ('Pakete "neu"', '"Pakete \\"neu\\""'),
        ("Pakete\\Alt", '"Pakete\\\\Alt"'),
    ],
)
def test_quote_mailbox(name, quoted):
    assert quote_mailbox(name) == quoted


@pytest.mark.parametrize(
    "name", ["", "Pakete\r\nA1 DELETE INBOX", "Pakete\x00", "Pak\tete", "A\x7f"]
)
def test_quote_mailbox_refuses_what_cannot_be_a_name(name):
    with pytest.raises(ValueError):
        quote_mailbox(name)


@pytest.mark.parametrize(
    ("value", "folder"),
    [
        (None, "INBOX"), ("", "INBOX"), ("   ", "INBOX"), (7, "INBOX"),
        ("inbox", "INBOX"), (" Inbox ", "INBOX"),
        (" Pakete ", "Pakete"), ("INBOX.Pakete", "INBOX.Pakete"), ("Inbox/Pakete", "Inbox/Pakete"),
    ],
)
def test_clean_folder(value, folder):
    assert clean_folder(value) == folder


@pytest.mark.parametrize(
    ("name", "reserved"),
    [
        (FOLDER_PROCESSED, True),
        (FOLDER_UNRECOGNIZED, True),
        (FOLDER_PROCESSED.upper(), True),
        (f"INBOX.{FOLDER_PROCESSED}", True),
        (f"INBOX/{FOLDER_UNRECOGNIZED}", True),
        ("INBOX", False),
        ("Pakete", False),
        (f"{FOLDER_PROCESSED}-Archiv", False),
    ],
)
def test_is_reserved_folder(name, reserved):
    assert is_reserved_folder(name) is reserved


def test_default_folder_is_inbox_exactly_as_before():
    client = _client(mails={"7": RAW})
    assert client.folder == "INBOX" and client.custom_folder is False
    client.fetch_unseen()
    client.finish([("7", None)], move=False)
    for fake in FakeImap.instances:
        assert [c for c in fake.calls if c[0] == "select"] == [("select", "INBOX")]


@pytest.mark.parametrize("folder", ["inbox", " INBOX ", "", None])
def test_inbox_in_any_spelling_is_the_default(folder):
    FakeImap.instances = []
    client = MailboxClient(
        "imap.mailbox.org", "u", "p", folder=folder,
        factory=lambda host, port, ssl_context=None, timeout=None: FakeImap(host, port),
    )
    client.check_login()
    assert ("select", "INBOX") in FakeImap.instances[0].calls
    assert client.custom_folder is False


@pytest.mark.parametrize(
    ("folder", "wire"),
    [
        ("Pakete", '"Pakete"'),
        ("Bestellungen & Pakete", '"Bestellungen &- Pakete"'),
        ("Müll", '"M&APw-ll"'),
        ("Pakete/DHL", '"Pakete/DHL"'),
        ("INBOX.Pakete", '"INBOX.Pakete"'),
    ],
)
def test_custom_folder_is_selected_for_reading_and_filing(folder, wire):
    client = _client(folder=folder, mails={"7": RAW}, login_caps=("IMAP4REV1", "MOVE"))
    assert client.custom_folder is True
    client.check_login()
    assert client.fetch_unseen() == [("7", RAW)]
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    assert len(FakeImap.instances) == 3
    for fake in FakeImap.instances:
        assert [c for c in fake.calls if c[0] == "select"] == [("select", wire)]
    calls = FakeImap.instances[1].calls
    # Everything else as for INBOX: unseen only, peeked, filed top-level.
    assert ("uid", "SEARCH", None, "UNSEEN") in calls
    assert ("uid", "FETCH", "7", "(BODY.PEEK[])") in calls
    calls = FakeImap.instances[2].calls
    assert ("uid", "STORE", "7", "+FLAGS", "(\\Seen)") in calls
    assert ("create", FOLDER_PROCESSED) in calls
    assert ("uid", "MOVE", "7", FOLDER_PROCESSED) in calls


def test_missing_custom_folder_is_told_apart_and_never_created():
    client = _client(folder="Pakete", results={"SELECT": "NO"})
    for call in (client.check_login, client.fetch_unseen, lambda: client.finish([], True)):
        with pytest.raises(ImapFolderNotFound):
            call()
    for fake in FakeImap.instances:
        assert not any(c[0] in ("create", "subscribe") for c in fake.calls)
        assert not any(c[0] == "uid" for c in fake.calls)
        assert fake.calls[-1] == ("logout",)
    # Callers that only know "unavailable" keep working.
    assert issubclass(ImapFolderNotFound, ImapUnavailable)


def test_failed_select_of_inbox_stays_plain_unavailable():
    client = _client(results={"SELECT": "NO"})
    with pytest.raises(ImapUnavailable) as err:
        client.check_login()
    assert not isinstance(err.value, ImapFolderNotFound)


@pytest.mark.parametrize(
    "folder", [FOLDER_PROCESSED, FOLDER_UNRECOGNIZED, f"INBOX.{FOLDER_PROCESSED}", "Pak\r\nete"]
)
def test_our_own_folders_and_broken_names_are_never_opened(folder):
    client = _client(folder=folder, mails={"7": RAW})
    for call in (client.check_login, client.fetch_unseen, lambda: client.finish([], True)):
        with pytest.raises(ImapFolderNotFound):
            call()
    assert FakeImap.instances == []  # not even a connection


def test_folder_name_is_not_part_of_the_error_or_the_log(caplog):
    caplog.set_level("DEBUG")
    client = _client(folder="Geheimer Ordner", results={"SELECT": "NO"})
    with pytest.raises(ImapFolderNotFound) as err:
        client.fetch_unseen()
    assert "Geheim" not in str(err.value)
    assert "Geheim" not in caplog.text


# ----- v0.3.32: port and connection security -----


def _recording(security=None, port=None, error=None, **extra):
    """A client whose connection is a FakeImap; returns it and the factory's arguments."""
    FakeImap.instances = []
    seen: list[tuple] = []

    def factory(*args, **kwargs):
        seen.append((args, kwargs))
        if error is not None:
            raise error
        return FakeImap(*args, **kwargs)

    if security is not None:
        extra["security"] = security
    if port is not None:
        extra["port"] = port
    client = MailboxClient("mail.fritz.box", "paket-user", "geheim-pw", factory=factory, **extra)
    return client, seen


def test_defaults_are_tls_with_verification_on_993():
    client, seen = _recording()
    assert (client.port, client.security, client.custom_port) == (993, "ssl", False)
    client.check_login()
    (args, kwargs), = seen
    assert args == ("mail.fritz.box", 993)
    assert kwargs["timeout"] == 30
    context = kwargs["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


@pytest.mark.parametrize(
    ("security", "factory"),
    [(None, imaplib.IMAP4_SSL), ("ssl", imaplib.IMAP4_SSL),
     ("ssl_noverify", imaplib.IMAP4_SSL), ("plain", imaplib.IMAP4)],
)
def test_each_mode_picks_its_imaplib_class(security, factory):
    extra = {} if security is None else {"security": security}
    assert MailboxClient("h", "u", "p", **extra)._factory is factory


def test_ssl_on_another_port_still_verifies():
    client, seen = _recording("ssl", 10993)
    client.fetch_unseen()
    (args, kwargs), = seen
    assert args == ("mail.fritz.box", 10993) and client.custom_port is True
    assert kwargs["ssl_context"].verify_mode == ssl.CERT_REQUIRED
    assert kwargs["ssl_context"].check_hostname is True


def test_noverify_is_tls_without_checking_certificate_or_name():
    client, seen = _recording("ssl_noverify", 993)
    client.check_login()
    (args, kwargs), = seen
    assert args == ("mail.fritz.box", 993)
    context = kwargs["ssl_context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_NONE and context.check_hostname is False


def test_noverify_uses_the_context_handed_in():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    client, seen = _recording("ssl_noverify", ssl_context=context)
    client.check_login()
    assert seen[0][1]["ssl_context"] is context


def test_plain_gets_no_tls_context_and_never_asks_for_starttls():
    client, seen = _recording("plain", 143)
    assert client.fetch_unseen() == []
    (args, kwargs), = seen
    assert args == ("mail.fritz.box", 143)
    assert kwargs == {"timeout": 30}  # the signature of imaplib.IMAP4
    commands = [call[0] for call in FakeImap.instances[0].calls]
    assert "starttls" not in commands and commands[0] == "login"


def test_plain_keeps_the_port_it_is_given():
    """Switching to "plain" never changes the port on its own, also not 993."""
    client, seen = _recording("plain")
    client.check_login()
    assert seen[0][0] == ("mail.fritz.box", 993)


def test_plain_ignores_a_context_handed_in():
    client, seen = _recording("plain", 143, ssl_context=ssl.create_default_context())
    client.check_login()
    assert "ssl_context" not in seen[0][1]


@pytest.mark.parametrize("security", ["", "SSL", "starttls", None, 7])
def test_an_unknown_mode_is_the_verifying_default(security):
    client = MailboxClient("h", "u", "p", security=security)
    assert client.security == "ssl" and client._factory is imaplib.IMAP4_SSL


@pytest.mark.parametrize("port", [None, 0, -1, 65536, "abc", 993.5, True])
def test_an_unusable_port_is_the_default(port):
    assert MailboxClient("h", "u", "p", port=port).port == 993


@pytest.mark.parametrize("port", [1, 143, 65535, 1143.0, "10993"])
def test_a_stored_port_is_used(port):
    assert MailboxClient("h", "u", "p", port=port).port == int(port)


def test_a_rejected_certificate_is_told_apart(caplog):
    error = ssl.SSLCertVerificationError(
        1, "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate for geheim.example"
    )
    client, _ = _recording("ssl", error=error)
    with caplog.at_level("DEBUG"), pytest.raises(ImapCertificateError) as raised:
        client.check_login()
    # Still a kind of "unavailable" for callers that do not care.
    assert isinstance(raised.value, ImapUnavailable)
    told = str(raised.value) + caplog.text
    for secret in ("geheim", "paket-user", "self-signed"):
        assert secret not in told


def test_other_tls_errors_stay_plain_unavailable():
    client, _ = _recording("ssl", error=ssl.SSLError(1, "wrong version number"))
    with pytest.raises(ImapUnavailable) as raised:
        client.check_login()
    assert not isinstance(raised.value, ImapCertificateError)


@pytest.mark.parametrize(
    ("host", "local"),
    [
        ("192.168.178.20", True),
        ("10.0.0.5", True),
        ("172.16.0.1", True),
        ("172.31.255.254", True),
        ("172.32.0.1", False),
        ("127.0.0.1", True),
        ("169.254.10.10", True),
        ("8.8.8.8", False),
        ("193.99.144.80", False),
        ("::1", True),
        ("[::1]", True),
        ("fd12:3456:789a::1", True),
        ("[fd12:3456:789a::1]", True),
        ("fe80::1", True),
        ("fe80::1%eth0", True),
        ("::ffff:192.168.1.10", True),
        ("::ffff:8.8.8.8", False),
        ("100.64.0.1", True),  # CGNAT, also what Tailscale hands out
        ("100.127.255.254", True),
        ("100.128.0.1", False),
        ("100.63.255.255", False),
        # One label, but a number: these resolve to 8.8.8.8 and 127.0.0.1.
        ("134744072", False),
        ("0x08080808", False),
        ("0X08080808", False),
        ("017700000001", False),
        ("0", False),
        ("0xcafe", False),
        ("cafe", True),
        ("nas2", True),
        ("2nas", True),
        ("mail.home", True),
        ("mail.localdomain", True),
        ("mail.intranet", True),
        ("nas.tail1234.ts.net", True),
        ("mail.homepage.example", False),
        ("ts.net.example.org", False),
        ("2a00:1450:4001:81b::200e", False),
        ("localhost", True),
        ("nas", True),
        ("Dovecot", True),
        ("mail.local", True),
        ("mail.lan", True),
        ("mail.home.arpa", True),
        ("nas.fritz.box", True),
        ("FRITZ.BOX", True),
        ("mail.internal", True),
        ("mail.internal.", True),
        (" mail.lan ", True),
        ("imap.mailbox.org", False),
        ("imap.gmail.com", False),
        ("mail.example.de", False),
        ("local.example.org", False),
        ("notlocal", True),
        ("mylan.example.com", False),
        ("", False),
        (None, False),
        ("999.1.1.1", False),
        ("192.168.1", False),
    ],
)
def test_looks_local(host, local):
    assert looks_local(host) is local


# ----- v0.3.32: a server that takes no login without encryption -----


def _capable(security, caps, port=143):
    FakeImap.instances = []

    def factory(*args, **kwargs):
        kwargs.pop("ssl_context", None)
        return FakeImap(*args, caps=caps, **kwargs)

    return MailboxClient(
        "mail.fritz.box", "paket-user", "geheim-pw", factory=factory, port=port, security=security
    )


@pytest.mark.parametrize("caps", [("IMAP4REV1", "LOGINDISABLED"), ("IMAP4rev1", "logindisabled")])
def test_plain_never_sends_the_login_to_a_server_that_disables_it(caps, caplog):
    """Dovecot on port 143 by default: the password must not go out in clear text."""
    client = _capable("plain", caps)
    with caplog.at_level("DEBUG"), pytest.raises(ImapLoginDisabled) as raised:
        client.check_login()
    calls = FakeImap.instances[0].calls
    assert not [call for call in calls if call[0] == "login"]
    assert calls == [("logout",)]
    assert isinstance(raised.value, ImapUnavailable)
    told = str(raised.value) + caplog.text
    for secret in ("geheim", "paket-user", "fritz"):
        assert secret not in told


def test_plain_logs_in_where_the_server_allows_it():
    client = _capable("plain", ("IMAP4REV1", "STARTTLS"))
    client.check_login()
    assert ("login", "paket-user") in FakeImap.instances[0].calls


@pytest.mark.parametrize("security", ["ssl", "ssl_noverify"])
def test_over_tls_the_servers_word_about_plain_logins_does_not_matter(security):
    client = _capable(security, ("IMAP4REV1", "LOGINDISABLED"), port=993)
    client.check_login()
    assert ("login", "paket-user") in FakeImap.instances[0].calls


# ----- v0.3.33: filing on servers whose folders live below INBOX (issue #25) -----

DOVECOT_PREFIX = b'(("INBOX." ".")) NIL NIL'
SLASH_PREFIX = b'(("INBOX/" "/")) NIL (("#shared/" "/"))'
NO_PREFIX = b'(("" "/")) NIL NIL'
LOGGER = "custom_components.parcel_tracker.mail.imap"


def _warnings(caplog):
    return [r for r in caplog.records if r.levelname == "WARNING" and r.name == LOGGER]


def test_finish_without_namespace_is_exactly_as_before():
    """No NAMESPACE announced: the same commands as up to v0.3.32, nothing more."""
    client = _client(login_caps=("IMAP4REV1", "MOVE"))
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    assert FakeImap.instances[0].calls == [
        ("login", "pakete@example.org"),
        ("select", "INBOX"),
        ("capability",),
        ("uid", "STORE", "7", "+FLAGS", "(\\Seen)"),
        ("list", FOLDER_PROCESSED),
        ("create", FOLDER_PROCESSED),
        ("subscribe", FOLDER_PROCESSED),
        ("uid", "MOVE", "7", FOLDER_PROCESSED),
        ("logout",),
    ]


def test_finish_with_an_empty_namespace_prefix_files_top_level():
    client = _client(login_caps=("IMAP4REV1", "MOVE", "NAMESPACE"), namespace=NO_PREFIX)
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert ("namespace",) in calls
    assert ("create", FOLDER_PROCESSED) in calls
    assert ("uid", "MOVE", "7", FOLDER_PROCESSED) in calls
    state = client.filing_state()
    assert (state["has_namespace"], state["namespace_prefix"], state["delimiter"]) == (
        True, "", "/",
    )
    assert state["folders"]["processed"] == {"state": "created", "place": "top_level"}


@pytest.mark.parametrize(
    ("reply", "prefix", "delimiter"),
    [(DOVECOT_PREFIX, "INBOX.", "."), (SLASH_PREFIX, "INBOX/", "/")],
)
def test_finish_creates_the_folders_below_the_namespace_prefix(reply, prefix, delimiter, caplog):
    """Courier, or Dovecot with a prefix: a top-level CREATE is refused, below INBOX works."""
    client = _client(
        login_caps=("IMAP4REV1", "MOVE", "NAMESPACE"),
        namespace=reply,
        delimiter=delimiter,
        create_under=prefix,
    )
    with caplog.at_level("DEBUG"):
        client.finish([("7", FOLDER_PROCESSED), ("8", FOLDER_UNRECOGNIZED)], move=True)
    calls = FakeImap.instances[0].calls
    for uid, name in (("7", FOLDER_PROCESSED), ("8", FOLDER_UNRECOGNIZED)):
        assert ("create", prefix + name) in calls
        assert ("subscribe", prefix + name) in calls
        assert ("uid", "MOVE", uid, prefix + name) in calls
        assert ("create", name) not in calls  # never tried top-level
    assert not _warnings(caplog)
    state = client.filing_state()
    assert (state["namespace_prefix"], state["delimiter"]) == (prefix, delimiter)
    assert state["folders"] == {
        "processed": {"state": "created", "place": "namespace"},
        "unrecognized": {"state": "created", "place": "namespace"},
    }
    assert (state["failing"], state["last_error"]) == (False, None)


def test_finish_finds_a_folder_the_user_created_below_inbox():
    """Created by hand in the mail client: internally INBOX.<name>, found, never re-created."""
    client = _client(
        login_caps=("IMAP4REV1", "MOVE", "NAMESPACE"),
        namespace=DOVECOT_PREFIX,
        delimiter=".",
        create_under="INBOX.",
        folders={f"INBOX.{FOLDER_PROCESSED}"},
    )
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert not any(c[0] in ("create", "subscribe") for c in calls)
    assert ("uid", "MOVE", "7", f"INBOX.{FOLDER_PROCESSED}") in calls
    assert client.filing_state()["folders"]["processed"] == {
        "state": "found", "place": "namespace",
    }


def test_finish_keeps_using_a_top_level_folder_that_already_exists_under_a_prefix_server():
    client = _client(
        login_caps=("IMAP4REV1", "MOVE", "NAMESPACE"),
        namespace=DOVECOT_PREFIX,
        folders={FOLDER_PROCESSED},
    )
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert calls.index(("list", f"INBOX.{FOLDER_PROCESSED}")) < calls.index(
        ("list", FOLDER_PROCESSED)
    )
    assert not any(c[0] == "create" for c in calls)
    assert ("uid", "MOVE", "7", FOLDER_PROCESSED) in calls
    assert client.filing_state()["folders"]["processed"]["place"] == "top_level"


def test_finish_without_namespace_falls_back_below_inbox_when_create_is_refused():
    """No NAMESPACE, top-level refused: LIST "" "" tells the delimiter, INBOX.<name> works."""
    client = _client(login_caps=("IMAP4REV1", "MOVE"), delimiter=".", create_under="INBOX.")
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert calls.index(("create", FOLDER_PROCESSED)) < calls.index(("list", '""'))
    assert ("create", f"INBOX.{FOLDER_PROCESSED}") in calls
    assert ("uid", "MOVE", "7", f"INBOX.{FOLDER_PROCESSED}") in calls
    state = client.filing_state()
    assert (state["has_namespace"], state["namespace_prefix"], state["delimiter"]) == (
        False, None, ".",
    )
    assert state["folders"]["processed"] == {"state": "created", "place": "below_inbox"}


def test_finish_without_namespace_finds_a_hand_made_folder_below_inbox():
    client = _client(
        login_caps=("IMAP4REV1", "MOVE"),
        delimiter="/",
        create_under="INBOX/",
        folders={f"INBOX/{FOLDER_PROCESSED}"},
    )
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert ("create", f"INBOX/{FOLDER_PROCESSED}") not in calls
    assert ("uid", "MOVE", "7", f"INBOX/{FOLDER_PROCESSED}") in calls
    assert client.filing_state()["folders"]["processed"] == {
        "state": "found", "place": "below_inbox",
    }


def test_refused_create_warns_once_per_outage(caplog):
    caplog.set_level("DEBUG", logger=LOGGER)
    client = _client(
        login_caps=("IMAP4REV1", "MOVE", "NAMESPACE"),
        namespace=DOVECOT_PREFIX,
        results={"CREATE": "NO"},
    )
    for uid in ("7", "8", "9"):
        client.finish([(uid, FOLDER_PROCESSED), (uid, FOLDER_UNRECOGNIZED)], move=True)
    for fake in FakeImap.instances:
        assert not any(c[:2] in (("uid", "MOVE"), ("uid", "COPY")) for c in fake.calls)
        assert any(c[-1] == "(\\Seen)" for c in fake.calls)
    # Three runs, both folders failing: one warning per folder, not per run.
    warnings = _warnings(caplog)
    assert len(warnings) == 2
    assert FOLDER_PROCESSED in warnings[0].getMessage()
    assert FOLDER_UNRECOGNIZED in warnings[1].getMessage()
    assert "pakete@example.org" not in caplog.text and "mailbox.org" not in caplog.text
    state = client.filing_state()
    assert (state["failing"], state["last_error"]) == (True, "folder_unavailable")
    assert state["failing_folders"] == ["processed", "unrecognized"]
    assert state["folders"]["processed"] == {"state": "missing", "place": None}

    # The folders can be created again: the outage is over, a new one warns again.
    client._factory = lambda host, port, ssl_context=None, timeout=None: FakeImap(
        host, port, ssl_context, timeout,
        login_caps=("IMAP4REV1", "MOVE", "NAMESPACE"), namespace=DOVECOT_PREFIX,
    )
    client.finish([("10", FOLDER_PROCESSED), ("10", FOLDER_UNRECOGNIZED)], move=True)
    state = client.filing_state()
    assert (state["failing"], state["last_error"]) == (False, "folder_unavailable")
    assert state["failing_folders"] == []
    assert state["folders"]["processed"]["state"] == "created"
    client._factory = lambda host, port, ssl_context=None, timeout=None: FakeImap(
        host, port, ssl_context, timeout, login_caps=("IMAP4REV1", "MOVE"),
        results={"CREATE": "NO"},
    )
    client.finish([("11", FOLDER_PROCESSED)], move=True)
    assert len(_warnings(caplog)) == 3


@pytest.mark.parametrize(
    ("caps", "results", "code"),
    [
        (("MOVE",), {"MOVE": "NO"}, "move_refused"),
        (("UIDPLUS",), {"COPY": "NO"}, "copy_refused"),
        ((), {"STORE": "NO"}, "delete_refused"),
    ],
)
def test_refused_move_or_copy_warns_once_and_is_told_in_the_state(caplog, caps, results, code):
    caplog.set_level("DEBUG", logger=LOGGER)
    client = _client(login_caps=caps, results=results, folders={FOLDER_PROCESSED})
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    client.finish([("8", FOLDER_PROCESSED)], move=True)
    assert len(_warnings(caplog)) == 1
    state = client.filing_state()
    assert (state["failing"], state["last_error"]) == (True, code)


def test_server_without_move_or_uidplus_copies_below_the_prefix_and_leaves_expunge():
    """Unchanged: COPY + \\Deleted, no EXPUNGE at all; only the target lies below INBOX."""
    client = _client(
        login_caps=("IMAP4REV1", "NAMESPACE"),
        namespace=DOVECOT_PREFIX,
        create_under="INBOX.",
    )
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert ("uid", "COPY", "7", f"INBOX.{FOLDER_PROCESSED}") in calls
    assert ("uid", "STORE", "7", "+FLAGS", "(\\Deleted)") in calls
    assert not any(c[0] == "expunge" or c[:2] == ("uid", "EXPUNGE") for c in calls)
    state = client.filing_state()
    assert (state["has_move"], state["has_uidplus"]) == (False, False)
    assert (state["failing"], state["last_error"]) == (False, None)


@pytest.mark.parametrize(
    ("folder", "wire"),
    [("INBOX.Pakete", '"INBOX.Pakete"'), ("INBOX.Päckchen", '"INBOX.P&AOQ-ckchen"')],
)
def test_custom_folder_with_a_prefix_server(folder, wire):
    client = _client(
        folder=folder,
        login_caps=("IMAP4REV1", "MOVE", "UIDPLUS", "NAMESPACE"),
        namespace=DOVECOT_PREFIX,
        create_under="INBOX.",
    )
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert ("select", wire) in calls
    assert ("uid", "MOVE", "7", f"INBOX.{FOLDER_PROCESSED}") in calls
    # The filing folders are never below the folder read.
    assert not any(c[0] == "create" and "Pakete" in c[1] for c in calls)


def test_a_prefix_that_is_no_atom_goes_out_quoted():
    client = _client(
        login_caps=("MOVE", "NAMESPACE"), namespace=b'(("Mail Ordner/" "/")) NIL NIL'
    )
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    wire = f'"Mail Ordner/{FOLDER_PROCESSED}"'
    assert ("create", wire) in calls
    assert ("uid", "MOVE", "7", wire) in calls
    # Not a fixed word: the diagnostics only say "other".
    assert client.filing_state()["namespace_prefix"] == "other"


@pytest.mark.parametrize(
    "reply",
    [None, b"garbage", b"NIL NIL NIL", b'(("INBOX.\x01" ".")) NIL NIL', (b"{6}", b"INBOX.")],
)
def test_an_unusable_namespace_answer_files_as_before(reply):
    client = _client(login_caps=("MOVE", "NAMESPACE"), namespace=reply)
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert ("create", FOLDER_PROCESSED) in calls
    assert ("uid", "MOVE", "7", FOLDER_PROCESSED) in calls
    assert client.filing_state()["has_namespace"] is False


def test_the_layout_is_asked_once_per_run_not_kept():
    client = _client(
        login_caps=("MOVE", "NAMESPACE"), namespace=DOVECOT_PREFIX, create_under="INBOX."
    )
    client.finish([("7", FOLDER_PROCESSED), ("8", FOLDER_PROCESSED)], move=True)
    client.finish([("9", FOLDER_PROCESSED)], move=True)
    first, second = FakeImap.instances
    assert first.calls.count(("namespace",)) == 1
    assert first.calls.count(("create", f"INBOX.{FOLDER_PROCESSED}")) == 1
    assert second.calls.count(("namespace",)) == 1  # asked again in the next run


def test_no_namespace_command_without_moving():
    client = _client(login_caps=("MOVE", "NAMESPACE"), namespace=DOVECOT_PREFIX)
    client.finish([("7", FOLDER_PROCESSED)], move=False)
    assert ("namespace",) not in FakeImap.instances[0].calls


def test_a_connection_error_while_filing_is_told_but_not_warned(caplog):
    class Broken(FakeImap):
        def uid(self, command, *args):
            if command == "MOVE":
                raise imaplib.IMAP4.abort("socket closed")
            return super().uid(command, *args)

    FakeImap.instances = []
    client = MailboxClient(
        "imap.mailbox.org", "u", "p",
        factory=lambda host, port, ssl_context=None, timeout=None: Broken(
            host, port, login_caps=("MOVE",)
        ),
    )
    with pytest.raises(ImapUnavailable):
        client.finish([("7", FOLDER_PROCESSED)], move=True)
    assert not _warnings(caplog)
    state = client.filing_state()
    assert (state["failing"], state["last_error"]) == (False, "connection")


def test_filing_state_before_any_run_and_free_of_names():
    client = _client(folder="Geheimer Ordner")
    assert client.filing_state() == {
        "has_move": None,
        "has_uidplus": None,
        "has_namespace": None,
        "namespace_prefix": None,
        "delimiter": None,
        "folders": {"processed": None, "unrecognized": None},
        "failing": False,
        "failing_folders": [],
        "last_error": None,
    }
    # A copy: changing it changes nothing in the client.
    client.filing_state()["folders"]["processed"] = "x"
    assert client.filing_state()["folders"]["processed"] is None


# ----- v0.3.33 review: per-folder outages, prefixes without delimiter, lazy NAMESPACE -----


def test_one_warning_per_folder_outage_even_when_runs_alternate(caplog):
    """Verarbeitet works, Nicht-erkannt cannot be created: runs that only file into the
    working folder do not end the other folder's outage."""
    caplog.set_level("DEBUG", logger=LOGGER)
    client = _client(
        login_caps=("IMAP4REV1", "MOVE"),
        folders={FOLDER_PROCESSED},
        create_under="INBOX.",  # (top-level CREATE refused, no LIST "" "" answer)
    )
    for uid, folder in [("1", FOLDER_UNRECOGNIZED), ("2", FOLDER_PROCESSED)] * 3:
        client.finish([(uid, folder)], move=True)
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert FOLDER_UNRECOGNIZED in warnings[0].getMessage()
    state = client.filing_state()
    assert state["failing"] is True
    assert state["failing_folders"] == ["unrecognized"]
    assert state["folders"]["processed"]["state"] == "found"


def test_a_second_folder_failing_warns_for_itself_and_recovery_is_per_folder(caplog):
    caplog.set_level("DEBUG", logger=LOGGER)
    client = _client(login_caps=("MOVE",), results={"CREATE": "NO"})
    client.finish([("1", FOLDER_UNRECOGNIZED)], move=True)
    client.finish([("2", FOLDER_PROCESSED)], move=True)
    client.finish([("3", FOLDER_PROCESSED), ("4", FOLDER_UNRECOGNIZED)], move=True)
    assert len(_warnings(caplog)) == 2  # one per folder
    assert client.filing_state()["failing_folders"] == ["processed", "unrecognized"]
    # Verarbeitet can be created now; Nicht-erkannt still fails, without a new warning.
    client._factory = lambda host, port, ssl_context=None, timeout=None: FakeImap(
        host, port, ssl_context, timeout, login_caps=("MOVE",), create_under=FOLDER_PROCESSED
    )
    client.finish([("5", FOLDER_PROCESSED), ("6", FOLDER_UNRECOGNIZED)], move=True)
    assert len(_warnings(caplog)) == 2
    state = client.filing_state()
    assert (state["failing"], state["failing_folders"]) == (True, ["unrecognized"])
    # Verarbeitet fails again: a new outage of that folder, a new warning.
    client._factory = lambda host, port, ssl_context=None, timeout=None: FakeImap(
        host, port, ssl_context, timeout, login_caps=("MOVE",), results={"MOVE": "NO"},
        folders={FOLDER_PROCESSED},
    )
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    assert len(_warnings(caplog)) == 3


@pytest.mark.parametrize(
    ("reply", "target", "prefix"),
    [
        # Prefix without its delimiter: the delimiter is added.
        (b'(("INBOX" ".")) NIL NIL', f"INBOX.{FOLDER_PROCESSED}", "INBOX."),
        (b'(("INBOX" "/")) NIL NIL', f"INBOX/{FOLDER_PROCESSED}", "INBOX/"),
    ],
)
def test_a_prefix_without_its_delimiter_gets_it(reply, target, prefix):
    client = _client(login_caps=("MOVE", "NAMESPACE"), namespace=reply)
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert ("create", target) in calls
    assert ("uid", "MOVE", "7", target) in calls
    assert not any(c[0] == "create" and c[1].startswith("INBOXPaket") for c in calls)
    assert client.filing_state()["namespace_prefix"] == prefix


def test_a_prefix_without_any_delimiter_is_ignored():
    client = _client(login_caps=("MOVE", "NAMESPACE"), namespace=b'(("INBOX" NIL)) NIL NIL')
    client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert ("create", FOLDER_PROCESSED) in calls
    assert ("uid", "MOVE", "7", FOLDER_PROCESSED) in calls
    assert client.filing_state()["has_namespace"] is False


def test_a_dropped_connection_on_namespace_never_blocks_marking_seen():
    class DropsOnNamespace(FakeImap):
        def namespace(self):
            self.calls.append(("namespace",))
            raise imaplib.IMAP4.abort("socket closed")

    FakeImap.instances = []
    client = MailboxClient(
        "imap.mailbox.org", "u", "p",
        factory=lambda host, port, ssl_context=None, timeout=None: DropsOnNamespace(
            host, port, login_caps=("MOVE", "NAMESPACE")
        ),
    )
    with pytest.raises(ImapUnavailable):
        client.finish([("7", FOLDER_PROCESSED)], move=True)
    calls = FakeImap.instances[0].calls
    assert calls.index(("uid", "STORE", "7", "+FLAGS", "(\\Seen)")) < calls.index(("namespace",))
    assert client.filing_state()["last_error"] == "connection"


def test_no_namespace_when_no_mail_needs_a_folder():
    client = _client(login_caps=("MOVE", "NAMESPACE"), namespace=DOVECOT_PREFIX)
    client.finish([("7", None), ("8", None)], move=True)
    calls = FakeImap.instances[0].calls
    assert ("namespace",) not in calls
    assert ("uid", "STORE", "8", "+FLAGS", "(\\Seen)") in calls
    # Filing was never set up: the diagnostics stay as they were.
    assert client.filing_state()["has_namespace"] is None

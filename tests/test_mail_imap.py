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
    ):
        self.host, self.port, self.ssl_context, self.timeout = host, port, ssl_context, timeout
        self.mails = dict(mails or {})
        self.capabilities = caps
        self.login_caps = caps if login_caps is None else login_caps
        self.results = dict(results or {})
        self.folders = set(folders)
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

    def list(self, directory, pattern):
        self.calls.append(("list", pattern))
        if pattern in self.folders:
            return "OK", [f'(\\HasNoChildren) "/" {pattern}'.encode()]
        return "OK", [None]

    def create(self, folder):
        self.calls.append(("create", folder))
        status = self._status("CREATE")
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

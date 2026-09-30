import imaplib
import ssl

import pytest

from custom_components.parcel_tracker.const import FOLDER_PROCESSED, FOLDER_UNRECOGNIZED
from custom_components.parcel_tracker.mail.imap import (
    ImapAuthError,
    ImapUnavailable,
    MailboxClient,
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


def _client(**fake_kwargs):
    FakeImap.instances = []

    def factory(host, port, ssl_context=None, timeout=None):
        return FakeImap(host, port, ssl_context, timeout, **fake_kwargs)

    return MailboxClient("imap.mailbox.org", "pakete@example.org", "secret", factory=factory)


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

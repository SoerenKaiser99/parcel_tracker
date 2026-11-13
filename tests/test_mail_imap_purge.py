"""Deleting recognised mails after X days (v0.3.46): only in Paket-Tracker-Verarbeitet.

A fake server with real folders: every folder holds mails with their arrival date
(INTERNALDATE); SEARCH BEFORE, STORE, EXPUNGE and UID EXPUNGE act only on the folder
selected, as on a real server. Never a real mail server.
"""

from __future__ import annotations

import imaplib
from datetime import date

import pytest

from custom_components.parcel_tracker.const import FOLDER_PROCESSED, FOLDER_UNRECOGNIZED
from custom_components.parcel_tracker.mail.imap import (
    ImapExpungeRefused,
    ImapUnavailable,
    MailboxClient,
    imap_date,
)

from .test_mail_imap import DOVECOT_PREFIX, FakeImap

TODAY = date(2026, 10, 29)
_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}


def _parse(text: str) -> date:
    day, month, year = text.split("-")
    return date(int(year), _MONTHS[month], int(day))


class FolderImap(FakeImap):
    """FakeImap with folders that hold mails: {folder (wire name): {uid: arrival date}}."""

    def __init__(self, *args, boxes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.boxes = {name: dict(mails) for name, mails in (boxes or {}).items()}
        self.folders |= {name for name in self.boxes if name != "INBOX"}
        self.flags: dict[tuple[str, str], set[str]] = {}
        self.selected: str | None = None

    def select(self, mailbox):
        self.calls.append(("select", mailbox))
        name = mailbox.strip('"')
        if self._status("SELECT") != "OK" or name not in self.boxes:
            self.selected = None
            return "NO", [b"no such folder"]
        self.selected = name
        return "OK", [str(len(self.boxes[name])).encode()]

    def _uids(self, spec):
        return spec.split(",")

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        status = self._status(command)
        if command == "SEARCH":
            assert self.selected is not None, "SEARCH without a selected folder"
            criteria = [a for a in args if a is not None]
            assert criteria[0] == "BEFORE"
            before = _parse(criteria[1])
            found = [u for u, d in self.boxes[self.selected].items() if d < before]
            return status, [" ".join(found).encode()]
        if command == "STORE":
            assert self.selected is not None
            if status == "OK":
                for uid in self._uids(args[0]):
                    if uid in self.boxes[self.selected]:
                        self.flags.setdefault((self.selected, uid), set()).add(args[2])
            return status, [None]
        if command == "EXPUNGE":
            assert self.selected is not None
            if status == "OK":
                for uid in self._uids(args[0]):
                    if "(\\Deleted)" in self.flags.get((self.selected, uid), set()):
                        self.boxes[self.selected].pop(uid, None)
            return status, [None]
        return status, [None]

    def expunge(self):
        self.calls.append(("expunge",))
        assert self.selected is not None
        if self._status("EXPUNGE") != "OK":
            return "NO", [b"refused"]
        box = self.boxes[self.selected]
        for uid in list(box):
            if "(\\Deleted)" in self.flags.get((self.selected, uid), set()):
                box.pop(uid)
        return "OK", [None]


OLD = date(2026, 9, 1)
YOUNG = date(2026, 10, 25)


def _boxes(processed=FOLDER_PROCESSED):
    return {
        "INBOX": {"1": OLD, "2": YOUNG},
        processed: {"10": OLD, "11": date(2026, 9, 27), "14": date(2026, 9, 28),
                    "12": YOUNG, "13": TODAY},
        FOLDER_UNRECOGNIZED: {"20": OLD},
        "Archiv": {"30": OLD},
    }


def _client(folder=None, **fake_kwargs):
    FakeImap.instances = []

    def factory(host, port, ssl_context=None, timeout=None):
        return FolderImap(host, port, ssl_context, timeout, **fake_kwargs)

    extra = {} if folder is None else {"folder": folder}
    return MailboxClient(
        "imap.mailbox.org", "pakete@example.org", "secret", factory=factory, **extra
    )


def _fake() -> FolderImap:
    return FakeImap.instances[0]


def test_imap_date_is_english_and_two_digits():
    assert imap_date(date(2026, 10, 1)) == "01-Oct-2026"
    assert imap_date(date(2026, 3, 29)) == "29-Mar-2026"


def test_with_uidplus_only_old_mails_in_the_processed_folder_go():
    client = _client(login_caps=("IMAP4REV1", "UIDPLUS"), boxes=_boxes())
    assert client.purge_processed(30, TODAY) == 2
    fake = _fake()
    # 30 days before 29 Oct is 29 Sep, one more day for safety: mails before 28 Sep.
    assert ("uid", "SEARCH", None, "BEFORE", "28-Sep-2026") in fake.calls
    assert fake.boxes[FOLDER_PROCESSED] == {"14": date(2026, 9, 28), "12": YOUNG, "13": TODAY}
    assert ("uid", "STORE", "10,11", "+FLAGS", "(\\Deleted)") in fake.calls
    assert ("uid", "EXPUNGE", "10,11") in fake.calls
    assert ("expunge",) not in fake.calls
    # Nothing else touched: neither the folder read nor the other folders.
    assert fake.boxes["INBOX"] == {"1": OLD, "2": YOUNG}
    assert fake.boxes[FOLDER_UNRECOGNIZED] == {"20": OLD}
    assert fake.boxes["Archiv"] == {"30": OLD}
    assert [c for c in fake.calls if c[0] == "select"] == [("select", FOLDER_PROCESSED)]
    # Only looked up, never created.
    assert not any(c[0] in ("create", "subscribe") for c in fake.calls)
    assert fake.calls[-1] == ("logout",)


def test_without_uidplus_expunge_runs_in_the_processed_folder_only():
    client = _client(login_caps=("IMAP4REV1",), boxes=_boxes())
    assert client.purge_processed(30, TODAY) == 2
    fake = _fake()
    assert fake.calls.count(("expunge",)) == 1
    # The only folder ever selected in this connection is the processed one.
    expunge = fake.calls.index(("expunge",))
    selects = [c for c in fake.calls[:expunge] if c[0] == "select"]
    assert selects == [("select", FOLDER_PROCESSED)]
    assert not any(c[:2] == ("uid", "EXPUNGE") for c in fake.calls)
    assert fake.boxes[FOLDER_PROCESSED] == {"14": date(2026, 9, 28), "12": YOUNG, "13": TODAY}
    assert fake.boxes["INBOX"] == {"1": OLD, "2": YOUNG}


def test_young_mails_stay():
    client = _client(login_caps=("UIDPLUS",), boxes=_boxes())
    assert client.purge_processed(365, TODAY) == 0
    fake = _fake()
    assert len(fake.boxes[FOLDER_PROCESSED]) == 5
    assert not any(c[:2] == ("uid", "STORE") for c in fake.calls)
    assert not any(c[0] == "expunge" or c[:2] == ("uid", "EXPUNGE") for c in fake.calls)


def test_one_day_keeps_the_last_two_server_dates():
    boxes = {FOLDER_PROCESSED: {
        "1": date(2026, 10, 28), "2": TODAY, "3": date(2026, 10, 27), "4": date(2026, 10, 26),
    }}
    client = _client(login_caps=("UIDPLUS",), boxes=boxes)
    assert client.purge_processed(1, TODAY) == 1
    assert ("uid", "SEARCH", None, "BEFORE", "27-Oct-2026") in _fake().calls
    assert _fake().boxes[FOLDER_PROCESSED] == {
        "1": date(2026, 10, 28), "2": TODAY, "3": date(2026, 10, 27),
    }


def test_one_day_never_deletes_a_mail_younger_than_24_hours_across_time_zones():
    """Server in UTC, Home Assistant in Berlin: at 00:30 on 29 Oct in Berlin (28 Oct 22:30
    UTC) a mail that arrived 27 Oct 23:00 UTC (00:00 Berlin, 23.5 hours ago) has the
    server date 27 Oct. Without the extra day BEFORE 28-Oct would delete it."""
    arrived_utc_date = date(2026, 10, 27)
    berlin_today = date(2026, 10, 29)
    boxes = {FOLDER_PROCESSED: {"7": arrived_utc_date, "8": date(2026, 10, 26)}}
    client = _client(login_caps=("UIDPLUS",), boxes=boxes)
    assert client.purge_processed(1, berlin_today) == 1
    # "8" arrived on 26 Oct UTC at the latest 23:59: more than 46 hours ago.
    assert _fake().boxes[FOLDER_PROCESSED] == {"7": arrived_utc_date}


@pytest.mark.parametrize("days", [0, -1, None, True, "30", 366])
def test_no_valid_days_means_no_connection(days):
    client = _client(login_caps=("UIDPLUS",), boxes=_boxes())
    assert client.purge_processed(days, TODAY) == 0
    assert FakeImap.instances == []


def test_folder_with_a_prefix_is_found():
    """Dovecot/Courier with INBOX.: the folder lives as INBOX.Paket-Tracker-Verarbeitet."""
    processed = f"INBOX.{FOLDER_PROCESSED}"
    client = _client(
        login_caps=("IMAP4REV1", "UIDPLUS", "NAMESPACE"),
        namespace=DOVECOT_PREFIX,
        delimiter=".",
        boxes=_boxes(processed),
    )
    assert client.purge_processed(30, TODAY) == 2
    fake = _fake()
    assert ("select", processed) in fake.calls
    assert fake.boxes[processed] == {"14": date(2026, 9, 28), "12": YOUNG, "13": TODAY}
    assert fake.boxes["INBOX"] == {"1": OLD, "2": YOUNG}
    assert not any(c[0] == "create" for c in fake.calls)


def test_folder_below_inbox_without_namespace_is_found():
    processed = f"INBOX.{FOLDER_PROCESSED}"
    client = _client(login_caps=("UIDPLUS",), delimiter=".", boxes=_boxes(processed))
    assert client.purge_processed(30, TODAY) == 2
    assert ("select", processed) in _fake().calls


def test_missing_folder_deletes_nothing_and_selects_nothing():
    boxes = {"INBOX": {"1": OLD}, FOLDER_UNRECOGNIZED: {"20": OLD}}
    client = _client(login_caps=("UIDPLUS",), delimiter=".", boxes=boxes)
    assert client.purge_processed(30, TODAY) == 0
    fake = _fake()
    assert not any(c[0] in ("select", "create", "expunge") for c in fake.calls)
    assert not any(c[0] == "uid" for c in fake.calls)
    assert fake.boxes == boxes


def test_refused_select_never_expunges():
    """Without the processed folder selected, nothing is marked or expunged anywhere."""
    client = _client(login_caps=("IMAP4REV1",), boxes=_boxes(), results={"SELECT": "NO"})
    with pytest.raises(ImapUnavailable):
        client.purge_processed(30, TODAY)
    fake = _fake()
    assert not any(c[0] == "expunge" or c[0] == "uid" for c in fake.calls)
    assert fake.calls[-1] == ("logout",)


def test_refused_search_never_expunges():
    client = _client(login_caps=("IMAP4REV1",), boxes=_boxes(), results={"SEARCH": "NO"})
    with pytest.raises(ImapUnavailable):
        client.purge_processed(30, TODAY)
    fake = _fake()
    assert not any(c[0] == "expunge" or c[1:2] == ("STORE",) for c in fake.calls)


def test_refused_store_expunges_nothing():
    client = _client(login_caps=("IMAP4REV1",), boxes=_boxes(), results={"STORE": "NO"})
    assert client.purge_processed(30, TODAY) == 0
    fake = _fake()
    assert ("expunge",) not in fake.calls
    assert len(fake.boxes[FOLDER_PROCESSED]) == 5


def test_a_connection_error_is_unavailable_and_logs_out():
    client = _client(login_caps=("UIDPLUS",), boxes=_boxes())
    original = FolderImap.uid

    def broken(self, command, *args):
        if command == "STORE":
            raise imaplib.IMAP4.abort("socket error")
        return original(self, command, *args)

    FolderImap.uid = broken
    try:
        with pytest.raises(ImapUnavailable):
            client.purge_processed(30, TODAY)
    finally:
        FolderImap.uid = original
    assert _fake().calls[-1] == ("logout",)


def test_many_mails_go_in_batches():
    boxes = {FOLDER_PROCESSED: {str(i): OLD for i in range(1, 451)}}
    client = _client(login_caps=("UIDPLUS",), boxes=boxes)
    assert client.purge_processed(30, TODAY) == 450
    fake = _fake()
    stores = [c for c in fake.calls if c[:2] == ("uid", "STORE")]
    expunges = [c for c in fake.calls if c[:2] == ("uid", "EXPUNGE")]
    assert len(stores) == 3 and len(expunges) == 3
    assert fake.boxes[FOLDER_PROCESSED] == {}


def test_a_reserved_or_custom_read_folder_does_not_matter():
    """The folder read is never selected here, also when it is another one than INBOX."""
    client = _client(folder="Archiv", login_caps=("IMAP4REV1",), boxes=_boxes())
    assert client.purge_processed(30, TODAY) == 2
    fake = _fake()
    assert [c for c in fake.calls if c[0] == "select"] == [("select", FOLDER_PROCESSED)]
    assert fake.boxes["Archiv"] == {"30": OLD}


def test_server_answers_with_odd_uids_are_ignored():
    client = _client(login_caps=("UIDPLUS",), boxes={FOLDER_PROCESSED: {"5": OLD}})
    original = FolderImap.uid

    def odd(self, command, *args):
        if command == "SEARCH":
            self.calls.append(("uid", command, *args))
            return "OK", [b"5 1:* x"]
        return original(self, command, *args)

    FolderImap.uid = odd
    try:
        assert client.purge_processed(30, TODAY) == 1
    finally:
        FolderImap.uid = original
    fake = _fake()
    assert ("uid", "STORE", "5", "+FLAGS", "(\\Deleted)") in fake.calls
    assert ("uid", "EXPUNGE", "5") in fake.calls


@pytest.mark.parametrize("caps", [("UIDPLUS",), ("IMAP4REV1",)])
def test_a_refused_expunge_counts_nothing(caps):
    client = _client(login_caps=caps, boxes=_boxes(), results={"EXPUNGE": "NO"})
    with pytest.raises(ImapExpungeRefused):
        client.purge_processed(30, TODAY)
    fake = _fake()
    assert len(fake.boxes[FOLDER_PROCESSED]) == 5  # marked, not removed
    assert fake.calls[-1] == ("logout",)
    assert issubclass(ImapExpungeRefused, ImapUnavailable)

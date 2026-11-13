"""Tester mode keeps the recipient headers the owner detection reads, with invented addresses."""

import email
import subprocess
import sys
from email import policy
from email.message import EmailMessage
from pathlib import Path

from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.owner import owner_from_message
from custom_components.parcel_tracker.models import PersonConfig

SCRIPT = Path(__file__).parent.parent / "scripts" / "anonymize_mail.py"
# Everything real in the test mail (compared in lower case).
REAL = ["famnuss", "nuss", "annabell", "berthold", "gemeinsam.example", "mailhost.example"]


def _mail(number: int = 1, to: str = "Annabell Nuss <famnuss+annabell@mailhost.example>") -> bytes:
    msg = EmailMessage()
    msg["Received"] = "from mx.mailhost.example by relay.mailhost.example"
    msg["From"] = "DHL Paket <noreply@dhl.de>"
    msg["To"] = to
    msg["Cc"] = "Berthold Nuss <berthold@gemeinsam.example>"
    msg["Delivered-To"] = "famnuss+annabell@mailhost.example"
    msg["Delivered-To"] = "famnuss@mailhost.example"
    msg["Delivered-To"] = "berthold@gemeinsam.example"
    msg["X-Original-To"] = "FamNuss+Annabell@mailhost.example"
    msg["X-Forwarded-For"] = "famnuss@mailhost.example berthold@gemeinsam.example"
    msg["Resent-To"] = "berthold@gemeinsam.example"
    msg["Subject"] = "Ihr DHL Paket kommt morgen"
    msg["Date"] = "Tue, 18 Jul 2023 08:02:46 +0000"
    msg["Message-ID"] = f"<{number}@mailhost.example>"
    msg.set_content("Ihre Sendung JJD000390007812345678 ist unterwegs.\n")
    return bytes(msg)


def _run(tmp_path, mails) -> list[bytes]:
    src = tmp_path / "mails"
    src.mkdir()
    for i, raw in enumerate(mails):
        (src / f"m{i}.eml").write_bytes(raw)
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(src), "--ohne-angaben"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr
    return [p.read_bytes() for p in sorted((src / "anonymisiert").glob("*.eml"))]


def _msg(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=policy.default)


def test_headers_stay_with_invented_addresses(tmp_path):
    out = _msg(_run(tmp_path, [_mail()])[0])
    assert out.get_all("To") == ["adresse1+person1@example.org"]
    assert out.get_all("Cc") == ["adresse2@example.org"]
    assert out.get_all("X-Original-To") == ["adresse1+person1@example.org"]
    assert out.get_all("Resent-To") == ["adresse2@example.org"]
    assert out.get_all("X-Forwarded-For") == ["adresse1@example.org, adresse2@example.org"]


def test_order_of_several_delivered_to_stays(tmp_path):
    out = _msg(_run(tmp_path, [_mail()])[0])
    assert out.get_all("Delivered-To") == [
        "adresse1+person1@example.org", "adresse1@example.org", "adresse2@example.org",
    ]


def test_same_real_address_same_invented_in_every_mail(tmp_path):
    first, second = (
        _msg(raw) for raw in _run(
            tmp_path, [_mail(1), _mail(2, to="Berthold <berthold@gemeinsam.example>")]
        )
    )
    assert first.get_all("Cc") == second.get_all("To") == ["adresse2@example.org"]
    assert first.get_all("To") != second.get_all("To")


def test_plus_parts_are_numbered_per_run(tmp_path):
    raw = _mail().replace(b"famnuss+annabell@", b"famnuss+tim@", 1)
    out = _msg(_run(tmp_path, [raw])[0])
    assert out.get_all("To") == ["adresse1+person1@example.org"]
    assert out.get_all("X-Original-To") == ["adresse1+person2@example.org"]


def test_nothing_real_is_left_in_the_result(tmp_path):
    raw = _run(tmp_path, [_mail()])[0].decode().lower()
    for part in REAL:
        assert part not in raw, part
    assert "<" not in "".join(_msg(raw.encode())[k] or "" for k in ("To", "Cc"))


def test_without_address_headers_to_is_the_placeholder(tmp_path):
    msg = EmailMessage()
    msg["From"] = "DHL Paket <noreply@dhl.de>"
    msg["Subject"] = "Ihr DHL Paket kommt morgen"
    msg.set_content("Ihre Sendung JJD000390007812345678 ist unterwegs.\n")
    out = _msg(_run(tmp_path, [bytes(msg)])[0])
    assert out.get_all("To") == ["max@example.org"]


def test_owner_detection_works_on_the_anonymised_mail(tmp_path):
    out = _msg(_run(tmp_path, [_mail()])[0])
    both = [
        PersonConfig("person.anna", ("adresse1+person1@example.org",), ()),
        PersonConfig("person.bert", ("adresse2@example.org",), ()),
    ]
    assert owner_from_message(out, both) is None  # both occur: unclear, as before
    assert owner_from_message(out, both[:1]) == "person.anna"
    assert owner_from_message(out, both[1:]) == "person.bert"


def test_parsed_result_does_not_change(tmp_path):
    before = parse_mail(_msg(_mail()))
    after = parse_mail(_msg(_run(tmp_path, [_mail()])[0]))
    assert before.updates
    assert [(u.carrier, u.status) for u in after.updates] == [
        (u.carrier, u.status) for u in before.updates
    ]

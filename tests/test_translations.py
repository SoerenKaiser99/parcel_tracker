import json
from pathlib import Path

from custom_components.parcel_tracker import const

BASE = Path(const.__file__).parent


def _load(name: str) -> dict:
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def _shape(node):
    if isinstance(node, dict):
        return {key: _shape(value) for key, value in node.items()}
    return None


def _texts(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _texts(value)
    else:
        yield node


def test_english_is_a_copy_of_strings():
    assert _load("translations/en.json") == _load("strings.json")


def test_german_has_the_same_keys():
    assert _shape(_load("translations/de.json")) == _shape(_load("strings.json"))


def test_german_copy_rules():
    for text in _texts(_load("translations/de.json")):
        lower = text.lower()
        assert "bitte" not in lower, text
        assert "erfolgreich" not in lower, text


def test_mail_translations_present():
    strings = _load("strings.json")
    section = strings["options"]["step"]["init"]["sections"]["mail"]
    assert set(section["data"]) == {
        "imap_host", "imap_user", "imap_password", "move_processed", "read_otp",
            "mail_interval",
    }
    assert {"imap_auth", "imap_cannot_connect", "imap_password_missing"} <= set(
        strings["options"]["error"]
    )
    assert {"imap_auth", "amazon_unrecognized"} <= set(strings["issues"])

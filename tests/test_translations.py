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


def test_ups_translations_present():
    for name in ("strings.json", "translations/de.json"):
        strings = _load(name)
        section = strings["options"]["step"]["init"]["sections"]["ups"]
        assert set(section["data"]) == {
            "ups_client_id", "ups_client_secret", "ups_monthly_budget",
        }
        assert {"ups_auth", "ups_cannot_connect", "ups_secret_missing"} <= set(
            strings["options"]["error"]
        )
        assert {"ups_auth", "ups_budget"} <= set(strings["issues"])
    services = _load("strings.json")["services"]["add_parcel"]["fields"]["carrier"]
    assert services["description"] == (
        "auto, dhl, dpd, hermes, ups or other (via 17track, needs a 17track API key)."
    )


def test_track17_issue_translations_present():
    for name in ("strings.json", "translations/de.json"):
        issues = _load(name)["issues"]
        assert {"track17_auth", "track17_quota_low", "track17_quota_exhausted"} <= set(issues)
        assert "{remain}" in issues["track17_quota_low"]["description"]


def test_track17_option_translations_present():
    for name in ("strings.json", "translations/de.json"):
        init = _load(name)["options"]["step"]["init"]
        assert "track17_api_key" in init["data"]
        assert "track17_api_key" in init["data_description"]
        assert {"track17_invalid_key", "track17_cannot_connect"} <= set(
            _load(name)["options"]["error"]
        )


def test_track17_service_translations_present():
    for name in ("strings.json", "translations/de.json"):
        strings = _load(name)
        assert {
            "track17_off", "track17_carrier", "track17_quota", "track17_auth",
            "track17_unavailable", "track17_not_possible",
        } <= set(strings["exceptions"])
        assert set(strings["services"]["track_17track"]["fields"]) == {"number"}
        assert "track17_quota" in strings["entity"]["sensor"]

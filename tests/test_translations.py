import json
import re
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
        "mail_enabled", "imap_host", "imap_user", "imap_password", "move_processed",
        "read_otp", "mail_interval",
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
            "ups_enabled", "ups_client_id", "ups_client_secret", "ups_monthly_budget",
        }
        assert {"ups_auth", "ups_cannot_connect", "ups_secret_missing"} <= set(
            strings["options"]["error"]
        )
        assert {"ups_auth", "ups_budget"} <= set(strings["issues"])
    services = _load("strings.json")["services"]["add_parcel"]["fields"]["carrier"]
    assert services["description"] == (
        "auto, dhl, dpd, gls, hermes, ups or other (via 17track, needs a 17track API key)."
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


def test_postcode_note_names_dhl_and_gls():
    english = _load("strings.json")["config"]["step"]["user"]["description"]
    german = _load("translations/de.json")["config"]["step"]["user"]["description"]
    assert english.endswith("lets DHL return more details and GLS the tracking history.")
    assert german.endswith("liefert DHL zusätzliche Details und GLS den Sendungsverlauf.")


def test_switch_translations_present():
    """Switching off is the explicit switch; no text says "leave empty to switch off"."""
    labels = {"strings.json": ("Mail import enabled", "UPS API enabled"),
              "translations/de.json": ("E-Mail-Import aktiv", "UPS-API aktiv")}
    for name, (mail_label, ups_label) in labels.items():
        sections = _load(name)["options"]["step"]["init"]["sections"]
        assert sections["mail"]["data"]["mail_enabled"] == mail_label
        assert sections["ups"]["data"]["ups_enabled"] == ups_label
        assert "mail_enabled" in sections["mail"]["data_description"]
        assert "ups_enabled" in sections["ups"]["data_description"]
        for section in sections.values():
            for key in ("imap_user", "ups_client_id"):
                text = section["data_description"].get(key, "").lower()
                assert "switch" not in text and "schalt" not in text, text


def test_notify_translations_present():
    labels = {
        "strings.json": ("Notifications (optional)", "Notifications enabled", "Targets", "Events"),
        "translations/de.json": (
            "Benachrichtigungen (optional)", "Benachrichtigungen aktiv", "Ziele", "Ereignisse",
        ),
    }
    for name, (title, enabled, targets, events) in labels.items():
        strings = _load(name)
        section = strings["options"]["step"]["init"]["sections"]["notify"]
        assert section["name"] == title
        assert section["data"] == {
            "notify_enabled": enabled, "notify_targets": targets, "notify_events": events,
        }
        assert set(section["data_description"]) == {
            "notify_enabled", "notify_targets", "notify_events",
        }
        assert "description" in section
        assert set(strings["selector"]["notify_events"]["options"]) == {
            "out_for_delivery", "delivered", "awaiting_pickup", "exception",
        }
        assert "notify_url" not in json.dumps(strings)
        assert strings["options"]["error"]["notify_no_target"]
    # Both kinds of targets are named: entities and classic services such as Pushover.
    english = _load("strings.json")["options"]["step"]["init"]["sections"]["notify"]
    assert "entities" in english["data_description"]["notify_targets"]
    assert "classic notify services" in english["data_description"]["notify_targets"]
    assert "Pushover" in english["data_description"]["notify_targets"]
    german = _load("translations/de.json")["options"]["step"]["init"]["sections"]["notify"]
    assert "Entitäten" in german["data_description"]["notify_targets"]
    assert "klassische Dienste" in german["data_description"]["notify_targets"]
    assert "Pushover" in german["data_description"]["notify_targets"]
    assert _load("translations/de.json")["options"]["error"]["notify_no_target"] == (
        "Wähl mindestens ein Ziel für die Benachrichtigungen."
    )
    german = _load("translations/de.json")["selector"]["notify_events"]["options"]
    assert german == {
        "out_for_delivery": "In Zustellung",
        "delivered": "Zugestellt",
        "awaiting_pickup": "Abholbereit",
        "exception": "Problem",
    }


def test_create_entry_says_to_reload_before_adding_the_card():
    """The frontend shows config.create_entry.default in the success dialog. An
    already open Home Assistant only knows the new card resource after a reload."""
    german = _load("translations/de.json")["config"]["create_entry"]["default"]
    assert german == (
        "Seite einmal neu laden, dann im Dashboard die Karte „Paket Tracker“ hinzufügen."
    )
    english = _load("strings.json")["config"]["create_entry"]["default"]
    assert "Reload the page once" in english and "“Paket Tracker” card" in english


def test_country_translations_present():
    labels = {
        "strings.json": ("Country", {"de": "Germany", "at": "Austria", "ch": "Switzerland"}),
        "translations/de.json": (
            "Land", {"de": "Deutschland", "at": "Österreich", "ch": "Schweiz"},
        ),
    }
    for name, (label, options) in labels.items():
        strings = _load(name)
        assert strings["selector"]["country"]["options"] == options
        for step in (strings["config"]["step"]["user"], strings["options"]["step"]["init"]):
            assert step["data"]["country"] == label
            assert list(step["data"]).index("country") + 1 == list(step["data"]).index("postcode")
            assert "country" in step["data_description"]
            assert "1010" in step["data_description"]["postcode"]


def test_postcode_errors_name_the_expected_length():
    expected = {
        "strings.json": ("Enter a 5-digit postcode.", "Enter a 4-digit postcode."),
        "translations/de.json": ("Gib eine 5-stellige PLZ ein.", "Gib eine 4-stellige PLZ ein."),
    }
    for name, (five, four) in expected.items():
        strings = _load(name)
        for part in ("config", "options"):
            assert strings[part]["error"]["invalid_postcode"] == five
            assert strings[part]["error"]["invalid_postcode_4"] == four


_KEY = re.compile(r"^[a-z0-9]([a-z0-9-_]*[a-z0-9])?$")


def _selector_keys(strings: dict) -> list[tuple[str, str]]:
    return [
        (name, key)
        for name, selector in strings["selector"].items()
        for key in selector.get("options", {})
    ]


def test_selector_option_keys_are_valid_translation_keys():
    """hassfest only accepts [a-z0-9-_]+ as a translation key; selector option values are
    translation keys, so e.g. "DE" fails CI ("Invalid translation key")."""
    for name in ("strings.json", "translations/de.json", "translations/en.json"):
        keys = _selector_keys(_load(name))
        assert keys, name
        for selector, key in keys:
            assert _KEY.match(key), f"{name}: selector.{selector}.options.{key}"


def test_selector_options_in_code_match_the_translation_keys():
    strings = _load("strings.json")
    assert set(strings["selector"]["country"]["options"]) == set(const.COUNTRIES)
    assert all(_KEY.match(c) for c in const.COUNTRIES)


def test_known_country_is_tolerant_of_case():
    assert [const.known_country(v) for v in ("AT", "at", " Ch ", "DE", "FR", None, 1)] == [
        "at", "at", "ch", "de", "de", "de", "de",
    ]


def test_pickup_sensor_is_named_in_every_language():
    """v0.3.18: the count sensor for parcels that wait at a pickup point."""
    names = {
        "strings.json": "Parcels ready for pickup",
        "translations/en.json": "Parcels ready for pickup",
        "translations/de.json": "Pakete abholbereit",
    }
    for name, text in names.items():
        assert _load(name)["entity"]["sensor"]["awaiting_pickup"] == {"name": text}, name


def test_hide_names_translations_present():
    """v0.3.24: the switch "Namen ausblenden" has a label and a description that says
    where it applies and that a typed-in name stays."""
    for name, label in (("strings.json", "Hide names"), ("translations/de.json",
                                                         "Namen ausblenden")):
        init = _load(name)["options"]["step"]["init"]
        assert init["data"]["hide_names"] == label
        assert init["data_description"]["hide_names"]
        assert "hide_names" not in _load(name)["config"]["step"]["user"]["data"]
    text = _load("translations/de.json")["options"]["step"]["init"]["data_description"][
        "hide_names"
    ]
    for word in ("DHL-Paket", "Amazon-Bestellung", "Karte", "Kalender", "Sensoren",
                 "Benachrichtigungen", "eingetippter Name"):
        assert word in text

"""The GitHub issue forms are valid and ask for what a report needs (and never for raw mails)."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"
README = (ROOT / "README.md").read_text(encoding="utf-8")
REPO = "https://github.com/SoerenKaiser99/parcel_tracker"
FIELD_TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}


def _load(name: str) -> dict:
    return yaml.safe_load((TEMPLATES / name).read_text(encoding="utf-8"))


def _fields(form: dict) -> dict[str, dict]:
    return {field["id"]: field for field in form["body"] if field["type"] != "markdown"}


def _required(field: dict) -> bool:
    return field.get("validations", {}).get("required", False)


def _text(form: dict) -> str:
    """Every text a reporter reads, in lower case."""
    parts = [form["name"], form["description"]]
    for field in form["body"]:
        attributes = field["attributes"]
        parts += [str(attributes.get(key, "")) for key in ("value", "label", "description")]
        parts += [
            option["label"] if isinstance(option, dict) else str(option)
            for option in attributes.get("options", [])
        ]
    return "\n".join(parts).lower()


@pytest.mark.parametrize("name", ["fehler.yml", "mail-nicht-erkannt.yml"])
def test_form_is_a_valid_german_issue_form(name):
    form = _load(name)
    assert set(form) <= {"name", "description", "title", "labels", "body"}
    assert form["name"] and form["description"] and isinstance(form["labels"], list)
    ids = [field["id"] for field in form["body"] if "id" in field]
    assert len(ids) == len(set(ids))
    for field in form["body"]:
        assert field["type"] in FIELD_TYPES
        if field["type"] == "markdown":
            assert field["attributes"]["value"].strip()
        else:
            assert field["id"].replace("_", "").isalnum() and field["attributes"]["label"]
    assert any(_required(field) for field in _fields(form).values())
    text = _text(form)
    assert "bitte" not in text and "erfolgreich" not in text
    assert "rohe" in text  # the rule about raw mails


def test_bug_form_asks_for_versions_carrier_and_diagnostics():
    form = _load("fehler.yml")
    fields = _fields(form)
    assert list(fields) == [
        "version", "ha_version", "carrier", "happened", "expected", "diagnostics", "logs",
    ]
    assert [fields[key]["type"] for key in fields] == [
        "input", "input", "dropdown", "textarea", "textarea", "textarea", "textarea",
    ]
    for key in ("version", "ha_version", "carrier", "happened", "expected"):
        assert _required(fields[key]), key
    assert not _required(fields["logs"])
    assert "optional" in fields["logs"]["attributes"]["label"].lower()
    assert fields["logs"]["attributes"]["render"] == "text"
    assert "render" not in fields["diagnostics"]["attributes"]  # files can be dropped in
    assert fields["carrier"]["attributes"]["options"] == [
        "DHL", "DPD", "GLS", "Hermes", "UPS", "Amazon", "eBay", "AliExpress", "17track", "anderer",
    ]
    hint = fields["diagnostics"]["attributes"]["description"]
    assert (
        "Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen" in hint
    )


def test_mail_form_requires_the_zip_and_both_confirmations():
    form = _load("mail-nicht-erkannt.yml")
    assert form["name"] == "Mail wird nicht erkannt"
    fields = _fields(form)
    assert list(fields) == ["sender", "country", "shop", "expected", "mails", "privacy"]
    for key in ("sender", "country", "shop", "expected", "mails"):
        assert _required(fields[key]), key
    assert "paket-tracker-beispiele.zip" in fields["mails"]["attributes"]["description"]
    assert "render" not in fields["mails"]["attributes"]
    assert fields["privacy"]["type"] == "checkboxes"
    assert fields["privacy"]["attributes"]["options"] == [
        {"label": "Ich habe keine rohen Mails angehängt", "required": True},
        {"label": "Ich habe die anonymisierten Dateien selbst durchgelesen", "required": True},
    ]
    text = _text(form)
    assert "anonymize_mail.py" in text and "nie privat" in text


def test_blank_issues_are_off_and_the_contact_link_leads_to_the_readme():
    config = _load("config.yml")
    assert config["blank_issues_enabled"] is False
    [link] = config["contact_links"]
    assert link["url"] == f"{REPO}#beispielmails-einreichen"
    assert link["name"] and link["about"]
    assert "\n## Beispielmails einreichen\n" in README  # the anchor exists
    assert sorted(path.name for path in TEMPLATES.iterdir()) == [
        "config.yml", "fehler.yml", "mail-nicht-erkannt.yml",
    ]

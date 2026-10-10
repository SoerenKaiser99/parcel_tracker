"""The documentation site (MkDocs, docs/): it only names what the code really has."""

import re
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
COMPONENT = ROOT / "custom_components" / "parcel_tracker"
PAGES = sorted(DOCS.glob("*.md"))
TEXTS = {page.name: page.read_text(encoding="utf-8") for page in PAGES}

SENSOR_PY = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
CALENDAR_PY = (COMPONENT / "calendar.py").read_text(encoding="utf-8")
CONST_PY = (COMPONENT / "const.py").read_text(encoding="utf-8")
COORDINATOR_PY = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
SERVICES = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))

# What the code offers, read from the code.
ENTITIES = set(re.findall(r'"((?:sensor|calendar)\.paket[a-z0-9_]*)"', SENSOR_PY + CALENDAR_PY))
SERVICE_NAMES = {f"parcel_tracker.{name}" for name in SERVICES}
EVENT = re.search(r'EVENT_STATUS_CHANGED = "([a-z_]+)"', CONST_PY).group(1)
# The fields of the status event, as coordinator._announce fires them.
EVENT_FIELDS = set(
    re.findall(r'^\s+"([a-z_]+)": ', COORDINATOR_PY.split("EVENT_STATUS_CHANGED,\n", 2)[2]
               .split("self._notify(parcel, old)")[0], re.M)
)
# Names with our prefix that are no entity, service or event.
NOT_AN_ID = {"parcel_tracker.zip"}
# Invented numbers the README and the demo use as well; every other long digit run in
# the docs has to be made of 9s and 0s.
SYNTHETIC_NUMBERS = {
    "00340999999999999901",
    "00340999999999999911",
    "990000000001",
}

FENCE = re.compile(r"^([ \t]*)```yaml[^\n]*\n(.*?)^\1```[ \t]*$", re.M | re.S)


def _nav_files(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        node = list(node.values())
    return [name for item in node for name in _nav_files(item)]


def _yaml_blocks() -> list[tuple[str, str]]:
    return [
        (name, textwrap.dedent(match.group(2)))
        for name, text in TEXTS.items()
        for match in FENCE.finditer(text)
    ]


def test_the_code_names_what_this_test_expects():
    assert ENTITIES >= {
        "sensor.pakete_heute", "sensor.pakete_unterwegs", "sensor.pakete_moeglich",
        "sensor.pakete_zugestellt_heute", "sensor.pakete_abholbereit",
        "sensor.paket_tracker_17track_kontingent", "calendar.pakete",
    }
    assert EVENT == "parcel_tracker_status_changed"
    assert EVENT_FIELDS == {
        "entry_id", "number", "name", "carrier", "carrier_name", "old_status", "new_status",
        "eta_date", "eta_from", "eta_to", "location", "assumed",
    }


def test_every_page_of_the_navigation_exists_and_every_page_is_in_it():
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    assert config["docs_dir"] == "docs"
    assert config["site_url"] == "https://soerenkaiser99.github.io/parcel_tracker/"
    files = _nav_files(config["nav"])
    assert len(files) == len(set(files)) == 12
    for name in files:
        assert (DOCS / name).is_file(), name
    assert set(files) == set(TEXTS)
    hook = ROOT / config["hooks"][0]
    assert hook.is_file()
    # The hook rewrites exactly the tag the demo page carries.
    tag = re.search(r'CARD = "([^"]+)"', hook.read_text(encoding="utf-8")).group(1)
    assert (ROOT / tag).is_file()
    assert f'<script src="../../{tag}"></script>' in (DOCS / "demo" / "index.html").read_text(
        encoding="utf-8"
    )


def test_every_yaml_block_parses():
    blocks = _yaml_blocks()
    assert len(blocks) >= 25
    for name, block in blocks:
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as err:  # pragma: no cover - the message is the point
            raise AssertionError(f"{name}: {err}\n{block}") from err
        assert isinstance(data, dict), (name, block)


def test_recipes_are_automations_in_the_current_syntax_or_cards():
    blocks = [yaml.safe_load(block) for name, block in _yaml_blocks() if name == "rezepte.md"]
    automations = [b for b in blocks if "triggers" in b]
    assert len(automations) >= 7
    for automation in automations:
        assert "actions" in automation and "alias" in automation
        assert not {"trigger", "action", "condition", "platform"} & automation.keys()
        for trigger in automation["triggers"]:
            assert "trigger" in trigger and "platform" not in trigger
            assert trigger["trigger"] != "device"  # device ids are picked in the editor
    assert len(re.findall(r"^## \d+\. ", TEXTS["rezepte.md"], re.M)) == 10
    assert TEXTS["rezepte.md"].count("**Anpassen:**") == 10
    assert TEXTS["rezepte.md"].count("**Wofür:**") == 10


def test_entities_services_and_the_event_exist_in_the_code():
    pattern = re.compile(
        r"(?<![\w./-])(sensor\.pakete_\w+|sensor\.paket_tracker_\w+|calendar\.pakete\w*"
        r"|parcel_tracker\.\w+|parcel_tracker_[a-z_]+)"
    )
    allowed = ENTITIES | SERVICE_NAMES | {EVENT} | NOT_AN_ID
    seen = set()
    for name, text in TEXTS.items():
        for found in pattern.findall(text):
            assert found in allowed, f"{name}: {found}"
            seen.add(found)
    # The reference names all of them.
    assert seen >= ENTITIES | SERVICE_NAMES | {EVENT}


def test_event_fields_and_attributes_exist_in_the_code():
    fields, attributes = set(), set()
    for text in TEXTS.values():
        fields |= set(re.findall(r"trigger\.event\.data\.([a-z_]+)", text))
        attributes |= set(re.findall(r"state_attr\([^,()]+,\s*'([a-z_0-9]+)'\)", text))
        attributes |= set(re.findall(r"is_state_attr',\s*'([a-z_0-9]+)'", text))
    assert fields and fields <= EVENT_FIELDS, fields - EVENT_FIELDS
    assert len(attributes) >= 8
    for attribute in attributes:
        assert f'"{attribute}": ' in SENSOR_PY, attribute


def test_no_page_says_bitte_or_erfolgreich():
    for name, text in TEXTS.items():
        found = re.findall(r"\b(bitte|erfolgreich\w*)\b", text, re.I)
        assert not found, f"{name}: {found}"


def test_no_page_carries_a_real_looking_number():
    runs = []
    for name, text in TEXTS.items():
        for run in re.findall(r"\d{10,}", text):
            runs.append(run)
            assert run in SYNTHETIC_NUMBERS or set(run) <= set("90"), f"{name}: {run}"
    assert runs


def test_site_is_built_and_deployed_by_its_own_workflow():
    workflow = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
    for text in (
        "mkdocs build --strict", "actions/upload-pages-artifact", "actions/deploy-pages",
        "pages: write", "id-token: write", "name: github-pages", "workflow_dispatch",
        "pull_request", "requirements-docs.txt",
    ):
        assert text in workflow, text
    pins = (ROOT / "requirements-docs.txt").read_text(encoding="utf-8").split()
    assert [pin.split("==")[0] for pin in pins] == ["mkdocs", "mkdocs-material"]
    assert all(re.fullmatch(r"[a-z-]+==\d+(\.\d+)+", pin) for pin in pins)
    assert "site/" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()


def test_readme_links_to_the_site():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    intro = readme.split("## Warum?")[0]
    assert "**Ausführliche Anleitung mit Rezepten:**" in intro
    assert intro.count("https://soerenkaiser99.github.io/parcel_tracker/") >= 2
    assert "img.shields.io/badge/Doku-" in intro.splitlines()[2]

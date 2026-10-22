"""The README is the landing page: what it is, how to install it, where the details are.

The details live on the documentation site (docs/*.md); tests/test_docs_content.py pins
them there. This file pins what the README itself has to say, the demo page, the images
and hacs.json.
"""

import re
import struct
import unicodedata
from pathlib import Path

import yaml

from custom_components.parcel_tracker.links import _PAGES

ROOT = Path(__file__).parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
DOCS = ROOT / "docs"
DEMO = DOCS / "demo"
IMAGES = ("karte-hell.png", "karte-dunkel.png", "karte-detail.png")
RAW = "https://raw.githubusercontent.com/SoerenKaiser99/parcel_tracker/main"
SITE = "https://soerenkaiser99.github.io/parcel_tracker/"
REPO = "https://github.com/SoerenKaiser99/parcel_tracker"


def _section(title: str) -> str:
    return README.split(f"\n## {title}\n")[1].split("\n## ")[0]


def _titles() -> list[str]:
    return [line[3:] for line in README.splitlines() if line.startswith("## ")]


def _nav_files(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        node = list(node.values())
    return [name for item in node for name in _nav_files(item)]


def _slug(heading: str) -> str:
    """The anchor MkDocs gives a heading (Python-Markdown's default slugify)."""
    text = re.sub(r"\{[^}]*\}\s*$", "", heading)  # attribute lists
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def _anchors(markdown: str) -> set[str]:
    return {_slug(line.lstrip("#").strip()) for line in markdown.splitlines()
            if re.match(r"#{1,6} ", line)}


def _site_links() -> list[tuple[str, str]]:
    """Every link of the README into the documentation site, as (path, anchor)."""
    links = re.findall(re.escape(SITE) + r"([^)\s#\"]*)(?:#([^)\s\"]*))?", README)
    assert len(links) >= 30
    return links


# ----- the landing page -----
def test_readme_is_a_landing_page():
    lines = README.splitlines()
    assert 70 <= len(lines) < 140, len(lines)
    assert lines[0] == "# Paket Tracker"
    assert _titles() == [
        "Warum?",
        "Was es kann",
        "Für Deutschland gebaut",
        "Installation",
        "Anleitung",
        "Mithelfen und Fehler melden",
        "Fehler melden",
        "Beispielmails einreichen",
        "Datenschutz",
        "Markenhinweis",
        "Roadmap & Status",
        "English summary",
    ]
    # No third-level sections: the details are on the site.
    assert not [line for line in lines if line.startswith("###")]


def test_readme_keeps_its_three_badges():
    badges = README.splitlines()[2]
    assert badges.count("https://img.shields.io/") == 3
    for text in (
        f"[![Version](https://img.shields.io/github/v/release/SoerenKaiser99/parcel_tracker"
        f"?label=Version)]({REPO}/releases/latest)",
        f"[![Downloads](https://img.shields.io/github/downloads/SoerenKaiser99/parcel_tracker"
        f"/total?label=Downloads)]({REPO}/releases)",
        f"[![Doku](https://img.shields.io/badge/Doku-Anleitung-blue)]({SITE})",
    ):
        assert text in badges, text


def test_readme_links_into_the_site_only_to_pages_and_anchors_that_exist():
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    assert config["site_url"] == SITE
    pages = {name[:-3]: name for name in _nav_files(config["nav"])}
    seen = set()
    for path, anchor in _site_links():
        if path == "":  # the start page
            assert not anchor
            continue
        if path == "demo/index.html":  # copied as it is, not a page of the navigation
            assert (DOCS / path).is_file() and not anchor
            continue
        assert path.endswith("/"), path  # directory URLs, as the site serves them
        name = path[:-1]
        assert name in pages, path
        seen.add(name)
        if anchor:
            text = (DOCS / pages[name]).read_text(encoding="utf-8")
            assert anchor in _anchors(text), (path, anchor)
    # Every chapter of the site is linked, the start page through the site root.
    assert seen == set(pages) - {"index"}


def test_readme_chapter_list_names_every_chapter_once():
    section = _section("Anleitung")
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    chapters = [name[:-3] for name in _nav_files(config["nav"]) if name != "index.md"]
    lines = [line for line in section.splitlines() if line.strip()]
    assert len(lines) == len(chapters) == 12
    for line, chapter in zip(lines, chapters, strict=True):
        assert re.fullmatch(rf"- \[[^\]]+\]\({re.escape(SITE)}{chapter}/\) – \S.*", line), line


def test_readme_has_no_relative_links():
    """HACS renders the README inside Home Assistant, where relative links break."""
    assert not re.search(r"\]\((?!https://|#)", README)
    assert 'src="docs/' not in README and 'href="' not in README
    assert not re.search(r"docs/[\w/-]+\.md", README)
    # (an absolute link to a file of the repository, such as the CHANGELOG, is fine)
    assert not re.search(r"\]\((?!https://)[^)]*\.md[)#]", README)
    # Anchors inside the README lead to headings it has.
    internal = re.findall(r"\]\(#([^)]+)\)", README)
    assert internal == ["beispielmails-einreichen"]
    for anchor in internal:
        assert anchor in _anchors(README), anchor


def test_readme_keeps_the_sections_that_issues_and_forum_posts_link_to():
    """…/parcel_tracker#beispielmails-einreichen and #fehler-melden stay valid."""
    assert {"beispielmails-einreichen", "fehler-melden"} <= _anchors(README)
    for template in ("config.yml", "mail-nicht-erkannt.yml"):
        text = (ROOT / ".github" / "ISSUE_TEMPLATE" / template).read_text(encoding="utf-8")
        assert f"{REPO}#beispielmails-einreichen" in text, template
    samples = _section("Beispielmails einreichen")
    for text in (
        "**Nie rohe Mails hochladen.**",
        "**Nie Mails privat an den Autor schicken.**",
        "ausschließlich anonymisierte Mails",
        "`Paket-Tracker-Nicht-erkannt`",
        "`anonymize_mail.py`",
        f"[Beispielmails einreichen]({SITE}hilfe/#beispielmails-einreichen)",
    ):
        assert text in samples, text
    assert 3 <= len([line for line in samples.splitlines() if line.strip()]) <= 5
    bugs = _section("Fehler melden")
    for text in (
        "**Einstellungen → Geräte & Dienste → Paket Tracker → ⋮ → Diagnose herunterladen**",
        "issues/new?template=fehler.yml",
        f"[Fehler melden]({SITE}hilfe/#fehler-melden)",
        "[Beispielmails einreichen](#beispielmails-einreichen)",
    ):
        assert text in bugs, text
    assert len([line for line in bugs.splitlines() if line.strip()]) == 1


def test_readme_report_sections_follow_the_section_on_helping():
    titles = _titles()
    at = titles.index("Mithelfen und Fehler melden")
    assert titles[at + 1 : at + 3] == ["Fehler melden", "Beispielmails einreichen"]
    assert titles.index("Beispielmails einreichen") < titles.index("Roadmap & Status")
    helping = _section("Mithelfen und Fehler melden")
    assert f"]({SITE}mithelfen/)" in helping and f"]({SITE}hilfe/)" in helping


def test_readme_installs_through_hacs_in_three_steps():
    section = _section("Installation")
    steps = [line for line in section.splitlines() if re.match(r"\d\. ", line)]
    assert [step[0] for step in steps] == ["1", "2", "3"]
    for text in (
        "[HACS](https://hacs.xyz/docs/use/)",
        "[![Repository in HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)]"
        "(https://my.home-assistant.io/redirect/hacs_repository/?owner=SoerenKaiser99"
        "&repository=parcel_tracker&category=integration)",
        "**Benutzerdefinierte Repositories**",
        f"`{REPO}`",
        "Typ **Integration**",
        "**Herunterladen**",
        "Home Assistant neu starten",
        "**Einstellungen → Geräte & Dienste → Integration hinzufügen**",
        "Seite einmal neu laden",
        "Karte „Paket Tracker“",
        f"[Installation]({SITE}installation/)",
    ):
        assert text in section, text
    # The same button and the same steps as on the site.
    install = (DOCS / "installation.md").read_text(encoding="utf-8")
    assert "redirect/hacs_repository/?owner=SoerenKaiser99&repository=parcel_tracker" in install
    assert "**Benutzerdefinierte Repositories**" in install


def test_readme_lists_what_it_can_do_with_a_link_per_line():
    section = _section("Was es kann")
    lines = [line for line in section.splitlines() if line.strip()]
    assert 8 <= len(lines) <= 10
    for line in lines:
        pattern = rf"- \*\*[^*]+\*\*.* – \[[^\]]+\]\({re.escape(SITE)}[^)]+\)"
        assert re.fullmatch(pattern, line), line
    for text in (
        "- **E-Mail-Import** (optional)",
        "- **Karte** `custom:parcel-tracker-card`",
        "- **Benachrichtigungen** (optional)",
        "- **Namen ausblenden** (optional)",
        f"[Benachrichtigungen]({SITE}benachrichtigungen/)",
        f"[Namen ausblenden]({SITE}datenschutz/#namen-ausblenden)",
        "`parcel_tracker.add_parcel`, `remove_parcel`, `rename_parcel`, `mark_delivered`,"
        " `refresh`, `track_17track`",
        "`parcel_tracker_status_changed`",
        "`sensor.pakete_heute`",
        "`calendar.pakete`",
    ):
        assert text in section, text


def test_readme_names_only_services_and_entities_the_code_has():
    services = yaml.safe_load(
        (ROOT / "custom_components" / "parcel_tracker" / "services.yaml").read_text("utf-8")
    )
    lines = _section("Was es kann").splitlines()
    line = next(item for item in lines if item.startswith("- **Dienste**"))
    found = re.findall(r"`([a-z_.0-9]+)`", line)
    named = [name.removeprefix("parcel_tracker.") for name in found]
    assert sorted(named) == sorted(services)
    sensor_py = (ROOT / "custom_components" / "parcel_tracker" / "sensor.py").read_text("utf-8")
    calendar_py = (ROOT / "custom_components" / "parcel_tracker" / "calendar.py").read_text("utf-8")
    assert '"sensor.pakete_heute"' in sensor_py and '"calendar.pakete"' in calendar_py


def test_readme_privacy_in_short():
    section = _section("Datenschutz")
    for text in (
        "Sendungsnummern gehen nur an den jeweiligen Carrier",
        "die PLZ nur an DHL und GLS",
        "an 17track geht eine Nummer nur auf ausdrücklichen Wunsch",
        "weder in Attributen noch im Log",
        f"[Datenschutz]({SITE}datenschutz/)",
    ):
        assert text in section, text
    assert len([line for line in section.splitlines() if line.strip()]) == 1
    english = _section("English summary")
    assert "Tracking numbers are sent only to the matching carrier" in english
    assert "the postcode is sent only to DHL and GLS" in english


def test_readme_roadmap_and_status():
    section = _section("Roadmap & Status")
    assert len([line for line in section.splitlines() if line.strip() and line != "---"]) == 1
    assert f"[Roadmap & Status]({SITE}stand/)" in section
    assert "Roadmap & Status" in README.split("## English summary")[1]


def test_readme_english_summary_is_short_and_links_to_the_site():
    english = _section("English summary")
    assert len([line for line in english.splitlines() if line.strip()]) == 1
    assert len(english.split()) < 220
    for text in (
        "Home Assistant custom integration",
        "Install it through HACS as a custom repository",
        "`custom:parcel-tracker-card`",
        "`parcel_tracker_status_changed`",
        "device triggers for automations without YAML",
        "push notifications",
        "classic notify services such as Pushover",
        "blueprint",
        "the mail import reads German mails only",
        f"]({SITE})",
        f"]({SITE}stand/)",
    ):
        assert text in english, text


def test_readme_says_it_is_built_for_germany():
    intro = README.split("## Installation")[0]
    assert "für Deutschland gebaut" in intro
    for text in (
        "DHL (offizielle API, weltweit)",
        "UPS (offizielle API)",
        "jeder Carrier über 17track",
        "nur deutsche Mails",
        "amazon.de",
    ):
        assert text in intro, text
    assert "built for Germany" in README


def test_readme_english_summary_names_the_country_setting():
    english = README.split("## English summary")[1]
    assert english.count("country setting") == 1
    assert "Austria" in english and "Switzerland" in english


def test_readme_german_texts_avoid_banned_words():
    german = README.split("## English summary")[0].lower()
    assert "bitte" not in german and "erfolgreich" not in german


def test_readme_brand_note_names_the_dhl_badge():
    section = _section("Markenhinweis")
    assert "DHL als gelbes Schild mit rotem Schriftzug" in section


# ----- screenshots, demo page, images -----
def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", data[16:24])


def test_readme_shows_the_card_screenshots_at_the_top():
    intro = README.split("## Was es kann")[0]
    for name in IMAGES:
        path = ROOT / "docs" / "images" / name
        assert path.is_file(), name
        assert path.stat().st_size < 400_000, name
        width, height = _png_size(path)
        assert width >= 900 and height > width, name
        # absolute: HACS shows the README without the repository around it
        assert f'src="{RAW}/docs/images/{name}"' in intro, name
    assert 'src="docs/' not in README
    alts = re.findall(r'<img [^>]*alt="([^"]+)"', intro)
    assert len(alts) == len(IMAGES)
    assert all("Karte" in alt for alt in alts)
    assert "hellen Design" in intro and "dunklen Design" in intro and "aufgeklappten" in intro
    assert "geöffneter Eingabe" in intro  # the detail screenshot shows the open form
    # v0.3.38: the links are icons behind the numbers; the alt text says so, not "Link".
    detail_alt = next(alt for alt in alts if "aufgeklappten DHL-Paket" in alt)
    assert "Sendungsnummer mit dem Symbol „Sendung verfolgen“" in detail_alt
    assert "„Erhalten“" in detail_alt
    assert "Link" not in detail_alt
    assert "Die Bilder zeigen erfundene Pakete" in intro
    # v0.3.40: the head shows the gift mode switch, one parcel is a gift.
    light_alt = next(alt for alt in alts if "hellen Design" in alt)
    assert "Schalter „Geschenkmodus“" in light_alt and "Geschenkbox" in light_alt
    # The demo page, on the site (docs/demo/ is published as it is).
    assert f"({SITE}demo/index.html)" in intro
    assert (DEMO / "index.html").is_file()


def test_readme_screenshots_show_all_three_badges_worth_of_parcels():
    intro = README.split("## Was es kann")[0]
    assert "zwölf Pakete" in intro and "elf Pakete" not in intro
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    assert len(re.findall(r'^    parcel\("', js, re.M)) == 12
    assert "delivered_today:" in js and "delivered_today_count:" in js


def test_readme_says_why_right_after_intro_and_screenshots():
    titles = _titles()
    assert titles[:2] == ["Warum?", "Was es kann"]
    assert README.index("karte-dunkel.png") < README.index("\n## Warum?\n")
    section = _section("Warum?")
    lines = [line for line in section.splitlines() if line.strip()]
    assert 5 <= len(lines) <= 8
    for text in (
        "„Kommt heute ein Paket, und wann?“",
        "an einer Stelle",
        "statt in fünf Apps",
        "Versandmails",
        "Amazons eigene Lieferungen",
        "keine öffentliche Sendungsverfolgung",
        "Benachrichtigung",
        "ohne eigene Automation",
        "Automationen",
        "Kalender",
        "„Pakete heute“",
        "kein Cloud-Konto",
        "kein fremder Tracking-Dienst",
        "Zugangsdaten bleiben in Home Assistant",
        "nur ein eigenes Paket-Postfach",
        "Open Source",
        "deutsche Carrier",
    ):
        assert text in section, text
    assert "Ich " in section  # the owner's own words
    english = README.split("## English summary")[1]
    assert "Why:" in english and "no cloud account" in english
    assert "third-party tracking service" in english


def test_readme_intro_names_what_is_tracked():
    intro = README.split("## Warum?")[0]
    for text in ("DHL, DPD, GLS, Hermes und (optional) UPS", "Amazon-", "eBay-", "AliExpress-",
                 "Eventim-Tickets mit Postversand", "aus E-Mails", "Dashboard-Karte"):
        assert text in intro, text
    assert "notify_url" not in README and "nicht beim Start" not in README


def test_demo_page_loads_the_real_card():
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    card = "../../custom_components/parcel_tracker/frontend/parcel-tracker-card.js"
    assert f'<script src="{card}"></script>' in html
    assert (DEMO / card).resolve().is_file()
    assert '<script src="demo.js"></script>' in html
    assert "erfunden" in html
    assert not re.search(r"https?://", html), "the demo page loads nothing from the network"


def test_demo_page_shows_one_parcel_per_carrier_and_the_fixed_sensors():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    for carrier in (
        "dhl", "dpd", "gls", "hermes", "ups", "amazon", "ebay", "aliexpress", "other"
    ):
        assert re.search(rf'parcel\("[a-z_]+", "{carrier}", ', js), carrier
    for text in (
        '"sensor.pakete_heute"',
        '"sensor.paket_tracker_17track_kontingent", "187"',
        'location_source: "17track"',
        'shipping_carrier_hint: "hermes"',
        "has_delivery_code: true",
        '"parcel_tracker/delivery_code"',
        "delivered_at:",
        'last_error: "unavailable"',
        'last_error: "missing_key"',
        "nicht ausgeführt",
        'parcel("awaiting_pickup", ',
        "pickup_point:",
        'tracking_ref: "00340999999999999914", tracking_carrier: "dhl"',
        '"Abflugregion verlassen"',
        '"Zollabfertigung beendet"',
    ):
        assert text in js, text
    # The only addresses are the carriers' tracking pages, exactly as links.py builds them.
    pages = {carrier: page.format("") for carrier, page in _PAGES.items()}
    assert dict(re.findall(r'^    (\w+): "(https?://[^"]*)",$', js, re.M)) == pages
    assert sorted(re.findall(r'https?://[^"]*', js)) == sorted(pages.values())
    # Dates are computed from today: no fixed calendar date in the file.
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", js)


def test_demo_page_contains_only_synthetic_numbers():
    """Every long digit run is a 9-style placeholder (e.g. 00340999999999999901)."""
    files = sorted(p for p in DEMO.rglob("*") if p.is_file())
    assert {p.name for p in files} >= {"index.html", "demo.js"}
    runs = []
    for path in files:
        runs += re.findall(r"\d{8,}", path.read_text(encoding="utf-8"))
    assert len(runs) >= 10
    for run in runs:
        assert "9999999" in run and set(run[:-2]) <= set("0349"), run


def test_demo_page_knows_the_add_form_views():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    for text in ("?add=open", "?add=always", "?add=never", "?hint=1", "integration_version:"):
        assert text in js, text
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    assert 'href="?add=open"' in html and 'href="?add=always"' in html


def test_demo_page_knows_the_show_option():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    for text in (
        "?show=active", "?show=today", "?show=today_possible", "?empty=1", "?edit=1",
        '"sensor.pakete_unterwegs"', '"sensor.pakete_moeglich"',
        '"sensor.pakete_zugestellt_heute"',
    ):
        assert text in js, text
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    assert 'href="?show=active&amp;empty=1"' in html


def test_demo_page_has_a_dhl_parcel_without_key_and_without_result():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    block = re.search(r'parcel\("unknown", "dhl", [^)]*\{([^}]*)\}\)', js)
    assert block and 'last_error: "missing_key"' in block.group(1)
    assert "events" not in block.group(1) and "eta_days" not in block.group(1)


def test_demo_page_can_show_the_note_after_adding():
    js = (DEMO / "demo.js").read_text(encoding="utf-8")
    for text in ("?added=missing_key", "?added=ups", 'last_error: "missing_key"'):
        assert text in js, text
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    assert 'href="?added=missing_key"' in html


def test_brand_icons_are_shipped_where_home_assistant_looks_for_them():
    """HA 2026.3+ serves custom_components/<domain>/brand/icon.png and icon@2x.png."""
    brand = ROOT / "custom_components" / "parcel_tracker" / "brand"
    assert _png_size(brand / "icon.png") == (256, 256)
    assert _png_size(brand / "icon@2x.png") == (512, 512)


# ----- repository -----
def test_no_planning_docs_in_the_repo():
    assert not (ROOT / "docs" / "superpowers").exists()


def test_hacs_is_not_told_about_the_blueprints_folder():
    """HACS installs custom_components/parcel_tracker only; the blueprint is imported
    through its link, so hacs.json stays as it is."""
    import json

    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert set(hacs) == {
        "name",
        "homeassistant",
        "render_readme",
        "zip_release",
        "filename",
        "country",
    }
    # Built for these countries (carriers, mails and the card are German).
    assert hacs["country"] == ["DE", "AT", "CH"]


def test_hacs_installs_from_the_release_zip():
    """zip_release makes HACS fetch the release asset, which GitHub counts as a
    download. Every release from v0.3.6 on needs parcel_tracker.zip attached
    (scripts/build_release_zip.sh)."""
    import json

    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "parcel_tracker.zip"
    assert hacs["name"] == "Paket Tracker"
    assert hacs["homeassistant"] == "2025.10.0"
    assert hacs["render_readme"] is True

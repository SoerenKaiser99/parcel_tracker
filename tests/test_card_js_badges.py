"""Card: the three badges in the head and the German status labels (run in Node)."""

import json
import re
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD
from custom_components.parcel_tracker.models import ParcelStatus

NODE = shutil.which("node")
SOURCE = BUNDLED_CARD.read_text(encoding="utf-8")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
// A tiny stand-in for the DOM: elements remember what the card writes into them.
const fakeEl = () => {
  const el = {
    hidden: false, value: "", innerHTML: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {}, children: [], dataset: {},
    addEventListener(name, fn) { el.listeners[name] = fn; },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    focus() {},
    contains() { return false; },
    appendChild(child) { el.children.push(child); },
    querySelector(sel) {
      if (sel === 'option[value="other"]') return null;
      return (el.kids[sel] ||= fakeEl());
    },
    querySelectorAll() { return []; },
    insertAdjacentHTML() {},
  };
  return el;
};
const sandbox = {
  HTMLElement: class {},
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {},
  document: { createElement: () => fakeEl() },
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(process.argv[1], "utf8")
    + "\n;globalThis.__label = stateLabel; globalThis.__html = badgesHtml;"
    + "globalThis.__badges = todayBadges;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];

function mount(hass) {
  const card = new Card();
  const els = {};
  const root = {
    innerHTML: "", activeElement: null,
    getElementById(id) { return (els[id] ||= fakeEl()); },
  };
  card.attachShadow = () => root;
  card.setConfig({});
  card.hass = hass;
  return { card, els, root };
}

// A Home Assistant whose user speaks English: its own labels for the states are English.
const ENGLISH = { pre_transit: "Announced", in_transit: "In transit",
  at_delivery_depot: "At delivery depot", out_for_delivery: "Out for delivery",
  awaiting_pickup: "Ready for pickup", delivered: "Delivered", exception: "Problem",
  unknown: "Unknown" };
const STATES = process.argv[2].split(",");
function englishHass(today) {
  const states = {};
  const entities = {};
  const add = (id, state, attributes) => {
    states[id] = { entity_id: id, state, attributes, last_updated: "t" };
    entities[id] = { platform: "parcel_tracker" };
  };
  STATES.forEach((state, i) => add(`sensor.paket_${i}`, state,
    { number: `N${i}`, name: `Paket ${i}`, carrier: "amazon", carrier_name: "Amazon" }));
  add("sensor.paket_dhl", "pre_transit",
    { number: "D1", name: "DHL-Paket", carrier: "dhl", carrier_name: "DHL" });
  if (today) add("sensor.pakete_heute", today.state, today.attributes);
  return {
    states, entities, language: "en", locale: { language: "en" },
    selectedLanguage: "en", config: { language: "en" },
    localize: (key) => key,
    formatEntityState: (st) => ENGLISH[st.state] || st.state,
  };
}
const subline = (item) => (/<div class="sub">([^<]*)<\/div>/.exec(item.innerHTML) || [])[1];

const out = {};
const st = (state, carrier) => ({ state, attributes: { carrier } });
out.labels = Object.fromEntries(STATES.map((s) => [s, sandbox.__label(st(s, "dhl"))]));
out.shop = { amazon: sandbox.__label(st("pre_transit", "amazon")),
  ebay: sandbox.__label(st("pre_transit", "ebay")),
  amazonLater: sandbox.__label(st("in_transit", "amazon")) };
out.odd = { other: sandbox.__label(st("returned", "dhl")),
  unavailable: sandbox.__label(st("unavailable", "dhl")),
  proto: sandbox.__label(st("constructor", "dhl")) };

const all = mount(englishHass({ state: "1",
  attributes: { possible_count: 2, delivered_today_count: 3 } }));
out.sublines = Object.fromEntries(
  all.els.list.children.map((item) => [/data-number="([^"]+)"/.exec(item.innerHTML)[1],
    subline(item)]));
out.head = all.els.today.innerHTML;
out.headText = all.els.today.textContent;
out.oldSensor = mount(englishHass({ state: "1", attributes: {} })).els.today.innerHTML;
out.oldSensorPossible = mount(englishHass({ state: "0",
  attributes: { possible_count: 1 } })).els.today.innerHTML;
out.noSensor = mount(englishHass(null)).els.today.innerHTML;
out.template = all.root.innerHTML;
// A badge's text and title are escaped like everything else the card writes.
out.escaped = sandbox.__html([{ kind: "sure", text: "<1>", title: 'a"b' }]);
out.empty = sandbox.__html([]);
console.log(JSON.stringify(out));
"""

STATES = [s.value for s in ParcelStatus]
GERMAN = {
    "pre_transit": "Angekündigt",
    "in_transit": "Unterwegs",
    "at_delivery_depot": "Im Zustelldepot",
    "out_for_delivery": "In Zustellung",
    "awaiting_pickup": "Abholbereit",
    "delivered": "Zugestellt",
    "exception": "Problem",
    "unknown": "Unbekannt",
}
ENGLISH = (
    "Announced", "In transit", "At delivery depot", "Out for delivery", "Ready for pickup",
    "Delivered", "Unknown",
)


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD), ",".join(STATES)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(run.stdout)


def _badges(html):
    return re.findall(
        r'<span class="badge (\w+)" role="img" title="([^"]*)" aria-label="([^"]*)">([^<]*)</span>',
        html,
    )


def test_the_card_has_a_german_label_for_every_status(card):
    assert set(GERMAN) == set(STATES)
    assert card["labels"] == GERMAN


def test_the_german_labels_are_the_ones_of_the_german_translation():
    """One wording: the card's table and translations/de.json say the same."""
    path = BUNDLED_CARD.parents[1] / "translations" / "de.json"
    states = json.loads(path.read_text(encoding="utf-8"))["entity"]["sensor"]["parcel"]["state"]
    assert states == GERMAN


def test_shop_orders_read_ordered_only_before_shipping(card):
    assert card["shop"] == {"amazon": "Bestellt", "ebay": "Bestellt", "amazonLater": "Unterwegs"}


def test_a_state_the_card_does_not_know_reads_unknown(card):
    assert card["odd"] == {
        "other": "Unbekannt", "unavailable": "Unbekannt", "proto": "Unbekannt",
    }


def test_sublines_are_german_in_an_english_home_assistant(card):
    """A tester's card read "Amazon · Delivered": the label came from Home Assistant's
    translation for the user's language. The card is German-only, so it uses its own."""
    sublines = card["sublines"]
    assert sublines == {
        **{
            f"N{i}": f"Amazon · {'Bestellt' if state == 'pre_transit' else GERMAN[state]}"
            for i, state in enumerate(STATES)
        },
        "D1": "DHL · Angekündigt",
    }
    assert sublines[f"N{STATES.index('delivered')}"] == "Amazon · Zugestellt"
    for line in sublines.values():
        assert not any(word in line for word in ENGLISH), line


def test_the_card_does_not_ask_home_assistant_for_state_labels():
    assert "formatEntityState" not in SOURCE
    assert "localize" not in SOURCE


def test_head_shows_three_badges_in_order(card):
    assert _badges(card["head"]) == [
        ("sure", "Kommt heute sicher", "1 heute – Kommt heute sicher", "1 heute"),
        ("possible", "Lieferzeitraum schließt heute ein",
         "2 möglich – Lieferzeitraum schließt heute ein", "2 möglich"),
        ("delivered", "Heute zugestellt", "3 zugestellt – Heute zugestellt", "3 zugestellt"),
    ]
    assert card["head"].count("<span") == 3
    assert card["headText"] == ""  # no combined text next to the badges
    assert "·" not in card["head"]


def test_a_sensor_without_the_new_attributes_shows_the_old_badges(card):
    assert [b[3] for b in _badges(card["oldSensor"])] == ["1 heute"]
    assert [b[3] for b in _badges(card["oldSensorPossible"])] == ["0 heute", "1 möglich"]
    assert [b[3] for b in _badges(card["noSensor"])] == ["0 heute"]


def test_badge_html_is_escaped(card):
    assert card["escaped"] == (
        '<span class="badge sure" role="img" title="a&quot;b" '
        'aria-label="&lt;1&gt; – a&quot;b">&lt;1&gt;</span>'
    )
    assert card["empty"] == ""


def test_badges_sit_between_the_title_and_the_plus_and_wrap_as_a_group(card):
    template = card["template"]
    head = template[template.index('<div class="head">'):template.index('<div id="form"')]
    # title and badges share a wrapping box; the plus is its sibling and stays at the right
    assert re.search(
        r'<div class="lead">\s*<div class="title">.*?</div>\s*'
        r'<div class="badges" id="today"></div>\s*</div>\s*<button type="button" class="plus"',
        head, re.S,
    )
    css = template[template.index("<style>"):template.index("</style>")]
    lead = re.search(r"\.lead \{([^}]*)\}", css).group(1)
    assert "flex:1" in lead and "flex-wrap:wrap" in lead and "min-width:0" in lead
    badges = re.search(r"\.badges \{([^}]*)\}", css).group(1)
    assert "display:flex" in badges and "flex-wrap:wrap" in badges
    badge = re.search(r"\.badge \{([^}]*)\}", css).group(1)
    assert "white-space:nowrap" in badge  # a badge never breaks inside
    assert re.search(r"\.plus \{[^}]*flex:none", css)


def test_badge_colours_come_from_the_theme(card):
    css = card["template"]
    sure = re.search(r"\.badge\.sure \{([^}]*)\}", css).group(1)
    assert "background:var(--primary-color)" in sure and "color:var(--text-primary-color)" in sure
    possible = re.search(r"\.badge\.possible \{([^}]*)\}", css).group(1)
    assert "border-color:var(--divider-color)" in possible
    assert "color:var(--secondary-text-color)" in possible and "background" not in possible
    delivered = re.findall(r"\.badge\.delivered \{([^}]*)\}", css)
    assert len(delivered) == 2  # a plain fallback and the tint
    assert "var(--success-color)" in delivered[0] and "color-mix" not in delivered[0]
    assert "@supports (color:color-mix(in srgb, red 50%, blue))" in css
    assert "color-mix(in srgb, var(--success-color)" in delivered[1]
    # no fixed colours: the tint follows light and dark themes
    for rule in (sure, possible, *delivered):
        assert "#" not in rule and "rgb(" not in rule

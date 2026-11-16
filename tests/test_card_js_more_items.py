"""Card: the further items of a box ("(+2)") stand beside its name and are never cut, the
name is cut to the card's width (run in Node)."""

import json
import re
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
// A tiny stand-in for the DOM: elements remember what the card writes into them.
const fakeEl = () => {
  let html = "";
  const el = {
    hidden: false, value: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {}, children: [], dataset: {},
    get innerHTML() { return html; },
    set innerHTML(value) { html = value; el.children = []; },
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
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Card = defined["parcel-tracker-card"];

const blank = { days_until: null, events: [], status_text: null, progress: 0, last_error: null };
const states = {};
const entities = {};
[
  { number: "AMZ99990000000000001", name: "Beispiel-Maßband 5 m mit Gürtelclip (+2)" },
  { number: "AMZ99990000000000002", name: "Beispiel-Kabel 2 m" },
  { number: "AMZ99990000000000003", name: "Beispiel-Set (+zwei)" },
  { number: "AMZ99990000000000004", name: "<b>Fett</b> (+1)" },
].forEach((attributes, i) => {
  const id = `sensor.paket_${i}`;
  states[id] = { entity_id: id, state: "in_transit", last_updated: "t",
                 attributes: { ...blank, carrier: "amazon", ...attributes } };
  entities[id] = { platform: "parcel_tracker" };
});
const card = new Card();
const els = {};
const root = {
  innerHTML: "", activeElement: null,
  getElementById(id) { return (els[id] ||= fakeEl()); },
};
card.attachShadow = () => root;
card.setConfig({});
card.hass = { states, entities };
const rows = Object.fromEntries(els.list.children.map((item) => [
  /data-number="([^"]+)"/.exec(item.innerHTML)[1], item.innerHTML]));
const bare = vm.runInContext(
  `[bareName("Beispiel-Maßband (+2)"), bareName("Beispiel-Kabel"),
    bareName("Set (+zwei)")]`, sandbox);
console.log(JSON.stringify({ rows, template: root.innerHTML, bare }));
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, encoding="utf-8", check=True
    )
    return json.loads(done.stdout)


def _name(html: str) -> str:
    """What the row's name holds after its symbol."""
    [name] = re.findall(r'<span class="name">.*?(<span>.*?)</span></span>', html)
    return name + "</span>"


def test_the_further_items_stand_in_a_part_of_their_own(card):
    assert _name(card["rows"]["AMZ99990000000000001"]) == (
        '<span>Beispiel-Maßband 5 m mit Gürtelclip</span><span class="more">(+2)</span>'
    )


def test_a_name_without_further_items_is_one_part(card):
    assert _name(card["rows"]["AMZ99990000000000002"]) == "<span>Beispiel-Kabel 2 m</span>"
    # Only "(+" and digits are further items.
    assert _name(card["rows"]["AMZ99990000000000003"]) == "<span>Beispiel-Set (+zwei)</span>"


def test_both_parts_stay_escaped(card):
    assert _name(card["rows"]["AMZ99990000000000004"]) == (
        '<span>&lt;b&gt;Fett&lt;/b&gt;</span><span class="more">(+1)</span>'
    )


def test_the_name_is_cut_and_the_further_items_never_are(card):
    [name] = re.findall(r"\.name span \{([^}]*)\}", card["template"])
    [more] = re.findall(r"\.name \.more \{([^}]*)\}", card["template"])
    assert "text-overflow:ellipsis" in name
    assert "flex:none" in more and "overflow:visible" in more


def test_renaming_offers_the_name_without_the_further_items(card):
    # Saved as it is, nothing changes (the coordinator knows the name without them too).
    assert card["bare"] == ["Beispiel-Maßband", "Beispiel-Kabel", "Set (+zwei)"]
    source = BUNDLED_CARD.read_text(encoding="utf-8")
    [prefill] = re.findall(r'on\("rename", \(\) => \{(.*?)\}\);', source)
    assert "bareName((this._revealed.get(num) || {}).name" in prefill
    assert "bareName(a.name" in prefill

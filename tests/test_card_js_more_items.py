"""Card: the further items of a box ("(+2)", the attribute ``more_items``) stand beside its
name and are never cut, the name is cut to the card's width (run in Node)."""

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
  { number: "AMZ99990000000000001", name: "Beispiel-Maßband 5 m mit Gürtelclip", more_items: 2 },
  { number: "AMZ99990000000000002", name: "Beispiel-Kabel 2 m", more_items: 0 },
  // A name typed in that ends like further items: shown as it is.
  { number: "AMZ99990000000000003", name: "Team-Geschenk (+1)", more_items: 0 },
  { number: "AMZ99990000000000004", name: "<b>Fett</b>", more_items: 1 },
  // Anything but a count is none.
  { number: "AMZ99990000000000005", name: "Beispiel-Set", more_items: "2" },
  { number: "AMZ99990000000000006", name: "Beispiel-Set", more_items: -1 },
  // Without a name the number is shown, never with further items.
  { number: "AMZ99990000000000007", name: null, more_items: 3 },
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
console.log(JSON.stringify({ rows, template: root.innerHTML }));
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, encoding="utf-8", check=True
    )
    return json.loads(done.stdout)


def _name(card, number: str) -> str:
    """What the row's name holds after its symbol."""
    [name] = re.findall(r'<span class="name">.*?(<span>.*?)</span></span>', card["rows"][number])
    return name + "</span>"


def test_the_further_items_stand_in_a_part_of_their_own(card):
    assert _name(card, "AMZ99990000000000001") == (
        '<span>Beispiel-Maßband 5 m mit Gürtelclip</span><span class="more">(+2)</span>'
    )


def test_only_the_attribute_tells_further_items(card):
    assert _name(card, "AMZ99990000000000002") == "<span>Beispiel-Kabel 2 m</span>"
    # A name is never read for them: one typed in stays whole.
    assert _name(card, "AMZ99990000000000003") == "<span>Team-Geschenk (+1)</span>"
    for number in ("AMZ99990000000000005", "AMZ99990000000000006"):
        assert _name(card, number) == "<span>Beispiel-Set</span>"
    assert _name(card, "AMZ99990000000000007") == "<span>AMZ99990000000000007</span>"


def test_the_name_stays_escaped(card):
    assert _name(card, "AMZ99990000000000004") == (
        '<span>&lt;b&gt;Fett&lt;/b&gt;</span><span class="more">(+1)</span>'
    )


def test_the_name_is_cut_and_the_further_items_never_are(card):
    [name] = re.findall(r"\.name span \{([^}]*)\}", card["template"])
    [more] = re.findall(r"\.name \.more \{([^}]*)\}", card["template"])
    assert "text-overflow:ellipsis" in name
    assert "flex:none" in more and "overflow:visible" in more


def test_renaming_offers_the_name_as_it_is():
    # The attribute holds the name alone: saved as it is, nothing changes.
    source = BUNDLED_CARD.read_text(encoding="utf-8")
    [prefill] = re.findall(r'on\("rename", \(\) => \{(.*?)\}\);', source)
    assert '(this._revealed.get(num) || {}).name || "" : a.name || ""' in prefill

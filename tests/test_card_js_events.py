"""Card: every event of the history is its own block, a long text wraps indented (run in Node)."""

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
    // As in the DOM: writing innerHTML drops what was appended before.
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
  ["in_transit", { number: "E1", name: "Mit Verlauf", carrier: "dhl", events: [
    { timestamp: "2026-10-09T07:42:00+02:00", text: "In das Zustellfahrzeug geladen",
      location: "Würzburg" },
    { timestamp: "2026-10-08T11:20:00+02:00", text: "Abholung <b>erfolgreich</b>" },
  ] }],
  ["in_transit", { number: "N1", name: "Ohne Verlauf", carrier: "dpd" }],
].forEach(([state, attributes], i) => {
  const id = `sensor.paket_${i}`;
  states[id] = { entity_id: id, state, last_updated: "t", attributes: { ...blank, ...attributes } };
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
const rows = () => Object.fromEntries(els.list.children.map((item) => [
  /data-number="([^"]+)"/.exec(item.innerHTML)[1], item]));
const html = () => Object.fromEntries(
  Object.entries(rows()).map(([n, item]) => [n, item.innerHTML]));
const out = { closed: html() };
rows().E1.kids[".row-toggle"].listeners.click();
rows().N1.kids[".row-toggle"].listeners.click();
out.open = html();
out.template = root.innerHTML;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, encoding="utf-8", check=True
    )
    return json.loads(done.stdout)


def test_every_event_is_a_block_of_its_own(card):
    html = card["open"]["E1"]
    # Nothing but the blocks in the history: no line break between them.
    assert re.search(r'<div class="detail">(?:<div class="ev">[^<]*</div>){2}</div>', html)
    events = re.findall(r'<div class="ev">([^<]*)</div>', html)
    assert events[0].endswith(" · In das Zustellfahrzeug geladen · Würzburg")
    assert "<br>" not in html


def test_an_event_text_stays_escaped(card):
    assert "Abholung &lt;b&gt;erfolgreich&lt;/b&gt;</div>" in card["open"]["E1"]
    assert "<b>" not in card["open"]["E1"]


def test_a_wrapped_event_is_indented(card):
    # Hanging indent: the first line starts at the edge, every further line one step in.
    [rule] = re.findall(r"\.ev \{([^}]*)\}", card["template"])
    assert "padding-inline-start:1em" in rule
    assert "text-indent:-1em" in rule


def test_without_events_the_card_says_so(card):
    assert '<div class="detail">Noch keine Ereignisse</div>' in card["open"]["N1"]
    assert 'class="ev"' not in card["open"]["N1"]


def test_a_closed_row_shows_no_events(card):
    assert 'class="ev"' not in card["closed"]["E1"]

"""Card: a parcel in delivery without a date shows "Heute" and sorts first (v0.3.47, Node).

The sensor reports days_until 0 for it (eta_date stays empty); the card must not need a date.
"""

import json
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
const fakeEl = () => {
  let html = "";
  const el = {
    hidden: false, value: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {}, children: [], dataset: {},
    get innerHTML() { return html; },
    set innerHTML(value) { html = value; el.children = []; },
    addEventListener(name, fn) { el.listeners[name] = fn; },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    toggleAttribute() {}, focus() {}, contains() { return false; },
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
  window: {}, Event: class { constructor(n) { this.type = n; } },
  document: { createElement: () => fakeEl() },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Card = defined["parcel-tracker-card"];
const blank = { eta_date: null, eta_latest: null, eta_from: null, eta_to: null, days_until: null,
                events: [], status_text: null, progress: 0, last_error: null, gift: false,
                owner: null, carrier: "hermes" };
const P = [
  // Listed first on purpose: the parcel in delivery without a date must come before them.
  ["in_transit", { number: "H1", name: "Unterwegs", days_until: null }],
  ["in_transit", { number: "H2", name: "Morgen", days_until: 1, eta_date: "2026-11-02" }],
  ["out_for_delivery", { number: "H3", name: "Gestern", days_until: null }],
  ["out_for_delivery", { number: "H4", name: "Hermes", days_until: 0 }],
];
const states = {};
const entities = {};
P.forEach(([state, attributes], i) => {
  const id = `sensor.paket_${i}`;
  states[id] = { entity_id: id, state, last_updated: "t", attributes: { ...blank, ...attributes } };
  entities[id] = { platform: "parcel_tracker" };
});
const card = new Card();
const els = {};
card.attachShadow = () => ({ innerHTML: "", activeElement: null,
  getElementById(id) { return (els[id] ||= fakeEl()); } });
card.setConfig({});
card.dispatchEvent = () => {};
card.hass = { states, entities, user: { id: "u" }, callWS: async () => ({ viewer: false }),
              callService: async () => {} };
console.log(JSON.stringify(els.list.children.map((it) => it.innerHTML)));
"""


@pytest.fixture(scope="module")
def rows():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)],
        capture_output=True, encoding="utf-8", check=True,
    )
    return json.loads(done.stdout)


def _number(html: str) -> str:
    return html.split('data-number="')[1].split('"')[0]


def test_in_delivery_without_a_date_sorts_first(rows):
    assert [_number(r) for r in rows] == ["H4", "H2", "H1", "H3"]


def test_in_delivery_without_a_date_says_heute(rows):
    assert ">Heute<" in rows[0]
    assert "Noch kein Termin" not in rows[0]


def test_others_keep_their_text(rows):
    assert "Morgen" in rows[1]
    assert "Noch kein Termin" in rows[2]  # in transit without a date
    assert "Noch kein Termin" in rows[3]  # a stale parcel in delivery

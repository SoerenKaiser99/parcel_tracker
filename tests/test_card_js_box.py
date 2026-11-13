"""Card: shop orders in the same parcel (same tracking_carrier + tracking_ref, v0.3.50)
stand as one row "<Shop> · N Bestellungen". Gifts never join, the option `person` filters
first, a different state splits. Run in Node."""

import json
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
REF = "00340999999999999941"
A1, A2, A3 = "ALI9999999999999901", "ALI9999999999999902", "ALI9999999999999903"
QUOTA = "sensor.paket_tracker_17track_kontingent"

GROUP_SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
const sandbox = {
  HTMLElement: class {},
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {}, Event: class {}, document: { createElement: () => ({}) },
  location: { reload() {} },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const REF = process.argv[2];
const st = (number, extra, state) => ({ state: state || "in_transit",
  attributes: Object.assign({ number, carrier: "aliexpress", tracking_carrier: "dhl",
    tracking_ref: REF, gift: false }, extra) });
const rows = (states) => sandbox.groupRows(states).map((r) =>
  ({ key: r.key, numbers: r.states.map((s) => s.attributes.number) }));
const out = {};
out.same = rows([st("A1"), st("A2"), st("A3"), st("S", { tracking_ref: null })]);
out.single = rows([st("A1")]);
out.gift = rows([st("A1"), st("G", { gift: true }), st("A2")]);
out.state = rows([st("A1"), st("A2"), st("D", {}, "delivered")]);
out.carrier = rows([st("C1", { carrier: "dhl" }), st("C2", { carrier: "dhl" })]);
out.order = rows([st("A", { tracking_ref: "00340999999999999942" }), st("B1"),
  st("C", { tracking_ref: null }), st("B2")]);
out.shops = rows([st("A1"), st("A2"), st("E1", { carrier: "ebay" }),
  st("E2", { carrier: "ebay" })]);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def grouped():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", GROUP_SCRIPT, str(BUNDLED_CARD), REF],
        capture_output=True, text=True, check=True,
    )
    return json.loads(run.stdout)


def test_same_box_becomes_one_row(grouped):
    assert grouped["same"] == [
        {"key": f"box:dhl:{REF}", "numbers": ["A1", "A2", "A3"]},
        {"key": "S", "numbers": ["S"]},
    ]


def test_single_entry_with_tracking_ref_stays_plain(grouped):
    assert grouped["single"] == [{"key": "A1", "numbers": ["A1"]}]


def test_gift_never_joins(grouped):
    assert grouped["gift"] == [
        {"key": f"box:dhl:{REF}", "numbers": ["A1", "A2"]},
        {"key": "G", "numbers": ["G"]},
    ]


def test_different_state_splits(grouped):
    assert grouped["state"] == [
        {"key": f"box:dhl:{REF}", "numbers": ["A1", "A2"]},
        {"key": "D", "numbers": ["D"]},
    ]


def test_carrier_parcels_are_never_grouped(grouped):
    assert grouped["carrier"] == [
        {"key": "C1", "numbers": ["C1"]},
        {"key": "C2", "numbers": ["C2"]},
    ]


def test_group_stands_where_its_first_member_was(grouped):
    assert [r["numbers"] for r in grouped["order"]] == [["A"], ["B1", "B2"], ["C"]]


def test_two_shops_in_one_parcel_get_distinct_keys(grouped):
    keys = [r["key"] for r in grouped["shops"]]
    assert len(keys) == 2 and len(set(keys)) == 2


RENDER_SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
const fakeEl = () => {
  let html = "";
  const el = {
    hidden: false, value: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {}, children: [], dataset: {},
    get innerHTML() { return html; },
    set innerHTML(value) { html = value; el.children = []; el.kids = {}; },
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
  location: { reload() {} },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Card = defined["parcel-tracker-card"];
const [REF, A1, A2, A3] = process.argv.slice(2);
const KEY = `box:dhl:${REF}`;
const QUOTA = process.argv[6];

const order = (number, name, state, extra) => ({ entity_id: `sensor.paket_${number.toLowerCase()}`,
  state, last_updated: "t0", attributes: Object.assign({ number, name, carrier: "aliexpress",
    carrier_name: "AliExpress", tracking_carrier: "dhl", tracking_ref: REF,
    shipping_carrier_hint: "dhl", progress: 3, days_until: 2,
    events: [{ timestamp: "2026-11-10T10:00:00+01:00", text: "Sendung im Zielland angekommen" }],
    gift: false, owner: null }, extra) });

function hass(parcels) {
  const states = { "sensor.pakete_heute": { entity_id: "sensor.pakete_heute", state: "0",
      last_updated: "t0", attributes: { parcels: [], possible: [], possible_count: 0,
        delivered_today: [], delivered_today_count: 0 } },
    "person.anna": { entity_id: "person.anna", state: "home",
      attributes: { friendly_name: "Anna" } },
    "person.ben": { entity_id: "person.ben", state: "home",
      attributes: { friendly_name: "Ben" } } };
  const entities = {};
  for (const p of parcels) {
    states[p.entity_id] = p;
    entities[p.entity_id] = { platform: "parcel_tracker" };
  }
  return { states, entities, user: { id: "u1" },
    callWS: async () => { throw new Error("unknown"); }, callService: async () => {} };
}

function mount(parcels, config) {
  const card = new Card();
  const els = {};
  card.attachShadow = () => ({ innerHTML: "", activeElement: null,
    getElementById(id) { return (els[id] ||= fakeEl()); } });
  card.dispatchEvent = () => {};
  card.calls = [];
  card._call = async (service, data) => { card.calls.push([service, data.number]); return true; };
  card.setConfig(config || {});
  card.hass = hass(parcels);
  const list = () => els.list.children;
  return { card, list, html: () => list().map((i) => i.innerHTML) };
}

(async () => {
  const out = {};
  const box = [order(A1, "Kabel", "in_transit"), order(A2, "Lampe", "in_transit")];

  let m = mount(box);
  out.closed = m.html();

  m = mount(box);
  m.list()[0].kids[".row-toggle"].listeners.click();
  out.open = m.html();
  m.card._renderList();
  m.card._renderList();
  out.reopened = m.html();

  m = mount([...box, order(A3, "Stecker", "delivered")]);
  m.card._open.add(KEY);
  m.card._renderList();
  m.list()[0].kids['[data-a="received"]'].listeners.click();
  out.asking = m.html()[0];
  await m.list()[0].kids['[data-a="received-confirm"]'].listeners.click();
  out.calls = m.card.calls;
  out.afterConfirm = m.html()[0];

  // A second tap on "Wirklich erhalten?" while the orders are still being marked.
  m = mount([...box, order(A3, "Stecker", "in_transit")]);
  m.card._open.add(KEY);
  m.card._receiving.add(KEY);
  m.card._renderList();
  const confirm = m.list()[0].kids['[data-a="received-confirm"]'].listeners.click;
  await Promise.all([confirm(), confirm()]);
  out.twice = m.card.calls;

  m = mount(box);
  m.card._hass.states[QUOTA] = { entity_id: QUOTA, state: "40", last_updated: "t0",
    attributes: {} };
  m.card._open.add(KEY);
  m.card._renderList();
  out.t17 = m.html()[0];

  m = mount([order(A1, "Kabel", "in_transit", { owner: "person.anna" }),
    order(A2, "Lampe", "in_transit", { owner: "person.ben" })], { person: "person.anna" });
  out.anna = m.html();
  console.log(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def rendered():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", RENDER_SCRIPT, str(BUNDLED_CARD), REF, A1, A2, A3, QUOTA],
        capture_output=True, text=True, check=True,
    )
    return json.loads(run.stdout)


def test_box_row_shows_one_head_with_count(rendered):
    assert len(rendered["closed"]) == 1
    row = rendered["closed"][0]
    assert "AliExpress · 2 Bestellungen" in row
    assert f'data-number="box:dhl:{REF}"' in row
    assert "Kabel" not in row and "Lampe" not in row


def test_open_box_lists_each_order_once_and_events_once(rendered):
    row = rendered["open"][0]
    assert 'aria-expanded="true"' in row
    assert row.count("Kabel") == 1 and row.count("Lampe") == 1
    assert row.count("Sendung im Zielland angekommen") == 1
    assert row.count("Sendungsnummer:") == 1
    assert row.count('class="member"') == 2
    # Rename and delete per order, "Erhalten" once for the parcel.
    assert row.count('data-a="rename"') == 2 and row.count('data-a="remove"') == 2
    assert row.count('data-a="received"') == 1
    assert "9999999999999901" in row and "9999999999999902" in row


def test_box_received_marks_each_open_order(rendered):
    assert 'data-a="received-confirm"' in rendered["asking"]
    assert "Wirklich erhalten?" in rendered["asking"]
    assert rendered["asking"].index("Abbrechen") < rendered["asking"].index("Wirklich erhalten?")
    assert rendered["calls"] == [["mark_delivered", A1], ["mark_delivered", A2]]
    assert 'data-a="received-confirm"' not in rendered["afterConfirm"]


def test_box_stays_open_after_rerender(rendered):
    assert 'aria-expanded="true"' in rendered["reopened"][0]
    assert "Kabel" in rendered["reopened"][0]


def test_box_respects_person_filter(rendered):
    assert len(rendered["anna"]) == 1
    row = rendered["anna"][0]
    assert "Kabel" in row and "Lampe" not in row
    assert "Bestellungen" not in row


def test_open_box_offers_17track_once(rendered):
    # One parcel, one 17track number: the button stands once, not once per order.
    assert rendered["t17"].count('data-a="t17"') == 1


def test_box_received_runs_once_when_tapped_twice(rendered):
    assert rendered["twice"] == [["mark_delivered", A1], ["mark_delivered", A2],
                                 ["mark_delivered", A3]]

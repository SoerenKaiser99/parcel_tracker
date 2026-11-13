"""Card: a sent parcel (attribute ``outgoing``, v0.3.48) stands in the list with the badge
"Versendet", has no "Erhalten", no code and no gift box, and counts nowhere. Run in Node."""

import json
import re
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
SOURCE = BUNDLED_CARD.read_text(encoding="utf-8")
SENT = "00340999999999999931"
OTHER = "00340999999999999932"

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
    toggleAttribute() {},
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
  window: {}, Event: class { constructor(n) { this.type = n; } },
  document: { createElement: () => fakeEl() },
  location: { reload() {} },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Card = defined["parcel-tracker-card"];
const SENT = process.argv[2];
const OTHER = process.argv[3];
const today = new Date();
const pad = (n) => String(n).padStart(2, "0");
const DAY = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;

const parcel = (number, state, extra) => ({ entity_id: `sensor.paket_${number}`, state,
  last_updated: "t0", attributes: Object.assign({ number, name: `Paket ${number.slice(-2)}`,
    carrier: "dhl", carrier_name: "DHL", eta_date: DAY, days_until: 0, progress: 4,
    events: [], has_delivery_code: true, gift: false, owner: null }, extra) });

// sensor.pakete_heute as the integration builds it: a sent parcel is in none of its lists.
function hass(parcels, sure) {
  const states = { "sensor.pakete_heute": { entity_id: "sensor.pakete_heute",
    state: String(sure.length), last_updated: "t0",
    attributes: { parcels: sure, possible: [], possible_count: 0, delivered_today: [],
      delivered_today_count: 0 } } };
  const entities = {};
  for (const p of parcels) {
    states[p.entity_id] = p;
    entities[p.entity_id] = { platform: "parcel_tracker" };
  }
  return { states, entities, user: { id: "u1" },
    callWS: async () => { throw new Error("unknown"); }, callService: async () => {} };
}

function mount(parcels, sure, open) {
  const card = new Card();
  const els = {};
  const root = { innerHTML: "", activeElement: null,
    getElementById(id) { return (els[id] ||= fakeEl()); } };
  card.attachShadow = () => root;
  card.dispatchEvent = () => {};
  card.setConfig({});
  card.hass = hass(parcels, sure);
  for (const n of open) card._open.add(n);
  if (open.length) card._renderList();
  const rows = Object.fromEntries(els.list.children.map((item) =>
    [/data-number="([^"]+)"/.exec(item.innerHTML)[1], item.innerHTML]));
  return { rows, list: els.list.innerHTML, count: els.list.children.length,
    head: els.today.innerHTML, headHidden: els.today.hidden,
    openNotGift: card._openNotGift() };
}

const out = {};
const sent = parcel(SENT, "out_for_delivery", { outgoing: true });
const other = parcel(OTHER, "out_for_delivery", { outgoing: false });
out.both = mount([sent, other], [{ number: OTHER }], [SENT, OTHER]);
out.only = mount([sent], [], []);
out.onlyPickup = mount([parcel(SENT, "awaiting_pickup", { outgoing: true,
  pickup_point: "Packstation 123", customs_amount: 12.5, customs_currency: "EUR" })], [], [SENT]);
out.incomingPickup = mount([parcel(OTHER, "awaiting_pickup", { outgoing: false,
  pickup_point: "Packstation 123", customs_amount: 12.5, customs_currency: "EUR" })], [], [OTHER]);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD), SENT, OTHER],
        capture_output=True, text=True, check=True,
    )
    return json.loads(run.stdout)


def _sub(row: str) -> str:
    return re.search(r'<div class="sub">(.*?)</div>', row, re.S).group(1)


def test_sent_parcel_shows_the_badge_beside_its_status(card):
    sub = _sub(card["both"]["rows"][SENT])
    badge = re.search(r'<span class="([^"]*)"[^>]*>Versendet</span>', sub)
    assert badge is not None
    classes = badge.group(1).split()
    assert {"badge", "possible"} <= set(classes)
    # Readable as text: no role="img" that would hide it behind a label.
    assert "role=" not in badge.group(0)
    assert sub.index("In Zustellung") < sub.index("Versendet")
    assert "Versendet" not in card["both"]["rows"][OTHER]


def test_sent_parcel_has_no_received_button_no_code_no_gift_box(card):
    row = card["both"]["rows"][SENT]
    assert 'data-a="received"' not in row
    assert 'data-a="code"' not in row
    assert "giftbox" not in row
    # Rename and delete stay.
    assert 'data-a="rename"' in row and 'data-a="remove"' in row
    assert 'data-a="received"' in card["both"]["rows"][OTHER]
    assert 'data-a="received"' not in card["onlyPickup"]["rows"][SENT]


def test_sent_parcel_does_not_count_today(card):
    assert "1 heute" in card["both"]["head"]
    sent_row = card["both"]["rows"][SENT]
    assert 'class="eta today"' not in sent_row
    assert card["only"]["head"] == "" and card["only"]["headHidden"] is True


def test_only_a_sent_parcel_still_shows_its_row_and_no_empty_hint(card):
    only = card["only"]
    assert only["count"] == 1 and SENT in only["rows"]
    assert "Noch keine Pakete" not in only["list"]


def test_gift_question_does_not_count_a_sent_parcel(card):
    assert card["both"]["openNotGift"] == 1
    assert card["only"]["openNotGift"] == 0


def test_badge_css_keeps_the_possible_look():
    assert ".badge.possible {" in SOURCE
    assert re.search(r"\.badge\.sent\s*\{", SOURCE)


def test_sent_parcel_shows_no_pickup_point_and_no_customs(card):
    row = card["onlyPickup"]["rows"][SENT]
    assert "Packstation 123" not in row
    assert "Zoll" not in row and "Einfuhrabgaben" not in row
    # An incoming parcel keeps both.
    other = card["incomingPickup"]["rows"][OTHER]
    assert "Packstation 123" in other and "Einfuhrabgaben" in other

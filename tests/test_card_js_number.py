"""Card: the expanded details name the tracking number, for an order the order number
(and the carrier's number once a mail named it), as text to copy (run in Node, v0.3.34)."""

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
  // "Namen ausblenden" gives a neutral name; the number is shown all the same.
  ["in_transit", { number: "00340999999999999911", name: "DHL-Paket …9911", carrier: "dhl" }],
  ["in_transit", { number: "AMZ99990000000000001P2", name: "Schuhe", carrier: "amazon",
                   tracking_ref: "00340999999999999922", tracking_carrier: "dhl",
                   amazon_shipment: "UhIjKl9mN" }],
  ["in_transit", { number: "AMZ99990000000000002", name: "Mütze", carrier: "amazon",
                   amazon_shipment: "TAbCdE9fG" }],
  ["in_transit", { number: "AMZ99990000000000003", name: "Schal", carrier: "amazon",
                   amazon_shipment: 42 }],
  ["pre_transit", { number: "EBAY990000000001", name: "Lampe", carrier: "ebay" }],
  ["in_transit", { number: "ALI9999999999990001", name: "Kabel", carrier: "aliexpress",
                   tracking_ref: "LP00999999999999" }],
  ["pre_transit", { number: "EVT999999901", name: "Konzert", carrier: "eventim" }],
  ["pre_transit", { number: "AMZ9", name: "Alt", carrier: "amazon" }],
  ["in_transit", { number: "X<b>9</b>", name: "Seltsam", carrier: "other" }],
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
for (const n of Object.keys(rows())) rows()[n].kids[".row-toggle"].listeners.click();
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


def _lines(html: str) -> list[tuple[str, str]]:
    [block] = re.findall(r'<div class="detail ids">(.*?)</div></div>', html)
    return re.findall(r'<div>([^<:]+): <span class="num">([^<]*)</span>', block + "</div>")


def test_a_carrier_parcel_shows_its_tracking_number(card):
    # Also with a neutral name ("Namen ausblenden"): it hides names, never numbers.
    assert _lines(card["open"]["00340999999999999911"]) == [
        ("Sendungsnummer", "00340999999999999911")
    ]


def test_an_amazon_order_shows_the_order_number_as_amazon_writes_it_and_the_carrier_number(card):
    # A further shipment ("P2") belongs to the same order.
    # The carrier's number comes instead of Amazon's id of the shipment.
    assert _lines(card["open"]["AMZ99990000000000001P2"]) == [
        ("Bestellnummer", "999-9000000-0000001"),
        ("Sendungsnummer", "00340999999999999922"),
    ]


def test_an_amazon_order_without_a_carrier_number_shows_amazons_shipment(card):
    assert _lines(card["open"]["AMZ99990000000000002"]) == [
        ("Bestellnummer", "999-9000000-0000002"),
        ("Amazon-Sendung", "TAbCdE9fG"),
    ]
    # Anything but a text is no id.
    assert _lines(card["open"]["AMZ99990000000000003"]) == [
        ("Bestellnummer", "999-9000000-0000003"),
    ]


def test_other_shops_show_their_order_numbers(card):
    assert _lines(card["open"]["EBAY990000000001"]) == [("Bestellnummer", "99-00000-00001")]
    assert _lines(card["open"]["ALI9999999999990001"]) == [
        ("Bestellnummer", "9999999999990001"),
        ("Sendungsnummer", "LP00999999999999"),
    ]
    assert _lines(card["open"]["EVT999999901"]) == [("Bestellnummer", "999999901")]


def test_an_order_number_of_another_shape_is_shown_as_stored(card):
    assert _lines(card["open"]["AMZ9"]) == [("Bestellnummer", "AMZ9")]


def test_numbers_stay_escaped(card):
    html = card["open"]["X&lt;b&gt;9&lt;/b&gt;"]
    assert '<span class="num">X&lt;b&gt;9&lt;/b&gt;</span>' in html
    assert "<b>" not in html


def test_the_numbers_stand_below_the_history(card):
    html = card["open"]["00340999999999999911"]
    assert html.index("Noch keine Ereignisse") < html.index('class="detail ids"')
    assert html.index('class="detail ids"') < html.index('class="actions"')


def test_a_closed_row_shows_no_number_line(card):
    for html in card["closed"].values():
        assert "Sendungsnummer" not in html
        assert "Bestellnummer" not in html


def test_two_lines_are_as_far_apart_as_a_symbols_hit_area(card):
    """A symbol is hit on 18px plus 3px above and below it: 24px (the WCAG minimum for a
    target), and 30px wide. As high is each number line, so on a phone the areas of the
    symbols in two lines never overlap."""
    [line] = re.findall(r"\.ids > div \{([^}]*)\}", card["template"])
    [link] = re.findall(r"\.ids a\.go \{([^}]*)\}", card["template"])
    [icon] = re.findall(r"\.ids a\.go ha-icon \{([^}]*)\}", card["template"])
    assert "line-height:24px" in line
    assert "padding:3px 6px" in link and "margin:-3px 0 -3px 0" in link
    assert "--mdc-icon-size:18px" in icon


def test_the_number_can_be_selected_to_copy_it(card):
    [rule] = re.findall(r"\.num \{([^}]*)\}", card["template"])
    assert "user-select:all" in rule
    assert "-webkit-user-select:all" in rule

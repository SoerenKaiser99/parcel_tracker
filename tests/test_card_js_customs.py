"""Card: the import duty (Zoll) of a DHL parcel from abroad, as the integration's attributes
customs_amount / customs_currency / customs_cash tell it (issue #36): a line in the details and
a small badge in the row (run in Node)."""

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
const duty = (amount, currency, cash) => (
  { customs_amount: amount, customs_currency: currency, customs_cash: cash });
[
  ["out_for_delivery", { number: "LE999999901BE", name: "Schallplatte", carrier: "dhl",
                         ...duty(12.34, "EUR", true) }],
  ["out_for_delivery", { number: "LE999999902BE", name: "Kabel", carrier: "dhl",
                         ...duty(1234.5, "EUR", false) }],
  ["out_for_delivery", { number: "00340999999999999903", name: "Lampe", carrier: "dhl",
                         ...duty(null, null, false) }],
  ["delivered", { number: "LE999999904BE", name: "Buch", carrier: "dhl",
                  ...duty(null, null, false) }],
  ["out_for_delivery", { number: "LE999999905BE", name: "Tasse", carrier: "dhl",
                         ...duty("12,34", "EUR", true) }],
  ["out_for_delivery", { number: "LE999999906BE", name: "Hut", carrier: "dhl",
                         ...duty(12.34, "<b>x</b>", true) }],
  ["out_for_delivery", { number: "LE999999907BE", name: "Uhr", carrier: "dhl" }],
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


def _detail(html: str) -> list[str]:
    return re.findall(r'<div class="detail duty">([^<]*)</div>', html)


def _badge(html: str) -> list[str]:
    return re.findall(r'<span class="badge duty"[^>]*>([^<]*)</span>', html)


def test_a_duty_to_pay_in_cash_is_a_line_in_the_details_and_a_badge_in_the_row(card):
    number = "LE999999901BE"
    assert _detail(card["open"][number]) == ["Einfuhrabgaben: 12,34 € in bar bei Zustellung"]
    assert _badge(card["open"][number]) == ["Zoll 12,34 €"]
    # Collapsed there is only the badge: it is what is seen without opening the parcel.
    assert _detail(card["closed"][number]) == []
    assert _badge(card["closed"][number]) == ["Zoll 12,34 €"]


def test_the_amount_is_written_the_german_way_and_cash_is_named_only_when_asked_for(card):
    number = "LE999999902BE"
    assert _detail(card["open"][number]) == ["Einfuhrabgaben: 1.234,50 € bei Zustellung"]
    assert _badge(card["open"][number]) == ["Zoll 1.234,50 €"]


@pytest.mark.parametrize(
    "number",
    [
        "00340999999999999903",  # no amount (attributes empty)
        "LE999999904BE",  # delivered: the integration empties the attributes
        "LE999999905BE",  # an amount that is no number is none
        "LE999999907BE",  # attributes missing altogether
    ],
)
def test_no_amount_no_line_and_no_badge(card, number):
    for state in ("open", "closed"):
        assert _detail(card[state][number]) == []
        assert _badge(card[state][number]) == []


def test_a_currency_nobody_knows_is_shown_as_text_never_as_markup(card):
    number = "LE999999906BE"
    assert _detail(card["open"][number]) == [
        "Einfuhrabgaben: 12,34 &lt;b&gt;x&lt;/b&gt; in bar bei Zustellung"
    ]
    assert "<b>x</b>" not in card["open"][number]


def test_the_badge_has_a_style(card):
    assert ".badge.duty" in card["template"]

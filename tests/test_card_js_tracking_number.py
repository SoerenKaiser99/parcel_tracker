"""Card: "Sendungsnummer: eintragen" below an order's numbers (run in Node)."""

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
const sandbox = {
  HTMLElement: class {},
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {},
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(process.argv[1], "utf8")
    + "\n;globalThis.__numbers = numbersHtml; globalThis.__svc = SERVICE_ERRORS;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];
const card = new Card();
card.setConfig({});
card._hass = { states: {}, entities: {} };
const order = { number: "AMZ99999999999999901", carrier: "amazon", amazon_shipment: "DAbCdE9fG" };
const out = {};
out.line = {
  order: card._refHtml(order, "in_transit"),
  delivered: card._refHtml(order, "delivered"),
  cancelled: card._refHtml(order, "cancelled"),
  tracked: card._refHtml({ ...order, tracking_ref: "00340999999999999901" }, "in_transit"),
  parcel: card._refHtml({ number: "00340999999999999901", carrier: "dhl" }, "in_transit"),
  ebay: card._refHtml({ number: "EBAY999999999901", carrier: "ebay" }, "in_transit"),
  amazonSends: card._refHtml({ ...order, amazon_shipment: "TAbCdE9fG" }, "in_transit"),
  noId: card._refHtml({ ...order, amazon_shipment: null }, "in_transit"),
};
out.inBlock = sandbox.__numbers(order, card._refHtml(order, "in_transit"));

const handlers = {};
const input = { value: "", listeners: {},
  addEventListener(name, fn) { this.listeners[name] = fn; } };
const item = { querySelector(q) {
  if (q === '[data-a="ref-input"]') return input;
  return { addEventListener(name, fn) { handlers[q] = fn; } };
} };
const click = (a) => handlers[`[data-a="${a}"]`]();
const calls = [];
const errors = [];
let answer = false;
card._renderList = () => {};
card._setError = (text) => errors.push(text);
card._call = async (service, data) => { calls.push([service, data]); return answer; };
card._wireActions(item, order);
click("ref");
out.editing = { adding: card._refAdding.has(order.number), focus: card._pendingFocus,
  html: card._refHtml(order, "in_transit") };
click("ref-save").then(() => {
  out.empty = { calls: calls.length, error: errors[errors.length - 1] };
  input.value = " 0034 0999 9999 9999 9901 ";
  input.listeners.input();
  return click("ref-save");
}).then(() => {
  out.refused = { adding: card._refAdding.has(order.number), call: calls[calls.length - 1] };
  answer = true;
  return click("ref-save");
}).then(() => {
  out.saved = { adding: card._refAdding.has(order.number), focus: card._pendingFocus };
  click("ref");
  click("ref-cancel");
  out.cancelled = { adding: card._refAdding.has(order.number), focus: card._pendingFocus };
  card._refAdding.set(order.number, "x");
  out.signature = card._signature().includes("|ref:" + order.number);
  out.errors = ["not_an_order", "has_tracking", "not_a_carrier_parcel"]
    .map((k) => sandbox.__svc[k]);

  // A DHL parcel naming Amazon waits in the list: an order Amazon sends offers the line too,
  // and its number typed in is asked about before the two are joined.
  const waiting = (name, state = "in_transit") => {
    card._hass = {
      states: { "sensor.paket_dhl": { entity_id: "sensor.paket_dhl", state, attributes: {
        number: "00340999999999999901", carrier: "dhl", name } } },
      entities: { "sensor.paket_dhl": { platform: "parcel_tracker" } },
    };
  };
  const tOrder = { ...order, amazon_shipment: "TAbCdE9fG" };
  card._refAdding.clear();
  waiting("Amazon-Sendung (DHL)");
  out.waits = card._refHtml(tOrder, "in_transit");
  waiting("Beispielmarke GmbH");
  out.otherWaits = card._refHtml(tOrder, "in_transit");
  waiting("Amazon-Sendung (DHL)", "delivered");
  out.deliveredWaits = card._refHtml(tOrder, "in_transit");
  waiting("Beispielmarke GmbH");
  card._refAdding.clear();
  calls.length = 0;
  click("ref");
  input.value = "0034 0999 9999 9999 9901";
  input.listeners.input();
  return click("ref-save");
}).then(() => {
  out.asked = { calls: calls.length, merging: card._refMerging.has(order.number),
    focus: card._pendingFocus, html: card._refHtml(order, "in_transit") };
  click("ref-merge-cancel");
  out.back = { merging: card._refMerging.has(order.number),
    text: card._refAdding.get(order.number), focus: card._pendingFocus };
  return click("ref-save");
}).then(() => click("ref-merge")).then(() => {
  out.merged = { call: calls[calls.length - 1], merging: card._refMerging.has(order.number),
    adding: card._refAdding.has(order.number) };
  console.log(JSON.stringify(out));
});
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


ADD = ('<div>Sendungsnummer: <button type="button" class="add" data-a="ref" '
       'data-number="AMZ99999999999999901">eintragen</button></div>')


def test_an_order_without_a_carriers_number_offers_the_line(card):
    line = card["line"]
    assert line["order"] == ADD
    assert 'data-a="ref"' in line["ebay"]
    # nothing comes, it came, there is one already, or it is a carrier's parcel itself
    assert line["cancelled"] == line["delivered"] == line["tracked"] == line["parcel"] == ""


def test_an_amazon_order_offers_it_only_when_a_carrier_of_its_own_brings_the_box(card):
    # The order above is sent by the seller ("D…"). One Amazon sends itself ("T…", "U…") or
    # one without an id: Amazon's own delivery has no number to type in ...
    assert card["line"]["amazonSends"] == card["line"]["noId"] == ""
    # ... unless a carrier's parcel naming Amazon waits alone in the list.
    assert 'data-a="ref"' in card["waits"]
    assert card["otherWaits"] == card["deliveredWaits"] == ""


def test_a_parcel_of_that_number_is_joined_only_after_asking(card):
    asked = card["asked"]
    assert asked["calls"] == 0 and asked["merging"] is True
    assert asked["focus"] == {"number": "AMZ99999999999999901", "a": "ref-merge-cancel"}
    assert 'role="group" aria-label="Zusammenführen bestätigen"' in asked["html"]
    assert "wird mit der Bestellung zusammengeführt" in asked["html"]
    assert asked["html"].index("Abbrechen") < asked["html"].index(">Zusammenführen<")
    # "Abbrechen" goes back to the field with what was typed
    assert card["back"] == {"merging": False, "text": "0034 0999 9999 9999 9901",
                            "focus": {"number": "AMZ99999999999999901", "a": "ref-input"}}
    assert card["merged"] == {
        "call": ["set_tracking_number", {"number": "AMZ99999999999999901",
                                         "tracking_number": "0034 0999 9999 9999 9901"}],
        "merging": False, "adding": False,
    }


def test_the_line_stands_with_the_numbers_not_in_the_action_row(card):
    block = card["inBlock"]
    assert block.startswith('<div class="detail ids">') and block.endswith(ADD + "</div>")
    assert block.index("Amazon-Sendung") < block.index("eintragen")


def test_a_tap_turns_the_line_into_a_field(card):
    editing = card["editing"]
    assert editing["adding"] is True
    assert editing["focus"] == {"number": "AMZ99999999999999901", "a": "ref-input"}
    assert 'data-a="ref-input"' in editing["html"]
    assert ">Speichern</button>" in editing["html"] and ">Abbrechen</button>" in editing["html"]
    assert 'aria-label="Sendungsnummer des Paketdienstes"' in editing["html"]


def test_saving_calls_the_service_and_closes_the_field_only_when_it_worked(card):
    assert card["empty"] == {"calls": 0, "error": "Gib eine Sendungsnummer ein."}
    assert card["refused"]["adding"] is True
    assert card["refused"]["call"] == [
        "set_tracking_number",
        {"number": "AMZ99999999999999901", "tracking_number": "0034 0999 9999 9999 9901"},
    ]
    assert card["saved"] == {
        "adding": False, "focus": {"number": "AMZ99999999999999901", "a": "toggle"},
    }
    assert card["cancelled"] == {
        "adding": False, "focus": {"number": "AMZ99999999999999901", "a": "ref"},
    }


def test_the_open_field_is_part_of_the_signature_and_errors_have_texts(card):
    assert card["signature"] is True
    assert all(card["errors"])

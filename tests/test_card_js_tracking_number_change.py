"""Card: a carrier's number typed in is changed or taken away again; the order of the
numbers; another person's waiting Amazon box (run in Node)."""

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
const sandbox = {
  HTMLElement: class {},
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {},
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(process.argv[1], "utf8") + "\n;globalThis.__numbers = numbersHtml;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];
const card = new Card();
card.setConfig({});
card._hass = { states: {}, entities: {} };
const DHL = "00340999999999999901";
const order = { number: "AMZ99999999999999901", carrier: "amazon", amazon_shipment: "DAbCdE9fG",
  tracking_ref: DHL, tracking_carrier: "dhl", tracking_manual: true };
const fromMail = { ...order, tracking_manual: false };
const out = {};
const block = (a, s = "in_transit") => sandbox.__numbers(a, ...card._refHtml(a, s));
out.typed = block(order);
out.fromMail = block(fromMail);
out.received = block({ ...order, manual_delivered: true }, "delivered");
out.cancelled = block(order, "cancelled");
out.typedDelivered = block(order, "delivered");
out.ebay = block({ number: "EBAY999999999901", carrier: "ebay", tracking_ref: DHL,
  tracking_manual: true });

const handlers = {};
const input = { value: "", listeners: {},
  addEventListener(name, fn) { this.listeners[name] = fn; } };
const item = { querySelector(q) {
  if (q === '[data-a="ref-input"]') return input;
  return { addEventListener(name, fn) { handlers[q] = fn; } };
} };
const click = (a) => handlers[`[data-a="${a}"]`]();
const calls = [];
card._renderList = () => {};
card._setError = () => {};
card._call = async (service, data) => { calls.push([service, data]); return true; };
card._wireActions(item, order);
click("ref");
out.field = { text: card._refAdding.get(order.number), html: block(order) };
input.value = "0034 0999 9999 9999 9901";
input.listeners.input();
click("ref-save").then(() => {
  out.unchanged = { calls: calls.length, open: card._refAdding.has(order.number) };
  click("ref");
  return click("ref-remove");
}).then(() => {
  out.removed = { call: calls[calls.length - 1], open: card._refAdding.has(order.number),
    focus: card._pendingFocus };

  // A DHL parcel naming Amazon waits, but it is another person's: with the option `person`
  // it says nothing about this person's Amazon order.
  card._refAdding.clear();
  card.setConfig({ person: "person.anna" });
  const states = { "sensor.paket_dhl": { entity_id: "sensor.paket_dhl", state: "in_transit",
    attributes: { number: DHL, carrier: "dhl", name: "Amazon-Sendung (DHL)",
      owner: "person.ben" } } };
  card._hass = { states, entities: { "sensor.paket_dhl": { platform: "parcel_tracker" } } };
  const tOrder = { number: "AMZ99999999999999902", carrier: "amazon",
    amazon_shipment: "TAbCdE9fG", owner: "person.anna" };
  out.othersBox = card._refHtml(tOrder, "in_transit")[0];
  states["sensor.paket_dhl"].attributes.owner = "person.anna";
  out.ownBox = card._refHtml(tOrder, "in_transit")[0];
  console.log(JSON.stringify(out));
});
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, encoding="utf-8",
        check=True,
    )
    return json.loads(done.stdout)


CHANGE = ('<button type="button" class="add" data-a="ref" '
          'data-number="AMZ99999999999999901">ändern</button>')


def _labels(html: str) -> list[str]:
    return re.findall(r"<div>([^<:]+): ", html)


def test_a_number_typed_in_has_change_at_the_end_of_its_line(card):
    # (order number, Amazon's shipment, the carrier's number: where "eintragen" stood)
    typed = card["typed"]
    assert _labels(typed) == ["Bestellnummer", "Amazon-Sendung", "Sendungsnummer"]
    assert typed.endswith(f"{CHANGE}</div></div>")
    # eBay alike
    assert 'data-a="ref"' in card["ebay"] and ">ändern<" in card["ebay"]


def test_a_number_a_mail_named_is_not_changed(card):
    assert "data-a=\"ref\"" not in card["fromMail"]
    # nor on an order marked as received or cancelled
    assert "data-a=\"ref\"" not in card["received"] and "data-a=\"ref\"" not in card["cancelled"]
    # what the wrong number told ("delivered") does not keep it from being changed
    assert ">ändern<" in card["typedDelivered"]


def test_the_field_takes_the_place_of_the_line_and_starts_from_the_number(card):
    field = card["field"]
    assert field["text"] == "00340999999999999901"
    assert _labels(field["html"]) == ["Bestellnummer", "Amazon-Sendung"]
    assert 'data-a="ref-input"' in field["html"] and ">Entfernen</button>" in field["html"]
    html = field["html"]
    assert html.index(">Speichern<") < html.index(">Entfernen<") < html.index(">Abbrechen<")


def test_the_same_number_again_only_closes_the_field(card):
    assert card["unchanged"] == {"calls": 0, "open": False}


def test_remove_takes_the_number_away(card):
    assert card["removed"] == {
        "call": ["set_tracking_number",
                 {"number": "AMZ99999999999999901", "tracking_number": ""}],
        "open": False, "focus": {"number": "AMZ99999999999999901", "a": "toggle"},
    }


def test_another_persons_waiting_amazon_box_opens_no_line(card):
    assert card["othersBox"] == ""
    assert 'data-a="ref"' in card["ownBox"]

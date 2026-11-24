"""Card: "Sendungsnummer: eintragen" at its edges - delivered orders, parcels the service
does not fold, a field that stays open, Enter twice (run in Node)."""

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
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Card = defined["parcel-tracker-card"];
const card = new Card();
card.setConfig({});
const DHL = "00340999999999999901";
const list = (attributes, state = "in_transit") => {
  card._hass = {
    states: { "sensor.paket_dhl": { entity_id: "sensor.paket_dhl", state,
      attributes: { number: DHL, carrier: "dhl", ...attributes } } },
    entities: { "sensor.paket_dhl": { platform: "parcel_tracker" } },
  };
};
list({ name: "Beispielmarke GmbH" });
const seller = { number: "AMZ99999999999999901", carrier: "amazon", amazon_shipment: "DAbCdE9fG" };
const out = {};
out.line = {
  delivered: card._refHtml(seller, "delivered"),
  assumed: card._refHtml({ ...seller, assumed_delivered: true }, "delivered"),
  manual: card._refHtml({ ...seller, manual_delivered: true }, "delivered"),
};
out.parcelOf = {
  plain: !!card._parcelOf("0034 0999-9999 9999 9901"),
};
list({ name: "Rücksendung", outgoing: true });
out.parcelOf.outgoing = !!card._parcelOf(DHL);
list({ name: "Teil einer Bestellung", tracking_ref: "X" });
out.parcelOf.tracked = !!card._parcelOf(DHL);
// GLS: the other form of the number (with or without the check digit) is the same parcel
list({ number: "99999999901", carrier: "gls", name: null });
out.parcelOf.glsWithCheckDigit = !!card._parcelOf("999999999017");
list({ number: "999999999017", carrier: "gls", name: null });
out.parcelOf.glsWithout = !!card._parcelOf("99999999901");
list({ number: "99999999901", carrier: "dhl", name: null });
out.parcelOf.notGls = !!card._parcelOf("999999999017");
// A sent parcel naming Amazon (a return) opens nothing for Amazon's own delivery.
list({ name: "Amazon Retoure", outgoing: true });
out.returnOpens = card._refHtml({ ...seller, amazon_shipment: "TAbCdE9fG" }, "in_transit");

// An Amazon order Amazon sends: the line comes from the waiting DHL parcel ...
const amazon = { ...seller, amazon_shipment: "TAbCdE9fG" };
list({ name: "Amazon-Sendung (DHL)" });
card._refAdding.set(amazon.number, "0034");
// ... which is delivered while the field is open: the field stays.
list({ name: "Amazon-Sendung (DHL)" }, "delivered");
out.stays = card._refHtml(amazon, "in_transit").includes('data-a="ref-input"');
card._refAdding.clear();
out.closedGone = card._refHtml(amazon, "in_transit");

// Enter twice: one call.
const handlers = {};
const input = { value: "", listeners: {},
  addEventListener(name, fn) { this.listeners[name] = fn; } };
const item = { querySelector(q) {
  if (q === '[data-a="ref-input"]') return input;
  return { addEventListener(name, fn) { handlers[q] = fn; } };
} };
let release;
const calls = [];
card._renderList = () => {};
card._setError = () => {};
card._call = (service, data) => { calls.push(data); return new Promise((r) => { release = r; }); };
card._hass = { states: {}, entities: {} };
card._wireActions(item, seller);
handlers['[data-a="ref"]']();
input.value = "00340999999999999902";
input.listeners.input();
const enter = { key: "Enter", preventDefault() {} };
input.listeners.keydown(enter);
input.listeners.keydown(enter);
out.whileSending = calls.length;
release(true);
setTimeout(() => {
  out.after = { calls: calls.length, open: card._refAdding.has(seller.number),
    sending: card._refSending.has(seller.number) };
  console.log(JSON.stringify(out));
}, 0);
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


def test_a_delivered_order_has_no_line_unless_it_was_only_closed(card):
    assert card["line"]["delivered"] == card["line"]["manual"] == ""
    assert 'data-a="ref"' in card["line"]["assumed"]


def test_only_a_parcel_the_service_folds_in_is_asked_about(card):
    # spaces and hyphens as typed do not matter; a GLS parcel is found under both forms
    assert card["parcelOf"] == {
        "plain": True, "outgoing": False, "tracked": False,
        "glsWithCheckDigit": True, "glsWithout": True, "notGls": False,
    }


def test_a_return_naming_amazon_opens_no_line_for_amazons_own_delivery(card):
    assert card["returnOpens"] == ""


def test_an_open_field_stays_when_the_parcel_that_showed_the_line_changes(card):
    assert card["stays"] is True
    assert card["closedGone"] == ""


def test_enter_twice_calls_the_service_once(card):
    assert card["whileSending"] == 1
    assert card["after"] == {"calls": 1, "open": False, "sending": False}

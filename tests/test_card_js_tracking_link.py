"""Card: "Sendung verfolgen" links to the carrier's tracking page (run in Node).

The page comes from the sensor attribute ``tracking_url``; the card only renders it.
"""

import json
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
DHL = (
    "https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html"
    "?piececode=00340999999999999901"
)
UPS = "https://www.ups.com/track?loc=de_DE&tracknum=1Z999AA10123456784"
AMAZON = "https://www.amazon.de/gp/your-account/order-details?orderID=999-9156534-2587125"

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
card._hass = { states: {}, entities: {} };
const [dhl, ups] = JSON.parse(process.argv[2]);
const parcel = { number: "00340999999999999901", carrier: "dhl", tracking_url: dhl };
const order = { number: "AMZ99991565342587125", carrier: "amazon", tracking_url: ups };
const out = {
  parcel: card._actionsHtml(parcel),
  order: card._actionsHtml(order),
  none: card._actionsHtml({ ...order, tracking_url: null }),
  old: card._actionsHtml({ number: "00340999999999999901", carrier: "dhl" }),
  odd: [42, {}, "", "javascript:alert(1)", "http://example.org/x", " https://example.org"].map(
    (u) => card._actionsHtml({ number: "09999999999901", carrier: "dpd", tracking_url: u })),
  escaped: card._actionsHtml(
    { number: "1", carrier: "ups", tracking_url: 'https://example.org/?a=1&b="<x>' }),
};
card._renaming.set(parcel.number, "Neu");
out.renaming = card._actionsHtml(parcel);
card._renaming.clear();
card._confirming.add(parcel.number);
out.confirming = card._actionsHtml(parcel);
console.log(JSON.stringify(out));
"""


def _link(url: str, text: str = "Sendung verfolgen") -> str:
    href = url.replace("&", "&amp;")
    return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{text}</a>'


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD), json.dumps([DHL, UPS])],
        capture_output=True, text=True, check=True,
    )
    return json.loads(done.stdout)


def test_the_link_stands_before_the_other_actions(card):
    assert card["parcel"].startswith(f'<div class="actions">{_link(DHL)}<button')
    assert 'data-a="rename"' in card["parcel"] and 'data-a="remove"' in card["parcel"]


def test_a_shop_order_with_a_carrier_number_shows_both_links(card):
    both = _link(UPS) + _link(AMAZON, "Bestellung")
    assert card["order"].startswith(f'<div class="actions">{both}<button')


def test_no_link_without_a_tracking_page(card):
    assert "Sendung verfolgen" not in card["none"]
    assert "Bestellung</a>" in card["none"]
    # A sensor of an older version has no such attribute.
    assert "<a " not in card["old"]


def test_only_an_https_address_becomes_a_link(card):
    for html in card["odd"]:
        assert "<a " not in html, html


def test_the_address_is_escaped(card):
    assert 'href="https://example.org/?a=1&amp;b=&quot;&lt;x&gt;"' in card["escaped"]


def test_no_link_while_renaming_or_confirming_the_deletion(card):
    assert "<a " not in card["renaming"] and 'data-a="rename-save"' in card["renaming"]
    assert "<a " not in card["confirming"] and 'data-a="remove-confirm"' in card["confirming"]

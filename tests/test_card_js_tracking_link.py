"""Card: a symbol behind the tracking number opens the tracking page (run in Node).

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
AMAZON_TRACKING = (
    "https://www.amazon.de/progress-tracker/package?orderId=999-9156534-2587125"
    "&packageIndex=0&shipmentId=TAbCdE9fG"
)

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
  fs.readFileSync(process.argv[1], "utf8") + "\n;globalThis.__numbers = numbersHtml;", sandbox);
const numbers = sandbox.__numbers;
const Card = defined["parcel-tracker-card"];
const card = new Card();
card.setConfig({});
card._hass = { states: {}, entities: {} };
const [dhl, ups, amazon] = JSON.parse(process.argv[2]);
const parcel = { number: "00340999999999999901", carrier: "dhl", tracking_url: dhl };
const order = {
  number: "AMZ99991565342587125", carrier: "amazon",
  tracking_ref: "1Z999AA10123456784", tracking_carrier: "ups", tracking_url: ups,
};
const amazonOnly = { number: "AMZ99991565342587125", carrier: "amazon", tracking_url: amazon };
const out = {
  parcel: numbers(parcel),
  order: numbers(order),
  amazonOnly: numbers(amazonOnly),
  amazonShipment: numbers({ ...amazonOnly, amazon_shipment: "TAbCdE9fG" }),
  // A carrier without a tracking page of ours: links.py links to Amazon's page instead.
  pagelessCarrier: numbers({
    ...amazonOnly, amazon_shipment: "TAbCdE9fG", tracking_ref: "LP00999999999999",
    tracking_carrier: "other",
  }),
  carrierAndAmazon: numbers({ ...order, amazon_shipment: "TAbCdE9fG" }),
  none: numbers({ ...amazonOnly, tracking_url: null }),
  old: numbers({ number: "00340999999999999901", carrier: "dhl" }),
  odd: [42, {}, "", "javascript:alert(1)", "http://example.org/x", " https://example.org"].map(
    (u) => numbers({ number: "09999999999901", carrier: "dpd", tracking_url: u })),
  escaped: numbers(
    { number: "1", carrier: "ups", tracking_url: 'https://example.org/?a=1&b="<x>' }),
  actions: card._actionsHtml(parcel),
};
console.log(JSON.stringify(out));
"""


def _link(url: str, words: str = "Sendung verfolgen", icon: str = "truck-delivery-outline") -> str:
    href = url.replace("&", "&amp;")
    return (
        f'<a class="go" href="{href}" target="_blank" rel="noopener noreferrer"'
        f' title="{words}" aria-label="{words}"><ha-icon icon="mdi:{icon}"></ha-icon></a>'
    )


def _order_link() -> str:
    return _link(AMAZON, "Bestellung öffnen", "receipt-text-outline")


def _line(label: str, number: str, links: str) -> str:
    return f'<div>{label}: <span class="num">{number}</span>{links}</div>'


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD), json.dumps([DHL, UPS, AMAZON_TRACKING])],
        capture_output=True, encoding="utf-8", check=True,
    )
    return json.loads(done.stdout)


def test_the_symbol_stands_behind_the_tracking_number(card):
    line = _line("Sendungsnummer", "00340999999999999901", _link(DHL))
    assert card["parcel"] == f'<div class="detail ids">{line}</div>'


def test_a_shop_order_with_a_carrier_number_has_one_symbol_behind_each_number(card):
    assert card["order"] == (
        '<div class="detail ids">'
        + _line("Bestellnummer", "999-9156534-2587125", _order_link())
        + _line("Sendungsnummer", "1Z999AA10123456784", _link(UPS))
        + "</div>"
    )


def test_amazons_tracking_page_stands_behind_amazons_shipment(card):
    assert card["amazonShipment"] == (
        '<div class="detail ids">'
        + _line("Bestellnummer", "999-9156534-2587125", _order_link())
        + _line("Amazon-Sendung", "TAbCdE9fG", _link(AMAZON_TRACKING))
        + "</div>"
    )


def test_amazons_page_for_a_carrier_without_a_page_stands_behind_amazons_shipment(card):
    # Not behind the carrier's number: that page is Amazon's, about Amazon's shipment.
    assert card["pagelessCarrier"] == (
        '<div class="detail ids">'
        + _line("Bestellnummer", "999-9156534-2587125", _order_link())
        + _line("Sendungsnummer", "LP00999999999999", "")
        + _line("Amazon-Sendung", "TAbCdE9fG", _link(AMAZON_TRACKING))
        + "</div>"
    )


def test_a_carriers_page_keeps_its_place_behind_the_carriers_number(card):
    # The carrier's own page comes first (links.py): Amazon's shipment is not shown then.
    assert card["carrierAndAmazon"] == card["order"]


def test_a_tracking_page_without_any_shipment_number_stands_behind_the_order_number(card):
    # (a sensor of an older version without amazon_shipment): first the tracking, then the
    # order, as everywhere else.
    assert card["amazonOnly"] == (
        '<div class="detail ids">'
        + _line("Bestellnummer", "999-9156534-2587125", _link(AMAZON_TRACKING) + _order_link())
        + "</div>"
    )


def test_no_symbol_without_a_tracking_page(card):
    assert "Sendung verfolgen" not in card["none"]
    assert "Bestellung öffnen" in card["none"]
    # A sensor of an older version has no such attribute.
    assert "<a " not in card["old"]


def test_only_an_https_address_becomes_a_link(card):
    for html in card["odd"]:
        assert "<a " not in html, html


def test_the_address_is_escaped(card):
    assert 'href="https://example.org/?a=1&amp;b=&quot;&lt;x&gt;"' in card["escaped"]


def test_the_action_row_has_no_link_any_more(card):
    assert "<a " not in card["actions"]
    assert card["actions"].startswith('<div class="actions"><button')

"""Card: an Amazon, eBay or AliExpress order links to its page at the shop (run in Node)."""

import json
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
AMAZON = "https://www.amazon.de/gp/your-account/order-details?orderID=999-9156534-2587125"
EBAY = "https://order.ebay.de/ord/show?orderId=99-00000-00001"
ALIEXPRESS = "https://www.aliexpress.com/p/order/detail.html?orderId=9999999999990001"

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
  fs.readFileSync(process.argv[1], "utf8") + "\n;globalThis.__url = orderUrl;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];
const card = new Card();
card.setConfig({});
card._hass = { states: {}, entities: {} };
const order = { number: "AMZ99991565342587125" };
const out = {
  url: {
    amazon: sandbox.__url("AMZ99991565342587125"),
    second: sandbox.__url("AMZ99991565342587125P2"),
    ebay: sandbox.__url("EBAY990000000001"),
    aliexpress: sandbox.__url("ALI9999999999990001"),
    aliexpressOdd: [sandbox.__url("ALI99999"), sandbox.__url("ALI9999999999990001P2"),
                    sandbox.__url("ALIX999999999990001")],
    dhl: sandbox.__url("00340999999999999911"),
    short: sandbox.__url("AMZ1"),
    missing: sandbox.__url(undefined),
  },
  order: card._actionsHtml(order),
  carrier: card._actionsHtml({ number: "00340999999999999911" }),
  aliexpressOrder: card._actionsHtml({ number: "ALI9999999999990001" }),
  aliexpressIcon: card._icon("aliexpress"),
};
card._renaming.set(order.number, "Neu");
out.renaming = card._actionsHtml(order);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


def test_an_order_links_to_its_page_at_the_shop(card):
    assert card["url"]["amazon"] == AMAZON
    assert card["url"]["ebay"] == EBAY
    # A further shipment of the same order ("… (2)") belongs to the same order page.
    assert card["url"]["second"] == AMAZON


def test_aliexpress_order_links_to_its_page_and_has_its_own_dot(card):
    assert card["url"]["aliexpress"] == ALIEXPRESS
    # The number is "ALI" + the order's digits and nothing else (one parcel per order).
    assert card["url"]["aliexpressOdd"] == [None, None, None]
    assert f'<a href="{ALIEXPRESS}" target="_blank"' in card["aliexpressOrder"]
    assert 'aria-label="aliexpress"' in card["aliexpressIcon"]
    assert 'fill="#E43225"' in card["aliexpressIcon"] and ">A</text>" in card["aliexpressIcon"]


def test_other_parcels_have_no_order_link(card):
    assert card["url"]["dhl"] is None
    assert card["url"]["short"] is None
    assert card["url"]["missing"] is None
    assert "<a " not in card["carrier"]


def test_the_link_stands_before_the_other_actions(card):
    link = f'<a href="{AMAZON}" target="_blank" rel="noopener noreferrer">Bestellung</a>'
    assert card["order"].startswith(f'<div class="actions">{link}<button')
    assert 'data-a="rename"' in card["order"] and 'data-a="remove"' in card["order"]


def test_no_link_while_the_parcel_is_renamed(card):
    assert "<a " not in card["renaming"]
    assert 'data-a="rename-save"' in card["renaming"]

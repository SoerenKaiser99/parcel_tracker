"""Card: an order closed without a delivery mail says so (run in Node)."""

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
    + "\n;globalThis.__label = stateLabel; globalThis.__eta = etaText;"
    + "globalThis.__sub = subText;",
  sandbox,
);
const st = (state, attributes) => ({ state, attributes });
const assumed = { carrier: "amazon", carrier_name: "Amazon", assumed_delivered: true,
  delivered_at: null, days_until: -5, eta_date: "2026-10-02", eta_latest: null };
const real = { ...assumed, assumed_delivered: false };
const out = {
  eta: {
    assumed: sandbox.__eta("delivered", assumed),
    assumedWindow: sandbox.__eta("delivered",
      { ...assumed, eta_date: "2026-09-30", eta_latest: "2026-10-02" }),
    real: sandbox.__eta("delivered", real),
    realToday: sandbox.__eta("delivered", { ...real, delivered_at: new Date().toISOString() }),
    missing: sandbox.__eta("delivered", { carrier: "amazon", delivered_at: null }),
    // The flag says nothing while the order is open again.
    open: sandbox.__eta("in_transit", { ...assumed, days_until: 1 }),
  },
  label: {
    assumed: sandbox.__label(st("delivered", assumed)),
    real: sandbox.__label(st("delivered", real)),
    open: sandbox.__label(st("in_transit", assumed)),
  },
};
out.sub = sandbox.__sub(out.label.assumed, assumed, "delivered");
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


def test_assumed_delivery_is_shown_as_closed_without_confirmation(card):
    assert card["eta"]["assumed"] == "Abgeschlossen (ohne Zustellbestätigung)"
    assert card["eta"]["assumedWindow"] == "Abgeschlossen (ohne Zustellbestätigung)"
    assert card["label"]["assumed"] == "Abgeschlossen"
    assert card["sub"] == "Amazon · Abgeschlossen"


def test_real_deliveries_read_as_before(card):
    assert card["eta"]["real"] == "Zugestellt"
    assert card["eta"]["realToday"] == "Zugestellt heute"
    assert card["eta"]["missing"] == "Zugestellt"
    assert card["label"]["real"] == "Zugestellt"


def test_the_mark_only_counts_for_a_delivered_order(card):
    assert card["eta"]["open"] == "Morgen"
    assert card["label"]["open"] == "Unterwegs"


def test_card_texts_follow_the_copy_rules():
    text = BUNDLED_CARD.read_text(encoding="utf-8").lower()
    assert "abgeschlossen (ohne zustellbestätigung)" in text

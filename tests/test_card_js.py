"""Run the card's pure helpers in Node (no browser needed)."""

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
    + "\n;globalThis.__icons = CARRIER_ICONS; globalThis.__label = stateLabel;"
    + "globalThis.__eta = etaText; globalThis.__sub = subText; globalThis.__err = errorLine;"
    + "globalThis.__labels = CARRIER_LABEL;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];
const card = new Card();
card.setConfig({});
card._hass = { states: {}, entities: {} };
const a = { number: "AMZ1", delivery_code: "12<3>" };
const out = { none: card._codeHtml({ number: "AMZ1" }), hidden: card._codeHtml(a) };
card._code.set("AMZ1", "ask");
out.ask = card._codeHtml(a);
card._code.set("AMZ1", "show");
out.show = card._codeHtml(a);
out.sig = card._signature();
out.icons = Object.fromEntries(Object.entries(sandbox.__icons).map(([k, v]) => [k, v.color]));
const fmt = { formatEntityState: (st) => "Angekündigt" };
out.amazon = sandbox.__label(fmt, { state: "pre_transit", attributes: { carrier: "amazon" } });
out.dhl = sandbox.__label(fmt, { state: "pre_transit", attributes: { carrier: "dhl" } });
const eta = (st, a) => sandbox.__eta(st, a);
const rg = (d, first, last) => ({ days_until: d, eta_date: first, eta_latest: last });
out.eta = {
  sameMonth: eta("in_transit", rg(2, "2026-10-02", "2026-10-05")),
  twoMonths: eta("in_transit", rg(1, "2026-09-30", "2026-10-02")),
  until: eta("in_transit", rg(0, "2026-10-02", "2026-10-05")),
  untilMid: eta("in_transit", rg(-1, "2026-09-30", "2026-10-02")),
  over: eta("in_transit", rg(-4, "2026-09-30", "2026-10-02")),
  delivered: eta("delivered", { ...rg(2, "2026-10-02", "2026-10-05"), delivered_at: null }),
  single: eta("in_transit", { days_until: 1, eta_date: "2026-10-02", eta_latest: null }),
  same: eta("in_transit", rg(3, "2026-10-02", "2026-10-02")),
  days: eta("in_transit", { days_until: 3, eta_date: "2026-10-02" }),
  none: eta("in_transit", { days_until: null }),
};
out.icon = { dhl: card._icon("dhl"), dpd: card._icon("dpd"), hermes: card._icon("hermes"),
  ebay: card._icon("ebay") };
out.ebayLabel = sandbox.__label(fmt, { state: "pre_transit", attributes: { carrier: "ebay" } });
out.labels = sandbox.__labels;
out.sub = {
  hint: sandbox.__sub("Unterwegs", { carrier: "ebay", shipping_carrier_hint: "hermes" },
    "in_transit"),
  rawHint: sandbox.__sub("Unterwegs", { carrier: "ebay", shipping_carrier_hint: "GLS <Paket>" },
    "in_transit"),
  place: sandbox.__sub("Unterwegs", { carrier: "dhl", location: "Bonn" }, "in_transit"),
  pickup: sandbox.__sub("Abholbereit", { carrier: "ups", pickup_point: "Kiosk", location: "X" },
    "awaiting_pickup"),
};
out.err = {
  upsAuth: sandbox.__err({ last_error: "auth", carrier: "ups" }),
  dhlAuth: sandbox.__err({ last_error: "auth", carrier: "dhl" }),
  mergedUpsAuth: sandbox.__err({ last_error: "auth", carrier: "amazon", tracking_carrier: "ups" }),
  mergedDhlAuth: sandbox.__err({ last_error: "auth", carrier: "amazon", tracking_carrier: "dhl" }),
  budget: sandbox.__err({ last_error: "ups_budget", carrier: "ups" }),
  none: sandbox.__err({ last_error: null }),
};
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(run.stdout)


def test_icons_include_mail_carriers(card):
    assert card["icons"] == {
        "dhl": "#FFCC00",
        "dpd": "#DC0032",
        "amazon": "#FF9900",
        "ups": "#150400",
        "ebay": "#E53238",
    }


def test_code_reveal_steps(card):
    assert card["none"] == ""
    assert "Code anzeigen" in card["hidden"] and "12" not in card["hidden"]
    assert "Zustell-Code anzeigen?" in card["ask"] and "12&lt;3&gt;" not in card["ask"]
    assert "12&lt;3&gt;" in card["show"] and "<3>" not in card["show"]
    assert "|code:AMZ1=show" in card["sig"]


def test_amazon_pre_transit_reads_ordered(card):
    assert card["amazon"] == "Bestellt"
    assert card["dhl"] == "Angekündigt"


def test_card_copy_has_no_filler_words():
    text = BUNDLED_CARD.read_text(encoding="utf-8").lower()
    assert "bitte" not in text
    assert "erfolgreich" not in text


def test_eta_ranges(card):
    eta = card["eta"]
    assert eta["sameMonth"] == "2.–5. Okt."
    assert eta["twoMonths"] == "30. Sep.–2. Okt."
    assert eta["until"] == "Bis 5. Okt."
    assert eta["untilMid"] == "Bis 2. Okt."
    assert eta["over"] == "Termin überschritten"
    assert eta["delivered"] == "Zugestellt"


def test_eta_single_dates_unchanged(card):
    eta = card["eta"]
    assert (eta["single"], eta["same"], eta["days"], eta["none"]) == (
        "Morgen",
        "In 3 Tagen",
        "In 3 Tagen",
        "Noch kein Termin",
    )


def test_dhl_icon_is_wide_others_square(card):
    assert 'width="28" height="18"' in card["icon"]["dhl"]
    assert 'width="18" height="18"' in card["icon"]["dpd"]


def test_hermes_has_a_coloured_dot_instead_of_a_logo(card):
    hermes = card["icon"]["hermes"]
    assert 'fill="#0091CD"' in hermes and ">H</text>" in hermes
    assert 'aria-label="hermes"' in hermes and "<path" not in hermes
    assert 'fill="#E53238"' in card["icon"]["ebay"]


def test_labels_and_ebay_order_state(card):
    assert card["labels"] == {
        "dhl": "DHL", "dpd": "DPD", "hermes": "Hermes", "ups": "UPS", "amazon": "Amazon",
        "ebay": "eBay", "other": "17track",
    }
    assert card["ebayLabel"] == "Bestellt"


def test_subline_shows_the_shipping_carrier_hint(card):
    assert card["sub"]["hint"] == "eBay · Unterwegs · via Hermes"
    assert card["sub"]["rawHint"] == "eBay · Unterwegs · via GLS &lt;Paket&gt;"
    assert card["sub"]["place"] == "DHL · Unterwegs · Bonn"
    assert card["sub"]["pickup"] == "UPS · Abholbereit · Kiosk"


def test_ups_error_texts(card):
    assert card["err"]["upsAuth"].startswith("UPS-Zugangsdaten abgelehnt")
    assert card["err"]["dhlAuth"].startswith("DHL-API-Key abgelehnt")
    assert card["err"]["mergedUpsAuth"].startswith("UPS-Zugangsdaten abgelehnt")
    assert card["err"]["mergedDhlAuth"].startswith("DHL-API-Key abgelehnt")
    assert card["err"]["budget"].startswith("UPS-Monatsbudget verbraucht")
    assert card["err"]["none"] is None


def test_carrier_select_offers_hermes_and_ups():
    text = BUNDLED_CARD.read_text(encoding="utf-8")
    assert (
        '<option value="auto">Automatisch</option><option value="dhl">DHL</option>'
        '<option value="dpd">DPD</option><option value="hermes">Hermes</option>'
        '<option value="ups">UPS</option>'
    ) in text

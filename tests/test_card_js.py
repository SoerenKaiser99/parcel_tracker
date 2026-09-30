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
    + "globalThis.__eta = etaText;",
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
out.icon = { dhl: card._icon("dhl"), dpd: card._icon("dpd") };
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

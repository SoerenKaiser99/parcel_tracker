"""Run the card's pure helpers in Node (no browser needed)."""

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
  fs.readFileSync(process.argv[1], "utf8")
    + "\n;globalThis.__icons = CARRIER_ICONS; globalThis.__label = stateLabel;"
    + "globalThis.__eta = etaText; globalThis.__sub = subText; globalThis.__err = errorLine;"
    + "globalThis.__labels = CARRIER_LABEL; globalThis.__badge = todayBadge;"
    + "globalThis.__sure = sureToday;",
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
  ebay: card._icon("ebay"), gls: card._icon("gls"), ups: card._icon("ups"),
  amazon: card._icon("amazon") };
out.ebayLabel = sandbox.__label(fmt, { state: "pre_transit", attributes: { carrier: "ebay" } });
out.labels = sandbox.__labels;
out.sub = {
  hint: sandbox.__sub("Unterwegs", { carrier: "ebay", shipping_carrier_hint: "hermes" },
    "in_transit"),
  rawHint: sandbox.__sub("Unterwegs", { carrier: "ebay", shipping_carrier_hint: "GLS <Paket>" },
    "in_transit"),
  place: sandbox.__sub("Unterwegs", { carrier: "dhl", location: "Bonn" }, "in_transit"),
  gls: sandbox.__sub("In Zustellung", { carrier: "gls", carrier_name: "GLS" }, "out_for_delivery"),
  glsHint: sandbox.__sub("Versendet", { carrier: "ebay", shipping_carrier_hint: "gls" },
    "in_transit"),
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
const badge = (state, possible_count) => sandbox.__badge(
  state === undefined ? undefined : { state, attributes: { possible_count } });
out.badge = {
  missing: badge(undefined),
  none: badge("0", 0),
  sure: badge("2", 0),
  oldSensor: badge("1", undefined),
  both: badge("1", 1),
  bothMany: badge("2", 3),
  possible: badge("0", 1),
  possibleMany: badge("0", 2),
  unavailable: badge("unavailable", undefined),
};
const listed = { state: "2", attributes: { parcels: [{ number: "A1" }, { number: "B2" }],
  possible: [{ number: "C3" }], possible_count: 1 } };
out.sure = {
  listed: sandbox.__sure(listed, "A1"),
  listedLast: sandbox.__sure(listed, "B2"),
  possible: sandbox.__sure(listed, "C3"),
  other: sandbox.__sure(listed, "D4"),
  noNumber: sandbox.__sure(listed, undefined),
  missing: sandbox.__sure(undefined, "A1"),
  noAttributes: sandbox.__sure({ state: "unavailable" }, "A1"),
  noList: sandbox.__sure({ state: "1", attributes: {} }, "A1"),
  oddList: sandbox.__sure({ state: "1", attributes: { parcels: "A1" } }, "A1"),
  oddItems: sandbox.__sure({ state: "1", attributes: { parcels: [null, "A1", { number: "A1" }] } },
    "A1"),
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
        "ups": "var(--primary-text-color)",
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


def test_dhl_icon_is_a_yellow_badge_with_the_red_wordmark(card):
    dhl = card["icon"]["dhl"]
    assert 'class="dhl"' in dhl and 'aria-label="dhl"' in dhl
    assert re.search(r'<rect [^>]*rx="[\d.]+"[^>]* fill="#FFCC00"/>', dhl)
    assert '<path fill="#D40511" d="M' in dhl
    assert dhl.index("<rect") < dhl.index("<path")  # the wordmark lies on the badge
    width, height = map(int, re.search(r'width="(\d+)" height="(\d+)"', dhl).groups())
    assert height == 18 and 28 <= width <= 40
    # The wordmark (its letters span x 3.1 to 20.9) fills the badge: at most a tenth of the
    # width is padding on each side, and the letters are at least 5 px high (3.4 units).
    x, _, box_width, _ = map(float, re.search(r'viewBox="([^"]+)"', dhl).group(1).split())
    assert 0 < (3.1 - x) / box_width <= 0.1 and 0 < (x + box_width - 20.9) / box_width <= 0.1
    assert 3.4 * width / box_width >= 4.9
    assert "v.242h3.398" not in dhl  # the thin speed lines are left out: unreadable at 18 px
    assert "#FFCC00" not in card["icon"]["dpd"]
    assert 'width="18" height="18"' in card["icon"]["dpd"]


def test_ups_icon_follows_the_text_colour_of_the_theme(card):
    ups = card["icon"]["ups"]
    assert 'style="fill:var(--primary-text-color)"' in ups
    assert "#150400" not in ups  # nearly invisible on a dark card
    assert 'width="18" height="18"' in ups and 'aria-label="ups"' in ups
    assert '<path fill="#FF9900"' in card["icon"]["amazon"]  # brand colours stay attributes


def test_delivered_rows_stay_dimmed_and_badge_has_its_width():
    text = BUNDLED_CARD.read_text(encoding="utf-8")
    assert ".done { opacity:.55; }" in text
    assert re.search(r"svg\.dhl \{ width:\d+px; \}", text)
    # ".badge" is the blue "n heute" pill in the card's head: the logo must not share the class
    assert 'svg class="badge"' not in text and "svg.badge" not in text
    assert "svg.wide" not in text


def test_hermes_has_a_coloured_dot_instead_of_a_logo(card):
    hermes = card["icon"]["hermes"]
    assert 'fill="#0091CD"' in hermes and ">H</text>" in hermes
    assert 'aria-label="hermes"' in hermes and "<path" not in hermes
    assert 'fill="#E53238"' in card["icon"]["ebay"]


def test_labels_and_ebay_order_state(card):
    assert card["labels"] == {
        "dhl": "DHL", "dpd": "DPD", "gls": "GLS", "hermes": "Hermes", "ups": "UPS",
        "amazon": "Amazon", "ebay": "eBay", "other": "17track",
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


def test_carrier_select_offers_gls_hermes_and_ups():
    text = BUNDLED_CARD.read_text(encoding="utf-8")
    assert (
        '<option value="auto">Automatisch</option><option value="dhl">DHL</option>'
        '<option value="dpd">DPD</option><option value="gls">GLS</option>'
        '<option value="hermes">Hermes</option><option value="ups">UPS</option></select>'
    ) in text


def test_gls_has_a_blue_dot_with_g_and_its_label(card):
    gls = card["icon"]["gls"]
    assert 'fill="#061AB1"' in gls and ">G</text>" in gls
    assert 'aria-label="gls"' in gls and "<path" not in gls
    assert card["sub"]["gls"] == "GLS · In Zustellung"
    assert card["sub"]["glsHint"] == "eBay · Versendet · via GLS"


def test_badge_counts_sure_parcels_and_names_possible_ones(card):
    """"N heute" is the sensor's state (sure); ranges that include today are "möglich"."""
    assert card["badge"] == {
        "missing": "0 heute",
        "none": "0 heute",
        "sure": "2 heute",
        "oldSensor": "1 heute",
        "both": "1 heute · 1 möglich",
        "bothMany": "2 heute · 3 möglich",
        "possible": "1 möglich",
        "possibleMany": "2 möglich",
        "unavailable": "0 heute",
    }


def test_green_follows_the_parcels_list_of_the_today_sensor(card):
    """Green ⇔ the parcel's number is in sensor.pakete_heute's ``parcels``: the card
    has no rule of its own, so it cannot disagree with the count in the badge."""
    assert card["sure"] == {
        "listed": True,
        "listedLast": True,
        "possible": False,
        "other": False,
        "noNumber": False,
        "missing": False,
        "noAttributes": False,
        "noList": False,
        "oddList": False,
        "oddItems": True,
    }


def test_green_is_rendered_from_the_today_sensor_only():
    text = BUNDLED_CARD.read_text(encoding="utf-8")
    assert '<span class="eta ${sureToday(today, a.number) ? "today" : ""}">' in text
    assert "function sureToday(today, number)" in text
    # no second rule in the card: neither the status nor the estimate decide
    body = text[text.index("function sureToday("):text.index("function todayBadge(")]
    assert "days_until" not in body and "eta_" not in body and "out_for_delivery" not in body


def test_badge_comment_is_in_one_piece_above_the_badge():
    text = BUNDLED_CARD.read_text(encoding="utf-8")
    assert (
        "// The badge in the card's head, from sensor.pakete_heute: its state counts the parcels"
        " that\n// come today for sure, possible_count those whose delivery window only includes"
        " today.\nfunction todayBadge(st) {"
    ) in text


def test_badge_is_rendered_from_the_today_sensor_only():
    """The card does not count itself: it reads sensor.pakete_heute."""
    text = BUNDLED_CARD.read_text(encoding="utf-8")
    assert 'getElementById("today").textContent = todayBadge(today);' in text
    assert "possible_count" in text


DEMO_JS = BUNDLED_CARD.parents[3] / "docs" / "demo" / "demo.js"

DEMO_SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
const fake = { setConfig() {}, appendChild() {}, shadowRoot: { querySelectorAll: () => [] } };
const sandbox = {
  HTMLElement: class {},
  customElements: { get: (n) => defined[n] || (n.startsWith("ha-") ? fake : undefined),
    define: (n, c) => { defined[n] = c; } },
  window: {}, console, URLSearchParams, location: { search: "" },
  document: {
    documentElement: { dataset: {} },
    createElement: () => fake,
    getElementById: () => fake,
    querySelector: () => ({ getBoundingClientRect: () => ({ height: 0 }) }),
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8") + "\n;globalThis.__badge = todayBadge;",
  sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const st = sandbox.window.demo.hass.states["sensor.pakete_heute"];
const iso = (days) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(12, 0, 0, 0);
  return d;
};
const ymd = (days) => {
  const d = iso(days);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
const group = (state, first, last, changed) => sandbox.window.demo.todayGroup({ state,
  attributes: {
    eta_date: first == null ? null : ymd(first), eta_latest: last == null ? null : ymd(last),
    days_until: first == null ? null : first,
    events: changed == null ? [] : [{ timestamp: iso(changed).toISOString() }],
  } });
const D = "out_for_delivery";
console.log(JSON.stringify({ state: st.state, attributes: st.attributes,
  badge: sandbox.__badge(st),
  groups: {
    today: group(D, 0, null, -5), tomorrow: group(D, 1, null, -5), range: group(D, -2, 0, -5),
    yesterday: group(D, -1, null, 0), ended: group(D, -3, -1, 0),
    latestOnly: group(D, null, 0, -5), latestOnlyOver: group(D, null, -1, 0),
    changedToday: group(D, null, null, 0), changedBefore: group(D, null, null, -2),
    neverChanged: group(D, null, null, null),
    fixed: group("in_transit", 0, null, -5), fixedSame: group("in_transit", 0, 0, -5),
    possible: group("in_transit", 0, 3, -5), later: group("in_transit", 1, null, 0),
    delivered: group("delivered", 0, null, 0),
  } }));
"""


def test_demo_page_shows_one_sure_and_one_possible_parcel():
    """The demo's "Pakete heute" follows the sensor's rule, so the badge shows both parts."""
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", DEMO_SCRIPT, str(BUNDLED_CARD), str(DEMO_JS)],
        capture_output=True, text=True, check=True,
    )
    today = json.loads(run.stdout)
    assert today["badge"] == "1 heute · 1 möglich"
    assert today["state"] == "1"
    attrs = today["attributes"]
    assert [p["name"] for p in attrs["parcels"]] == ["Druckerpatronen"]
    assert [p["name"] for p in attrs["possible"]] == ["Fahrradklingel"]
    assert attrs["possible_count"] == 1
    assert set(attrs["possible"][0]) == set(attrs["parcels"][0])
    # The demo follows today_group() in schedule.py, also for parcels "in Zustellung".
    assert today["groups"] == {
        "today": "sure", "tomorrow": "sure", "range": "sure",
        "yesterday": None, "ended": None,
        "latestOnly": "sure", "latestOnlyOver": None,
        "changedToday": "sure", "changedBefore": None, "neverChanged": None,
        "fixed": "sure", "fixedSame": "sure", "possible": "possible", "later": None,
        "delivered": None,
    }

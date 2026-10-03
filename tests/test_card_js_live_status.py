"""Card: a missing key is a quiet note, "Kein Live-Status", and the chevron (run in Node)."""

import json
import re
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
SOURCE = BUNDLED_CARD.read_text(encoding="utf-8")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
// A tiny stand-in for the DOM: elements remember what the card writes into them.
const fakeEl = () => {
  const el = {
    hidden: false, value: "", innerHTML: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {}, children: [], dataset: {},
    addEventListener(name, fn) { el.listeners[name] = fn; },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    focus() {},
    contains() { return false; },
    appendChild(child) { el.children.push(child); },
    querySelector(sel) {
      if (sel === 'option[value="other"]') return null;
      return (el.kids[sel] ||= fakeEl());
    },
    querySelectorAll() { return []; },
    insertAdjacentHTML() {},
  };
  return el;
};
const sandbox = {
  HTMLElement: class {},
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {},
  document: { createElement: () => fakeEl() },
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(process.argv[1], "utf8")
    + "\n;globalThis.__eta = etaText; globalThis.__err = errorLine;"
    + "globalThis.__stale = staleLine; globalThis.__note = keyNote;"
    + "globalThis.__can = canTrack17;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];

const blank = { days_until: null, events: [], status_text: null, progress: 0 };
const out = {};
const eta = (state, a) => sandbox.__eta(state, { ...blank, ...a });
out.eta = {
  noKey: eta("unknown", { last_error: "missing_key", carrier: "dhl" }),
  noKeyUps: eta("unknown", { last_error: "missing_key", carrier: "ups" }),
  // A result from a mail or from 17track: the parcel has a status, only no day yet.
  noKeyMail: eta("in_transit", { last_error: "missing_key", carrier: "dhl" }),
  noKey17: eta("in_transit", { last_error: "missing_key", carrier: "dhl", track17: true }),
  noKeyEvents: eta("unknown", { last_error: "missing_key", carrier: "dhl",
    events: [{ timestamp: "2026-09-29T10:00:00+00:00", text: "x" }] }),
  noKeyText: eta("unknown", { last_error: "missing_key", carrier: "dhl", status_text: "x" }),
  noKeyDay: eta("unknown", { last_error: "missing_key", carrier: "dhl", days_until: 1 }),
  noKeyDelivered: eta("delivered", { last_error: "missing_key", carrier: "dhl" }),
  // Asked, nothing there (yet): the carrier can be asked, the parcel may still come.
  notFound: eta("unknown", { last_error: "not_found", carrier: "dhl" }),
  carrierNotFound: eta("unknown", { last_error: "carrier_not_found" }),
  auth: eta("unknown", { last_error: "auth", carrier: "dhl" }),
  unavailable: eta("unknown", { last_error: "unavailable", carrier: "dhl" }),
  budget: eta("unknown", { last_error: "ups_budget", carrier: "ups" }),
  fresh: eta("unknown", { last_error: null, carrier: "dhl" }),
  bare: sandbox.__eta("in_transit", { days_until: null }),
};
const p = (last_error, extra = {}) => ({ ...blank, last_error, carrier: "dhl", ...extra });
out.row = {
  noKey: sandbox.__stale(p("missing_key"), "unknown"),
  noKeyErr: sandbox.__err(p("missing_key"), "unknown"),
  // A mail gave a status: the sensor calls that "stale", the row still says nothing.
  noKeyMail: sandbox.__stale(p("missing_key",
    { stale: true, last_update: "2026-09-29T10:00:00+00:00" }), "in_transit"),
  noKey17: sandbox.__stale(p("missing_key", { track17: true, stale: true,
    last_update: "2026-09-29T10:00:00+00:00" }), "in_transit"),
  auth: sandbox.__stale(p("auth"), "unknown"),
  upsAuth: sandbox.__stale(p("auth", { carrier: "ups" }), "unknown"),
  notFound: sandbox.__stale(p("not_found"), "unknown"),
  carrierNotFound: sandbox.__stale(p("carrier_not_found", { carrier: null }), "unknown"),
  unavailable: sandbox.__stale(p("unavailable"), "unknown"),
  rateLimited: sandbox.__stale(p("rate_limited"), "unknown"),
  budget: sandbox.__stale(p("ups_budget", { carrier: "ups" }), "unknown"),
};
out.note = {
  dhl: sandbox.__note(p("missing_key"), "unknown"),
  auto: sandbox.__note(p("missing_key", { carrier: null }), "unknown"),
  ups: sandbox.__note(p("missing_key", { carrier: "ups" }), "unknown"),
  mergedUps: sandbox.__note(p("missing_key", { carrier: "amazon", tracking_carrier: "ups" }),
    "in_transit"),
  mergedDhl: sandbox.__note(p("missing_key", { carrier: "amazon", tracking_carrier: "dhl" }),
    "in_transit"),
  mail: sandbox.__note(p("missing_key"), "in_transit"),
  covered: sandbox.__note(p("missing_key", { track17: true }), "in_transit"),
  registeredNoStatus: sandbox.__note(p("missing_key", { track17: true }), "unknown"),
  auth: sandbox.__note(p("auth"), "unknown"),
  notFound: sandbox.__note(p("not_found"), "unknown"),
  none: sandbox.__note(p(null), "in_transit"),
};
// 17track is offered as before, with or without the note.
const t17 = { on: true, rest: 150 };
out.can17 = {
  noKey: sandbox.__can(p("missing_key"), "unknown", t17),
  noKeyRegistered: sandbox.__can(p("missing_key", { track17: true }), "unknown", t17),
  noKeyOff: sandbox.__can(p("missing_key"), "unknown", { on: false, rest: null }),
};

function mount(parcels) {
  const states = {};
  const entities = {};
  parcels.forEach(([state, attributes], i) => {
    const id = `sensor.paket_${i}`;
    states[id] = { entity_id: id, state, last_updated: "t",
      attributes: { ...blank, ...attributes } };
    entities[id] = { platform: "parcel_tracker" };
  });
  const card = new Card();
  const els = {};
  const root = {
    innerHTML: "", activeElement: null,
    getElementById(id) { return (els[id] ||= fakeEl()); },
  };
  card.attachShadow = () => root;
  card.setConfig({});
  card.hass = { states, entities };
  return { card, els, root };
}
const rows = (m) => Object.fromEntries(m.els.list.children.map((item) => [
  /data-number="([^"]+)"/.exec(item.innerHTML)[1], item]));
const m = mount([
  ["unknown", { number: "K1", name: "Ohne Key", carrier: "dhl", last_error: "missing_key" }],
  ["unknown", { number: "A1", name: "Abgelehnt", carrier: "dhl", last_error: "auth" }],
  ["awaiting_pickup", { number: "P1", name: "Abholung", carrier: "dhl", progress: 4 }],
  ["in_transit", { number: "T1", name: "Unterwegs", carrier: "dpd", progress: 2, days_until: 1 }],
]);
out.closed = Object.fromEntries(Object.entries(rows(m)).map(([n, item]) => [n, item.innerHTML]));
rows(m).K1.kids[".row-toggle"].listeners.click();
rows(m).A1.kids[".row-toggle"].listeners.click();
out.open = Object.fromEntries(Object.entries(rows(m)).map(([n, item]) => [n, item.innerHTML]));
out.template = m.root.innerHTML;
console.log(JSON.stringify(out));
"""

NO_KEY = "Kein Live-Status: DHL-API-Key fehlt (unter „Konfigurieren“ eintragen)."
NO_KEY_UPS = "Kein Live-Status: UPS-Zugangsdaten fehlen (unter „Konfigurieren“ eintragen)."
WARNING = '<div class="stale">'


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(run.stdout)


def _toggle(html):
    return re.search(r'<button type="button" class="row-toggle"[^>]*>(.*?)</button>', html, re.S)


def test_no_live_status_instead_of_no_date_when_the_carrier_cannot_be_asked(card):
    eta = card["eta"]
    assert eta["noKey"] == "Kein Live-Status"
    assert eta["noKeyUps"] == "Kein Live-Status"


def test_no_date_yet_stays_for_parcels_that_have_a_status_or_can_be_asked(card):
    eta = card["eta"]
    for key in (
        "noKeyMail", "noKey17", "noKeyEvents", "noKeyText",
        "notFound", "carrierNotFound", "auth", "unavailable", "budget", "fresh", "bare",
    ):
        assert eta[key] == "Noch kein Termin", key
    assert eta["noKeyDay"] == "Morgen"
    assert eta["noKeyDelivered"] == "Zugestellt"


def test_a_missing_key_is_no_warning_in_the_row(card):
    row = card["row"]
    assert row["noKey"] is None and row["noKeyErr"] is None
    assert row["noKeyMail"] is None  # also not as "Stand …, Carrier nicht erreichbar"
    assert row["noKey17"] is None


def test_real_problems_stay_in_the_row(card):
    row = card["row"]
    assert row["auth"] == "DHL-API-Key abgelehnt – in den Integrations-Optionen prüfen"
    assert row["upsAuth"] == "UPS-Zugangsdaten abgelehnt – in den Integrations-Optionen prüfen"
    assert row["notFound"] == "Noch keine Daten vom Carrier"
    assert row["carrierNotFound"] == "Carrier nicht gefunden – wähle den Carrier aus"
    assert row["unavailable"] == "Carrier gerade nicht erreichbar"
    assert row["rateLimited"] == "Zu viele Abfragen – nächster Versuch später"
    assert row["budget"].startswith("UPS-Monatsbudget verbraucht")


def test_the_note_names_the_missing_key_and_where_to_enter_it(card):
    note = card["note"]
    assert note["dhl"] == NO_KEY
    assert note["auto"] == NO_KEY
    assert note["mergedDhl"] == NO_KEY
    assert note["mail"] == NO_KEY
    assert note["registeredNoStatus"] == NO_KEY
    assert note["ups"] == NO_KEY_UPS
    assert note["mergedUps"] == NO_KEY_UPS
    # 17track shows a live status, and other errors have their line in the row.
    assert (note["covered"], note["auth"], note["notFound"], note["none"]) == (None,) * 4


def test_17track_is_offered_as_before(card):
    assert card["can17"] == {"noKey": True, "noKeyRegistered": False, "noKeyOff": False}


def test_collapsed_row_of_a_parcel_without_key_is_quiet(card):
    html = card["closed"]["K1"]
    assert WARNING not in html and "fehlt" not in html
    assert '<span class="eta ">Kein Live-Status</span>' in html
    assert "Noch kein Termin" not in html
    # A rejected key is still a warning in the row.
    assert f"{WARNING}DHL-API-Key abgelehnt" in card["closed"]["A1"]
    assert "Noch kein Termin" in card["closed"]["A1"]


def test_expanded_details_carry_the_note_in_secondary_text(card):
    html = card["open"]["K1"]
    assert f'<div class="detail note">{NO_KEY}</div>' in html
    assert WARNING not in html
    assert "Umbenennen" in html and "Löschen" in html
    assert "Kein Live-Status:" not in card["open"]["A1"]
    assert "Kein Live-Status:" not in card["open"]["T1"]  # not expanded, no key problem
    # ".detail" is secondary text; the note has no colour of its own.
    assert re.search(r"\.detail \{[^}]*color:var\(--secondary-text-color\)", SOURCE)
    assert not re.search(r"\.note \{[^}]*color", SOURCE)


def test_every_row_has_a_chevron_that_turns_when_open(card):
    for number, html in card["closed"].items():
        toggle = _toggle(html)
        assert toggle, number
        assert 'aria-expanded="false"' in toggle.group(0), number
        assert toggle.group(1).count('<span class="chev" aria-hidden="true"></span>') == 1, number
    assert 'aria-expanded="true"' in _toggle(card["open"]["K1"]).group(0)
    assert 'aria-expanded="false"' in _toggle(card["open"]["T1"]).group(0)
    # The chevron comes last, after the day or the pickup pill.
    assert re.search(r'Morgen</span><span class="chev"', card["closed"]["T1"])
    assert re.search(r'Abholbereit</span><span class="chev"', card["closed"]["P1"])


def test_the_toggle_keeps_its_name(card):
    """Its name is its text (parcel name and day); the chevron adds nothing to it."""
    toggle = _toggle(card["closed"]["T1"])
    assert "aria-label" not in toggle.group(0).split(">")[0]
    text = re.sub(r"<svg.*?</svg>", "", toggle.group(1), flags=re.S)
    assert re.sub(r"<[^>]+>", " ", text).split() == ["Unterwegs", "Morgen"]


def test_the_chevron_is_drawn_with_css_and_takes_no_room_from_the_other_columns():
    rule = re.search(r"\.chev \{([^}]*)\}", SOURCE).group(1)
    assert "flex:none" in rule and "border-right:" in rule and "border-bottom:" in rule
    assert "color:var(--secondary-text-color)" in rule
    assert "rotate(-45deg)" in rule
    assert re.search(
        r'\.row-toggle\[aria-expanded="true"\] \.chev \{[^}]*[ :]rotate\(45deg\)', SOURCE
    )
    assert re.search(r"prefers-reduced-motion: reduce\) \{[^}]*\.chev \{ transition:none", SOURCE)
    # The name takes the free room, so day and chevron stay at the right edge.
    assert re.search(r"\.name \{[^}]*flex:1 1 auto", SOURCE)
    for emoji in ("▸", "▾", "▶", "▼", "›"):
        assert emoji not in SOURCE

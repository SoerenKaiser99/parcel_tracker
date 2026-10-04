"""Card: the note under the add form after adding a parcel whose carrier cannot be asked
(no DHL key, no UPS credentials). Run in Node."""

import json
import re
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
SOURCE = BUNDLED_CARD.read_text(encoding="utf-8")

DHL = (
    "Hinzugefügt. Ohne DHL-API-Key gibt es dafür keinen Live-Status: Key unter"
    " „Konfigurieren“ eintragen – oder der Status kommt aus den DHL-Mails über den"
    " Mail-Import."
)
UPS = (
    "Hinzugefügt. Ohne UPS-Zugangsdaten gibt es dafür keinen Live-Status: Zugangsdaten"
    " unter „Konfigurieren“ eintragen – oder der Status kommt aus den UPS-Mails über den"
    " Mail-Import."
)

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
const fakeEl = () => {
  const el = {
    hidden: false, value: "", innerHTML: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {}, children: [], dataset: {}, focused: 0,
    addEventListener(name, fn) { el.listeners[name] = fn; },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    focus() { el.focused += 1; },
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
  HTMLElement: class {
    toggleAttribute(name, on) { this[name] = on; }
    dispatchEvent() {}
  },
  Event: class { constructor(type) { this.type = type; } },
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {},
  document: { createElement: () => fakeEl() },
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(process.argv[1], "utf8")
    + "\n;globalThis.__note = addedNote; globalThis.__parcel = addedParcel;"
    + "globalThis.__key = numberKey; globalThis.__cannot = cannotQuery;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];

const blank = { days_until: null, events: [], status_text: null, progress: 0, last_error: null };
const sensor = (state, a) => ({ state, last_updated: "t", attributes: { ...blank, ...a } });
const out = {};

// --- the decision and the text per carrier ----------------------------------------
const note = (state, a) => sandbox.__note(sensor(state, a));
out.note = {
  dhl: note("unknown", { carrier: "dhl", last_error: "missing_key" }),
  auto: note("unknown", { carrier: null, last_error: "missing_key" }),
  ups: note("unknown", { carrier: "ups", last_error: "missing_key" }),
  mergedUps: note("unknown", { carrier: "amazon", tracking_carrier: "ups",
    last_error: "missing_key" }),
  noState: note(undefined, { carrier: "dhl", last_error: "missing_key" }),
  // The carrier can be asked, or something already told a status: no note.
  fine: note("unknown", { carrier: "dhl" }),
  notFound: note("unknown", { carrier: "dhl", last_error: "not_found" }),
  auth: note("unknown", { carrier: "dhl", last_error: "auth" }),
  dpd: note("in_transit", { carrier: "dpd", days_until: 1 }),
  mail: note("in_transit", { carrier: "dhl", last_error: "missing_key" }),
  events: note("unknown", { carrier: "dhl", last_error: "missing_key",
    events: [{ timestamp: "2026-10-01T08:00:00Z", text: "x" }] }),
  text: note("unknown", { carrier: "dhl", last_error: "missing_key", status_text: "x" }),
  day: note("unknown", { carrier: "dhl", last_error: "missing_key", days_until: 2 }),
  track17: note("in_transit", { carrier: "dhl", last_error: "missing_key", track17: true }),
  none: sandbox.__note(null),
  bare: sandbox.__note({ state: "unknown" }),
};
out.cannot = {
  yes: sandbox.__cannot("unknown", { ...blank, last_error: "missing_key" }),
  status: sandbox.__cannot("in_transit", { ...blank, last_error: "missing_key" }),
  other: sandbox.__cannot("unknown", { ...blank, last_error: "unavailable" }),
};
out.key = [sandbox.__key(" 1z 999-aa1 "), sandbox.__key(null), sandbox.__key(12)];

// --- which sensor is the parcel just added ----------------------------------------
const list = [sensor("unknown", { number: "OLD1" }), sensor("unknown", { number: "NEW1" }),
  sensor("in_transit", { number: "MAIL1" })];
const pick = (added) => {
  const st = sandbox.__parcel(list, added);
  return st ? st.attributes.number : null;
};
out.pick = {
  fresh: pick({ key: "NEW1", before: new Set(["OLD1"]) }),
  wasThere: pick({ key: "OLD1", before: new Set(["OLD1"]) }),
  notYet: pick({ key: "LATER1", before: new Set(["OLD1"]) }),
  nothing: pick(null),
};

// --- the card ---------------------------------------------------------------------
function mount(config, parcels = {}) {
  const hass = {
    states: { "sensor.pakete_heute": { state: "0", last_updated: "t", attributes: {} } },
    entities: {},
  };
  const m = { hass, els: {}, calls: [], visibility: [] };
  m.put = (number, state, attributes) => {
    const id = "sensor.paket_" + number.toLowerCase();
    hass.states[id] = { entity_id: id, state, last_updated: "t" + Math.random(),
      attributes: { ...blank, number, ...attributes } };
    hass.entities[id] = { platform: "parcel_tracker" };
  };
  m.drop = (number) => {
    const id = "sensor.paket_" + number.toLowerCase();
    delete hass.states[id];
    delete hass.entities[id];
  };
  for (const [number, [state, a]] of Object.entries(parcels)) m.put(number, state, a);
  // What the integration does with a new number (null: the sensor comes later).
  m.onAdd = null;
  hass.callService = async (...args) => {
    m.calls.push(args);
    if (m.onAdd) m.onAdd(args[2]);
  };
  m.card = new Card();
  m.card.dispatchEvent = (ev) => m.visibility.push(ev.detail.value);
  const root = {
    innerHTML: "", activeElement: null,
    getElementById(id) { return (m.els[id] ||= fakeEl()); },
  };
  m.root = root;
  m.card.attachShadow = () => root;
  m.card.setConfig(config);
  m.card.hass = hass;
  m.push = () => { m.card.hass = hass; };
  m.add = async (number, carrier = "auto") => {
    m.els.num.value = number;
    m.els.car.value = carrier;
    await m.card._add();
  };
  m.look = () => ({
    form: !m.els.form.hidden,
    // The fake DOM knows no `hidden` attribute from the template: untouched means hidden.
    note: !m.els.added || m.els.added.hidden ? null : m.els["added-text"].textContent,
  });
  return m;
}
const NO_KEY = ["unknown", { carrier: "dhl", last_error: "missing_key" }];

(async () => {
  // Default (add_form: button): the form collapses as before, the note stays under the head.
  const a = mount({}, { OLD1: NO_KEY });
  out.start = a.look();
  a.els.toggle.listeners.click();
  out.opened = a.look();  // an old parcel without key says nothing here
  await a.add("0034 0999-9999 9999 9911", "dhl");
  out.afterAdd = { ...a.look(), toggleFocused: a.els.toggle.focused };
  // The sensor arrives with a later hass: the note appears, and stays on later updates.
  a.push();
  out.beforeSensor = a.look();
  a.put("00340999999999999911", ...NO_KEY);
  a.push();
  out.afterHass = a.look();
  a.hass.states["sensor.pakete_heute"].last_updated = "later";
  a.push();
  a.push();
  out.afterMoreHass = a.look();
  // Opening the form again keeps the note; closing it ends the note.
  a.els.toggle.listeners.click();
  out.reopened = a.look();
  a.els.toggle.listeners.click();
  out.closedAgain = a.look();
  a.push();
  out.staysGone = a.look();

  // The ×: gone, and gone for good; the focus goes to the plus.
  const b = mount({});
  b.els.toggle.listeners.click();
  b.onAdd = () => b.put("1Z9999999999999904", "unknown",
    { carrier: "ups", last_error: "missing_key" });
  await b.add("1z9999999999999904");
  out.upsAtOnce = b.look();  // the sensor was there before the service call returned
  b.push();
  out.ups = b.look();
  const focusBefore = b.els.toggle.focused;
  b.els["added-close"].listeners.click();
  b.push();
  out.dismissed = { ...b.look(), toggleFocused: b.els.toggle.focused - focusBefore };

  // The next add ends the note of the one before, also when it fails.
  const c = mount({ add_form: "always" });
  c.onAdd = () => c.put("00340999999999999911", ...NO_KEY);
  await c.add("00340999999999999911");
  c.push();
  out.always = c.look();
  c.onAdd = () => c.put("09999999999901", "in_transit", { carrier: "dpd", days_until: 1 });
  await c.add("09999999999901");
  c.push();
  out.alwaysNext = c.look();
  c.onAdd = () => c.put("00340999999999999912", ...NO_KEY);
  await c.add("00340999999999999912");
  c.push();
  out.alwaysThird = c.look();
  c.hass.callService = async () => { throw { code: "duplicate" }; };
  await c.add("00340999999999999912");
  c.push();
  out.alwaysFailed = { ...c.look(), err: c.els.err.innerHTML };
  // add_form: always has no plus: the × hands the focus to the number field.
  const d = mount({ add_form: "always" });
  d.onAdd = () => d.put("00340999999999999911", ...NO_KEY);
  await d.add("00340999999999999911");
  d.push();
  d.els["added-close"].listeners.click();
  out.alwaysDismiss = { ...d.look(), numFocused: d.els.num.focused };

  // Only the parcel that was added: a mail parcel arriving meanwhile, and the same number
  // already in the list (the service refuses it) never show the note.
  const e = mount({}, { "00340999999999999911": NO_KEY });
  e.els.toggle.listeners.click();
  e.onAdd = () => e.put("00340999999999999913", ...NO_KEY);  // another parcel, e.g. from a mail
  await e.add("09999999999901");
  e.push();
  out.otherParcel = e.look();
  e.onAdd = null;
  e.els.toggle.listeners.click();
  await e.add("00340999999999999911");
  e.push();
  out.wasThere = e.look();

  // The parcel gets a status (a mail, 17track) or is removed: the note goes away.
  const f = mount({});
  f.els.toggle.listeners.click();
  f.onAdd = () => f.put("00340999999999999911", ...NO_KEY);
  await f.add("00340999999999999911");
  f.push();
  out.beforeStatus = f.look();
  f.put("00340999999999999911", "in_transit",
    { carrier: "dhl", last_error: "missing_key", days_until: 1 });
  f.push();
  out.afterStatus = f.look();
  const g = mount({});
  g.els.toggle.listeners.click();
  g.onAdd = () => g.put("00340999999999999911", ...NO_KEY);
  await g.add("00340999999999999911");
  g.push();
  g.drop("00340999999999999911");
  g.push();
  out.afterRemove = g.look();

  // A changed card config starts over.
  const h = mount({});
  h.els.toggle.listeners.click();
  h.onAdd = () => h.put("00340999999999999911", ...NO_KEY);
  await h.add("00340999999999999911");
  h.push();
  h.card.setConfig({ add_form: "always" });
  h.push();
  out.afterConfig = h.look();

  // show: today would hide the card (nothing comes today): it stays while the note is shown.
  const i = mount({ show: "today" });
  i.hass.states["sensor.pakete_heute"].attributes = { delivered_today_count: 0 };
  i.push();
  out.show = { hiddenAtStart: i.card.hidden === true };
  i.card._setFormOpen(true);
  i.onAdd = () => i.put("00340999999999999911", ...NO_KEY);
  await i.add("00340999999999999911");
  i.push();
  out.show.withNote = { hidden: i.card.hidden === true, ...i.look() };
  i.els["added-close"].listeners.click();
  out.show.afterDismiss = i.card.hidden === true;

  out.template = a.root.innerHTML;
  console.log(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(run.stdout)


def test_the_note_names_the_missing_key_per_carrier(card):
    note = card["note"]
    assert note["dhl"] == DHL
    assert note["auto"] == DHL  # "Automatisch": only DHL answers "no key"
    assert note["noState"] == DHL
    assert note["ups"] == UPS
    assert note["mergedUps"] == UPS


def test_no_note_when_the_carrier_can_be_asked_or_a_status_is_known(card):
    note = card["note"]
    for case in (
        "fine", "notFound", "auth", "dpd", "mail", "events", "text", "day", "track17",
        "none", "bare",
    ):
        assert note[case] is None, case


def test_the_decision_is_the_one_behind_kein_live_status(card):
    assert card["cannot"] == {"yes": True, "status": False, "other": False}
    # One rule for the row's "Kein Live-Status" and the note.
    assert SOURCE.count("cannotQuery(") == 2
    assert "if (cannotQuery(state, a)) return NO_LIVE_STATUS;" in SOURCE


def test_numbers_compare_the_way_the_integration_stores_them(card):
    assert card["key"] == ["1Z999AA1", "", "12"]


def test_only_a_parcel_that_was_not_in_the_list_counts_as_added(card):
    assert card["pick"] == {"fresh": "NEW1", "wasThere": None, "notYet": None, "nothing": None}


def test_the_form_collapses_and_the_note_appears_with_the_sensor(card):
    assert card["start"] == {"form": False, "note": None}
    assert card["opened"] == {"form": True, "note": None}
    assert card["afterAdd"] == {"form": False, "note": None, "toggleFocused": 1}
    assert card["beforeSensor"] == {"form": False, "note": None}
    assert card["afterHass"] == {"form": False, "note": DHL}
    assert card["upsAtOnce"] == {"form": False, "note": UPS}


def test_the_note_survives_hass_updates(card):
    assert card["afterMoreHass"] == {"form": False, "note": DHL}


def test_reopening_keeps_the_note_and_closing_the_form_ends_it(card):
    assert card["reopened"] == {"form": True, "note": DHL}
    assert card["closedAgain"] == {"form": False, "note": None}
    assert card["staysGone"] == {"form": False, "note": None}


def test_the_close_button_dismisses_the_note_for_good(card):
    assert card["ups"] == {"form": False, "note": UPS}
    assert card["dismissed"] == {"form": False, "note": None, "toggleFocused": 1}
    assert card["alwaysDismiss"] == {"form": True, "note": None, "numFocused": 1}


def test_another_add_ends_the_note(card):
    assert card["always"] == {"form": True, "note": DHL}
    assert card["alwaysNext"] == {"form": True, "note": None}  # DPD needs no key
    assert card["alwaysThird"] == {"form": True, "note": DHL}
    assert card["alwaysFailed"] == {
        "form": True, "note": None, "err": "Dieses Paket ist schon in der Liste.",
    }


def test_no_note_for_mail_parcels_or_parcels_added_before(card):
    assert card["otherParcel"] == {"form": False, "note": None}
    assert card["wasThere"]["note"] is None


def test_the_note_goes_when_the_parcel_gets_a_status_or_is_removed(card):
    assert card["beforeStatus"]["note"] == DHL
    assert card["afterStatus"]["note"] is None
    assert card["afterRemove"]["note"] is None


def test_a_config_change_starts_over(card):
    assert card["afterConfig"] == {"form": True, "note": None}


def test_a_card_hidden_by_show_stays_while_the_note_is_shown(card):
    show = card["show"]
    assert show["hiddenAtStart"] is True
    assert show["withNote"] == {"hidden": False, "form": False, "note": DHL}
    assert show["afterDismiss"] is True


def test_the_note_is_a_muted_status_line_with_a_close_button(card):
    template = card["template"]
    block = re.search(
        r'<div class="added" id="added" role="status" hidden>(.*?)</div>', template, re.S
    )
    assert block, "the note sits in the card, hidden until needed"
    assert '<span id="added-text"></span>' in block.group(1)
    button = re.search(
        r'<button type="button" id="added-close"[^>]*>(.*?)</button>', block.group(1)
    )
    assert button and button.group(1) == "×"
    assert 'aria-label="Hinweis schließen"' in button.group(0)
    assert 'title="Hinweis schließen"' in button.group(0)
    # Directly under the form, above the error line and the list.
    assert re.search(r'id="addask"[^>]*></div>\s*</div>\s*<div class="added" id="added"', template)
    assert template.index('id="added"') < template.index('id="err"') < template.index('id="list"')
    rule = re.search(r"\.added \{([^}]*)\}", template).group(1)
    assert "color:var(--secondary-text-color)" in rule
    assert "warning" not in rule and "error" not in rule
    assert re.search(r"\.added button:focus-visible \{[^}]*outline:2px solid", template)


def test_the_texts_avoid_banned_words():
    for text in (DHL, UPS):
        assert text in SOURCE
        assert "bitte" not in text.lower()
